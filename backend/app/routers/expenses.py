"""운영비 분리 · 월 결산."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Expense, ExpenseRule, Property, Transaction, TransactionAllocation, Unit
from app.routers.payments import _txn_out
from app.schemas import (
    ClassifyOut,
    ConfirmedOut,
    ExpenseDecisionIn,
    ExpenseOut,
    ExpenseRuleOut,
    ManualExpenseIn,
    MonthlyReportOut,
    QueueItem,
    SuggestionOut,
    UnitOut,
)
from app.services import expenses, reports
from app.services.charges import parse_period
from app.services.matching import MatchError, org_transactions

router = APIRouter(prefix="/api/v1", tags=["expenses"])


def _unit_map(session: Session, organization_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(session.execute(
        select(Unit.id, Unit.label).join(Property, Unit.property_id == Property.id)
        .where(Property.organization_id == organization_id)).all())


@router.get("/units", response_model=list[UnitOut])
def units(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> list[UnitOut]:
    return [UnitOut(unit_id=i, unit_no=n)
            for i, n in sorted(_unit_map(session, organization_id).items(), key=lambda x: x[1])]


@router.post("/expenses/classify", response_model=ClassifyOut)
def classify(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> ClassifyOut:
    return ClassifyOut(**expenses.classify(session, organization_id))


@router.get("/expenses/queue", response_model=list[QueueItem])
def queue(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> list[QueueItem]:
    """확정되지 않은 출금 거래."""
    approved = select(TransactionAllocation.transaction_id).where(
        TransactionAllocation.review_status == "approved")
    txns = session.scalars(
        org_transactions(organization_id)
        .where(Transaction.direction == "out", Transaction.id.not_in(approved))
        .order_by(Transaction.occurred_at)).all()
    pending = {a.transaction_id: a for a in session.scalars(select(TransactionAllocation).where(
        TransactionAllocation.transaction_id.in_([t.id for t in txns]),
        TransactionAllocation.review_status == "pending"))} if txns else {}
    return [QueueItem(transaction=_txn_out(t), suggestion=SuggestionOut(
        allocation_id=a.id, lease_id=a.lease_id, unit_no=None, category=a.category,
        confidence=float(a.confidence) if a.confidence is not None else None, reason=a.reason,
    ) if (a := pending.get(t.id)) else None) for t in txns]


@router.post("/transactions/{txn_id}/expense-decision", response_model=ConfirmedOut)
def decide(txn_id: uuid.UUID, organization_id: uuid.UUID, body: ExpenseDecisionIn,
           session: Session = Depends(get_session)) -> ConfirmedOut:
    try:
        allocs = expenses.decide(
            session, organization_id, txn_id,
            splits=[expenses.Split(s.category, s.amount, s.unit_id) for s in body.splits],
            lease_id=body.lease_id, remember=body.remember)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except MatchError as e:
        session.rollback()
        raise HTTPException(409, str(e))
    return _confirmed(session, organization_id, session.get(Transaction, txn_id), allocs)


@router.post("/transactions/{txn_id}/expense-cancel", status_code=204)
def cancel(txn_id: uuid.UUID, organization_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    try:
        expenses.cancel(session, organization_id, txn_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except MatchError as e:
        raise HTTPException(409, str(e))


@router.get("/expenses/confirmed", response_model=list[ConfirmedOut])
def confirmed(organization_id: uuid.UUID, limit: int = 30,
              session: Session = Depends(get_session)) -> list[ConfirmedOut]:
    """최근 확정된 출금 (나눈 것은 묶어서)."""
    txns = session.scalars(
        org_transactions(organization_id)
        .where(Transaction.direction == "out", Transaction.id.in_(
            select(TransactionAllocation.transaction_id).where(
                TransactionAllocation.review_status == "approved")))
        .order_by(Transaction.occurred_at.desc()).limit(min(limit, 200))).all()
    out = []
    for t in txns:
        allocs = session.scalars(select(TransactionAllocation).where(
            TransactionAllocation.transaction_id == t.id,
            TransactionAllocation.review_status == "approved")).all()
        out.append(_confirmed(session, organization_id, t, allocs))
    return out


def _confirmed(session: Session, organization_id: uuid.UUID, t: Transaction, allocs) -> ConfirmedOut:
    unit_nos = _unit_map(session, organization_id)
    splits = []
    for a in allocs:
        unit_id = session.scalar(select(Expense.unit_id).where(Expense.transaction_allocation_id == a.id))
        splits.append({"category": a.category, "amount": a.amount, "unit_no": unit_nos.get(unit_id)})
    return ConfirmedOut(transaction=_txn_out(t), splits=splits, reason=allocs[0].reason if allocs else None)


@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(organization_id: uuid.UUID, period: str,
                  session: Session = Depends(get_session)) -> list[ExpenseOut]:
    try:
        first, nxt, _, _ = reports.month_range(period)
    except ValueError as e:
        raise HTTPException(422, str(e))
    unit_nos = _unit_map(session, organization_id)
    rows = session.scalars(select(Expense).where(
        Expense.organization_id == organization_id, Expense.spent_on >= first, Expense.spent_on < nxt,
    ).order_by(Expense.spent_on, Expense.created_at)).all()
    return [ExpenseOut(id=e.id, category=e.category, amount=e.amount, spent_on=e.spent_on, memo=e.memo,
                       unit_no=unit_nos.get(e.unit_id), from_bank=e.transaction_allocation_id is not None)
            for e in rows]


@router.post("/expenses", response_model=ExpenseOut, status_code=201)
def add_manual(organization_id: uuid.UUID, body: ManualExpenseIn,
               session: Session = Depends(get_session)) -> ExpenseOut:
    try:
        e = expenses.add_manual(session, organization_id, category=body.category, amount=body.amount,
                                spent_on=body.spent_on, memo=body.memo, unit_id=body.unit_id)
    except MatchError as err:
        raise HTTPException(409, str(err))
    return ExpenseOut(id=e.id, category=e.category, amount=e.amount, spent_on=e.spent_on, memo=e.memo,
                      unit_no=_unit_map(session, organization_id).get(e.unit_id), from_bank=False)


@router.delete("/expenses/{expense_id}", status_code=204)
def delete_manual(expense_id: uuid.UUID, organization_id: uuid.UUID,
                  session: Session = Depends(get_session)) -> None:
    try:
        expenses.delete_manual(session, organization_id, expense_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except MatchError as e:
        raise HTTPException(409, str(e))


@router.get("/expense-rules", response_model=list[ExpenseRuleOut])
def rules(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> list[ExpenseRuleOut]:
    return [ExpenseRuleOut(id=r.id, label=r.label, splits=r.splits) for r in session.scalars(
        select(ExpenseRule).where(ExpenseRule.organization_id == organization_id)
        .order_by(ExpenseRule.label))]


@router.delete("/expense-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, organization_id: uuid.UUID, session: Session = Depends(get_session)) -> None:
    """규칙만 지운다. 이미 확정된 거래는 그대로 (필요하면 거래별로 취소)."""
    r = session.scalar(select(ExpenseRule).where(
        ExpenseRule.id == rule_id, ExpenseRule.organization_id == organization_id))
    if r is None:
        raise HTTPException(404, "규칙을 찾을 수 없습니다")
    session.delete(r)
    session.commit()


@router.get("/reports/monthly", response_model=MonthlyReportOut)
def monthly(organization_id: uuid.UUID, period: str, session: Session = Depends(get_session)) -> MonthlyReportOut:
    try:
        parse_period(period)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return MonthlyReportOut(**reports.monthly(session, organization_id, period))
