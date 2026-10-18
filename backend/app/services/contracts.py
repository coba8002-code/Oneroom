"""계약서 등록 · OCR · 검수 (PRD §3-3, §6 "AI가 계약 내용을 확정하지 않음").

업로드 → (설정돼 있으면) 클라우드 OCR → 후보 값 → 관리자 검수 → 그때만 원장(leases) 반영.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Deposit, Lease, LeaseDocument, Property, Unit
from app.services import contract_extract, ocr, storage
from app.services.matching import MatchError

class UploadError(MatchError):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


MAX_BYTES = 10_000_000
MAGIC = {b"\xff\xd8\xff": ("jpg", "image/jpeg"), b"\x89PNG": ("png", "image/png"), b"%PDF": ("pdf", "application/pdf")}
FIELDS = ("deposit", "rent", "mgmt_fee", "due_day", "start_date", "end_date")
KEEP = object()  # 검수 화면이 관리비를 보내지 않으면 기존 값을 그대로 둔다


def detect(raw: bytes) -> tuple[str, str]:
    for magic, kind in MAGIC.items():
        if raw.startswith(magic):
            return kind
    raise UploadError("JPG · PNG · PDF 파일만 올릴 수 있습니다", 415)


def lease_in_org(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID) -> Lease | None:
    return session.scalar(
        select(Lease).join(Unit, Lease.unit_id == Unit.id).join(Property, Unit.property_id == Property.id)
        .where(Lease.id == lease_id, Property.organization_id == organization_id))


def doc_in_org(session: Session, organization_id: uuid.UUID, doc_id: uuid.UUID) -> LeaseDocument | None:
    return session.scalar(
        select(LeaseDocument).join(Lease, LeaseDocument.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id).join(Property, Unit.property_id == Property.id)
        .where(LeaseDocument.id == doc_id, Property.organization_id == organization_id))


def run_ocr(session: Session, doc: LeaseDocument, provider=None) -> None:
    provider = provider if provider is not None else ocr.get_provider()
    if provider is None:
        doc.ocr_status = "not_configured"
        doc.ocr_json = {"provider": None, "text": None, "fields": None,
                        "error": "OCR 이 설정되지 않았습니다. 값을 직접 입력하세요."}
        return
    fmt = detect_format(doc)
    session.add(AuditLog(action="ocr.send", entity_type="lease_document", entity_id=str(doc.id),
                         detail={"provider": provider.name}))  # 외부 전송 기록 (PRD §4 개인정보)
    try:
        text = provider.read(storage.load(doc.file_path), fmt)
    except ocr.OcrError as e:
        doc.ocr_status = "failed"
        doc.ocr_json = {"provider": provider.name, "text": None, "fields": None, "error": str(e)}
        return
    doc.ocr_status = "done"
    doc.ocr_json = {"provider": provider.name, "text": text, "fields": contract_extract.extract(text),
                    "error": None}


def detect_format(doc: LeaseDocument) -> str:
    return {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}[doc.content_type]


def upload(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID, filename: str | None,
           raw: bytes, provider=None) -> LeaseDocument:
    lease = lease_in_org(session, organization_id, lease_id)
    if lease is None:
        raise LookupError("계약을 찾을 수 없습니다")
    if len(raw) > MAX_BYTES:
        raise UploadError("파일이 너무 큽니다 (10MB 이하)", 413)
    _, content_type = detect(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if session.scalar(select(LeaseDocument.id).where(
            LeaseDocument.lease_id == lease_id, LeaseDocument.sha256 == digest)):
        raise UploadError("이 계약에 이미 올린 파일입니다", 409)

    doc = LeaseDocument(lease_id=lease_id, file_path=storage.save(raw), original_name=(filename or "")[:255],
                        content_type=content_type, sha256=digest)
    session.add(doc)
    session.flush()
    session.add(AuditLog(action="document.upload", entity_type="lease_document", entity_id=str(doc.id),
                         detail={"lease_id": str(lease_id), "content_type": content_type, "bytes": len(raw)}))
    run_ocr(session, doc, provider)
    session.commit()
    return doc


def retry_ocr(session: Session, organization_id: uuid.UUID, doc_id: uuid.UUID, provider=None) -> LeaseDocument:
    doc = doc_in_org(session, organization_id, doc_id)
    if doc is None:
        raise LookupError("문서를 찾을 수 없습니다")
    if doc.verified_at:
        raise MatchError("이미 검수를 마친 문서입니다")
    run_ocr(session, doc, provider)
    session.commit()
    return doc


def lease_values(lease: Lease) -> dict:
    return {"deposit": lease.deposit, "rent": lease.rent, "mgmt_fee": lease.mgmt_fee, "due_day": lease.due_day,
            "start_date": lease.start_date.isoformat(), "end_date": lease.end_date.isoformat() if lease.end_date else None}


def _set_deposit(session: Session, lease: Lease, deposit: int) -> None:
    """계약 보증금을 바꾼다. 보증금은 받은 묶음별로 기록 — 이미 받은 금액은 그대로 두고,
    차액만 '받을 보증금'(미수령 묶음)으로 둔다. 증액분 입금은 임대료 화면에서 '보증금 수령'으로 확정."""
    tranches = session.scalars(select(Deposit).where(Deposit.lease_id == lease.id)).all()
    if any(d.returned_at is not None for d in tranches):
        raise MatchError("보증금을 이미 돌려준 계약입니다. 새 계약은 새로 등록하세요")
    received = sum(d.amount for d in tranches if d.received_at is not None)
    if deposit < received:
        raise MatchError(f"이미 받은 보증금 {received:,}원보다 적게 바꿀 수 없습니다. "
                         "감액(일부 반환)은 운영비 화면에서 반환 출금을 '보증금 반환'으로 확정하세요")
    pending = next((d for d in tranches if d.received_at is None), None)
    rest = deposit - received
    if pending and rest:
        pending.amount = rest
    elif pending:
        session.delete(pending)
    elif rest:
        session.add(Deposit(lease_id=lease.id, amount=rest))


def verify(session: Session, organization_id: uuid.UUID, doc_id: uuid.UUID, *, deposit: int, rent: int,
           due_day: int, start_date: date, end_date: date | None, mgmt_fee=KEEP) -> LeaseDocument:
    """관리자가 확정한 값을 원장에 반영한다. 이미 생성된 청구는 바꾸지 않는다 (다음 청구부터)."""
    doc = doc_in_org(session, organization_id, doc_id)
    if doc is None:
        raise LookupError("문서를 찾을 수 없습니다")
    if doc.verified_at:
        raise MatchError("이미 검수를 마친 문서입니다. 바뀐 계약은 새 계약서로 올리세요")
    if end_date and end_date < start_date:
        raise MatchError("계약종료가 계약시작보다 빠릅니다")
    lease = session.get(Lease, doc.lease_id)
    before = lease_values(lease)

    if deposit != lease.deposit:
        _set_deposit(session, lease, deposit)
    lease.deposit, lease.rent, lease.due_day = deposit, rent, due_day
    lease.start_date, lease.end_date = start_date, end_date
    if mgmt_fee is not KEEP:
        lease.mgmt_fee = mgmt_fee

    after = lease_values(lease)
    changed = [k for k in FIELDS if before[k] != after[k]]
    doc.verified_fields = {**after, "changed": changed}
    doc.verified_at = datetime.now(timezone.utc)
    session.add(AuditLog(action="document.verify", entity_type="lease", entity_id=str(lease.id),
                         detail={"document_id": str(doc.id), "before": before, "after": after, "changed": changed}))
    session.commit()
    return doc
