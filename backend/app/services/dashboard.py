"""홈 대시보드 (PRD §3-1). 모든 숫자는 DB 조회 결과 — 추정·보간 없음."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Charge, Deposit, Lease, Payment, Property, Tenant, Transaction, TransactionAllocation, Unit
from app.services import backup, fixtures, lease_renewal, lease_rules, ledger, receivables, reports, tax_calendar
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
LEASE_END_WINDOW = 60  # 보증금 반환 준비 안내
NOTICE_PREVIEW_DAYS = 30  # 통지 기간이 열리기 이만큼 전부터 미리 알림
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

    # 계약 만료 예정 + 돌려줄 보증금 (만료가 지났는데 아직 반환 안 한 것도).
    # 갱신 통지 기간(만료 6개월~2개월 전, 주임법 §6)이 열리기 한 달 전부터 보여 준다
    lease_endings = []
    for lease, name in leases.values():
        if lease.end_date is None:
            continue
        w = lease_renewal.window(lease.end_date)
        stage = w.stage(as_of)
        unreturned = session.scalar(select(func.sum(Deposit.amount)).where(  # 받았고 아직 안 돌려준 것 (최초분+증액분)
            Deposit.lease_id == lease.id, Deposit.received_at.is_not(None),
            Deposit.returned_at.is_(None)))
        if (stage == "early" and (w.notice_from - as_of).days > NOTICE_PREVIEW_DAYS) or (stage == "ended" and not unreturned):
            continue
        lease_endings.append({
            "unit_no": next(u.unit_no for u in units if u.id == lease.unit_id),
            "tenant_name": name, "end_date": lease.end_date, "days_left": (lease.end_date - as_of).days,
            "deposit_to_return": int(unreturned) if unreturned else None,
            "stage": stage, "notice_from": w.notice_from, "notice_until": w.notice_until,
            "notice_sent_on": lease_renewal.notice_sent_on(session, lease.id, lease.end_date),
        })
    lease_endings.sort(key=lambda x: x["end_date"])

    got = aliased(Deposit)
    deposits_unreceived = session.execute(
        select(Unit.unit_no, Deposit.amount,
               select(got.id).where(got.lease_id == Lease.id, got.received_at.is_not(None))
               .correlate(Lease).exists())  # 이미 받은 묶음이 있으면 이건 증액분
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
    for unit_no, amount, increase in deposits_unreceived:
        what = "보증금 증액분" if increase else "보증금"
        add("info", "deposit_unreceived", f"{unit_no} {what} {amount:,}원 수령 기록 없음.", "/payments")
    for e in lease_endings:
        unit, end, until = e["unit_no"], f"{e['end_date']:%Y-%m-%d}", f"{e['notice_until']:%Y-%m-%d}"
        sent = e["notice_sent_on"]
        if e["stage"] == "early":
            add("info", "lease_notice_soon", f"{unit} 계약 {end} 만료 — 갱신 거절·조건 변경 통지 기간이 "
                f"{e['notice_from']:%Y-%m-%d}부터 {until}까지입니다 ({lease_renewal.LAW}).", "/notifications")
        elif e["stage"] == "open" and not sent:
            add("warn", "lease_notice_open", f"{unit} 계약 {end} 만료 — 갱신 거절이나 조건 변경을 하려면 {until}까지 "
                f"임차인에게 닿도록 통지하세요. 통지가 없으면 같은 조건으로 갱신된 것으로 봅니다 ({lease_renewal.LAW}).",
                "/notifications")
        elif e["stage"] == "closed" and not sent:
            add("warn", "lease_notice_missed", f"{unit} 통지 기간({until}까지)에 보낸 계약 만료 안내 기록이 없습니다. "
                f"따로 통지하지 않았다면 {end} 만료 때 같은 조건으로 2년 갱신된 것으로 봅니다 ({lease_renewal.LAW}). "
                "임차인과 갱신 여부를 확인하세요.", "/contracts")
        if e["days_left"] <= LEASE_END_WINDOW:
            when = f"{e['days_left']}일 후 만료" if e["days_left"] >= 0 else f"만료 {-e['days_left']}일 지남"
            dep = f", 보증금 {e['deposit_to_return']:,}원 반환 예정" if e["deposit_to_return"] else ""
            add("info", "lease_ending", f"{unit} 계약 {when}{dep}.", "/expenses")
    if open_repairs := fixtures.open_repair_count(session, organization_id):
        add("info", "repair_open", f"진행 중인 수리 {open_repairs}건.", "/assets")
    for le, due, late in lease_rules.report_reminders(session, [le for le, _ in leases.values()], as_of):
        unit_no = next(u.unit_no for u in units if u.id == le.unit_id)
        add("warn", "lease_report", f"{unit_no} 임대차 신고 기한 {due:%Y-%m-%d}" + (" 이 지났습니다" if late else " 입니다")
            + " (보증금 6천만 원 초과 또는 월세 30만 원 초과). 신고했거나 대상 지역이 아니면 호실·계약에서 표시하세요.", "/units")
    # 종료된 계약이라도 보증금을 돌려주기 전까지는 부채 — 계속 알린다
    for unit_no, amount, ended_on in session.execute(
            select(Unit.unit_no, func.sum(Deposit.amount), Lease.ended_on)
            .join(Lease, Deposit.lease_id == Lease.id).join(Unit, Lease.unit_id == Unit.id)
            .join(Property, Unit.property_id == Property.id)
            .where(Property.organization_id == organization_id, Lease.status == "ended",
                   Deposit.received_at.is_not(None), Deposit.returned_at.is_(None))
            .group_by(Unit.unit_no, Lease.id, Lease.ended_on).order_by(Unit.unit_no)):
        add("warn", "deposit_unreturned_ended",
            f"{unit_no} 계약이 {ended_on:%Y-%m-%d}에 끝났는데 보증금 {int(amount):,}원을 돌려준 기록이 없습니다.", "/expenses")
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
