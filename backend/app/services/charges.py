"""월 청구 생성.

규칙
- 납부일은 계약마다 다르다 (leases.due_day).
- 그 달에 납부일이 없으면 말일 (31일 → 2월 28/29일, 4월 30일).
- 납부일에 계약이 유효할 때만 청구한다 (start_date ≤ 납부일 ≤ end_date).
  일할 계산 없음 — 월세 전액 (CLAUDE.md "확정된 정책").
- (lease_id, period, kind) 유일 → 다시 실행해도 중복 청구 없음.
- 정액 관리비(leases.mgmt_fee)가 적혀 있으면 월세와 같은 납부일로 관리비 청구(kind='mgmt')를 따로 만든다.
  비어 있으면(모름) 만들지 않는다 — 그 계약의 월세에 관리비가 섞여 있을 수 있다.
- 선납 잔액이 있으면 새 청구에 바로 차감한다.
"""
from __future__ import annotations

import calendar
import re
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Charge, Lease, Property, Unit
from app.services.ledger import apply_credits

MONTHLY = ("rent", "mgmt")  # 계약에서 매달 생기는 청구 (공과금 배분 청구와 구분)
UTILITY_ITEMS = {"electricity": "전기", "water": "수도", "gas": "가스", "internet": "인터넷"}
KIND_LABEL = {"rent": "월세", "mgmt": "관리비", **UTILITY_ITEMS}


def kind_label(kind: str) -> str:
    return KIND_LABEL.get(kind, kind)


PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_period(period: str) -> tuple[int, int]:
    m = PERIOD_RE.match(period)
    if not m:
        raise ValueError("period 는 YYYY-MM 형식이어야 합니다")
    return int(m.group(1)), int(m.group(2))


def due_date_for(period: str, due_day: int) -> date:
    year, month = parse_period(period)
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(due_day, last))


def generate_charges(
    session: Session, organization_id: uuid.UUID, period: str
) -> tuple[list[tuple[Charge, str]], int]:
    """period 의 청구를 만든다. 반환: ([(charge, unit_no)], 이미 있던 건수)."""
    parse_period(period)
    rows = session.execute(
        select(Lease, Unit.label)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .where(Property.organization_id == organization_id, Lease.status == "active")
        .order_by(Unit.label)
    ).all()

    existing = {
        (c.lease_id, c.kind): c
        for c in session.scalars(
            select(Charge).where(Charge.period == period, Charge.kind.in_(MONTHLY),
                                Charge.lease_id.in_([r[0].id for r in rows]))
        )
    }

    result: list[tuple[Charge, str]] = []  # 월세 청구 (호실당 1건)
    already = 0
    new_leases: set[uuid.UUID] = set()
    mgmt_created = 0
    for lease, unit_no in rows:
        due = due_date_for(period, lease.due_day)
        if lease.start_date > due or (lease.end_date is not None and lease.end_date < due):
            continue
        if (lease.id, "rent") in existing:
            already += 1
            result.append((existing[(lease.id, "rent")], unit_no))
        else:
            charge = Charge(lease_id=lease.id, period=period, due_date=due, amount=lease.rent, status="open")
            session.add(charge)
            result.append((charge, unit_no))
            new_leases.add(lease.id)
        # 관리비는 월세 청구를 만들 때만 같이 만든다 — 이미 청구한 달에 나중에 관리비를 적어도 그 달은 그대로
        if lease.mgmt_fee and lease.id in new_leases and (lease.id, "mgmt") not in existing:
            session.add(Charge(lease_id=lease.id, period=period, due_date=due, amount=lease.mgmt_fee,
                               status="open", kind="mgmt"))
            mgmt_created += 1

    session.flush()
    for lease_id in new_leases:
        apply_credits(session, lease_id)

    created = len(result) - already
    session.add(AuditLog(
        action="charges.generate", entity_type="organization", entity_id=str(organization_id),
        detail={"period": period, "created": created, "already_existed": already, "mgmt_created": mgmt_created},
    ))
    session.commit()
    return result, already
