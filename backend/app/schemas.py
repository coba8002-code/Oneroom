from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PropertyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: Literal["multi_household", "apartment", "rural_house"] = "multi_household"
    address: str | None = None


class UnitIn(BaseModel):
    unit_no: str = Field(min_length=1, max_length=20)
    floor: int | None = None
    area_m2: float | None = Field(default=None, ge=0)
    use_type: Literal["rental", "owner"] = "rental"
    # 임차인이 있으면 계약 생성. 없으면 공실.
    tenant_name: str | None = None
    tenant_phone: str | None = None
    deposit: int | None = Field(default=None, ge=0)
    rent: int | None = Field(default=None, ge=0)
    mgmt_fee: int | None = Field(default=None, ge=0)  # 정액 관리비 (선택). 비우면 '따로 적지 않음'
    due_day: int | None = Field(default=None, ge=1, le=31)
    start_date: date | None = None
    end_date: date | None = None
    deposit_received_on: date | None = None

    @model_validator(mode="after")
    def _lease_fields(self) -> UnitIn:
        if self.use_type == "owner":
            if self.tenant_name:
                raise ValueError(f"{self.unit_no}: 주인세대에는 임차인을 넣을 수 없습니다")
            return self
        if self.tenant_name:
            missing = [
                label
                for label, v in (("월세", self.rent), ("납부일", self.due_day), ("계약시작", self.start_date))
                if v is None
            ]
            if missing:
                raise ValueError(f"{self.unit_no}: 계약을 만들려면 {', '.join(missing)} 이(가) 필요합니다")
            if self.end_date and self.start_date and self.end_date < self.start_date:
                raise ValueError(f"{self.unit_no}: 계약종료가 계약시작보다 빠릅니다")
        return self


class OnboardingIn(BaseModel):
    property: PropertyIn
    bank_account_alias: str = Field(default="주거래 통장", max_length=100)
    bank_account_id: uuid.UUID | None = None  # 두 번째 건물부터: 이미 있는 계좌를 함께 쓰려면 지정 (비우면 새 계좌)
    units: list[UnitIn] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_units(self) -> OnboardingIn:
        seen: set[str] = set()
        for u in self.units:
            if u.unit_no in seen:
                raise ValueError(f"호실 번호 중복: {u.unit_no}")
            seen.add(u.unit_no)
        return self


class OnboardingOut(BaseModel):
    organization_id: uuid.UUID
    property_id: uuid.UUID
    bank_account_id: uuid.UUID
    units: int
    leases: int
    vacant: int
    deposits_total: int  # 반환의무 합계 (매출 아님)


class RowError(BaseModel):
    row: int  # 파일 기준 행 번호 (헤더 = 1)
    message: str


class CsvPreviewOut(BaseModel):
    units: list[UnitIn]
    errors: list[RowError]


class ChargeOut(BaseModel):
    id: uuid.UUID
    lease_id: uuid.UUID
    unit_no: str
    period: str
    due_date: date
    amount: int
    status: str
    kind: str = "rent"  # rent | electricity | water | gas | internet (공과금 배분 청구)


class GenerateChargesOut(BaseModel):
    period: str
    created: int
    already_existed: int
    charges: list[ChargeOut]


class ImportOut(BaseModel):
    batch: str
    total_rows: int
    inserted: int
    duplicates: int
    errors: list[RowError]
    merged_alerts: int = 0  # 입금 알림으로 먼저 들어온 거래와 합친 줄 수
    alerts_without_statement: int = 0  # 이 파일 기간 안인데 내역에서 짝을 못 찾은 알림 거래 — 확인 필요


# ── 입금 매칭 · 미수 ─────────────────────────────────────────

class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str


class LeaseOut(BaseModel):
    lease_id: uuid.UUID
    unit_no: str
    tenant_name: str
    rent: int
    due_day: int


class MatchRunOut(BaseModel):
    auto_confirmed: int
    pending: int


class TransactionOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    amount: int
    direction: str
    counterparty: str | None
    description: str | None


Category = Literal["rent", "deposit_in", "personal", "owner_household", "other"]


class SuggestionOut(BaseModel):
    allocation_id: uuid.UUID
    lease_id: uuid.UUID | None
    unit_no: str | None
    category: str
    confidence: float | None
    reason: str | None


