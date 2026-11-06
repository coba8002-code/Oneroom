"""셀프 신고 도우미 — 주택임대소득 종합소득세를 건물주가 홈택스에서 직접 신고하도록 숫자를 모아 준다.

원칙 (CLAUDE.md 규칙 6 · 세무사법)
- 세액은 '추정'만. 신고 확정·판정·상담이 아니다. 대신 작성·제출하지 않는다 (제출은 본인이 홈택스에서)
- 수입은 장부의 확정 입금만, 은행 내역이 있는 달만 더한다 (모르는 달을 0 이나 평균으로 채우지 않음)
- 분리과세는 연 수입 2천만 원 이하일 때만 선택지로 보여 준다. 넘으면 세무사 상담을 권한다
- 세율·경비율·공제액은 아래 상수 — 귀속연도마다 법령을 확인해 바꿀 것 (LAW_BASIS)

계산 (추정)
- 수입 = 월세 확정 입금 + 관리비 확정 입금 (공과금 배분 입금·보증금은 넣지 않음)
- 분리과세: (수입 × (1 − 필요경비율) − 기본공제) × 14%  · 기본공제는 다른 종합소득금액 2천만 원 이하일 때만
- 종합과세(장부 기준): 수입 − 장부의 운영비 → 다른 종합소득에 더했을 때 늘어나는 소득세 (누진세율 차이)
  · 인적공제·세액공제·감가상각·이자·임대주택 세액감면·간주임대료는 넣지 않음 (화면에 표시)
- 지방소득세 = 소득세의 10%
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.services import tax_prep

LAW_BASIS = "2026년 귀속 기준으로 넣은 값 — 신고 전 국세청 안내로 확인 필요"
SEPARATE_LIMIT = 20_000_000
SEPARATE_RATE = 0.14
EXPENSE_RATE = {True: 0.60, False: 0.50}  # 등록 임대주택 / 미등록
BASIC_DEDUCTION = {True: 4_000_000, False: 2_000_000}
OTHER_INCOME_LIMIT = 20_000_000  # 기본공제 조건: 다른 종합소득금액 2천만 원 이하
LOCAL_RATE = 0.10
BRACKETS = (  # (과세표준 상한, 세율, 누진공제)
    (14_000_000, 0.06, 0), (50_000_000, 0.15, 1_260_000), (88_000_000, 0.24, 5_760_000),
    (150_000_000, 0.35, 15_440_000), (300_000_000, 0.38, 19_940_000), (500_000_000, 0.40, 25_940_000),
    (1_000_000_000, 0.42, 35_940_000), (None, 0.45, 65_940_000),
)
NOTICE = ("추정치입니다 — 신고 확정이나 세무 판정이 아닙니다. 어느 방식으로 신고할지는 본인이 정하고, "
          "홈택스 모의계산으로 확인한 뒤 본인이 직접 제출하세요. 복잡한 경우(수입 2천만 원 초과, 공동명의, "
          "주택 여러 채·고가주택, 임대주택 세액감면)는 세무사 상담을 권합니다.")
NOT_INCLUDED = ["인적공제·특별공제·세액공제", "감가상각비·대출이자 등 장부에 없는 경비", "등록 임대주택 세액감면",
                "보증금 간주임대료 (해당 여부 확인 필요)", "다른 소득의 세부 공제"]
HOMETAX_STEPS = [
    "홈택스(또는 손택스)에 본인 인증으로 로그인합니다",
    "종합소득세 신고 메뉴로 들어갑니다 (메뉴 이름은 해마다 바뀔 수 있습니다)",
    "주택임대소득 항목에 아래 '수입금액'을 넣고, 분리과세 또는 종합과세 중 고른 방식을 선택합니다",
    "등록 임대주택이면 등록 여부를 표시합니다 (필요경비율·공제가 달라짐)",
    "모의계산 결과를 이 화면의 추정치와 비교합니다 — 많이 다르면 제출 전에 세무사·126 상담",
    "제출은 본인이 홈택스에서 직접 합니다 (ROOMAX 는 대신 제출하지 않습니다)",
]


def progressive_tax(base: int) -> int:
    if base <= 0:
        return 0
    for limit, rate, deduct in BRACKETS:
        if limit is None or base <= limit:
            return int(base * rate - deduct)
    return 0  # 도달하지 않음


def estimate(session: Session, organization_id: uuid.UUID, year: int, registered: bool, other_income: int | None,
             today: date) -> dict:
    data = tax_prep.annual(session, organization_id, year, today)
    t = data["totals_known_months"]
    st = data["status"]
    rent, mgmt = t["rent_received"], t["mgmt_received"]
    revenue = None if rent is None and mgmt is None else int((rent or 0) + (mgmt or 0))
    expenses = t["operating_total"]
    warnings = []
    if st["months_without_bank_data"]:
        warnings.append(f"은행 내역이 없는 달 {len(st['months_without_bank_data'])}개는 수입에 들어가지 않았습니다: "
                        + ", ".join(st["months_without_bank_data"]))
    if st["pending_review_in"]:
        warnings.append(f"검토 대기 입금 {st['pending_review_in']}건 — 확정하면 수입이 바뀔 수 있습니다")
    if not st["year_complete"]:
        warnings.append("아직 끝나지 않은 연도입니다 — 지금까지의 값입니다")
    if other_income is None:
        warnings.append("다른 종합소득금액을 넣지 않아 0원으로 보고 계산했습니다 (근로·사업소득 등이 있으면 넣으세요)")
    other = max(0, other_income or 0)

    separate = None
    if revenue is not None and revenue <= SEPARATE_LIMIT:
        rate = EXPENSE_RATE[registered]
        deduction = BASIC_DEDUCTION[registered] if other <= OTHER_INCOME_LIMIT else 0
        income = int(revenue * (1 - rate))
        base = max(0, income - deduction)
        tax = int(base * SEPARATE_RATE)
        separate = {"revenue": revenue, "expense_rate": rate, "income": income, "deduction": deduction,
                    "taxable": base, "income_tax": tax, "local_tax": int(tax * LOCAL_RATE),
                    "total": tax + int(tax * LOCAL_RATE)}

    combined = None
    if revenue is not None:
        rent_income = max(0, revenue - (expenses or 0))
        added = progressive_tax(other + rent_income) - progressive_tax(other)
        combined = {"revenue": revenue, "book_expenses": expenses, "income": rent_income, "other_income": other,
                    "income_tax_added": added, "local_tax": int(added * LOCAL_RATE),
                    "total": added + int(added * LOCAL_RATE)}

    lower = None
    if separate and combined:
        lower = "separate" if separate["total"] < combined["total"] else "combined" if combined["total"] < separate["total"] else "same"
    return {
        "year": year, "registered": registered, "law_basis": LAW_BASIS, "notice": NOTICE,
        "revenue": revenue, "rent_received": rent, "mgmt_received": mgmt,
        "separate_available": revenue is not None and revenue <= SEPARATE_LIMIT,
        "separate": separate, "combined": combined, "lower_estimate": lower,
        "advisor_recommended": revenue is not None and revenue > SEPARATE_LIMIT,
        "warnings": warnings, "not_included": NOT_INCLUDED, "hometax_steps": HOMETAX_STEPS,
    }
