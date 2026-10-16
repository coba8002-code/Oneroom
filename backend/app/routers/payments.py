"""입금 매칭 · 검토 대기열 · 미수 현황."""
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import BankAccount, Organization, Transaction, TransactionAllocation
from app.schemas import (
    AllocationOut,
    DecisionIn,
    LeaseOut,
    MatchRunOut,
    OrganizationOut,
    QueueItem,
    ReceivablesOut,
    SuggestionOut,
    TransactionOut,
)
from app.services import matching
from app.services import receivables as receivables_service

router = APIRouter(prefix="/api/v1", tags=["payments"])
KST = ZoneInfo("Asia/Seoul")


def _txn_out(t: Transaction) -> TransactionOut:
    return TransactionOut(id=t.id, occurred_at=t.occurred_at, amount=t.amount, direction=t.direction,
                          counterparty=t.counterparty, description=t.description)


def _unit_nos(session: Session, organization_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return {li.lease.id: li.unit_no for li in matching.active_leases(session, organization_id)}


def _org_txns(organization_id: uuid.UUID):
    return (select(Transaction).join(BankAccount, Transaction.bank_account_id == BankAccount.id)
            .where(BankAccount.organization_id == organization_id))


@router.get("/organizations", response_model=list[OrganizationOut])
def organizations(session: Session = Depends(get_session)) -> list[OrganizationOut]:
    return [OrganizationOut(id=o.id, name=o.name)
            for o in session.scalars(select(Organization).order_by(Organization.created_at))]


@router.get("/leases", response_model=list[LeaseOut])
def leases(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> list[LeaseOut]:
    return [LeaseOut(lease_id=li.lease.id, unit_no=li.unit_no, tenant_name=li.tenant_name,
                     rent=li.lease.rent, due_day=li.lease.due_day)
            for li in matching.active_leases(session, organization_id)]


@router.post("/matching/run", response_model=MatchRunOut)
def run(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> MatchRunOut:
    return MatchRunOut(**matching.run_matching(session, organization_id))


@router.get("/matching/queue", response_model=list[QueueItem])
def queue(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> list[QueueItem]:
    """확정되지 않은 입금 거래. 제안이 있으면 함께."""
    active = select(TransactionAllocation.transaction_id).where(
        TransactionAllocation.review_status == "approved")
    txns = session.scalars(
        _org_txns(organization_id)
        .where(Transaction.direction == "in", Transaction.id.not_in(active))
        .order_by(Transaction.occurred_at)
    ).all()
    pending = {
        a.transaction_id: a for a in session.scalars(
            select(TransactionAllocation).where(
                TransactionAllocation.transaction_id.in_([t.id for t in txns]),
                TransactionAllocation.review_status == "pending"))
    } if txns else {}
    units = _unit_nos(session, organization_id)
    out = []
    for t in txns:
        a = pending.get(t.id)
        out.append(QueueItem(transaction=_txn_out(t), suggestion=SuggestionOut(
            allocation_id=a.id, lease_id=a.lease_id, unit_no=units.get(a.lease_id),
            category=a.category, confidence=float(a.confidence) if a.confidence is not None else None,
            reason=a.reason,
        ) if a else None))
    return out


@router.post("/transactions/{txn_id}/decision", response_model=AllocationOut)
def decision(txn_id: uuid.UUID, organization_id: uuid.UUID, body: DecisionIn,
             session: Session = Depends(get_session)) -> AllocationOut:
    try:
        alloc = matching.decide(session, organization_id, txn_id, lease_id=body.lease_id,
                                category=body.category, remember_alias=body.remember_alias)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except matching.MatchError as e:
        session.rollback()
        raise HTTPException(409, str(e))
    return _alloc_out(session, organization_id, alloc)


@router.post("/allocations/{allocation_id}/cancel", status_code=204)
def cancel(allocation_id: uuid.UUID, organization_id: uuid.UUID,
           session: Session = Depends(get_session)) -> None:
    try:
        matching.cancel(session, organization_id, allocation_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except matching.MatchError as e:
        raise HTTPException(409, str(e))


@router.get("/allocations", response_model=list[AllocationOut])
def allocations(organization_id: uuid.UUID, limit: int = 50,
                session: Session = Depends(get_session)) -> list[AllocationOut]:
    """최근 확정된 입금 배분 (자동 확정 포함). 잘못됐으면 취소."""
    rows = session.scalars(
        select(TransactionAllocation)
        .join(Transaction, TransactionAllocation.transaction_id == Transaction.id)
        .join(BankAccount, Transaction.bank_account_id == BankAccount.id)
        .where(BankAccount.organization_id == organization_id,
               TransactionAllocation.review_status == "approved")
        .order_by(Transaction.occurred_at.desc())
        .limit(min(limit, 200))
    ).all()
    return [_alloc_out(session, organization_id, a) for a in rows]


def _alloc_out(session: Session, organization_id: uuid.UUID, a: TransactionAllocation) -> AllocationOut:
    units = _unit_nos(session, organization_id)
    return AllocationOut(
        id=a.id, transaction=_txn_out(session.get(Transaction, a.transaction_id)),
        lease_id=a.lease_id, unit_no=units.get(a.lease_id), category=a.category, amount=a.amount,
        review_status=a.review_status,
        confidence=float(a.confidence) if a.confidence is not None else None, reason=a.reason,
    )


@router.get("/receivables", response_model=ReceivablesOut)
def receivables(organization_id: uuid.UUID, as_of: date | None = None,
                session: Session = Depends(get_session)) -> ReceivablesOut:
    """미수 현황. 독촉 여부는 판단하지 않는다 — 최신 거래 시각·검토 대기 건수를 함께 보여줄 뿐."""
    return receivables_service.compute(session, organization_id, as_of or datetime.now(KST).date())
