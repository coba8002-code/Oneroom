"""입금 매칭 (PRD §4: 불확실하면 검토 대기).

자동 확정은 아래가 **모두** 맞을 때만:
  1) 입금자명(이름 또는 학습된 별칭)이 활성 계약 1건에만 일치
  2) 금액 = 그 계약의 가장 오래된 미납 청구 잔액
그 밖에는 제안(pending)만 만들고 관리자가 확정한다. 모든 배분은 근거·신뢰도를 남긴다.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    BankAccount,
    Deposit,
    Lease,
    PayerAlias,
    Property,
    Tenant,
    Transaction,
    TransactionAllocation,
    Unit,
)
from app.services import ledger

KST = ZoneInfo("Asia/Seoul")
AUTO_CONFIDENCE = 0.95


def normalize_name(name: str | None) -> str:
    return re.sub(r"\s+", "", name or "").lower()


@dataclass
class LeaseInfo:
    lease: Lease
    unit_no: str
    tenant_name: str


@dataclass
class Suggestion:
    lease_id: uuid.UUID | None
    category: str
    confidence: float
    reason: str
    auto: bool = False


class MatchError(ValueError):
    pass


def active_leases(session: Session, organization_id: uuid.UUID) -> list[LeaseInfo]:
    rows = session.execute(
        select(Lease, Unit.unit_no, Tenant.name)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Property.organization_id == organization_id, Lease.status == "active")
        .order_by(Unit.unit_no)
    ).all()
    return [LeaseInfo(lease, unit_no, name) for lease, unit_no, name in rows]


def _aliases(session: Session, organization_id: uuid.UUID) -> dict[str, uuid.UUID]:
    return {
        a.name: a.lease_id
        for a in session.scalars(select(PayerAlias).where(PayerAlias.organization_id == organization_id))
    }


def _unreceived_deposit(session: Session, lease_id: uuid.UUID) -> Deposit | None:
    return session.scalar(
        select(Deposit).where(Deposit.lease_id == lease_id, Deposit.received_at.is_(None)).limit(1)
    )


def suggest(session: Session, txn: Transaction, leases: list[LeaseInfo],
            aliases: dict[str, uuid.UUID]) -> Suggestion:
    payer = normalize_name(txn.counterparty)
    by_id = {li.lease.id: li for li in leases}

    def next_due(li: LeaseInfo) -> tuple[str, int] | None:
        oc = ledger.open_charges(session, li.lease.id)
        return (oc[0][0].period, oc[0][1]) if oc else None

    name_hits = {li.lease.id for li in leases if payer and normalize_name(li.tenant_name) == payer}
    if payer in aliases and aliases[payer] in by_id:
        name_hits.add(aliases[payer])

    if len(name_hits) == 1:
        li = by_id[next(iter(name_hits))]
        how = "별칭" if payer in aliases else "이름"
        nd = next_due(li)
        if nd and txn.amount == nd[1]:
            return Suggestion(li.lease.id, "rent", AUTO_CONFIDENCE,
                              f"입금자 {how} 일치 ({li.unit_no}) + 금액 = {nd[0]} 청구 잔액", auto=True)
        dep = _unreceived_deposit(session, li.lease.id)
        if dep and txn.amount == dep.amount:
            return Suggestion(li.lease.id, "deposit_in", 0.8,
                              f"입금자 {how} 일치 ({li.unit_no}) + 금액 = 미수령 보증금")
        if nd and txn.amount < nd[1]:
            return Suggestion(li.lease.id, "rent", 0.7,
                              f"입금자 {how} 일치 ({li.unit_no}), 청구 잔액보다 적음 → 부분납부?")
        if nd:
            return Suggestion(li.lease.id, "rent", 0.7,
                              f"입금자 {how} 일치 ({li.unit_no}), 청구 잔액보다 많음 → 선납?")
        return Suggestion(li.lease.id, "rent", 0.6,
                          f"입금자 {how} 일치 ({li.unit_no}), 미납 청구 없음 → 선납?")

    if len(name_hits) > 1:
        units = ", ".join(sorted(by_id[i].unit_no for i in name_hits))
        return Suggestion(None, "unclassified", 0.3, f"같은 입금자명 계약 여러 건: {units}")

    amount_hits = [li for li in leases if (nd := next_due(li)) and nd[1] == txn.amount]
    shown = f"'{txn.counterparty}'" if txn.counterparty else "(입금자 없음)"
    if len(amount_hits) == 1:
        li = amount_hits[0]
        return Suggestion(li.lease.id, "rent", 0.5,
                          f"금액만 일치 ({li.unit_no}). 입금자 {shown} 미등록")
    if len(amount_hits) > 1:
        units = ", ".join(li.unit_no for li in amount_hits)
        return Suggestion(None, "unclassified", 0.2,
                          f"같은 금액 청구 여러 건: {units}. 입금자 {shown} 미등록")
    return Suggestion(None, "unclassified", 0.0, f"일치하는 계약 없음. 입금자 {shown}")


def org_transactions(organization_id: uuid.UUID):
    return (
        select(Transaction)
        .join(BankAccount, Transaction.bank_account_id == BankAccount.id)
        .where(BankAccount.organization_id == organization_id)
    )


def run_matching(session: Session, organization_id: uuid.UUID) -> dict[str, int]:
    """배분이 하나도 없는 입금 거래에 제안을 만든다. 확실한 것만 자동 확정."""
    has_alloc = select(TransactionAllocation.transaction_id)
    txns = session.scalars(
        org_transactions(organization_id)
        .where(Transaction.direction == "in", Transaction.id.not_in(has_alloc))
        .order_by(Transaction.occurred_at)
    ).all()
    leases = active_leases(session, organization_id)
    aliases = _aliases(session, organization_id)

    counts = {"auto_confirmed": 0, "pending": 0}
    for txn in txns:
        s = suggest(session, txn, leases, aliases)
        alloc = TransactionAllocation(
            transaction_id=txn.id, lease_id=s.lease_id, category=s.category, amount=txn.amount,
            review_status="approved" if s.auto else "pending", confidence=s.confidence,
            reason=("자동 확정: " if s.auto else "제안: ") + s.reason,
        )
        session.add(alloc)
        session.flush()
        if s.auto:
            ledger.apply_rent(session, alloc)  # 다음 거래 판단이 갱신된 잔액을 보도록 즉시 반영
            counts["auto_confirmed"] += 1
        else:
            counts["pending"] += 1

    session.add(AuditLog(action="matching.run", entity_type="organization",
                         entity_id=str(organization_id), detail=counts))
    session.commit()
    return counts


def _apply(session: Session, alloc: TransactionAllocation, txn: Transaction) -> None:
    if alloc.category == "rent":
        ledger.apply_rent(session, alloc)
    elif alloc.category == "deposit_in":
        dep = _unreceived_deposit(session, alloc.lease_id)
        if dep is None:
            raise MatchError("이 계약에는 받을 보증금이 없습니다 (이미 수령했거나 0원)")
        occurred = txn.occurred_at
        if occurred.tzinfo is None:  # 저장값은 UTC. 드라이버가 tz 를 떼어 돌려줘도 서버 시간대에 의존하지 않게
            occurred = occurred.replace(tzinfo=timezone.utc)
        dep.received_at = occurred.astimezone(KST).date()


def decide(session: Session, organization_id: uuid.UUID, txn_id: uuid.UUID, *,
           lease_id: uuid.UUID | None, category: str, remember_alias: bool) -> TransactionAllocation:
    """관리자 확정. 제안과 같으면 그 제안을 승인하고, 다르면 제안은 rejected 로 남기고 새로 만든다."""
    txn = session.scalar(org_transactions(organization_id).where(Transaction.id == txn_id))
    if txn is None:
        raise LookupError("거래를 찾을 수 없습니다")
    if category in ("rent", "deposit_in"):
        if lease_id is None:
            raise MatchError("월세·보증금은 계약(호실)을 골라야 합니다")
        if lease_id not in {li.lease.id for li in active_leases(session, organization_id)}:
            raise MatchError("활성 계약이 아닙니다")
    elif lease_id is not None and category not in ("rent", "deposit_in"):
        lease_id = None  # 계약과 무관한 분류

    current = session.scalars(
        select(TransactionAllocation).where(
            TransactionAllocation.transaction_id == txn.id,
            TransactionAllocation.review_status.in_(("pending", "approved")),
        )
    ).all()
    if any(a.review_status == "approved" for a in current):
        raise MatchError("이미 확정된 거래입니다. 먼저 확정을 취소하세요")

    pending = current[0] if current else None
    if pending and pending.lease_id == lease_id and pending.category == category:
        alloc = pending
        alloc.review_status = "approved"
        alloc.reason = f"{alloc.reason} → 관리자 승인"
    else:
        if pending:
            pending.review_status = "rejected"
        alloc = TransactionAllocation(
            transaction_id=txn.id, lease_id=lease_id, category=category, amount=txn.amount,
            review_status="approved", confidence=None,
            reason="관리자 지정" + (f" (거절한 제안: {(pending.reason or '').removeprefix('제안: ')})" if pending else ""),
        )
        session.add(alloc)
    session.flush()
    _apply(session, alloc, txn)

    if remember_alias and lease_id and txn.counterparty:
        name = normalize_name(txn.counterparty)
        existing = session.scalar(select(PayerAlias).where(
            PayerAlias.organization_id == organization_id, PayerAlias.name == name))
        if existing:
            existing.lease_id = lease_id
        else:
            session.add(PayerAlias(organization_id=organization_id, lease_id=lease_id, name=name))

    session.add(AuditLog(
        action="allocation.approve", entity_type="transaction_allocation", entity_id=str(alloc.id),
        detail={"category": category, "lease_id": str(lease_id) if lease_id else None,
                "from_suggestion": alloc is pending, "alias_saved": bool(remember_alias and lease_id)},
    ))
    session.commit()
    return alloc


def cancel(session: Session, organization_id: uuid.UUID, allocation_id: uuid.UUID) -> None:
    """확정(자동 포함) 취소 → rejected. 그 거래는 다시 검토 대기열로 돌아간다."""
    alloc = session.scalar(
        select(TransactionAllocation)
        .join(Transaction, TransactionAllocation.transaction_id == Transaction.id)
        .join(BankAccount, Transaction.bank_account_id == BankAccount.id)
        .where(TransactionAllocation.id == allocation_id, BankAccount.organization_id == organization_id)
    )
    if alloc is None:
        raise LookupError("배분을 찾을 수 없습니다")
    if alloc.review_status != "approved":
        raise MatchError("확정된 배분만 취소할 수 있습니다")
    if session.get(Transaction, alloc.transaction_id).direction != "in":
        raise MatchError("출금 거래는 운영비 화면에서 취소하세요")
    ledger.unapply(session, alloc)
    if alloc.category == "deposit_in":
        dep = session.scalar(select(Deposit).where(
            Deposit.lease_id == alloc.lease_id, Deposit.received_at.is_not(None)).limit(1))
        if dep:
            dep.received_at = None
    alloc.review_status = "rejected"
    session.add(AuditLog(action="allocation.cancel", entity_type="transaction_allocation",
                         entity_id=str(alloc.id), detail={"category": alloc.category}))
    session.commit()