class QueueItem(BaseModel):
    transaction: TransactionOut
    suggestion: SuggestionOut | None  # None = 제안을 거절했거나 확정을 취소한 거래


class DecisionIn(BaseModel):
    lease_id: uuid.UUID | None = None
    category: Category
    remember_alias: bool = False


class AllocationOut(BaseModel):
    id: uuid.UUID
    transaction: TransactionOut
    lease_id: uuid.UUID | None
    unit_no: str | None
    category: str
    amount: int
    review_status: str
    confidence: float | None
    reason: str | None


class ReceivableItem(BaseModel):
    unit_no: str
    tenant_name: str
    period: str
    due_date: date
    amount: int
    paid: int
    outstanding: int
    days_past_due: int
    kind: str = "rent"


class CreditItem(BaseModel):
    unit_no: str
    credit: int


class ReceivablesOut(BaseModel):
    as_of: date
    # 미납 판단의 근거가 되는 최신 거래 시각. 오래됐으면 미납이 아닐 수 있다 (PRD §4)
    bank_data_as_of: datetime | None
    pending_review: int
    items: list[ReceivableItem]
    credits: list[CreditItem]


# ── 운영비 · 월 결산 ────────────────────────────────────────

ExpenseCategory = Literal[
    "common_electricity", "water", "cleaning", "repair", "other_operating", "owner_household", "personal",
]
OutCategory = Literal[
    "common_electricity", "water", "cleaning", "repair", "other_operating", "owner_household", "personal",
    "deposit_out",
]


class ClassifyOut(BaseModel):
    auto_confirmed: int
    pending: int


class SplitIn(BaseModel):
    category: OutCategory
    amount: int = Field(gt=0)
    unit_id: uuid.UUID | None = None  # 특정 호실 수리 등


class ExpenseDecisionIn(BaseModel):
    splits: list[SplitIn] = Field(min_length=1, max_length=10)
    lease_id: uuid.UUID | None = None  # 보증금 반환일 때
    remember: bool = False  # 이 거래처를 같은 비율로 기억 → 다음부터 자동 확정


class ConfirmedOut(BaseModel):
    transaction: TransactionOut
    splits: list[dict]  # [{category, amount, unit_no}]
    reason: str | None


class ExpenseOut(BaseModel):
    id: uuid.UUID
    category: str
    amount: int
    spent_on: date
    memo: str | None
    unit_no: str | None
    from_bank: bool


class ManualExpenseIn(BaseModel):
    category: ExpenseCategory
    amount: int = Field(gt=0)
    spent_on: date
    memo: str | None = Field(default=None, max_length=200)
    unit_id: uuid.UUID | None = None


class ExpenseRuleOut(BaseModel):
    id: uuid.UUID
    label: str
    splits: list[dict]


class UnitOut(BaseModel):
    unit_id: uuid.UUID
    unit_no: str


class MonthlyReportOut(BaseModel):
    """null = 모름 (청구 전이거나 은행 내역이 그 달에 닿지 않음). 화면은 '—'."""
    period: str
    charges_ready: bool  # 그 달 청구를 만들었는가
    bank_covered: bool  # 은행 내역이 그 달 1일 이후까지 있는가
    rent_charged: int | None
    rent_received: int | None  # 월세 몫만 (같은 입금으로 채운 공과금 청구는 아래로)
    mgmt_charged: int | None = None  # 관리비 청구 합 (따로 청구하지 않았으면 비움)
    mgmt_received: int | None = None
    utility_charged: int | None = None  # 공과금 배분 청구 합 (없으면 비움)
    utility_received: int | None = None
    operating: dict[str, int | None]
    operating_total: int | None
    noi: int | None
    excluded: dict[str, int | None]
    unconfirmed_in: int
    unconfirmed_out: int
    complete: bool
    bank_data_as_of: datetime | None


# ── 대시보드 ────────────────────────────────────────────────

class BankAccountOut(BaseModel):
    id: uuid.UUID
    alias: str
    alert_since: datetime | None = None  # 입금 알림 연결 주소를 만든 시각 (없으면 연결 안 됨)


