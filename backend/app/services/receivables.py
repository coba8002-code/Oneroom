"""미수 현황 — 수납 화면과 대시보드가 함께 쓴다."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Charge, Lease, Property, Tenant, Transaction, TransactionAllocation, Unit
from app.schemas import CreditItem, ReceivableItem, ReceivablesOut
from app.services import ledger, matching
from app.services.matching import org_transactions


def unconfirmed_count(session: Session, organization_id: uuid.UUID, direction: str) -> int:
    approved = aliased(TransactionAllocation)
    return session.scalar(select(func.count()).select_from(
        org_transactions(organization_id)
        .where(Transaction.direction == direction,
               ~select(approved.id).where(approved.transaction_id == Transaction.id,
                                          approved.review_status == "approved").exists())
        .subquery()))


def latest_transaction_at(session: Session, organization_id: uuid.UUID):
    """통장 내역 파일이 어디까지 있나. 입금 알림은 '안 들어왔다'의 증거가 아니라 넣지 않는다."""
    return session.scalar(org_transactions(organization_id).where(Transaction.source == "statement")
                          .with_only_columns(func.max(Transaction.occurred_at)))


def compute(session: Session, organization_id: uuid.UUID, as_of: date) -> ReceivablesOut:
    rows = session.execute(
        select(Charge, Unit.unit_no, Tenant.name)
        .join(Lease, Charge.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Property.organization_id == organization_id,
               Charge.status.in_(("open", "partial")), Charge.due_date <= as_of)
        .order_by(Charge.due_date, Unit.unit_no)
    ).all()
    items = []
    for c, unit_no, name in rows:
        paid = ledger.paid_amount(session, c.id)
        if c.amount - paid <= 0:
            continue
        items.append(ReceivableItem(unit_no=unit_no, tenant_name=name, period=c.period,
                                    due_date=c.due_date, amount=c.amount, paid=paid,
                                    outstanding=c.amount - paid,
                                    days_past_due=max(0, (as_of - c.due_date).days)))

    credits = []
    for li in matching.active_leases(session, organization_id):
        credit = ledger.lease_credit(session, li.lease.id)
        if credit > 0:
            credits.append(CreditItem(unit_no=li.unit_no, credit=credit))

    return ReceivablesOut(as_of=as_of, bank_data_as_of=latest_transaction_at(session, organization_id),
                          pending_review=unconfirmed_count(session, organization_id, "in"),
                          items=items, credits=credits)
