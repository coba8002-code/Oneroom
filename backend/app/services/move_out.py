"""입주·퇴실 점검과 퇴실 정산.

규칙
- 점검은 계약마다 입주 1번·퇴실 1번. 퇴실 점검은 입주 점검과 같은 항목으로 만들어 나란히 비교한다.
- 항목 목록 = 기본 공간(벽지·바닥·욕실·계량기 …) + 그 호실 자산대장의 품목. 상태를 모르면 비워 둔다.
- 임차인과 함께 확인(tenant_confirmed_on)한 점검은 잠근다 — 증빙이 나중에 바뀌지 않게. 고치려면 확인을 풀어야 하고 기록이 남는다.
- 퇴실 정산의 숫자는 장부에서 온 사실값만 쓴다: 돌려줄 보증금(받았고 아직 안 돌려준 묶음), 선납 잔액, 기준일까지 납부일이
  지난 미납 청구. 파손·청소 같은 공제는 관리자가 적는다. 다툼이 있는 공제는 '먼저 돌려줄 금액'에서 빼 따로 둔다.
- 보증금 수령 기록이 없으면 돌려줄 금액을 계산하지 않는다 (모르는 것을 0으로 치지 않음).
- 실제 반환은 은행 출금을 '보증금 반환'으로 확정할 때 기록된다. 정산서는 그 근거 문서.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (AuditLog, Deposit, Fixture, Inspection, InspectionItem, InspectionPhoto, Lease,
                        MoveOutSettlement, Property, SettlementDeduction, Tenant, Unit)
from app.services import ledger, receivables, storage
from app.services.contracts import detect, lease_in_org, UploadError

KINDS = {"move_in": "입주", "move_out": "퇴실"}
CONDITIONS = {"good": "양호", "worn": "생활 마모", "dirty": "오염", "damaged": "파손", "missing": "없음·분실"}
DEDUCTION_CATEGORIES = {"damage": "파손 수리", "cleaning": "청소", "utility": "공과금", "other": "기타"}
STANDARD_AREAS = ("현관·도어락", "열쇠·카드키", "벽지", "바닥(장판)", "천장", "창문·방충망", "조명", "콘센트·스위치",
                  "주방(싱크대)", "욕실·변기", "전기 계량기", "가스 계량기", "수도 계량기")
MAX_PHOTO_BYTES = 4_000_000  # Vercel 요청 한도(4.5MB) 안 — 화면에서 사진을 줄여 올린다
MAX_PHOTOS_PER_ITEM = 10


class MoveOutError(Exception):
    pass


def _audit(session: Session, user_id, action: str, entity: str, entity_id, detail: dict | None = None) -> None:
    session.add(AuditLog(user_id=user_id, action=action, entity_type=entity, entity_id=str(entity_id), detail=detail))


def _text(v: str | None) -> str | None:
    return (v or "").strip() or None


def _lease(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID) -> Lease:
    lease = lease_in_org(session, organization_id, lease_id)
    if lease is None:
        raise LookupError("계약을 찾을 수 없습니다")
    return lease


# ── 점검 ─────────────────────────────────────────────────────

def _template(session: Session, lease: Lease) -> list[tuple[str, uuid.UUID | None]]:
    """(항목 이름, 품목 id). 기본 공간 + 그 호실에서 쓰는 자산대장 품목."""
    fixtures = session.scalars(select(Fixture).where(Fixture.unit_id == lease.unit_id, Fixture.status == "in_use")
                               .order_by(Fixture.created_at)).all()
    return [(a, None) for a in STANDARD_AREAS] + [
        (f"{f.name} (임차인 소유)" if f.owner == "tenant" else f.name, f.id) for f in fixtures]


def create_inspection(session: Session, organization_id: uuid.UUID, user_id, lease_id: uuid.UUID, kind: str,
                      inspected_on: date) -> Inspection:
    lease = _lease(session, organization_id, lease_id)
    if kind not in KINDS:
        raise MoveOutError("점검 종류는 입주 또는 퇴실입니다")
    if session.scalar(select(Inspection.id).where(Inspection.lease_id == lease.id, Inspection.kind == kind)):
        raise MoveOutError(f"이 계약의 {KINDS[kind]} 점검이 이미 있습니다")
    rows = _template(session, lease)
    if kind == "move_out":  # 입주 점검과 같은 항목·순서로 — 나란히 비교하려고. 입주 뒤 생긴 품목·직접 추가한 항목도 포함
        move_in = session.scalar(select(Inspection).where(Inspection.lease_id == lease.id, Inspection.kind == "move_in"))
        if move_in is not None:
            prev = [(i.area, i.fixture_id) for i in _items(session, move_in.id)]
            rows = prev + [r for r in rows if r not in prev]
    insp = Inspection(lease_id=lease.id, kind=kind, inspected_on=inspected_on)
    session.add(insp)
    session.flush()
    session.add_all(InspectionItem(inspection_id=insp.id, area=area, fixture_id=fid, position=n)
                    for n, (area, fid) in enumerate(rows))
    _audit(session, user_id, "inspection.create", "inspection", insp.id, {"kind": kind})
    session.commit()
    return insp


def _items(session: Session, inspection_id: uuid.UUID) -> list[InspectionItem]:
    return list(session.scalars(select(InspectionItem).where(InspectionItem.inspection_id == inspection_id)
                                .order_by(InspectionItem.position, InspectionItem.created_at)))


def get_inspection(session: Session, organization_id: uuid.UUID, inspection_id: uuid.UUID) -> Inspection:
    insp = session.get(Inspection, inspection_id)
    if insp is None or lease_in_org(session, organization_id, insp.lease_id) is None:
        raise LookupError("점검을 찾을 수 없습니다")
    return insp


def get_item(session: Session, organization_id: uuid.UUID, item_id: uuid.UUID) -> tuple[InspectionItem, Inspection]:
    item = session.get(InspectionItem, item_id)
    if item is None:
        raise LookupError("점검 항목을 찾을 수 없습니다")
    return item, get_inspection(session, organization_id, item.inspection_id)


def _unlocked(insp: Inspection) -> None:
    if insp.tenant_confirmed_on is not None:
        raise MoveOutError("임차인과 확인한 점검은 바꿀 수 없습니다. 고치려면 먼저 '확인 풀기'를 하세요 (기록이 남습니다)")


def update_inspection(session: Session, insp: Inspection, user_id, *, inspected_on: date,
                      note: str | None) -> Inspection:
    _unlocked(insp)
    insp.inspected_on, insp.note = inspected_on, _text(note)
    _audit(session, user_id, "inspection.update", "inspection", insp.id)
    session.commit()
    return insp


def confirm_inspection(session: Session, insp: Inspection, user_id, confirmed_on: date,
                       note: str | None) -> Inspection:
    _unlocked(insp)
    insp.tenant_confirmed_on, insp.confirm_note = confirmed_on, _text(note)
    _audit(session, user_id, "inspection.confirm", "inspection", insp.id, {"on": confirmed_on.isoformat()})
    session.commit()
    return insp


def unconfirm_inspection(session: Session, insp: Inspection, user_id, reason: str | None) -> Inspection:
    if insp.tenant_confirmed_on is None:
        raise MoveOutError("확인하지 않은 점검입니다")
    _audit(session, user_id, "inspection.unconfirm", "inspection", insp.id,
           {"was": insp.tenant_confirmed_on.isoformat(), "reason": _text(reason)})
    insp.tenant_confirmed_on, insp.confirm_note = None, None
    session.commit()
    return insp


def delete_inspection(session: Session, insp: Inspection, user_id) -> None:
    _unlocked(insp)
    items = _items(session, insp.id)
    if session.scalar(select(SettlementDeduction.id).where(
            SettlementDeduction.inspection_item_id.in_([i.id for i in items])).limit(1)):
        raise MoveOutError("정산 공제 항목이 이 점검을 근거로 하고 있습니다. 공제 항목을 먼저 고치세요")
    photos = list(session.scalars(select(InspectionPhoto).where(InspectionPhoto.item_id.in_([i.id for i in items]))))
    files = [p.file_path for p in photos]
    for p in photos:
        session.delete(p)
    session.flush()
    for i in items:
        session.delete(i)
    session.flush()
    _audit(session, user_id, "inspection.delete", "inspection", insp.id, {"kind": insp.kind, "photos": len(files)})
    session.delete(insp)
    session.commit()
    for name in files:  # 커밋 뒤 파일 정리
        storage.delete(name)


def add_item(session: Session, insp: Inspection, user_id, area: str) -> InspectionItem:
    _unlocked(insp)
    if not area.strip():
        raise MoveOutError("항목 이름을 적어 주세요")
    last = session.scalar(select(func.max(InspectionItem.position)).where(InspectionItem.inspection_id == insp.id))
    item = InspectionItem(inspection_id=insp.id, area=area.strip()[:50], position=(last or 0) + 1)
    session.add(item)
    session.flush()
    _audit(session, user_id, "inspection.item_add", "inspection", insp.id, {"area": item.area})
    session.commit()
    return item


def update_item(session: Session, item: InspectionItem, insp: Inspection, *, condition: str | None,
                reading: str | None, note: str | None) -> InspectionItem:
    _unlocked(insp)
    if condition is not None and condition not in CONDITIONS:
        raise MoveOutError("상태는 양호·생활 마모·오염·파손·없음 중 하나입니다")
    item.condition, item.reading, item.note = condition, _text(reading), _text(note)
    session.commit()
    return item


def delete_item(session: Session, item: InspectionItem, insp: Inspection, user_id) -> None:
    _unlocked(insp)
    if session.scalar(select(InspectionPhoto.id).where(InspectionPhoto.item_id == item.id).limit(1)):
        raise MoveOutError("사진이 있는 항목은 지울 수 없습니다. 사진을 먼저 지우세요")
    if session.scalar(select(SettlementDeduction.id).where(SettlementDeduction.inspection_item_id == item.id).limit(1)):
        raise MoveOutError("정산 공제 항목이 이 항목을 근거로 하고 있습니다")
    _audit(session, user_id, "inspection.item_delete", "inspection", insp.id, {"area": item.area})
    session.delete(item)
    session.commit()


def add_photo(session: Session, item: InspectionItem, insp: Inspection, user_id, raw: bytes) -> InspectionPhoto:
    _unlocked(insp)
    if len(raw) > MAX_PHOTO_BYTES:
        raise UploadError("사진이 너무 큽니다 (4MB 이하)", 413)
    _, content_type = detect(raw)
    if not content_type.startswith("image/"):
        raise UploadError("사진(JPG·PNG)만 올릴 수 있습니다", 415)
    count = session.scalar(select(func.count()).select_from(InspectionPhoto).where(InspectionPhoto.item_id == item.id))
    if count >= MAX_PHOTOS_PER_ITEM:
        raise MoveOutError(f"항목마다 사진은 {MAX_PHOTOS_PER_ITEM}장까지입니다")
    digest = hashlib.sha256(raw).hexdigest()
    if session.scalar(select(InspectionPhoto.id).where(InspectionPhoto.item_id == item.id,
                                                       InspectionPhoto.sha256 == digest)):
        raise MoveOutError("이 항목에 이미 올린 사진입니다")
    photo = InspectionPhoto(item_id=item.id, file_path=storage.save(raw), content_type=content_type, size=len(raw),
                            sha256=digest)
    session.add(photo)
    session.flush()
    _audit(session, user_id, "inspection.photo_add", "inspection", insp.id, {"sha256": digest})
    session.commit()
    return photo


def get_photo(session: Session, organization_id: uuid.UUID, photo_id: uuid.UUID) -> tuple[InspectionPhoto, Inspection]:
    photo = session.get(InspectionPhoto, photo_id)
    if photo is None:
        raise LookupError("사진을 찾을 수 없습니다")
    _, insp = get_item(session, organization_id, photo.item_id)
    return photo, insp


def delete_photo(session: Session, photo: InspectionPhoto, insp: Inspection, user_id) -> None:
    _unlocked(insp)
    name = photo.file_path
    _audit(session, user_id, "inspection.photo_delete", "inspection", insp.id, {"sha256": photo.sha256})
    session.delete(photo)
    session.commit()
    storage.delete(name)


def _inspection_out(session: Session, insp: Inspection | None) -> dict | None:
    if insp is None:
        return None
    items = _items(session, insp.id)
    photos: dict[uuid.UUID, list[dict]] = {}
    for p in session.scalars(select(InspectionPhoto).where(InspectionPhoto.item_id.in_([i.id for i in items]))
                             .order_by(InspectionPhoto.created_at)):
        photos.setdefault(p.item_id, []).append({"id": str(p.id), "uploaded_at": p.created_at, "size": p.size})
    return {"id": str(insp.id), "kind": insp.kind, "inspected_on": insp.inspected_on,
            "tenant_confirmed_on": insp.tenant_confirmed_on, "confirm_note": insp.confirm_note, "note": insp.note,
            "locked": insp.tenant_confirmed_on is not None,
            "items": [{"id": str(i.id), "area": i.area, "fixture_id": str(i.fixture_id) if i.fixture_id else None,
                       "condition": i.condition, "reading": i.reading, "note": i.note,
                       "photos": photos.get(i.id, [])} for i in items]}


def overview(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID) -> dict:
    lease = _lease(session, organization_id, lease_id)
    unit_no, tenant = session.execute(select(Unit.label, Tenant.name).join(Lease, Lease.unit_id == Unit.id)
                                      .join(Tenant, Lease.tenant_id == Tenant.id).where(Lease.id == lease.id)).one()
    by_kind = {i.kind: i for i in session.scalars(select(Inspection).where(Inspection.lease_id == lease.id))}
    return {"lease": {"id": str(lease.id), "unit_no": unit_no, "tenant_name": tenant, "start_date": lease.start_date,
                      "end_date": lease.end_date, "deposit": lease.deposit, "rent": lease.rent, "status": lease.status},
            "move_in": _inspection_out(session, by_kind.get("move_in")),
            "move_out": _inspection_out(session, by_kind.get("move_out"))}


# ── 퇴실 정산 ─────────────────────────────────────────────────

def _settlement(session: Session, lease_id: uuid.UUID, create: bool = False) -> MoveOutSettlement | None:
    s = session.scalar(select(MoveOutSettlement).where(MoveOutSettlement.lease_id == lease_id))
    if s is None and create:
        s = MoveOutSettlement(lease_id=lease_id, status="draft")
        session.add(s)
        session.flush()
    return s


def _draft(s: MoveOutSettlement) -> None:
    if s.status == "confirmed":
        raise MoveOutError("확정한 정산서는 바꿀 수 없습니다. 고치려면 먼저 '확정 풀기'를 하세요")


def _deduction_values(session: Session, lease_id: uuid.UUID, *, category: str, label: str, amount: int,
                      disputed: bool, inspection_item_id: uuid.UUID | None, note: str | None) -> dict:
    if category not in DEDUCTION_CATEGORIES:
        raise MoveOutError("공제 종류를 고르세요")
    if not label.strip():
        raise MoveOutError("무엇을 공제하는지 적어 주세요")
    if amount < 0:
        raise MoveOutError("공제 금액은 0원 이상입니다")
    if inspection_item_id is not None:
        item = session.get(InspectionItem, inspection_item_id)
        insp = session.get(Inspection, item.inspection_id) if item else None
        if insp is None or insp.lease_id != lease_id:
            raise LookupError("이 계약의 점검 항목이 아닙니다")
    return {"category": category, "label": label.strip()[:100], "amount": amount, "disputed": disputed,
            "inspection_item_id": inspection_item_id, "note": _text(note)}


def add_deduction(session: Session, organization_id: uuid.UUID, user_id, lease_id: uuid.UUID, **fields) -> SettlementDeduction:
    lease = _lease(session, organization_id, lease_id)
    s = _settlement(session, lease.id, create=True)
    _draft(s)
    d = SettlementDeduction(settlement_id=s.id, **_deduction_values(session, lease.id, **fields))
    session.add(d)
    session.flush()
    _audit(session, user_id, "settlement.deduction_add", "move_out_settlement", s.id,
           {"category": d.category, "amount": d.amount, "disputed": d.disputed})
    session.commit()
    return d


def get_deduction(session: Session, organization_id: uuid.UUID, deduction_id: uuid.UUID) -> tuple[SettlementDeduction, MoveOutSettlement]:
    d = session.get(SettlementDeduction, deduction_id)
    s = session.get(MoveOutSettlement, d.settlement_id) if d else None
    if s is None or lease_in_org(session, organization_id, s.lease_id) is None:
        raise LookupError("공제 항목을 찾을 수 없습니다")
    return d, s


def update_deduction(session: Session, d: SettlementDeduction, s: MoveOutSettlement, user_id, **fields) -> SettlementDeduction:
    _draft(s)
    for k, v in _deduction_values(session, s.lease_id, **fields).items():
        setattr(d, k, v)
    _audit(session, user_id, "settlement.deduction_update", "move_out_settlement", s.id,
           {"amount": d.amount, "disputed": d.disputed})
    session.commit()
    return d


def delete_deduction(session: Session, d: SettlementDeduction, s: MoveOutSettlement, user_id) -> None:
    _draft(s)
    _audit(session, user_id, "settlement.deduction_delete", "move_out_settlement", s.id, {"amount": d.amount})
    session.delete(d)
    session.commit()


def compute(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID, as_of: date) -> dict:
    """정산서. 확정했으면 확정 때 숫자(snapshot)를 그대로 돌려준다."""
    lease = _lease(session, organization_id, lease_id)
    s = _settlement(session, lease.id)
    if s is not None and s.status == "confirmed" and s.snapshot:
        return {**s.snapshot, "status": "confirmed", "confirmed_at": s.confirmed_at, "note": s.note,
                "settlement_id": str(s.id)}

    tranches = list(session.scalars(select(Deposit).where(Deposit.lease_id == lease.id, Deposit.received_at.is_not(None))))
    unreturned = [d for d in tranches if d.returned_at is None]
    deposit_known = bool(tranches) or lease.deposit == 0
    deposit_unreturned = int(sum(d.amount for d in unreturned)) if deposit_known else None
    returned_on = max((d.returned_at for d in tranches if d.returned_at), default=None) if tranches and not unreturned else None

    # 금액은 원 단위 정수로 — PostgreSQL 의 SUM 은 Decimal 을 돌려줘 그대로 두면 API 에서 문자열이 되고 JSON 스냅숏에 못 담긴다
    unpaid = [{"period": c.period, "due_date": c.due_date, "amount": int(remaining)}
              for c, remaining in ledger.open_charges(session, lease.id) if c.due_date <= as_of and remaining > 0]
    unpaid_total = sum(u["amount"] for u in unpaid)
    credit = int(ledger.lease_credit(session, lease.id))

    deductions = list(session.scalars(select(SettlementDeduction).where(SettlementDeduction.settlement_id == s.id)
                                      .order_by(SettlementDeduction.created_at))) if s else []
    items = {i.id: i for i in session.scalars(select(InspectionItem).where(
        InspectionItem.id.in_([d.inspection_item_id for d in deductions if d.inspection_item_id])))}
    agreed = sum(d.amount for d in deductions if not d.disputed)
    held = sum(d.amount for d in deductions if d.disputed)

    warnings: list[str] = []
    if not deposit_known:
        warnings.append("보증금 수령 기록이 없어 돌려줄 금액을 계산하지 않습니다. 임대료 관리에서 보증금 입금을 먼저 확정하세요")
    if returned_on:
        warnings.append(f"보증금을 이미 돌려준 기록이 있습니다 ({returned_on.isoformat()})")
    pending = receivables.unconfirmed_count(session, organization_id, "in")
    if pending:
        warnings.append(f"입금 검토 대기 {pending}건 — 확정하기 전에는 미납 금액이 실제와 다를 수 있습니다")
    latest = receivables.latest_transaction_at(session, organization_id)
    if latest is None:
        warnings.append("은행 거래내역이 없습니다. 미납 금액의 근거가 없습니다")
    if not session.scalar(select(Inspection.id).where(Inspection.lease_id == lease.id, Inspection.kind == "move_out")):
        warnings.append("퇴실 점검 기록이 없습니다. 파손·청소 공제를 하려면 사진과 함께 점검을 먼저 남기세요")
    for d in deductions:
        it = items.get(d.inspection_item_id)
        if it is not None and it.condition == "worn" and d.category == "damage":
            warnings.append(f"'{d.label}': 점검 상태가 '생활 마모'입니다 — 통상 사용에 따른 마모는 보통 공제 대상이 아닙니다")

    return_now = None if deposit_unreturned is None else deposit_unreturned + credit - unpaid_total - agreed - held
    return {
        "settlement_id": str(s.id) if s else None, "status": s.status if s else "draft", "confirmed_at": None,
        "note": s.note if s else None, "as_of": as_of,
        "deposit_unreturned": deposit_unreturned, "deposit_returned_on": returned_on,
        "prepaid_credit": credit, "unpaid": unpaid, "unpaid_total": unpaid_total,
        "deductions": [{"id": str(d.id), "category": d.category, "label": d.label, "amount": d.amount,
                        "disputed": d.disputed, "note": d.note,
                        "inspection_item_id": str(d.inspection_item_id) if d.inspection_item_id else None,
                        "inspection_item_area": items[d.inspection_item_id].area if d.inspection_item_id in items else None}
                       for d in deductions],
        "agreed_deductions": agreed, "disputed_held": held,
        # 먼저 돌려줄 금액 (다툼 있는 금액은 빼서 따로 둠). 음수면 임차인에게 받을 금액
        "return_now": return_now,
        "bank_data_as_of": latest, "warnings": warnings,
    }


def confirm_settlement(session: Session, organization_id: uuid.UUID, user_id, lease_id: uuid.UUID, as_of: date,
                       note: str | None) -> dict:
    lease = _lease(session, organization_id, lease_id)
    s = _settlement(session, lease.id, create=True)
    _draft(s)
    s.note = _text(note)
    snap = compute(session, organization_id, lease.id, as_of)
    if snap["return_now"] is None:
        raise MoveOutError("보증금 수령 기록이 없어 정산서를 확정할 수 없습니다")
    snap = {k: v for k, v in snap.items() if k not in ("status", "confirmed_at", "note", "settlement_id")}
    s.snapshot = _jsonable(snap)
    s.status, s.confirmed_at = "confirmed", datetime.now(timezone.utc)
    _audit(session, user_id, "settlement.confirm", "move_out_settlement", s.id,
           {"return_now": snap["return_now"], "disputed_held": snap["disputed_held"]})
    session.commit()
    return compute(session, organization_id, lease.id, as_of)


def reopen_settlement(session: Session, organization_id: uuid.UUID, user_id, lease_id: uuid.UUID,
                      reason: str | None) -> None:
    lease = _lease(session, organization_id, lease_id)
    s = _settlement(session, lease.id)
    if s is None or s.status != "confirmed":
        raise MoveOutError("확정한 정산서가 없습니다")
    _audit(session, user_id, "settlement.reopen", "move_out_settlement", s.id,
           {"was": s.snapshot.get("return_now") if s.snapshot else None, "reason": _text(reason)})
    s.status, s.confirmed_at, s.snapshot = "draft", None, None
    session.commit()


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def leases_for_move(session: Session, organization_id: uuid.UUID) -> list[dict]:
    """점검·정산 대상 계약 목록 (진행 중 계약 전부)과 점검·정산 상태."""
    rows = session.execute(
        select(Lease, Unit.label, Tenant.name).join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id).join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Property.organization_id == organization_id).order_by(Unit.label, Lease.start_date)).all()
    kinds: dict[uuid.UUID, set[str]] = {}
    for lid, kind in session.execute(select(Inspection.lease_id, Inspection.kind)
                                     .where(Inspection.lease_id.in_([r[0].id for r in rows]))):
        kinds.setdefault(lid, set()).add(kind)
    settled = dict(session.execute(select(MoveOutSettlement.lease_id, MoveOutSettlement.status)
                                   .where(MoveOutSettlement.lease_id.in_([r[0].id for r in rows]))).all())
    return [{"lease_id": str(lease.id), "unit_no": unit_no, "tenant_name": name, "start_date": lease.start_date,
             "end_date": lease.end_date, "status": lease.status,
             "move_in": "move_in" in kinds.get(lease.id, set()), "move_out": "move_out" in kinds.get(lease.id, set()),
             "settlement": settled.get(lease.id)} for lease, unit_no, name in rows]
