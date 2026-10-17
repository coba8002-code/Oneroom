"""계약 종료와 새 계약 (공실 → 입주).

규칙
- 종료일(퇴거일) 뒤에 납부일이 오는 청구는 받지 않는다 — 월 청구는 '납부일에 계약이 유효하면 그 달 전액'(일할 없음)이므로.
  아무것도 안 낸 청구만 면제(waived)하고, 일부라도 낸 청구는 그대로 두고 알린다 (돈이 섞인 것은 사람이 판단).
- 종료한다고 보증금이 사라지지 않는다. 돌려주기 전까지는 부채로 남고 홈에서 계속 알린다.
- 정산서 확정·보증금 반환이 안 됐어도 종료는 막지 않는다 — 대신 무엇이 남았는지 돌려준다.
- 잘못 종료했으면 되돌릴 수 있다 (그 호실에 새 계약이 없을 때). 종료 때 면제한 청구도 되살린다.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Charge, Deposit, Lease, MoveOutSettlement, Payment, Property, Tenant, Unit
from app.services import ledger
from app.services.contracts import lease_in_org


class LeaseError(Exception):
    pass


def _audit(session: Session, user_id, action: str, entity_id, detail: dict | None = None) -> None:
    session.add(AuditLog(user_id=user_id, action=action, entity_type="lease", entity_id=str(entity_id), detail=detail))


def _paid(session: Session, charge_id) -> int:
    return int(session.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.charge_id == charge_id)))


def _unreturned(session: Session, lease_id) -> int:
    return int(session.scalar(select(func.coalesce(func.sum(Deposit.amount), 0)).where(
        Deposit.lease_id == lease_id, Deposit.received_at.is_not(None), Deposit.returned_at.is_(None))))


def end_lease(session: Session, organization_id: uuid.UUID, user_id, lease_id: uuid.UUID, ended_on: date,
              reason: str | None) -> dict:
    lease = lease_in_org(session, organization_id, lease_id)
    if lease is None:
        raise LookupError("계약을 찾을 수 없습니다")
    if lease.status != "active":
        raise LeaseError("이미 종료된 계약입니다")
    if ended_on < lease.start_date:
        raise LeaseError("종료일이 계약 시작일보다 앞설 수 없습니다")
    waived, kept = [], []
    for c in session.scalars(select(Charge).where(Charge.lease_id == lease.id, Charge.due_date > ended_on,
                                                  Charge.status.in_(("open", "partial")))):
        if _paid(session, c.id) == 0:
            c.status = "waived"
            waived.append(c)
        else:
            kept.append(c)
    lease.status, lease.ended_on, lease.end_reason = "ended", ended_on, (reason or "").strip() or None
    unit = session.get(Unit, lease.unit_id)
    others = session.scalar(select(Lease.id).where(Lease.unit_id == unit.id, Lease.status == "active", Lease.id != lease.id))
    if others is None and unit.use_type == "rental":
        unit.status = "vacant"
    _audit(session, user_id, "lease.end", lease.id, {"ended_on": ended_on.isoformat(),
                                                     "waived_charge_ids": [str(c.id) for c in waived]})
    session.commit()

    settlement = session.scalar(select(MoveOutSettlement.status).where(MoveOutSettlement.lease_id == lease.id))
    remaining = [{"period": c.period, "amount": int(r)} for c, r in ledger.open_charges(session, lease.id) if r > 0]
    warnings = []
    if kept:
        warnings.append("종료일 뒤 납부일인데 일부 입금된 청구가 있어 그대로 두었습니다: "
                        + ", ".join(c.period for c in kept) + " — 돌려줄지 확인하세요")
    if remaining:
        warnings.append(f"남은 미납 {sum(r['amount'] for r in remaining):,}원 ({', '.join(r['period'] for r in remaining)})")
    if (dep := _unreturned(session, lease.id)):
        warnings.append(f"돌려줄 보증금 {dep:,}원이 남아 있습니다 — 반환 출금을 '보증금 반환'으로 확정하세요")
    if settlement != "confirmed":
        warnings.append("퇴실 정산서를 확정하지 않았습니다")
    return {"lease_id": str(lease.id), "ended_on": ended_on, "unit_status": unit.status,
            "waived": [c.period for c in waived], "warnings": warnings}


def undo_end(session: Session, organization_id: uuid.UUID, user_id, lease_id: uuid.UUID) -> dict:
    lease = lease_in_org(session, organization_id, lease_id)
    if lease is None:
        raise LookupError("계약을 찾을 수 없습니다")
    if lease.status != "ended":
        raise LeaseError("종료된 계약이 아닙니다")
    if session.scalar(select(Lease.id).where(Lease.unit_id == lease.unit_id, Lease.status == "active")):
        raise LeaseError("그 호실에 이미 새 계약이 있어 되돌릴 수 없습니다")
    last = session.scalar(select(AuditLog).where(AuditLog.action == "lease.end", AuditLog.entity_id == str(lease.id))
                          .order_by(AuditLog.created_at.desc()).limit(1))
    ids = [uuid.UUID(i) for i in ((last.detail or {}).get("waived_charge_ids", []) if last else [])]
    for c in session.scalars(select(Charge).where(Charge.id.in_(ids), Charge.status == "waived")):
        c.status = "open"
    lease.status, lease.ended_on, lease.end_reason = "active", None, None
    unit = session.get(Unit, lease.unit_id)
    unit.status = "occupied"
    _audit(session, user_id, "lease.end_undo", lease.id, {"restored_charges": len(ids)})
    session.commit()
    return {"lease_id": str(lease.id), "status": lease.status}


def new_lease(session: Session, organization_id: uuid.UUID, user_id, unit_id: uuid.UUID, *, tenant_name: str,
              tenant_phone: str | None, deposit: int, rent: int, due_day: int, start_date: date,
              end_date: date | None, deposit_received_on: date | None, signed_on: date | None = None) -> Lease:
    unit = session.scalar(select(Unit).join(Property, Unit.property_id == Property.id)
                          .where(Unit.id == unit_id, Property.organization_id == organization_id))
    if unit is None:
        raise LookupError("호실을 찾을 수 없습니다")
    if unit.use_type != "rental":
        raise LeaseError("주인세대에는 임대 계약을 넣을 수 없습니다")
    if session.scalar(select(Lease.id).where(Lease.unit_id == unit.id, Lease.status == "active")):
        raise LeaseError("이 호실에는 진행 중인 계약이 있습니다. 먼저 종료하세요")
    if not tenant_name.strip():
        raise LeaseError("임차인 이름을 적어 주세요")
    if deposit < 0 or rent < 0 or not 1 <= due_day <= 31:
        raise LeaseError("보증금·월세는 0원 이상, 납부일은 1~31일입니다")
    if end_date is not None and end_date <= start_date:
        raise LeaseError("만료일은 시작일보다 뒤여야 합니다")
    prev_end = session.scalar(select(func.max(Lease.ended_on)).where(Lease.unit_id == unit.id))
    if prev_end is not None and start_date <= prev_end:
        raise LeaseError(f"앞 계약이 {prev_end.isoformat()}에 끝났습니다. 시작일은 그 뒤로 정하세요")
    org_id = session.scalar(select(Property.organization_id).where(Property.id == unit.property_id))
    tenant = Tenant(organization_id=org_id, name=tenant_name.strip(), phone=(tenant_phone or "").strip() or None)
    session.add(tenant)
    session.flush()
    lease = Lease(unit_id=unit.id, tenant_id=tenant.id, start_date=start_date, end_date=end_date, deposit=deposit,
                  rent=rent, due_day=due_day, status="active", signed_on=signed_on)
    session.add(lease)
    session.flush()
    if deposit:
        session.add(Deposit(lease_id=lease.id, amount=deposit, received_at=deposit_received_on))  # 부채 — 수입 아님
    unit.status = "occupied"
    _audit(session, user_id, "lease.create", lease.id, {"unit_no": unit.unit_no})  # 이름·연락처는 기록하지 않음
    session.commit()
    return lease


def history(session: Session, organization_id: uuid.UUID) -> list[dict]:
    """호실별 계약 이력 (진행 중 + 종료). 공실 호실도 포함."""
    units = session.execute(select(Unit).join(Property, Unit.property_id == Property.id)
                            .where(Property.organization_id == organization_id).order_by(Unit.unit_no)).scalars().all()
    leases: dict[uuid.UUID, list] = {}
    for lease, name in session.execute(select(Lease, Tenant.name).join(Tenant, Lease.tenant_id == Tenant.id)
                                       .where(Lease.unit_id.in_([u.id for u in units]))
                                       .order_by(Lease.start_date.desc())):
        leases.setdefault(lease.unit_id, []).append({
            "lease_id": str(lease.id), "tenant_name": name, "status": lease.status, "start_date": lease.start_date,
            "end_date": lease.end_date, "signed_on": lease.signed_on, "ended_on": lease.ended_on, "end_reason": lease.end_reason,
            "deposit": lease.deposit, "rent": lease.rent, "deposit_unreturned": _unreturned(session, lease.id)})
    return [{"unit_id": str(u.id), "unit_no": u.unit_no, "use_type": u.use_type, "status": u.status,
             "leases": leases.get(u.id, [])} for u in units]
