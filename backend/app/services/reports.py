"""월 결산 — 임대 순운영수익(NOI).

NOI = 그 달 확정된 월세 입금 − 그 달 운영비
- 운영비: 공용전기·수도·청소·수리·공용 기타 (expenses)
- 제외(따로 보여줌): 주인세대 비용, 개인 생활비, 보증금 수령/반환
- 그 달 거래 중 확정 안 된 것이 있으면 complete=False → 화면은 "확정 전 수치"
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Charge, Expense, Lease, Property, Transaction, TransactionAllocation, Unit
from app.services.charges import parse_period
from app.services.expenses import NON_OPERATING, OPERATING
from app.services.matching import org_transactions

KST = ZoneInfo("Asia/Seoul")


def month_range(period: str) -> tuple[date, date, datetime, datetime]:
    """[1일, 다음 달 1일) — 날짜와, 그 KST 경계를 UTC 로 바꾼 시각."""
    y, m = parse_period(period)
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    to_utc = lambda d: datetime.combine(d, time(), KST).astimezone(timezone.utc)  # noqa: E731
    return first, nxt, to_utc(first), to_utc(nxt)


def monthly(session: Session, organization_id: uuid.UUID, period: str) -> dict:
    first, nxt, start, end = month_range(period)
    in_month = org_transactions(organization_id).where(
        Transaction.occurred_at >= start, Transaction.occurred_at < end)
    txn_ids = in_month.with_only_columns(Transaction.id)

    def alloc_sum(category: str) -> int:
        return session.scalar(
            select(func.coalesce(func.sum(TransactionAllocation.amount), 0)).where(
                TransactionAllocation.transaction_id.in_(txn_ids),
                TransactionAllocation.category == category,
                TransactionAllocation.review_status == "approved"))

    expenses = dict(session.execute(
        select(Expense.category, func.sum(Expense.amount))
        .where(Expense.organization_id == organization_id,
               Expense.spent_on >= first, Expense.spent_on < nxt)
        .group_by(Expense.category)
    ).all())

    rent_charged, charge_count = session.execute(
        select(func.coalesce(func.sum(Charge.amount), 0), func.count(Charge.id))
        .join(Lease, Charge.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .where(Property.organization_id == organization_id, Charge.period == period)).one()

    approved = aliased(TransactionAllocation)
    unconfirmed = dict(session.execute(
        in_month.where(~select(approved.id).where(
            approved.transaction_id == Transaction.id, approved.review_status == "approved").exists())
        .with_only_columns(Transaction.direction, func.count())
        .group_by(Transaction.direction)
    ).all())

    earliest, latest = (
        t.replace(tzinfo=timezone.utc) if t is not None and t.tzinfo is None else t  # SQLite 는 시간대 없이 돌려줌 (저장은 UTC)
        for t in session.execute(org_transactions(organization_id).where(Transaction.source == "statement")
                                 .with_only_columns(func.min(Transaction.occurred_at),
                                                    func.max(Transaction.occurred_at))).one())
    # 모르면 비워 둔다 (CLAUDE.md 규칙 7): 청구 전이면 청구액을, 은행 내역 기간이 이 달과 겹치지 않으면 입금·지출을 모름
    charges_ready = charge_count > 0
    bank_covered = latest is not None and earliest < end and latest >= start
    known = lambda v: int(v) if bank_covered else None  # noqa: E731
    operating = {c: known(expenses.get(c, 0)) for c in OPERATING}
    operating_total = known(sum(int(expenses.get(c, 0)) for c in OPERATING))
    rent_received = known(alloc_sum("rent"))
    return {
        "period": period,
        "charges_ready": charges_ready,
        "bank_covered": bank_covered,
        "rent_charged": int(rent_charged) if charges_ready else None,
        "rent_received": rent_received,
        "operating": operating,
        "operating_total": operating_total,
        "noi": rent_received - operating_total if bank_covered else None,
        "excluded": {
            **{c: known(expenses.get(c, 0)) for c in NON_OPERATING},
            "deposit_in": known(alloc_sum("deposit_in")),
            "deposit_out": known(alloc_sum("deposit_out")),
        },
        "unconfirmed_in": int(unconfirmed.get("in", 0)),
        "unconfirmed_out": int(unconfirmed.get("out", 0)),
        "complete": not unconfirmed,
        "bank_data_as_of": latest,
    }
