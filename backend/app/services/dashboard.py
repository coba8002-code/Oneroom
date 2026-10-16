"""홈 대시보드 (PRD §3-1). 모든 숫자는 DB 조회 결과 — 추정·보간 없음."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Charge, Deposit, Lease, Payment, Property, Tenant, Transaction, TransactionAllocation, Unit
from app.services import backup, ledger, receivables, reports, tax_calendar
from app.services.charges import due_date_for
from app.services.expenses import kst_date
from app.services.matching import org_transactions

LABEL = {"rent": "월세", "deposit_in": "보증금 입금", "deposit_out": "보증금 반환", "personal": "생활비",
         "owner_household": "주인세대", "other": "기타", "common_electricity": "공용 전기료", "water": "수도료",
         "cleaning": "청소비", "repair": "수리비", "other_operating": "공용 기타"}
RECENT_LIMIT = 6


def _paid_on(session: Session, charge_id) -> date | None:
    """이 청구에 들어간 입금 중 가장 늦은 거래일 (완납일)."""
    latest = session.scalar(
        select(func.max(Transaction.occurred_at))
        .join(TransactionAllocation, TransactionAllocation.transaction_id == Transaction.id)
        .join(Payment, Payment.transaction_allocation_id == TransactionAllocation.id)
        .where(Payment.charge_id == charge_id))
    return kst_date(latest) if latest else None


def _recent(session: Session, organization_id, unit_by_lease: dict) -> list[dict]:
    out = []
    for t in session.scalars(org_transactions(organization_id)
                             .order_by(Transaction.occurred_at.desc()).limit(RECENT_LIMIT)):
        allocs = session.scalars(select(TransactionAllocation).where(
            TransactionAllocation.transaction_id == t.id,
            TransactionAllocation.review_status == "approved")).all()
        who = t.counterparty or t.description or ""
        if not allocs:
            label = f"{who} · 확인 전"
        else:
            a = allocs[0]
            unit = unit_by_lease.get(a.lease_id)
            if a.category in ("rent", "deposit_in", "deposit_out") and unit:
                label = f"{unit}호 {LABEL[a.category]}" + (" 입금" if a.category == "rent" else "")
            else:
                label = LABEL.get(a.category, a.category)
                if len(allocs) > 1:
                    label += f" 외 {len(allocs) - 1}"
                if who:
                    label += f" ({who})"
        out.append({"occurred_at": t.occurred_at, "direction": t.direction, "amount": t.amount,
                    "label": label, "confirmed": bool(allocs)})
    return out

STALE_BANK_DAYS = 7
LEASE_END_WINDOW = 60
DUE_SOON_DAYS = 7
BACKUP_REMIND_DAYS = 30


def build(session: Session, organization_id: uuid.UUID, as_of: date) -> dict:
    period = as_of.strftime("%Y-%m")

    units = session.execute(
        select(Unit).join(Property, Unit.property_id == Property.id)
        .where(Property.organization_id == organization_id).order_by(Unit.unit_no)
    ).scalars().all()
    leases = {lease.unit_id: (lease, name) for lease, name in session.execute(
        select(Lease, Tenant.name).join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Lease.unit_id.in_([u.id for u in units]), Lease.status == "active"))}
    charges = {c.lease_id: c for c in session.scalars(select(Charge).where(
        Charge.period == period, Charge.lease_id.in_([lease.id for lease, _ in leases.values()])))}

    unit_rows = []
    for u in units:
        row = {"unit_no": u.unit_no, "floor": u.floor, "use_type": u.use_type, "status": u.status,
               "tenant_name": None, "rent": None, "due_day": None, "due_date": None, "charge_status": None,
               "outstanding": None, "paid_on": None, "lease_end": None}
        if u.id in leases:
            lease, name = leases[u.id]
            c = charges.get(lease.id)
            row.update(tenant_name=name, rent=lease.rent, due_day=lease.due_day, lease_end=lease.end_date,
                       due_date=c.due_date if c else due_date_for(period, lease.due_day),
                       charge_status=c.status if c else "none",
                       outstanding=(c.amount - ledger.paid_amount(session, c.id)) if c else None,
                       paid_on=_paid_on(session, c.id) if c and c.status == "paid" else None)
        unit_rows.append(row)

    counts = {
        "total": len(units),
        "rental": sum(u.use_type == "rental" for u in units),
        "occupied": sum(u.status == "occupied" for u in units),
        "vacant": sum(u.status == "vacant" for u in units),
        "owner": sum(u.use_type == "owner" for u in units),
    }

    recv = receivables.compute(session, organization_id, as_of)
    overdue = [i for i in recv.items if i.days_past_due > 0]
    month = reports.monthly(session, organization_id, period)

    due_soon = []
    for lease, _ in leases.values():
        for c, remaining in ledger.open_charges(session, lease.id):
            if as_of <= c.due_date <= as_of + timedelta(days=DUE_SOON_DAYS):
                unit_no = next(u.unit_no for u in units if u.id == lease.unit_id)
                due_soon.append({"unit_no": unit_no, "due_date": c.due_date, "outstanding": remaining})
    due_soon.sort(key=lambda x: (x["due_date"], x["unit_no"]))

    # 계약 만료 예정 + 돌려줄 보증금 (만료가 지났는데 아직 반환 안 한 것도)
    lease_endings = []
    for lease, name in leases.values():
        if lease.end_date is None:
            continue
        days_left = (lease.end_date - as_of).days
        unreturned = session.scalar(select(Deposit).where(  # 받았고 아직 안 돌려준 것만
            Deposit.lease_id == lease.id, Deposit.received_at.is_not(None),
            Deposit.returned_at.is_(None)).limit(1))
        if days_left <= LEASE_END_WINDOW and (days_left >= 0 or unreturned):
            lease_endings.append({
                "unit_no": next(u.unit_no for u in units if u.id == lease.unit_id),
                "tenant_name": name, "end_date": lease.end_date, "days_left": days_left,
                "deposit_to_return": unreturned.amount if unreturned else None,
            })
    lease_endings.sort(key=lambda x: x["end_date"])

    deposits_unreceived = session.execute(
        select(Unit.unit_no, Deposit.amount)
        .join(Lease, Deposit.lease_id == Lease.id).join(Unit, Lease.unit_id == Unit.id)
        .where(Lease.id.in_([lease.id for lease, _ in leases.values()]),
               Deposit.received_at.is_(None), Deposit.amount > 0)
        .order_by(Unit.unit_no)).all()

    latest = receivables.latest_transaction_at(session, organization_id)
    pending_out = receivables.unconfirmed_count(session, organization_id, "out")

    attention: list[dict] = []

    def add(level: str, kind: str, message: str, href: str) -> None:
        attention.append({"level": level, "kind": kind, "message": message, "href": href})

    if latest is None:
        add("warn", "bank_none", "은행 거래내역을 아직 가져오지 않았습니다. 입금 확인·미납 판단의 근거가 없습니다.",
            "/payments")
    elif (stale := (as_of - kst_date(latest)).days) > STALE_BANK_DAYS:
        add("warn", "bank_stale", f"최근 {stale}일간 은행 내역이 없습니다. 미납으로 보기 전에 최신 내역을 가져오세요.",
            "/payments")
    if leases and not charges:
        add("warn", "charges_missing", f"{period} 청구가 아직 생성되지 않았습니다.", "#generate")
    if recv.pending_review:
        add("warn", "review_in", f"입금 검토 대기 {recv.pending_review}건 — 확정 전에는 미납·수입이 정확하지 않습니다.",
            "/payments")
    if pending_out:
        add("warn", "review_out", f"출금 검토 대기 {pending_out}건 — 확정 전에는 운영비·순운영수익이 정확하지 않습니다.",
            "/expenses")
    if overdue:
        units_txt = ", ".join(sorted({i.unit_no for i in overdue}))
        add("info", "overdue", f"납부일이 지난 미수 {len(overdue)}건 ({units_txt}). 연락은 내역 확인 후 직접 판단하세요.",
            "/payments")
    for unit_no, amount in deposits_unreceived:
        add("info", "deposit_unreceived", f"{unit_no} 보증금 {amount:,}원 수령 기록 없음.", "/payments")
    for e in lease_endings:
        when = f"{e['days_left']}일 후 만료" if e["days_left"] >= 0 else f"만료 {-e['days_left']}일 지남"
        dep = f", 보증금 {e['deposit_to_return']:,}원 반환 예정" if e["deposit_to_return"] else ""
        add("info", "lease_ending", f"{e['unit_no']} 계약 {when}{dep}.", "/expenses")
    last_backup = backup.last_backup_at(session, organization_id)
    if last_backup is None:
        add("info", "backup_none", "아직 백업한 적이 없습니다. 설정에서 백업 파일을 내려받아 두세요.", "/settings")
    elif (age := (as_of - kst_date(last_backup)).days) > BACKUP_REMIND_DAYS:
        add("info", "backup_old", f"마지막 백업이 {age}일 전입니다.", "/settings")
    if counts["vacant"]:
        vac = ", ".join(u.unit_no for u in units if u.status == "vacant")
        add("info", "vacant", f"공실 {counts['vacant']}실 ({vac}).", "/onboarding")

    return {
        "as_of": as_of,
        "period": period,
        "bank_data_as_of": latest,
        "counts": counts,
        "units": unit_rows,
        "money": {
            "rent_charged": month["rent_charged"],
            "rent_received": month["rent_received"],
            "overdue_total": sum(i.outstanding for i in overdue),
            "overdue_count": len(overdue),
            "operating_total": month["operating_total"],
            "noi": month["noi"],
            "non_operating_total": (sum(month["excluded"][k] for k in ("personal", "owner_household"))
                                    if month["bank_covered"] else None),
            "complete": month["complete"],
            "charges_ready": month["charges_ready"],
            "bank_covered": month["bank_covered"],
        },
        "recent_transactions": _recent(
            session, organization_id,
            {lease.id: next(u.unit_no for u in units if u.id == lease.unit_id) for lease, _ in leases.values()}),
        "due_soon": due_soon,
        "lease_endings": lease_endings,
        "tax_events": tax_calendar.upcoming(as_of),
        "attention": attention,
    }
