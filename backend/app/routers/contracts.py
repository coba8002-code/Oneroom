"""계약서 등록 · OCR · 검수."""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Lease, LeaseDocument, Property, Tenant, Unit
from app.schemas import ContractOut, DocumentOut, DocumentSummary, OcrSettingsOut, VerifyIn
from app.services import contracts, ocr, storage
from app.services.matching import MatchError

router = APIRouter(prefix="/api/v1", tags=["contracts"])


@router.get("/settings/ocr", response_model=OcrSettingsOut)
def ocr_settings() -> OcrSettingsOut:
    p = ocr.get_provider()
    return OcrSettingsOut(configured=p is not None, provider=p.name if p else None)


@router.get("/contracts", response_model=list[ContractOut])
def list_contracts(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> list[ContractOut]:
    rows = session.execute(
        select(Lease, Unit.label, Tenant.name)
        .join(Unit, Lease.unit_id == Unit.id).join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Property.organization_id == organization_id, Lease.status == "active")
        .order_by(Unit.label)).all()
    docs: dict[uuid.UUID, list[LeaseDocument]] = {}
    for d in session.scalars(select(LeaseDocument).where(
            LeaseDocument.lease_id.in_([lease.id for lease, _, _ in rows])).order_by(LeaseDocument.created_at)):
        docs.setdefault(d.lease_id, []).append(d)
    return [ContractOut(
        lease_id=lease.id, unit_no=unit_no, tenant_name=name, deposit=lease.deposit, rent=lease.rent,
        mgmt_fee=lease.mgmt_fee, due_day=lease.due_day, start_date=lease.start_date, end_date=lease.end_date,
        documents=[DocumentSummary(id=d.id, original_name=d.original_name, created_at=d.created_at,
                                   ocr_status=d.ocr_status, verified_at=d.verified_at)
                   for d in docs.get(lease.id, [])],
    ) for lease, unit_no, name in rows]


def _out(session: Session, doc: LeaseDocument) -> DocumentOut:
    lease = session.get(Lease, doc.lease_id)
    unit_no = session.scalar(select(Unit.label).where(Unit.id == lease.unit_id))
    j = doc.ocr_json or {}
    return DocumentOut(
        id=doc.id, lease_id=doc.lease_id, unit_no=unit_no, original_name=doc.original_name,
        content_type=doc.content_type, created_at=doc.created_at, ocr_status=doc.ocr_status,
        ocr_provider=j.get("provider"), ocr_error=j.get("error"), ocr_text=j.get("text"),
        fields=j.get("fields"), current=contracts.lease_values(lease),
        verified_at=doc.verified_at, verified_fields=doc.verified_fields,
    )


def _get(session: Session, organization_id: uuid.UUID, doc_id: uuid.UUID) -> LeaseDocument:
    doc = contracts.doc_in_org(session, organization_id, doc_id)
    if doc is None:
        raise HTTPException(404, "문서를 찾을 수 없습니다")
    return doc


@router.post("/leases/{lease_id}/documents", response_model=DocumentOut, status_code=201)
async def upload(lease_id: uuid.UUID, organization_id: uuid.UUID, file: UploadFile = File(...),
                 session: Session = Depends(get_session)) -> DocumentOut:
    raw = await file.read(contracts.MAX_BYTES + 1)
    try:
        doc = contracts.upload(session, organization_id, lease_id, file.filename, raw)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except contracts.UploadError as e:
        raise HTTPException(e.status, str(e))
    return _out(session, doc)


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def detail(doc_id: uuid.UUID, organization_id: uuid.UUID, session: Session = Depends(get_session)) -> DocumentOut:
    return _out(session, _get(session, organization_id, doc_id))


@router.get("/documents/{doc_id}/file")
def file(doc_id: uuid.UUID, organization_id: uuid.UUID, session: Session = Depends(get_session)) -> Response:
    doc = _get(session, organization_id, doc_id)
    return Response(storage.load(doc.file_path), media_type=doc.content_type,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/documents/{doc_id}/ocr", response_model=DocumentOut)
def retry(doc_id: uuid.UUID, organization_id: uuid.UUID, session: Session = Depends(get_session)) -> DocumentOut:
    try:
        doc = contracts.retry_ocr(session, organization_id, doc_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except MatchError as e:
        raise HTTPException(409, str(e))
    return _out(session, doc)


@router.post("/documents/{doc_id}/verify", response_model=DocumentOut)
def verify(doc_id: uuid.UUID, organization_id: uuid.UUID, body: VerifyIn,
           session: Session = Depends(get_session)) -> DocumentOut:
    try:
        fields = body.model_dump()
        if "mgmt_fee" not in body.model_fields_set:
            fields.pop("mgmt_fee")  # 보내지 않았으면 기존 관리비 유지
        doc = contracts.verify(session, organization_id, doc_id, **fields)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except MatchError as e:
        session.rollback()
        raise HTTPException(409, str(e))
    return _out(session, doc)
