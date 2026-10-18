"""월세 납부 확인서 — 한 계약의 한 해 동안 실제로 받은 월세를 장부 그대로 적은 확인서 (인쇄·PDF).

임차인이 월세 세액공제(조세특례제한법 §95조의2) 증빙에 곁들일 수 있게 만들지만, 공제 대상인지 판정하지 않는다 (CLAUDE.md 규칙 6).
- 숫자는 관리자가 '월세'로 확정(approved)한 입금만. 검토 대기·보증금(부채, 규칙 3)·다른 분류·공과금 청구에 채운 몫은 넣지 않는다
- 연도는 입금일(KST) 기준 — 그 해에 실제로 낸 돈. 청구 월이 아니다. 어느 청구를 채웠는지는 참고로 적는다
- 통장 내역이 그 해 끝까지 없으면 '어디까지의 내역인지'를 같이 적는다. 모르는 값을 채우지 않는다 (규칙 7)
- 임차인 이름은 확인서에 꼭 필요해 넣는다(관리자만 만든다). 연락처는 넣지 않는다
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, BankAccount, Charge, Lease, Payment, Property, Tenant, Transaction, TransactionAllocation, Unit
from app.services import receivables
from app.services.expenses import KST, kst_date

LAW = "조세특례제한법 §95조의2 (월세액 세액공제)"
NOTICE = ("임대인 장부에 월세로 확정된 입금만 적었습니다. 세액공제 대상 여부(무주택 세대주·소득·주택 요건 등)는 "
          "확인하지 않았으며 신고 확정 자료가 아닙니다. 계좌이체 내역 등 지급 증빙과 함께 쓰세요.")


class CertificateError(ValueError):
    pass


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    start = datetime.combine(date(year, 1, 1), time.min, tzinfo=KST).astimezone(timezone.utc)
    end = datetime.combine(date(year + 1, 1, 1), time.min, tzinfo=KST).astimezone(timezone.utc)
    return start, end


def build(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID, year: int, today: date,
          user_id=None) -> dict:
    row = session.execute(
        select(Lease, Unit, Property, Tenant).join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id).join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Lease.id == lease_id, Property.organization_id == organization_id)).first()
    if row is None:
        raise LookupError("계약을 찾을 수 없습니다")
    lease, unit, prop, tenant = row
    if year > today.year:
        raise CertificateError("아직 오지 않은 해입니다")
    last_day = lease.ended_on or lease.end_date
    if year < lease.start_date.year - 1 or (last_day and year > last_day.year + 1):
        raise CertificateError("이 계약 기간과 겹치지 않는 해입니다")

    start, end = _year_bounds(year)
    rent = (select(TransactionAllocation, Transaction.occurred_at)
            .join(Transaction, TransactionAllocation.transaction_id == Transaction.id)
            .where(TransactionAllocation.lease_id == lease.id, TransactionAllocation.category == "rent",
                   TransactionAllocation.review_status == "approved", Transaction.direction == "in",
                   Transaction.occurred_at >= start, Transaction.occurred_at < end)
            .order_by(Transaction.occurred_at))
    lines = []
    for alloc, occurred in session.execute(rent).all():
        periods = list(session.scalars(select(Charge.period).join(Payment, Payment.charge_id == Charge.id)
                                       .where(Payment.transaction_allocation_id == alloc.id, Charge.kind == "rent")
                                       .order_by(Charge.period).distinct()))
        # 같은 입금으로 공과금 청구를 채운 몫은 월세가 아니므로 뺀다
        utility = session.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                                 .join(Charge, Payment.charge_id == Charge.id)
                                 .where(Payment.transaction_allocation_id == alloc.id, Charge.kind != "rent"))
        amount = int(alloc.amount) - int(utility)
        if amount > 0:
            lines.append({"paid_on": kst_date(occurred), "amount": amount, "periods": periods})
    # 검토 대기 입금은 아직 어느 계약 것인지 모른다 — 그 해 사업장 전체 건수를 알려 주기만 한다
    pending = len(session.scalars(
        select(TransactionAllocation.id).join(Transaction, TransactionAllocation.transaction_id == Transaction.id)
        .join(BankAccount, Transaction.bank_account_id == BankAccount.id)
        .where(BankAccount.organization_id == organization_id, TransactionAllocation.review_status == "pending",
               Transaction.direction == "in", Transaction.occurred_at >= start, Transaction.occurred_at < end)).all())

    latest = receivables.latest_transaction_at(session, organization_id)
    year_end = date(year, 12, 31)
    covered_to = kst_date(latest) if latest else None
    session.add(AuditLog(user_id=user_id, action="rent_certificate.view", entity_type="lease",
                         entity_id=str(lease.id), detail={"year": year}))
    session.commit()
    return {
        "year": year, "law": LAW, "notice": NOTICE, "generated_at": datetime.now(timezone.utc),
        "building": prop.name,
        "tenant_name": tenant.name,
        "unit_no": unit.label, "address": prop.address,
        "lease": {"start_date": lease.start_date, "end_date": lease.end_date, "ended_on": lease.ended_on,
                  "deposit": lease.deposit, "rent": lease.rent, "due_day": lease.due_day},
        "lines": lines,
        "total": sum(x["amount"] for x in lines),
        "count": len(lines),
        "pending_review_in_year": pending,  # 화면 경고용 — 확인서 합계에는 없음
        "bank_data_to": covered_to,
        "bank_complete": covered_to is not None and covered_to >= year_end,  # 그 해 끝까지 통장 내역이 있나
        "year_in_progress": year == today.year,
    }
