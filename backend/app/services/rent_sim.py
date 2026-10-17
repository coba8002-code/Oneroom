"""전월세 시뮬레이션 — 지금 계약(사실값)에서 시작해 호실별 보증금·월세를 바꿔 본다.

- 운용 수익률·운영비·보유 현금·건물 가치는 관리자가 넣은 값만 쓴다. 비우면 그 값이 필요한 결과도 비운다 (추정하지 않음).
- 지난 12개월 실제 운영비는 '참고'로만 보여 주고 자동으로 넣지 않는다.
- 세금(간주임대료·종합소득세)은 계산하지 않는다 — 판정 기준은 관리자 확인이 필요 (CLAUDE.md '임의로 정하지 말 것').
- 반환 유동성: 앞으로 12개월 안에 만료되는 계약의 보증금을 달별로 묶고, 보유 현금과 비교한다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Lease, Property, Tenant, Unit
from app.services import reports


class SimError(Exception):
    pass


@dataclass
class Row:
    lease_id: str
    deposit: int
    rent: int


def _floor(v: Decimal) -> int:
    return int(v.to_integral_value(rounding=ROUND_FLOOR))


def _pct(v: str | None, label: str) -> Decimal | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        d = Decimal(str(v).strip())
    except Exception as e:  # noqa: BLE001
        raise SimError(f"{label}은 숫자로 적으세요") from e
    if not Decimal(-50) <= d <= Decimal(100):
        raise SimError(f"{label}이 범위를 벗어났습니다")
    return d


def _add_months(d: date, n: int) -> tuple[int, int]:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return y, m + 1


def baseline(session: Session, organization_id: uuid.UUID) -> list[dict]:
    rows = session.execute(
        select(Lease, Unit.unit_no, Tenant.name).join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id).join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Property.organization_id == organization_id, Lease.status == "active").order_by(Unit.unit_no)).all()
    return [{"lease_id": str(le.id), "unit_no": u, "tenant_name": n, "deposit": int(le.deposit), "rent": int(le.rent),
             "end_date": le.end_date} for le, u, n in rows]


def past_operating(session: Session, organization_id: uuid.UUID, as_of: date) -> dict:
    """지난 12개월 실제 운영비 (참고용). 은행 내역 없는 달은 빼고, 몇 달 치인지 함께."""
    total, months = 0, 0
    for i in range(1, 13):
        y, m = _add_months(as_of, -i)
        r = reports.monthly(session, organization_id, f"{y}-{m:02d}")
        if r["operating_total"] is not None:
            total += int(r["operating_total"])
            months += 1
    return {"months_with_data": months, "operating_total": total if months else None}


def _summary(rows: list[dict], yield_pct: Decimal | None, opex: int | None, property_value: int | None) -> dict:
    rent_year = sum(r["rent"] for r in rows) * 12
    deposits = sum(r["deposit"] for r in rows)
    dep_income = _floor(Decimal(deposits) * yield_pct / 100) if yield_pct is not None else None
    net = rent_year + dep_income - opex if dep_income is not None and opex is not None else None
    equity = property_value - deposits if property_value is not None else None
    return {"annual_rent": rent_year, "deposit_total": deposits, "deposit_income": dep_income, "annual_net": net,
            "equity": equity,
            "equity_yield_pct": (format((Decimal(net) * 100 / equity).quantize(Decimal("0.01")), "f")
                                 if net is not None and equity and equity > 0 else None)}


def simulate(session: Session, organization_id: uuid.UUID, as_of: date, scenario: list[Row], *,
             deposit_yield_pct: str | None, annual_opex: int | None, cash_on_hand: int | None,
             property_value: int | None) -> dict:
    base = baseline(session, organization_id)
    by_id = {b["lease_id"]: b for b in base}
    if any(r.lease_id not in by_id for r in scenario):
        raise SimError("진행 중인 계약이 아닌 항목이 있습니다")
    if any(r.deposit < 0 or r.rent < 0 for r in scenario):
        raise SimError("보증금·월세는 0원 이상입니다")
    for v, label in ((annual_opex, "운영비"), (cash_on_hand, "보유 현금"), (property_value, "건물 가치")):
        if v is not None and v < 0:
            raise SimError(f"{label}은 0원 이상입니다")
    yld = _pct(deposit_yield_pct, "운용 수익률")
    changed = {r.lease_id: r for r in scenario}
    after = [{**b, "deposit": changed[b["lease_id"]].deposit if b["lease_id"] in changed else b["deposit"],
              "rent": changed[b["lease_id"]].rent if b["lease_id"] in changed else b["rent"]} for b in base]

    # 반환 유동성: 만료일이 앞으로 12개월 안인 계약의 (시나리오) 보증금을 달별로
    schedule: dict[str, int] = {}
    for r in after:
        if r["end_date"] and as_of <= r["end_date"]:
            y, m = r["end_date"].year, r["end_date"].month
            if (y * 12 + m) - (as_of.year * 12 + as_of.month) < 12:
                key = f"{y}-{m:02d}"
                schedule[key] = schedule.get(key, 0) + r["deposit"]
    cumulative, worst = 0, 0
    months = []
    for key in sorted(schedule):
        cumulative += schedule[key]
        worst = max(worst, cumulative)
        months.append({"month": key, "due": schedule[key], "cumulative": cumulative,
                       "shortfall": max(0, cumulative - cash_on_hand) if cash_on_hand is not None else None})
    no_end = [r["unit_no"] for r in after if r["end_date"] is None]
    return {
        "as_of": as_of, "rows": [{**b, "new_deposit": a["deposit"], "new_rent": a["rent"]} for b, a in zip(base, after)],
        "current": _summary(base, yld, annual_opex, property_value),
        "scenario": _summary(after, yld, annual_opex, property_value),
        "liquidity": {"months": months, "max_cumulative_due": worst, "cash_on_hand": cash_on_hand,
                      "covered": cash_on_hand >= worst if cash_on_hand is not None else None,
                      "leases_without_end_date": no_end},
        "reference": past_operating(session, organization_id, as_of),
        "tax_note": "간주임대료·종합소득세 해당 여부와 세액은 계산하지 않습니다 (주택 수·보증금 합계 등 판정 기준은 세무사 확인).",
    }
