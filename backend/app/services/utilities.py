"""공과금 — 건물·항목(전기·수도·가스·인터넷)별 처리 방식과 배분 청구.

원룸마다 다르다: 공과금을 따로 나눠 받는 곳, 수도만 나누는 곳, 관리비(월세)에 포함된 곳, 임차인이 직접 내는 곳.
그래서 처리 방식은 건물·항목마다 관리자가 고른 값만 쓴다 (기본값으로 청구하지 않음).

- 나눠 청구(split)만 고지서를 받는다. 나누는 방법: 호실 수(equal) · 전용면적(area) · 호실별 직접 입력(manual)
- 균등·면적일 때 공실과 주인세대의 몫을 '집주인 부담'으로 셀지, 아예 빼고 나눌지도 관리자가 고른다
- 나눈 금액은 원 단위 정수, 합이 고지서 금액과 정확히 맞게 (최대 나머지 방식 — 끝수는 소수점이 큰 호실부터 1원씩)
- 청구 대상은 그 달 납부일에 계약이 유효한 호실 (월세 청구와 같은 기준). 면적이 없으면 계산하지 않고 알려 준다 (규칙 7)
- 청구하면 계약별 청구(Charge, kind=항목)가 월세와 같은 납부일로 생긴다. 입금이 배분되기 전까지만 취소할 수 있다
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Charge, Lease, Payment, Property, Unit, UtilityBill, UtilitySetting
from app.services.charges import due_date_for, parse_period
from app.services.ledger import apply_credits

ITEMS = {"electricity": "전기", "water": "수도", "gas": "가스", "internet": "인터넷"}
MODES = {"included": "월세·관리비에 포함 (따로 청구 안 함)", "split": "나눠서 청구", "direct": "임차인이 직접 납부"}
METHODS = {"equal": "호실 수로 똑같이", "area": "전용면적 비율로", "manual": "호실별 금액 직접 입력"}
SHARES = {"landlord": "몫을 나눈 뒤 집주인이 부담", "exclude": "빼고 나눔"}


class UtilityError(ValueError):
    pass


def _audit(session: Session, user_id, action: str, entity: str, entity_id, detail: dict | None = None) -> None:
    session.add(AuditLog(user_id=user_id, action=action, entity_type=entity, entity_id=str(entity_id), detail=detail))


def _property(session: Session, organization_id: uuid.UUID, property_id: uuid.UUID) -> Property:
    prop = session.get(Property, property_id)
    if prop is None or prop.organization_id != organization_id:
        raise LookupError("건물을 찾을 수 없습니다")
    return prop


def _setting_out(s: UtilitySetting | None) -> dict | None:
    return None if s is None else {"mode": s.mode, "method": s.method, "vacant": s.vacant, "owner": s.owner}


def settings(session: Session, organization_id: uuid.UUID) -> dict:
    props = session.scalars(select(Property).where(Property.organization_id == organization_id)
                            .order_by(Property.created_at)).all()
    rows = {(s.property_id, s.item): s for s in session.scalars(
        select(UtilitySetting).where(UtilitySetting.property_id.in_([p.id for p in props])))}
    return {
        "items": ITEMS, "modes": MODES, "methods": METHODS, "shares": SHARES,
        "buildings": [{"property_id": p.id, "name": p.name,
                       "settings": {k: _setting_out(rows.get((p.id, k))) for k in ITEMS}} for p in props],
    }


@dataclass
class SettingFields:
    mode: str
    method: str | None = None
    vacant: str | None = None
    owner: str | None = None


def save_setting(session: Session, organization_id: uuid.UUID, property_id: uuid.UUID, item: str, user_id,
                 f: SettingFields) -> UtilitySetting:
    prop = _property(session, organization_id, property_id)
    if item not in ITEMS:
        raise UtilityError("공과금 항목을 고르세요")
    if f.mode not in MODES:
        raise UtilityError("처리 방식을 고르세요")
    method = vacant = owner = None
    if f.mode == "split":
        if f.method not in METHODS:
            raise UtilityError("나누는 방법을 고르세요")
        method = f.method
        if method != "manual":
            if f.vacant not in SHARES or f.owner not in SHARES:
                raise UtilityError("공실과 주인세대 몫을 어떻게 할지 고르세요")
            vacant, owner = f.vacant, f.owner
    if f.mode != "split" and session.scalar(select(UtilityBill.id).where(
            UtilityBill.property_id == prop.id, UtilityBill.item == item, UtilityBill.status == "draft")):
        raise UtilityError("청구 전 고지서가 남아 있습니다. 먼저 청구하거나 지우세요")
    s = session.scalar(select(UtilitySetting).where(UtilitySetting.property_id == prop.id,
                                                    UtilitySetting.item == item))
    if s is None:
        s = UtilitySetting(property_id=prop.id, item=item, mode=f.mode)
        session.add(s)
    s.mode, s.method, s.vacant, s.owner = f.mode, method, vacant, owner
    s.updated_at = datetime.now(timezone.utc)
    session.flush()
    _audit(session, user_id, "utility.setting", "property", prop.id,
           {"item": item, "mode": f.mode, "method": method, "vacant": vacant, "owner": owner})
    session.commit()
    return s


# ── 나누기 ──────────────────────────────────────────────────

def _valid_lease(session: Session, unit: Unit, period: str) -> tuple[Lease, object] | None:
    """그 달 납부일에 유효한 진행 중 계약 (월세 청구와 같은 기준)."""
    for lease in session.scalars(select(Lease).where(Lease.unit_id == unit.id, Lease.status == "active")):
        due = due_date_for(period, lease.due_day)
        if lease.start_date <= due and (lease.end_date is None or lease.end_date >= due):
            return lease, due
    return None


def _largest_remainder(total: int, weights: list[Fraction]) -> list[int]:
    whole = sum(weights)
    exact = [total * w / whole for w in weights]
    shares = [int(x) for x in exact]  # 내림 (모두 0 이상)
    left = total - sum(shares)
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - shares[i]), i))
    for i in order[:left]:
        shares[i] += 1
    return shares


def split(session: Session, bill: UtilityBill, setting: UtilitySetting) -> dict:
    """고지서 한 장을 나눈 결과. 계산할 수 없으면 UtilityError (이유와 호실)."""
    units = session.scalars(select(Unit).where(Unit.property_id == bill.property_id).order_by(Unit.label)).all()
    rows = []
    for u in units:
        found = _valid_lease(session, u, bill.period) if u.use_type == "rental" else None
        if found:
            lease, due = found
            rows.append({"unit": u, "lease": lease, "due": due, "role": "leased"})
        elif u.use_type == "owner":
            rows.append({"unit": u, "lease": None, "due": None, "role": "owner"})
        else:
            rows.append({"unit": u, "lease": None, "due": None, "role": "vacant"})

    if setting.method == "manual":
        manual = {str(k): int(v) for k, v in (bill.manual or {}).items() if v is not None}
        unknown = [r["unit"].label for r in rows if str(r["unit"].id) in manual and r["role"] != "leased"]
        if unknown:
            raise UtilityError(f"그 달 계약이 없는 호실에는 금액을 넣을 수 없습니다: {', '.join(unknown)}")
        if any(v < 0 for v in manual.values()):
            raise UtilityError("금액은 0원 이상입니다")
        billed = sum(manual.values())
        if billed > bill.total:
            raise UtilityError(f"호실별 금액 합({billed:,}원)이 고지서 금액({bill.total:,}원)보다 큽니다")
        shares = [{"unit_id": r["unit"].id, "unit_no": r["unit"].label, "role": r["role"],
                   "lease_id": r["lease"].id if r["lease"] else None,
                   "amount": manual.get(str(r["unit"].id)) if r["role"] == "leased" else None,
                   "billed": r["role"] == "leased" and manual.get(str(r["unit"].id)) is not None}
                  for r in rows]
        landlord = bill.total - billed
    else:
        take = [r for r in rows if r["role"] == "leased"
                or (r["role"] == "vacant" and setting.vacant == "landlord")
                or (r["role"] == "owner" and setting.owner == "landlord")]
        if not any(r["role"] == "leased" for r in take):
            raise UtilityError("그 달 납부일에 계약이 있는 호실이 없습니다")
        if setting.method == "area":
            missing = [r["unit"].label for r in take if r["unit"].area_m2 is None]
            if missing:
                raise UtilityError(f"전용면적이 없는 호실이 있어 나눌 수 없습니다: {', '.join(missing)}")
            weights = [Fraction(str(r["unit"].area_m2)) for r in take]
        else:
            weights = [Fraction(1)] * len(take)
        amounts = dict(zip((r["unit"].id for r in take), _largest_remainder(bill.total, weights)))
        shares = [{"unit_id": r["unit"].id, "unit_no": r["unit"].label, "role": r["role"],
                   "lease_id": r["lease"].id if r["lease"] else None, "amount": amounts.get(r["unit"].id),
                   "billed": r["role"] == "leased"} for r in rows]
        billed = sum(s["amount"] for s in shares if s["billed"])
        landlord = bill.total - billed
    return {"method": setting.method, "vacant": setting.vacant, "owner": setting.owner, "shares": shares,
            "billed_total": billed, "landlord_total": landlord}


# ── 고지서 ──────────────────────────────────────────────────

def _split_setting(session: Session, property_id: uuid.UUID, item: str) -> UtilitySetting:
    s = session.scalar(select(UtilitySetting).where(UtilitySetting.property_id == property_id,
                                                    UtilitySetting.item == item))
    if s is None or s.mode != "split":
        raise UtilityError(f"{ITEMS.get(item, item)}는 '나눠서 청구'로 정해 둔 항목이 아닙니다. 공과금 설정에서 먼저 고르세요")
    return s


@dataclass
class BillFields:
    property_id: uuid.UUID
    item: str
    period: str
    total: int
    note: str | None = None
    manual: dict[str, int | None] | None = None


def _check(f: BillFields) -> None:
    if f.item not in ITEMS:
        raise UtilityError("공과금 항목을 고르세요")
    try:
        parse_period(f.period)
    except ValueError as e:
        raise UtilityError("청구 월은 YYYY-MM 형식입니다") from e
    if f.total <= 0:
        raise UtilityError("고지서 금액은 1원 이상입니다")


def _bill(session: Session, organization_id: uuid.UUID, bill_id: uuid.UUID) -> UtilityBill:
    b = session.get(UtilityBill, bill_id)
    if b is None:
        raise LookupError("고지서를 찾을 수 없습니다")
    _property(session, organization_id, b.property_id)
    return b


def create_bill(session: Session, organization_id: uuid.UUID, user_id, f: BillFields) -> UtilityBill:
    _check(f)
    prop = _property(session, organization_id, f.property_id)
    _split_setting(session, prop.id, f.item)
    if session.scalar(select(UtilityBill.id).where(UtilityBill.property_id == prop.id, UtilityBill.item == f.item,
                                                   UtilityBill.period == f.period)):
        raise UtilityError(f"{f.period} {ITEMS[f.item]} 고지서가 이미 있습니다")
    b = UtilityBill(property_id=prop.id, item=f.item, period=f.period, total=f.total,
                    note=(f.note or "").strip() or None, manual=f.manual, status="draft")
    session.add(b)
    session.flush()
    _audit(session, user_id, "utility.bill_create", "utility_bill", b.id, {"item": f.item, "period": f.period})
    session.commit()
    return b


def update_bill(session: Session, organization_id: uuid.UUID, bill_id: uuid.UUID, user_id,
                total: int, note: str | None, manual: dict | None) -> UtilityBill:
    b = _bill(session, organization_id, bill_id)
    if b.status != "draft":
        raise UtilityError("이미 청구한 고지서입니다. 고치려면 먼저 청구를 취소하세요")
    if total <= 0:
        raise UtilityError("고지서 금액은 1원 이상입니다")
    b.total, b.note, b.manual = total, (note or "").strip() or None, manual
    _audit(session, user_id, "utility.bill_update", "utility_bill", b.id)
    session.commit()
    return b


def delete_bill(session: Session, organization_id: uuid.UUID, bill_id: uuid.UUID, user_id) -> None:
    b = _bill(session, organization_id, bill_id)
    if b.status != "draft":
        raise UtilityError("이미 청구한 고지서입니다. 먼저 청구를 취소하세요")
    _audit(session, user_id, "utility.bill_delete", "utility_bill", b.id)
    session.delete(b)
    session.commit()


def bill_out(session: Session, b: UtilityBill) -> dict:
    out = {"id": b.id, "property_id": b.property_id, "item": b.item, "item_label": ITEMS.get(b.item, b.item),
           "period": b.period, "total": b.total, "note": b.note, "manual": b.manual, "status": b.status,
           "charged_at": b.charged_at, "split": None, "problem": None}
    if b.status == "charged":
        out["split"] = b.split_json
        return out
    setting = session.scalar(select(UtilitySetting).where(UtilitySetting.property_id == b.property_id,
                                                          UtilitySetting.item == b.item))
    if setting is None or setting.mode != "split":
        out["problem"] = "이 항목의 처리 방식이 '나눠서 청구'가 아닙니다"
        return out
    try:
        out["split"] = _json(split(session, b, setting))
    except UtilityError as e:
        out["problem"] = str(e)
    return out


def _json(result: dict) -> dict:
    return {**result, "shares": [{**s, "unit_id": str(s["unit_id"]),
                                  "lease_id": str(s["lease_id"]) if s["lease_id"] else None}
                                 for s in result["shares"]]}


def list_bills(session: Session, organization_id: uuid.UUID, period: str | None = None) -> list[dict]:
    q = (select(UtilityBill).join(Property, UtilityBill.property_id == Property.id)
         .where(Property.organization_id == organization_id))
    if period:
        q = q.where(UtilityBill.period == period)
    return [bill_out(session, b) for b in session.scalars(
        q.order_by(UtilityBill.period.desc(), Property.created_at, UtilityBill.item))]


def charge_bill(session: Session, organization_id: uuid.UUID, bill_id: uuid.UUID, user_id) -> UtilityBill:
    b = _bill(session, organization_id, bill_id)
    if b.status != "draft":
        raise UtilityError("이미 청구한 고지서입니다")
    result = split(session, b, _split_setting(session, b.property_id, b.item))
    targets = [s for s in result["shares"] if s["billed"] and s["amount"]]
    if not targets:
        raise UtilityError("청구할 금액이 있는 호실이 없습니다")
    taken = set(session.scalars(select(Charge.lease_id).where(
        Charge.lease_id.in_([s["lease_id"] for s in targets]), Charge.period == b.period, Charge.kind == b.item)))
    if taken:
        raise UtilityError(f"{b.period} {ITEMS[b.item]} 청구가 이미 있는 계약이 있습니다")
    for s in targets:
        lease = session.get(Lease, s["lease_id"])
        session.add(Charge(lease_id=lease.id, period=b.period, due_date=due_date_for(b.period, lease.due_day),
                           amount=s["amount"], status="open", kind=b.item, utility_bill_id=b.id))
    session.flush()
    for s in targets:
        apply_credits(session, s["lease_id"])  # 선납 잔액이 있으면 채운다 (월세 청구와 같게)
    b.status, b.charged_at, b.split_json = "charged", datetime.now(timezone.utc), _json(result)
    _audit(session, user_id, "utility.bill_charge", "utility_bill", b.id,
           {"item": b.item, "period": b.period, "charges": len(targets), "billed": result["billed_total"]})
    session.commit()
    return b


def uncharge_bill(session: Session, organization_id: uuid.UUID, bill_id: uuid.UUID, user_id) -> UtilityBill:
    b = _bill(session, organization_id, bill_id)
    if b.status != "charged":
        raise UtilityError("아직 청구하지 않은 고지서입니다")
    charges = session.scalars(select(Charge).where(Charge.utility_bill_id == b.id)).all()
    if session.scalar(select(Payment.id).where(Payment.charge_id.in_([c.id for c in charges])).limit(1)):
        raise UtilityError("입금이 배분된 청구가 있어 취소할 수 없습니다. 임대료 관리에서 그 배분을 먼저 취소하세요")
    for c in charges:
        session.delete(c)
    b.status, b.charged_at, b.split_json = "draft", None, None
    _audit(session, user_id, "utility.bill_uncharge", "utility_bill", b.id, {"charges": len(charges)})
    session.commit()
    return b
