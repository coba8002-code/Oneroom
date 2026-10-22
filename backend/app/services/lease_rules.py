"""계약 법정 체크리스트와 계산기 (주택임대차보호법 · 부동산 거래신고 등에 관한 법률).

- 정보 제시 의무 (주임법 §3조의7, 2023 개정): 계약할 때 임대인이 ① 확정일자 부여일·차임·보증금 등 선순위 임대차 정보,
  ② 납세증명서(또는 미납세 열람 동의)를 임차인에게 보여 줘야 한다.
- 임대차 신고 (부동산거래신고법 §6조의2): 보증금 6천만 원 초과 또는 월차임 30만 원 초과 계약은 계약일부터 30일 안에 신고.
  수도권·광역시·세종·제주·도의 시 지역이 대상(군 지역 제외) — 주소만으로 확정하지 않고 관리자가 '해당 없음'으로 표시할 수 있다.
  2025-06-01 부터 과태료 부과.
- 증액 상한 (§7): 존속 중 증액 청구와 갱신요구권 갱신은 약정 금액의 1/20(5%)까지, 계약·직전 증액 뒤 1년이 지나야 청구.
  시·도 조례로 더 낮출 수 있다. 새 계약·합의 재계약에는 적용되지 않는다.
- 월차임 전환율 (§7조의2·시행령 §9): 연 10% 와 '한국은행 기준금리 + 연 2%' 중 낮은 비율. 기준금리는 바뀌므로 관리자가 넣는다.
계산값은 법령 문언을 옮긴 참고값이다. 원 단위 아래는 버린다.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Deposit, Inspection, Lease, LeaseCheck
from app.services import rental_business
from app.services.contracts import lease_in_org

REPORT_DEPOSIT_OVER = 60_000_000
REPORT_RENT_OVER = 300_000
REPORT_DAYS = 30
INCREASE_CAP = Decimal(1) / Decimal(20)
CONVERSION_CAP_PCT = Decimal(10)
CONVERSION_ADD_PCT = Decimal(2)
MANUAL_KEYS = {
    "info_disclosure": ("선순위 임대차 정보 제시 (확정일자 부여일·차임·보증금)", "주택임대차보호법 §3조의7 1호"),
    "tax_certificate": ("납세증명서 제시 또는 미납 국세·지방세 열람 동의", "주택임대차보호법 §3조의7 2호"),
    "lease_report": ("임대차 신고 (계약일부터 30일 안)", "부동산 거래신고 등에 관한 법률 §6조의2"),
}


class RuleError(Exception):
    pass


def _lease(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID) -> Lease:
    lease = lease_in_org(session, organization_id, lease_id)
    if lease is None:
        raise LookupError("계약을 찾을 수 없습니다")
    return lease


def report_required(deposit: int, rent: int) -> bool:
    return deposit > REPORT_DEPOSIT_OVER or rent > REPORT_RENT_OVER


def checklist(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID, as_of: date) -> dict:
    lease = _lease(session, organization_id, lease_id)
    checks = {c.key: c for c in session.scalars(select(LeaseCheck).where(LeaseCheck.lease_id == lease.id))}
    items = []
    for key, (label, basis) in MANUAL_KEYS.items():
        c = checks.get(key)
        item = {"key": key, "label": label, "basis": basis, "auto": False,
                "status": c.status if c else "todo", "done_on": c.done_on if c else None, "note": c.note if c else None,
                "due_on": None, "overdue": False, "hint": None}
        if key == "lease_report":
            required = report_required(lease.deposit, lease.rent)
            if not required:
                item["hint"] = "보증금 6천만 원 이하이고 월세 30만 원 이하라 금액 기준으로는 신고 대상이 아닙니다"
                if not c:
                    item["status"] = "na"
            else:
                item["hint"] = "금액 기준 신고 대상 — 수도권·광역시·세종·제주·도의 시 지역이면 신고(군 지역 제외). 계약서 1부로 한쪽만 신고해도 됩니다"
                if lease.signed_on:
                    item["due_on"] = lease.signed_on + timedelta(days=REPORT_DAYS)
                    item["overdue"] = item["status"] == "todo" and as_of > item["due_on"]
                elif item["status"] == "todo":
                    item["hint"] += ". 계약일을 넣으면 기한을 계산합니다"
        items.append(item)
    items += rental_business.contract_items(session, lease, as_of, checks)  # 등록 임대주택이면 민특법 항목
    move_in = session.scalar(select(Inspection).where(Inspection.lease_id == lease.id, Inspection.kind == "move_in"))
    items.append({"key": "move_in_inspection", "label": "입주 점검 (사진·임차인 확인)", "basis": "퇴실 정산의 근거", "auto": True,
                  "status": "done" if move_in and move_in.tenant_confirmed_on else "todo",
                  "done_on": move_in.tenant_confirmed_on if move_in else None,
                  "note": None if move_in is None else ("임차인 확인 전" if not move_in.tenant_confirmed_on else None),
                  "due_on": None, "overdue": False, "hint": None})
    tranches = list(session.scalars(select(Deposit).where(Deposit.lease_id == lease.id)))
    got = [d for d in tranches if d.received_at]
    items.append({"key": "deposit_received", "label": "보증금 수령 확인", "basis": "보증금은 부채로 기록", "auto": True,
                  "status": "na" if lease.deposit == 0 else ("done" if tranches and len(got) == len(tranches) else "todo"),
                  "done_on": max((d.received_at for d in got), default=None), "note": None, "due_on": None,
                  "overdue": False, "hint": None})
    return {"lease_id": str(lease.id), "signed_on": lease.signed_on, "deposit": lease.deposit, "rent": lease.rent,
            "start_date": lease.start_date, "items": items}


def set_signed_on(session: Session, organization_id: uuid.UUID, user_id, lease_id: uuid.UUID,
                  signed_on: date | None) -> None:
    lease = _lease(session, organization_id, lease_id)
    lease.signed_on = signed_on
    session.add(AuditLog(user_id=user_id, action="lease.signed_on", entity_type="lease", entity_id=str(lease.id),
                         detail={"signed_on": signed_on.isoformat() if signed_on else None}))
    session.commit()


def set_check(session: Session, organization_id: uuid.UUID, user_id, lease_id: uuid.UUID, key: str, *,
              status: str | None, done_on: date | None, note: str | None) -> None:
    """status None 이면 기록을 지운다(해야 할 일로 되돌림)."""
    lease = _lease(session, organization_id, lease_id)
    if key not in MANUAL_KEYS and not (key in rental_business.CONTRACT_KEYS
                                       and rental_business.registration_for_lease(session, lease)):
        raise RuleError("직접 표시할 수 없는 항목입니다")
    if status not in (None, "done", "na"):
        raise RuleError("상태는 '했음' 또는 '해당 없음'입니다")
    row = session.scalar(select(LeaseCheck).where(LeaseCheck.lease_id == lease.id, LeaseCheck.key == key))
    if status is None:
        if row:
            session.delete(row)
    else:
        row = row or LeaseCheck(lease_id=lease.id, key=key)
        row.status, row.done_on, row.note = status, done_on if status == "done" else None, (note or "").strip() or None
        session.add(row)
    session.add(AuditLog(user_id=user_id, action="lease.check", entity_type="lease", entity_id=str(lease.id),
                         detail={"key": key, "status": status}))
    session.commit()


def _add_year(d: date) -> date:
    return date(d.year + 1, d.month, min(d.day, calendar.monthrange(d.year + 1, d.month)[1]))


def _floor(v: Decimal) -> int:
    return int(v.to_integral_value(rounding=ROUND_FLOOR))


def increase_caps(deposit: int, rent: int, since: date, as_of: date) -> dict:
    """§7: 존속 중 증액 청구·갱신요구권 갱신 때 올릴 수 있는 최대 금액과 청구 가능일."""
    if deposit < 0 or rent < 0:
        raise RuleError("금액은 0원 이상입니다")
    claim_from = _add_year(since)
    return {"max_deposit": deposit + _floor(Decimal(deposit) * INCREASE_CAP),
            "max_rent": rent + _floor(Decimal(rent) * INCREASE_CAP),
            "claim_from": claim_from, "can_claim_now": as_of >= claim_from, "cap_pct": 5,
            "note": "새 계약·합의 재계약에는 적용되지 않습니다. 시·도 조례로 상한이 더 낮을 수 있습니다"}


def conversion(amount: int, base_rate_pct: str) -> dict:
    """§7조의2: 보증금 일부를 월세로 바꿀 때 연 비율 상한 = min(10%, 기준금리 + 2%)."""
    try:
        base = Decimal(str(base_rate_pct).strip())
    except InvalidOperation as e:
        raise RuleError("기준금리는 숫자로 적으세요 (예: 3.00)") from e
    if amount < 0 or not Decimal(0) <= base <= Decimal(20):
        raise RuleError("금액은 0원 이상, 기준금리는 0~20% 사이입니다")
    rate = min(CONVERSION_CAP_PCT, base + CONVERSION_ADD_PCT)
    return {"rate_pct": format(rate.normalize(), "f"), "monthly_max": _floor(Decimal(amount) * rate / 100 / 12),
            "base_rate_pct": str(base), "rule": f"min(10%, 기준금리 {base}% + 2%)"}


def report_reminders(session: Session, leases: list[Lease], as_of: date, soon_days: int = 7) -> list[tuple[Lease, date, bool]]:
    """신고 대상 금액이고 계약일을 아는데 신고·해당없음 기록이 없는 계약 → (계약, 기한, 지났나)."""
    marked = set(session.scalars(select(LeaseCheck.lease_id).where(
        LeaseCheck.lease_id.in_([le.id for le in leases]), LeaseCheck.key == "lease_report")))
    out = []
    for le in leases:
        if le.id in marked or not le.signed_on or not report_required(le.deposit, le.rent):
            continue
        due = le.signed_on + timedelta(days=REPORT_DAYS)
        if as_of >= due - timedelta(days=soon_days):
            out.append((le, due, as_of > due))
    return out
