"""세무 준비 — 귀속연도별 입력자료 모음과 지출 증빙. 세액을 계산하거나 판정하지 않는다 (CLAUDE.md 규칙 6).

- 월별 숫자는 월 결산(reports.monthly)과 같은 정의. 은행 내역이 없는 달은 비워 두고(None), 그 달을 '자료 없는 달'로 표시한다.
  연간 합계는 '자료 있는 달만 더한 값'이라고 이름 붙여 돌려준다 — 빈 달을 0 으로 치지 않는다.
- 월세는 두 기준을 함께 보인다: 청구 기준(납부일이 그 해) · 입금 기준(확정된 입금이 그 해). 어느 쪽이 세법상 수입시기인지는 정하지 않는다.
- 보증금은 수입이 아니라 부채 — 연말(12/31) 기준 받았고 돌려주지 않은 잔액을 계약별로 보인다 (간주임대료 판단의 입력자료).
- 결과에는 귀속연도·작성 시각·입력자료 상태를 붙이고, '신고 확정'이 아니라고 적는다.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from datetime import date, datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Deposit, Expense, ExpenseReceipt, Lease, Property, Tenant, Unit
from app.services import receivables, reports, storage
from app.services.contracts import UploadError, detect
from app.services.expenses import NON_OPERATING, OPERATING

LABELS = {"common_electricity": "공용 전기료", "water": "수도료", "cleaning": "청소비", "repair": "수리비",
          "other_operating": "공용 기타", "owner_household": "주인세대", "personal": "개인 생활비"}
MAX_RECEIPT_BYTES = 4_000_000
NOTICE = "세무 신고용 입력자료 모음입니다. 세액 계산·신고 확정이 아니며, 수입 시기·필요경비 인정 여부는 세무사·국세청 안내로 확인하세요."


class TaxPrepError(Exception):
    pass


def _expense(session: Session, organization_id: uuid.UUID, expense_id: uuid.UUID) -> Expense:
    e = session.scalar(select(Expense).where(Expense.id == expense_id, Expense.organization_id == organization_id))
    if e is None:
        raise LookupError("지출을 찾을 수 없습니다")
    return e


def add_receipt(session: Session, organization_id: uuid.UUID, user_id, expense_id: uuid.UUID, raw: bytes,
                filename: str | None) -> ExpenseReceipt:
    e = _expense(session, organization_id, expense_id)
    if len(raw) > MAX_RECEIPT_BYTES:
        raise UploadError("파일이 너무 큽니다 (4MB 이하)", 413)
    _, content_type = detect(raw)  # JPG·PNG·PDF
    digest = hashlib.sha256(raw).hexdigest()
    if session.scalar(select(ExpenseReceipt.id).where(ExpenseReceipt.expense_id == e.id, ExpenseReceipt.sha256 == digest)):
        raise TaxPrepError("이 지출에 이미 붙인 파일입니다")
    r = ExpenseReceipt(expense_id=e.id, file_path=storage.save(raw), content_type=content_type, size=len(raw),
                       sha256=digest, original_name=(filename or "")[:255] or None)
    session.add(r)
    session.flush()
    session.add(AuditLog(user_id=user_id, action="expense.receipt_add", entity_type="expense", entity_id=str(e.id),
                         detail={"sha256": digest}))
    session.commit()
    return r


def get_receipt(session: Session, organization_id: uuid.UUID, receipt_id: uuid.UUID) -> ExpenseReceipt:
    r = session.get(ExpenseReceipt, receipt_id)
    if r is None:
        raise LookupError("증빙을 찾을 수 없습니다")
    _expense(session, organization_id, r.expense_id)
    return r


def delete_receipt(session: Session, r: ExpenseReceipt, user_id) -> None:
    name = r.file_path
    session.add(AuditLog(user_id=user_id, action="expense.receipt_delete", entity_type="expense",
                         entity_id=str(r.expense_id), detail={"sha256": r.sha256}))
    session.delete(r)
    session.commit()
    storage.delete(name)


def expenses_of_year(session: Session, organization_id: uuid.UUID, year: int) -> list[dict]:
    unit_no = dict(session.execute(select(Unit.id, Unit.label).join(Property, Unit.property_id == Property.id)
                                   .where(Property.organization_id == organization_id)).all())
    rows = list(session.scalars(select(Expense).where(
        Expense.organization_id == organization_id, Expense.spent_on >= date(year, 1, 1),
        Expense.spent_on < date(year + 1, 1, 1)).order_by(Expense.spent_on, Expense.created_at)))
    receipts: dict[uuid.UUID, list[dict]] = {}
    for r in session.scalars(select(ExpenseReceipt).where(ExpenseReceipt.expense_id.in_([e.id for e in rows]))
                             .order_by(ExpenseReceipt.created_at)):
        receipts.setdefault(r.expense_id, []).append(
            {"id": str(r.id), "name": r.original_name, "content_type": r.content_type, "uploaded_at": r.created_at})
    return [{"id": str(e.id), "spent_on": e.spent_on, "category": e.category, "label": LABELS.get(e.category, e.category),
             "operating": e.category in OPERATING, "amount": int(e.amount), "unit_no": unit_no.get(e.unit_id),
             "memo": e.memo, "from_bank": e.transaction_allocation_id is not None,
             "receipts": receipts.get(e.id, [])} for e in rows]


def _deposits_at(session: Session, organization_id: uuid.UUID, day: date) -> list[dict]:
    rows = session.execute(
        select(Deposit, Unit.label, Tenant.name, Lease.status).join(Lease, Deposit.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id).join(Property, Unit.property_id == Property.id)
        .join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Property.organization_id == organization_id, Deposit.received_at.is_not(None),
               Deposit.received_at <= day)
        .order_by(Unit.label, Deposit.received_at)).all()
    return [{"unit_no": u, "tenant_name": n, "amount": int(d.amount), "received_at": d.received_at,
             "returned_at": d.returned_at, "lease_status": st}
            for d, u, n, st in rows if d.returned_at is None or d.returned_at > day]


def annual(session: Session, organization_id: uuid.UUID, year: int, as_of: date) -> dict:
    if not 2000 <= year <= as_of.year:
        raise TaxPrepError("귀속연도를 확인하세요")
    months = []
    for m in range(1, 13):
        period = f"{year}-{m:02d}"
        if date(year, m, 1) > as_of:
            months.append({"period": period, "future": True})
            continue
        r = reports.monthly(session, organization_id, period)
        months.append({"period": period, "future": False, "bank_covered": r["bank_covered"],
                       "rent_charged": r["rent_charged"], "rent_received": r["rent_received"],
                       # 관리비·공과금은 월세와 따로 (따로 청구한 달만 값이 있음)
                       "mgmt_charged": r["mgmt_charged"], "mgmt_received": r["mgmt_received"],
                       "utility_charged": r["utility_charged"], "utility_received": r["utility_received"],
                       "operating_total": r["operating_total"], "operating": r["operating"],
                       "excluded": {k: r["excluded"][k] for k in NON_OPERATING},
                       "unconfirmed": r["unconfirmed_in"] + r["unconfirmed_out"]})
    past = [m for m in months if not m["future"]]
    known = [m for m in past if m["bank_covered"]]

    def known_sum(key: str):
        vals = [m[key] for m in known if m[key] is not None]
        return int(sum(vals)) if vals else None

    expenses = expenses_of_year(session, organization_id, year)
    operating = [e for e in expenses if e["operating"]]
    dec31 = date(year, 12, 31)
    deposits = _deposits_at(session, organization_id, min(dec31, as_of))
    status = {
        "months_with_bank_data": [m["period"] for m in known],
        "months_without_bank_data": [m["period"] for m in past if not m["bank_covered"]],
        "unconfirmed_transactions": sum(m["unconfirmed"] for m in past),
        "pending_review_in": receivables.unconfirmed_count(session, organization_id, "in"),
        "pending_review_out": receivables.unconfirmed_count(session, organization_id, "out"),
        "operating_without_receipt": sum(1 for e in operating if not e["receipts"]),
        "year_complete": as_of > dec31,
    }
    return {
        "year": year, "generated_at": datetime.now(timezone.utc), "notice": NOTICE, "status": status, "months": months,
        "totals_known_months": {  # 자료 있는 달만 더한 값 — 빈 달을 0 으로 치지 않음
            "rent_charged": int(sum(m["rent_charged"] or 0 for m in past)) if any(m["rent_charged"] is not None for m in past) else None,
            "rent_received": known_sum("rent_received"),
            "mgmt_charged": _sum_present(past, "mgmt_charged"),
            "mgmt_received": known_sum("mgmt_received"),
            "utility_charged": _sum_present(past, "utility_charged"),
            "utility_received": known_sum("utility_received"),
            "operating_total": known_sum("operating_total"),
            "by_category": {c: int(sum(e["amount"] for e in operating if e["category"] == c)) for c in OPERATING},
        },
        "deposits_at": min(dec31, as_of), "deposits": deposits,
        "deposits_total": int(sum(d["amount"] for d in deposits)),
        "expenses": expenses,
    }


def _sum_present(months: list[dict], key: str) -> int | None:
    vals = [m[key] for m in months if m[key] is not None]
    return int(sum(vals)) if vals else None


def to_xlsx(data: dict) -> bytes:
    wb = Workbook()
    bold = Font(bold=True)
    ws = wb.active
    ws.title = "요약"
    st = data["status"]
    rows = [
        ["ROOMAX 세무 준비 자료", ""], ["귀속연도", data["year"]],
        ["작성 시각 (KST)", data["generated_at"].astimezone(reports.KST).strftime("%Y-%m-%d %H:%M")],
        ["주의", data["notice"]], [],
        ["입력자료 상태", ""],
        ["은행 내역 있는 달", ", ".join(st["months_with_bank_data"]) or "—"],
        ["은행 내역 없는 달 (합계에서 빠짐)", ", ".join(st["months_without_bank_data"]) or "없음"],
        ["확정 안 된 거래 (그 해)", st["unconfirmed_transactions"]],
        ["증빙 없는 운영비 건수", st["operating_without_receipt"]],
        ["연도 마감 여부", "마감" if st["year_complete"] else "진행 중 (연도가 끝나지 않음)"], [],
        ["합계 (자료 있는 달만)", ""],
        ["월세 청구 (납부일 기준)", data["totals_known_months"]["rent_charged"]],
        ["월세 입금 (확정 입금 기준)", data["totals_known_months"]["rent_received"]],
        ["관리비 청구 (따로 청구한 달)", data["totals_known_months"]["mgmt_charged"]],
        ["관리비 입금 (확정 입금 기준)", data["totals_known_months"]["mgmt_received"]],
        ["공과금 청구 (배분)", data["totals_known_months"]["utility_charged"]],
        ["공과금 입금 (확정 입금 기준)", data["totals_known_months"]["utility_received"]],
        ["운영비", data["totals_known_months"]["operating_total"]],
        *[[f"  {LABELS[c]}", v] for c, v in data["totals_known_months"]["by_category"].items()],
        [f"보증금 잔액 ({data['deposits_at']} 기준, 부채)", data["deposits_total"]],
    ]
    for r in rows:
        ws.append([("—" if v is None else v) for v in r] if r else [])
    for cell in ("A1", "A6", "A13"):
        ws[cell].font = bold
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 60

    wm = wb.create_sheet("월별")
    wm.append(["월", "은행 내역", "월세 청구", "월세 입금", "관리비 청구", "관리비 입금", "공과금 청구", "공과금 입금",
               "운영비", "주인세대", "생활비", "미확정 거래"])
    for m in data["months"]:
        if m["future"]:
            wm.append([m["period"], "아직", *[None] * 10])
            continue
        dash = lambda v: "—" if v is None else v  # noqa: E731
        wm.append([m["period"], "있음" if m["bank_covered"] else "없음", dash(m["rent_charged"]), dash(m["rent_received"]),
                   dash(m["mgmt_charged"]), dash(m["mgmt_received"]), dash(m["utility_charged"]),
                   dash(m["utility_received"]), dash(m["operating_total"]), dash(m["excluded"]["owner_household"]), dash(m["excluded"]["personal"]),
                   m["unconfirmed"]])

    we = wb.create_sheet("경비 내역")
    we.append(["날짜", "분류", "운영비", "금액", "호실", "메모", "출처", "증빙 수"])
    for e in data["expenses"]:
        we.append([e["spent_on"].isoformat(), e["label"], "예" if e["operating"] else "아니오(제외)", e["amount"],
                   e["unit_no"] or "", e["memo"] or "", "은행" if e["from_bank"] else "수기", len(e["receipts"])])

    wd = wb.create_sheet("보증금")
    wd.append(["호실", "임차인", "금액", "받은 날", "돌려준 날", "계약 상태"])
    for d in data["deposits"]:
        wd.append([d["unit_no"], d["tenant_name"], d["amount"], d["received_at"].isoformat(),
                   d["returned_at"].isoformat() if d["returned_at"] else "", "진행 중" if d["lease_status"] == "active" else "종료"])
    for sheet in (wm, we, wd):
        for c in sheet[1]:
            c.font = bold
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
