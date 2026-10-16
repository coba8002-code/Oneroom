"""원장: 승인된 입금을 청구에 배분한다.

- 승인된 rent 배분의 금액은 그 계약의 미납 청구에 오래된 것부터 채운다 (payments).
- 다 못 쓴 금액 = 선납 잔액. 새 청구가 생기면 apply_credits() 가 채운다.
- 청구 상태는 payments 합계로만 정한다: 0 → open, 일부 → partial, 전액 → paid.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Charge, Payment, TransactionAllocation


def paid_amount(session: Session, charge_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.charge_id == charge_id)
    )


def applied_amount(session: Session, allocation_id: uuid.UUID) -> int:
    return session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.transaction_allocation_id == allocation_id)
    )


def refresh_status(session: Session, charge: Charge) -> None:
    if charge.status == "waived":
        return
    paid = paid_amount(session, charge.id)
    charge.status = "paid" if paid >= charge.amount else ("partial" if paid > 0 else "open")


def open_charges(session: Session, lease_id: uuid.UUID) -> list[tuple[Charge, int]]:
    """미납 청구와 잔액, 납부일 오래된 순."""
    charges = session.scalars(
        select(Charge)
        .where(Charge.lease_id == lease_id, Charge.status.in_(("open", "partial")))
        .order_by(Charge.due_date, Charge.period)
    ).all()
    out = []
    for c in charges:
        remaining = c.amount - paid_amount(session, c.id)
        if remaining > 0:
            out.append((c, remaining))
    return out


def apply_rent(session: Session, allocation: TransactionAllocation) -> int:
    """승인된 rent 배분을 미납 청구에 채운다. 남은(선납) 금액을 돌려준다."""
    assert allocation.category == "rent" and allocation.review_status == "approved"
    left = allocation.amount - applied_amount(session, allocation.id)
    for charge, remaining in open_charges(session, allocation.lease_id):
        if left <= 0:
            break
        pay = min(left, remaining)
        session.add(Payment(charge_id=charge.id, transaction_allocation_id=allocation.id, amount=pay))
        session.flush()
        refresh_status(session, charge)
        left -= pay
    return left


def apply_credits(session: Session, lease_id: uuid.UUID) -> None:
    """선납 잔액이 남은 승인 배분을 오래된 것부터 새 청구에 채운다."""
    allocations = session.scalars(
        select(TransactionAllocation)
        .where(
            TransactionAllocation.lease_id == lease_id,
            TransactionAllocation.category == "rent",
            TransactionAllocation.review_status == "approved",
        )
        .order_by(TransactionAllocation.created_at)
    ).all()
    for a in allocations:
        if a.amount - applied_amount(session, a.id) > 0:
            apply_rent(session, a)


def lease_credit(session: Session, lease_id: uuid.UUID) -> int:
    approved = session.scalar(
        select(func.coalesce(func.sum(TransactionAllocation.amount), 0)).where(
            TransactionAllocation.lease_id == lease_id,
            TransactionAllocation.category == "rent",
            TransactionAllocation.review_status == "approved",
        )
    )
    applied = session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(TransactionAllocation, Payment.transaction_allocation_id == TransactionAllocation.id)
        .where(TransactionAllocation.lease_id == lease_id, TransactionAllocation.category == "rent",
               TransactionAllocation.review_status == "approved")
    )
    return approved - applied


def unapply(session: Session, allocation: TransactionAllocation) -> None:
    """배분 취소: 이 배분으로 만든 payments 를 지우고 청구 상태를 다시 계산."""
    payments = session.scalars(
        select(Payment).where(Payment.transaction_allocation_id == allocation.id)
    ).all()
    charge_ids = {p.charge_id for p in payments}
    for p in payments:
        session.delete(p)
    session.flush()
    for cid in charge_ids:
        refresh_status(session, session.get(Charge, cid))
