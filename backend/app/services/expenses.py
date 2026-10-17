"""운영비 분리 (PRD §3-5, §4).

출금 분류
- 운영비(NOI 반영): 공용전기 · 수도 · 청소 · 수리 · 공용 기타
- 운영비 아님:      주인세대 · 개인 생활비  → 임대 순운영수익에 절대 넣지 않는다
- 보증금 반환:      부채 상환 (비용 아님)

자동 확정은 **관리자가 '기억'한 거래처 규칙**과 정확히 같은 거래처일 때만.
'한국전력' 같은 키워드는 주인세대 전기일 수도 있으므로 제안(검토 대기)까지만 한다.
혼합 거래는 여러 분류로 나눠 확정한다 (합계 = 거래금액).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Deposit,
    Expense,
    ExpenseRule,
    Lease,
    Property,
    Tenant,
    Transaction,
    TransactionAllocation,
    Unit,
)
from app.services.matching import MatchError, normalize_name, org_transactions

KST = ZoneInfo("Asia/Seoul")

OPERATING = ("common_electricity", "water", "cleaning", "repair", "other_operating")
NON_OPERATING = ("owner_household", "personal")
EXPENSE_CATEGORIES = OPERATING + NON_OPERATING
OUT_CATEGORIES = EXPENSE_CATEGORIES + ("deposit_out",)

# 제안용 힌트 (자동 확정에 쓰지 않음). 실제 통장 표기를 보고 보강한다.
HINTS: tuple[tuple[tuple[str, ...], str, float, str], ...] = (
    (("한국전력", "한전"), "common_electricity", 0.6, "공용전기? (주인세대 전기일 수도 있음)"),
    (("수도",), "water", 0.6, "수도요금?"),
    (("청소",), "cleaning", 0.6, "청소비?"),
    (("철물", "설비", "수리", "보일러", "도배", "배관"), "repair", 0.5, "수리비?"),
    (("마트", "편의점", "카드"), "personal", 0.3, "생활비? 주인세대와 섞였으면 나눠서 확정"),
)


@dataclass
class Split:
    category: str
    amount: int
    unit_id: uuid.UUID | None = None


def payee_key(txn: Transaction) -> str:
    return normalize_name(txn.counterparty or txn.description)


def kst_date(dt: datetime) -> date:
    if dt.tzinfo is None:  # 저장값은 UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).date()


def split_by_bp(amount: int, splits: list[dict]) -> list[Split]:
    """만분율로 금액을 나눈다. 반올림 차이는 비중이 가장 큰 항목에 몰아준다."""
    parts = [Split(s["category"], amount * s["bp"] // 10000) for s in splits]
    biggest = max(range(len(splits)), key=lambda i: splits[i]["bp"])
    parts[biggest].amount += amount - sum(p.amount for p in parts)
    return [p for p in parts if p.amount > 0]


def to_bp(splits: list[Split]) -> list[dict]:
    total = sum(s.amount for s in splits)
    merged: dict[str, int] = {}
    for s in splits:
        merged[s.category] = merged.get(s.category, 0) + s.amount
    bps = [{"category": c, "bp": a * 10000 // total} for c, a in merged.items()]
    biggest = max(range(len(bps)), key=lambda i: bps[i]["bp"])
    bps[biggest]["bp"] += 10000 - sum(b["bp"] for b in bps)
    return bps


def _rules(session: Session, organization_id: uuid.UUID) -> dict[str, ExpenseRule]:
    return {r.key: r for r in session.scalars(
        select(ExpenseRule).where(ExpenseRule.organization_id == organization_id))}


def _org_leases(session: Session, organization_id: uuid.UUID) -> list[tuple[Lease, str, str]]:
    """보증금 반환은 종료된 계약에도 일어나므로 상태와 무관하게."""
    return session.execute(
        select(Lease, Unit.unit_no, Tenant.name)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Property.organization_id == organization_id)
    ).all()


def _unreturned_deposits(session: Session, lease_id: uuid.UUID) -> list[Deposit]:
    """받았고 아직 돌려주지 않은 보증금 묶음들 (최초분 + 증액분). 반환은 합계로 한 번에."""
    return list(session.scalars(select(Deposit).where(
        Deposit.lease_id == lease_id, Deposit.received_at.is_not(None), Deposit.returned_at.is_(None))))


def _suggest(session: Session, txn: Transaction, leases) -> tuple[uuid.UUID | None, str, float, str]:
    payee = normalize_name(txn.counterparty)
    for lease, unit_no, name in leases:
        if payee and normalize_name(name) == payee:
            deps = _unreturned_deposits(session, lease.id)
            if deps and sum(d.amount for d in deps) == txn.amount:
                return lease.id, "deposit_out", 0.8, f"받는 분 = {unit_no} 임차인, 금액 = 보증금 → 보증금 반환?"
    text = f"{txn.counterparty or ''} {txn.description or ''}"
    for words, category, confidence, why in HINTS:
        if any(w in text for w in words):
            return None, category, confidence, why
    return None, "unclassified", 0.0, "분류 규칙 없음"


def _property_id(session: Session, organization_id: uuid.UUID) -> uuid.UUID | None:
    """건물이 하나면 그 건물. 여러 개면 비워 둔다 (추측하지 않음)."""
    ids = session.scalars(select(Property.id).where(Property.organization_id == organization_id)).all()
    return ids[0] if len(ids) == 1 else None


def _unit_in_org(session: Session, organization_id: uuid.UUID, unit_id: uuid.UUID) -> bool:
    return session.scalar(
        select(Unit.id).join(Property, Unit.property_id == Property.id)
        .where(Unit.id == unit_id, Property.organization_id == organization_id)
    ) is not None


def _record(session: Session, organization_id: uuid.UUID, txn: Transaction,
            alloc: TransactionAllocation, unit_id: uuid.UUID | None) -> None:
    if alloc.category == "deposit_out":
        deps = _unreturned_deposits(session, alloc.lease_id)
        if not deps:
            raise MatchError("이 계약에는 돌려줄 보증금이 없습니다 (미수령 또는 이미 반환)")
        for dep in deps:
            dep.returned_at = kst_date(txn.occurred_at)
        return
    session.add(Expense(
        organization_id=organization_id,
        property_id=None if alloc.category == "personal" else _property_id(session, organization_id),
        unit_id=unit_id, transaction_allocation_id=alloc.id, category=alloc.category,
        amount=alloc.amount, spent_on=kst_date(txn.occurred_at),
    ))


def classify(session: Session, organization_id: uuid.UUID) -> dict[str, int]:
    """배분이 하나도 없는 출금 거래를 분류한다. 기억된 규칙만 자동 확정."""
    has_alloc = select(TransactionAllocation.transaction_id)
    txns = session.scalars(
        org_transactions(organization_id)
        .where(Transaction.direction == "out", Transaction.id.not_in(has_alloc))
        .order_by(Transaction.occurred_at)
    ).all()
    rules = _rules(session, organization_id)
    leases = _org_leases(session, organization_id)

    counts = {"auto_confirmed": 0, "pending": 0}
    for txn in txns:
        rule = rules.get(payee_key(txn))
        if rule:
            label = " + ".join(f"{s['category']} {s['bp'] / 100:g}%" for s in rule.splits)
            for part in split_by_bp(txn.amount, rule.splits):
                alloc = TransactionAllocation(
                    transaction_id=txn.id, category=part.category, amount=part.amount,
                    review_status="approved", confidence=0.9,
                    reason=f"자동 확정: 기억한 규칙 '{rule.label}' → {label}",
                )
                session.add(alloc)
                session.flush()
                _record(session, organization_id, txn, alloc, None)
            counts["auto_confirmed"] += 1
            continue
        lease_id, category, confidence, why = _suggest(session, txn, leases)
        session.add(TransactionAllocation(
            transaction_id=txn.id, lease_id=lease_id, category=category, amount=txn.amount,
            review_status="pending", confidence=confidence, reason=f"제안: {why}",
        ))
        counts["pending"] += 1

    session.add(AuditLog(action="expenses.classify", entity_type="organization",
                         entity_id=str(organization_id), detail=counts))
    session.commit()
    return counts


def decide(session: Session, organization_id: uuid.UUID, txn_id: uuid.UUID, *, splits: list[Split],
           lease_id: uuid.UUID | None, remember: bool) -> list[TransactionAllocation]:
    txn = session.scalar(org_transactions(organization_id).where(Transaction.id == txn_id))
    if txn is None or txn.direction != "out":
        raise LookupError("출금 거래를 찾을 수 없습니다")
    if not splits:
        raise MatchError("분류를 하나 이상 고르세요")
    for s in splits:
        if s.category not in OUT_CATEGORIES:
            raise MatchError(f"알 수 없는 분류: {s.category}")
        if s.amount <= 0:
            raise MatchError("금액은 0보다 커야 합니다")
        if s.unit_id and not _unit_in_org(session, organization_id, s.unit_id):
            raise MatchError("이 건물의 호실이 아닙니다")
    if sum(s.amount for s in splits) != txn.amount:
        raise MatchError(f"나눈 금액 합계({sum(s.amount for s in splits):,})가 "
                         f"거래 금액({txn.amount:,})과 다릅니다")
    if any(s.category == "deposit_out" for s in splits):
        if len(splits) != 1 or lease_id is None:
            raise MatchError("보증금 반환은 나누지 않고 계약(호실)을 골라야 합니다")
        if lease_id not in {lease.id for lease, _, _ in _org_leases(session, organization_id)}:
            raise MatchError("이 건물의 계약이 아닙니다")

    current = session.scalars(select(TransactionAllocation).where(
        TransactionAllocation.transaction_id == txn.id,
        TransactionAllocation.review_status.in_(("pending", "approved")))).all()
    if any(a.review_status == "approved" for a in current):
        raise MatchError("이미 확정된 거래입니다. 먼저 확정을 취소하세요")
    pending = current[0] if current else None

    created: list[TransactionAllocation] = []
    if (pending and len(splits) == 1 and pending.category == splits[0].category
            and pending.lease_id == (lease_id if splits[0].category == "deposit_out" else None)):
        pending.review_status = "approved"
        pending.reason = f"{pending.reason} → 관리자 승인"
        created.append(pending)
    else:
        if pending:
            pending.review_status = "rejected"
        note = "관리자 지정" + (" (나눔)" if len(splits) > 1 else "")
        if pending:
            note += f" (거절한 제안: {(pending.reason or '').removeprefix('제안: ')})"
        for s in splits:
            alloc = TransactionAllocation(
                transaction_id=txn.id, category=s.category, amount=s.amount,
                lease_id=lease_id if s.category == "deposit_out" else None,
                review_status="approved", confidence=None, reason=note,
            )
            session.add(alloc)
            created.append(alloc)
    session.flush()
    units = {id(a): s.unit_id for a, s in zip(created, splits)}
    for a in created:
        _record(session, organization_id, txn, a, units.get(id(a)))

    rule_saved = False
    key = payee_key(txn)
    if remember and key and not any(s.category == "deposit_out" for s in splits):
        rule = session.scalar(select(ExpenseRule).where(
            ExpenseRule.organization_id == organization_id, ExpenseRule.key == key))
        bps = to_bp(splits)
        if rule:
            rule.splits = bps
        else:
            session.add(ExpenseRule(organization_id=organization_id, key=key,
                                    label=txn.counterparty or txn.description or key, splits=bps))
        rule_saved = True

    session.add(AuditLog(
        action="expense.approve", entity_type="transaction", entity_id=str(txn.id),
        detail={"splits": [{"category": s.category, "amount": s.amount} for s in splits],
                "rule_saved": rule_saved},
    ))
    session.commit()
    return created


def _no_receipts(session: Session, e: Expense) -> None:
    """증빙이 붙은 지출은 조용히 지우지 않는다 — 증빙을 먼저 지워야 한다."""
    from app.models import ExpenseReceipt
    if session.scalar(select(ExpenseReceipt.id).where(ExpenseReceipt.expense_id == e.id).limit(1)):
        raise MatchError(f"{e.spent_on.isoformat()} {e.amount:,}원 지출에 증빙이 붙어 있습니다. 세무 준비에서 증빙을 먼저 지우세요")


def cancel(session: Session, organization_id: uuid.UUID, txn_id: uuid.UUID) -> None:
    """출금 확정 취소 (나눈 것 전부). 거래는 검토 대기로 돌아간다."""
    txn = session.scalar(org_transactions(organization_id).where(Transaction.id == txn_id))
    if txn is None or txn.direction != "out":
        raise LookupError("출금 거래를 찾을 수 없습니다")
    allocs = session.scalars(select(TransactionAllocation).where(
        TransactionAllocation.transaction_id == txn.id,
        TransactionAllocation.review_status == "approved")).all()
    if not allocs:
        raise MatchError("확정된 거래가 아닙니다")
    for a in allocs:
        for e in session.scalars(select(Expense).where(Expense.transaction_allocation_id == a.id)):
            _no_receipts(session, e)
            session.delete(e)
        if a.category == "deposit_out":
            for dep in session.scalars(select(Deposit).where(
                    Deposit.lease_id == a.lease_id, Deposit.returned_at == kst_date(txn.occurred_at))):
                dep.returned_at = None
        a.review_status = "rejected"
    session.add(AuditLog(action="expense.cancel", entity_type="transaction", entity_id=str(txn.id),
                         detail={"allocations": len(allocs)}))
    session.commit()


def add_manual(session: Session, organization_id: uuid.UUID, *, category: str, amount: int,
               spent_on: date, memo: str | None, unit_id: uuid.UUID | None) -> Expense:
    """통장을 거치지 않은 지출 (현금 등)."""
    if category not in EXPENSE_CATEGORIES:
        raise MatchError(f"알 수 없는 분류: {category}")
    if unit_id and not _unit_in_org(session, organization_id, unit_id):
        raise MatchError("이 건물의 호실이 아닙니다")
    e = Expense(
        organization_id=organization_id,
        property_id=None if category == "personal" else _property_id(session, organization_id),
        unit_id=unit_id, category=category, amount=amount, spent_on=spent_on, memo=memo,
    )
    session.add(e)
    session.flush()
    session.add(AuditLog(action="expense.manual", entity_type="expense", entity_id=str(e.id),
                         detail={"category": category, "amount": amount}))
    session.commit()
    return e


def delete_manual(session: Session, organization_id: uuid.UUID, expense_id: uuid.UUID) -> None:
    e = session.scalar(select(Expense).where(
        Expense.id == expense_id, Expense.organization_id == organization_id))
    if e is None:
        raise LookupError("지출을 찾을 수 없습니다")
    if e.transaction_allocation_id is not None:
        raise MatchError("은행 거래에서 온 지출은 거래 확정을 취소하세요")
    _no_receipts(session, e)
    session.delete(e)
    session.add(AuditLog(action="expense.manual_delete", entity_type="expense", entity_id=str(expense_id),
                         detail={"category": e.category, "amount": e.amount}))
    session.commit()