class DashUnit(BaseModel):
    unit_no: str
    floor: int | None
    use_type: str
    status: str
    tenant_name: str | None
    rent: int | None
    due_day: int | None
    due_date: date | None  # 이번 달 납부일 (말일 보정)
    charge_status: str | None  # paid | partial | open | none(청구 미생성) | None(공실·주인세대)
    outstanding: int | None
    paid_on: date | None  # 완납일 (마지막 입금 거래일, KST)
    lease_end: date | None


class DashCounts(BaseModel):
    total: int
    rental: int
    occupied: int
    vacant: int
    owner: int


class DashMoney(BaseModel):
    """null = 모름 (MonthlyReportOut 과 같은 규칙). 화면은 '—'."""
    rent_charged: int | None
    rent_received: int | None
    overdue_total: int
    overdue_count: int
    operating_total: int | None
    noi: int | None
    non_operating_total: int | None  # 생활비 + 주인세대 (NOI 제외)
    complete: bool
    charges_ready: bool
    bank_covered: bool


class RecentTransaction(BaseModel):
    occurred_at: datetime
    direction: str
    amount: int
    label: str
    confirmed: bool


class DueSoon(BaseModel):
    unit_no: str
    due_date: date
    outstanding: int


class DueToday(BaseModel):
    unit_no: str
    tenant_name: str
    period: str
    amount: int
    paid: int
    status: str  # paid | partial | review(입금 검토 대기 있음) | not_yet(아직 확인된 입금 없음 — 미납 단정 아님)
    paid_at: datetime | None  # 이 청구에 들어간 가장 늦은 입금 시각
    via: str | None  # alert(휴대폰 알림) | statement(통장 내역)
    review_count: int


class LeaseEnding(BaseModel):
    unit_no: str
    tenant_name: str
    end_date: date
    days_left: int
    deposit_to_return: int | None
    stage: Literal["early", "open", "closed", "ended"]
    notice_from: date
    notice_until: date
    notice_sent_on: date | None


class TaxEventOut(BaseModel):
    name: str
    start: date
    end: date
    note: str
    url: str
    in_progress: bool
    days_until_end: int


class AttentionItem(BaseModel):
    level: Literal["warn", "info"]
    kind: str
    message: str
    href: str


class DashboardOut(BaseModel):
    as_of: date
    period: str
    bank_data_as_of: datetime | None
    counts: DashCounts
    units: list[DashUnit]
    money: DashMoney
    recent_transactions: list[RecentTransaction]
    due_soon: list[DueSoon]
    due_today: list[DueToday] = []
    lease_endings: list[LeaseEnding]
    tax_events: list[TaxEventOut]
    attention: list[AttentionItem]


# ── 계약서 · OCR ────────────────────────────────────────────

class DocumentSummary(BaseModel):
    id: uuid.UUID
    original_name: str | None
    created_at: datetime
    ocr_status: str
    verified_at: datetime | None


class ContractOut(BaseModel):
    lease_id: uuid.UUID
    unit_no: str
    tenant_name: str
    deposit: int
    rent: int
    mgmt_fee: int | None = None
    due_day: int
    start_date: date
    end_date: date | None
    documents: list[DocumentSummary]


class ExtractedField(BaseModel):
    value: int | str | None
    evidence: str | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    lease_id: uuid.UUID
    unit_no: str
    original_name: str | None
    content_type: str | None
    created_at: datetime
    ocr_status: str  # not_configured | done | failed
    ocr_provider: str | None
    ocr_error: str | None
    ocr_text: str | None
    fields: dict[str, ExtractedField] | None  # OCR 후보 (확정 아님)
    current: dict  # 지금 원장 값
    verified_at: datetime | None
    verified_fields: dict | None


class VerifyIn(BaseModel):
    """관리자가 확정한 최종 값 (화면에서 OCR 후보로 미리 채움)."""
    deposit: int = Field(ge=0)
    rent: int = Field(ge=0)
    mgmt_fee: int | None = Field(default=None, ge=0)  # 정액 관리비. 비우면 '따로 적지 않음'
    due_day: int = Field(ge=1, le=31)
    start_date: date
    end_date: date | None = None


class OcrSettingsOut(BaseModel):
    configured: bool
    provider: str | None
