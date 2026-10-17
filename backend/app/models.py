"""ROOMAX 데이터 모델 (PRD §5).

- 금액: 원 단위 정수 (BigInteger)
- 시각: UTC timestamptz
- 모든 업무 데이터는 organization_id 로 거슬러 올라갈 수 있다 (향후 RLS)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.crypto import EncryptedString


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ── 조직·사용자 ──────────────────────────────────────────────

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()


class User(Base):
    """로그인 계정. 한 사업장(organization)에 속한다. 비밀번호는 해시만, MFA 비밀키는 암호화 저장."""
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)  # 소문자로 저장
    name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="owner")  # owner | manager | viewer
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    mfa_secret: Mapped[str | None] = mapped_column(EncryptedString())
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 동의 기록 (개인정보보호법 · 정보통신망법). 마케팅은 선택이라 null 가능
    terms_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    privacy_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marketing_agreed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class EmailToken(Base):
    """이메일 인증·비밀번호 재설정 링크. 링크에는 무작위 토큰, DB 에는 해시만. 한 번 쓰면 끝."""
    __tablename__ = "email_tokens"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # verify_email | reset_password
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Invitation(Base):
    """멤버 초대. 링크에는 무작위 토큰, DB 에는 해시만. 수락·취소하면 이메일을 지운다."""
    __tablename__ = "invitations"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str | None] = mapped_column(String(320))  # 대기 중일 때만 (소문자)
    role: Mapped[str] = mapped_column(String(20))  # manager | viewer
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class AuthSession(Base):
    """로그인 세션. 쿠키에는 무작위 토큰, DB 에는 그 해시만 둔다."""
    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()


# ── 자산·호실 ────────────────────────────────────────────────

class Property(Base):
    __tablename__ = "properties"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(30))  # multi_household | apartment | rural_house
    address: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at()


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (UniqueConstraint("property_id", "unit_no"),)
    id: Mapped[uuid.UUID] = pk()
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), index=True)
    unit_no: Mapped[str] = mapped_column(String(20))
    floor: Mapped[int | None] = mapped_column(Integer)
    area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2))
    use_type: Mapped[str] = mapped_column(String(10))  # rental | owner
    status: Mapped[str] = mapped_column(String(20), default="vacant")  # occupied | vacant | owner
    created_at: Mapped[datetime] = created_at()


# ── 임차인·계약 ──────────────────────────────────────────────

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(EncryptedString())  # 저장 시 암호화
    created_at: Mapped[datetime] = created_at()


class Lease(Base):
    __tablename__ = "leases"
    __table_args__ = (
        CheckConstraint("due_day BETWEEN 1 AND 31", name="ck_leases_due_day"),
        CheckConstraint("rent >= 0 AND deposit >= 0", name="ck_leases_amounts"),
    )
    id: Mapped[uuid.UUID] = pk()
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    deposit: Mapped[int] = mapped_column(BigInteger, default=0)
    rent: Mapped[int] = mapped_column(BigInteger, default=0)  # 관리비 포함 월세
    due_day: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | ended | draft
    signed_on: Mapped[date | None] = mapped_column(Date)  # 계약 체결일 (임대차 신고 기한 30일의 기준). 모르면 비움
    ended_on: Mapped[date | None] = mapped_column(Date)  # 실제로 계약이 끝난 날 (퇴거일). 계약서의 만료일과 다를 수 있음
    end_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class PayerAlias(Base):
    """통장에 찍히는 입금자명 → 계약. 관리자가 매칭을 승인할 때 학습한다."""
    __tablename__ = "payer_aliases"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_payer_aliases_name"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))  # normalize_name() 결과
    created_at: Mapped[datetime] = created_at()


class LeaseDocument(Base):
    """계약서 이미지와 OCR 결과. verified_at 이 채워지기 전에는 원장에 반영하지 않는다.

    파일은 암호화해 저장한다 (file_path = 저장소 안 상대 경로).
    ocr_json = {"provider", "text", "fields": {이름: {"value", "evidence"}}, "error"}
    """
    __tablename__ = "lease_documents"
    id: Mapped[uuid.UUID] = pk()
    lease_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leases.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    original_name: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(50))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)  # 원본 기준, 같은 파일 중복 업로드 확인
    # not_configured | done | failed
    ocr_status: Mapped[str] = mapped_column(String(20), default="not_configured")
    ocr_json: Mapped[dict | None] = mapped_column(JSON)
    verified_fields: Mapped[dict | None] = mapped_column(JSON)  # 관리자가 확정한 값
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


# ── 은행 거래 ────────────────────────────────────────────────

class BankAccount(Base):
    __tablename__ = "bank_accounts"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    alias: Mapped[str] = mapped_column(String(100))
    # 입금 알림 연결 주소의 비밀 토큰 (sha256 만 저장 — 원문은 만들 때 한 번만 보여 줌)
    alert_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    alert_token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("bank_account_id", "fingerprint", name="uq_transactions_fingerprint"),
        CheckConstraint("amount > 0", name="ck_transactions_amount"),
        CheckConstraint("direction IN ('in','out')", name="ck_transactions_direction"),
    )
    id: Mapped[uuid.UUID] = pk()
    bank_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_accounts.id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    description: Mapped[str | None] = mapped_column(String(500))
    counterparty: Mapped[str | None] = mapped_column(String(200))
    balance_after: Mapped[int | None] = mapped_column(BigInteger)
    fingerprint: Mapped[str] = mapped_column(String(64))
    import_batch: Mapped[str | None] = mapped_column(String(64))
    # statement: 통장 내역 파일(CSV/XLSX) · alert: 휴대폰 입금 알림. 알림은 '들어왔다'의 증거일 뿐
    # '안 들어왔다'의 증거가 아니므로, 은행 내역이 어디까지 있는지(미납 판단·결산)는 statement 만 본다
    source: Mapped[str] = mapped_column(String(10), default="statement", server_default="statement")
    created_at: Mapped[datetime] = created_at()


class TransactionAllocation(Base):
    """거래 1건을 계약·분류별로 나눈 것. 혼합 거래의 비율 배분도 여기서."""
    __tablename__ = "transaction_allocations"
    id: Mapped[uuid.UUID] = pk()
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transactions.id"), index=True)
    lease_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leases.id"), index=True)
    # 입금: rent | deposit_in | personal | owner_household | other
    # 출금: common_electricity | water | cleaning | repair | other_operating | owner_household | personal | deposit_out
    # 미정: unclassified
    category: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int] = mapped_column(BigInteger)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | rejected
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    reason: Mapped[str | None] = mapped_column(Text)  # 자동 분류 근거
    created_at: Mapped[datetime] = created_at()


# ── 청구·수납 ────────────────────────────────────────────────

class Charge(Base):
    __tablename__ = "charges"
    __table_args__ = (UniqueConstraint("lease_id", "period", name="uq_charges_lease_period"),)
    id: Mapped[uuid.UUID] = pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | partial | paid | waived
    created_at: Mapped[datetime] = created_at()


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = pk()
    charge_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("charges.id"), index=True)
    transaction_allocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("transaction_allocations.id"), index=True
    )
    amount: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = created_at()


# ── 운영비·보증금 ────────────────────────────────────────────

class Expense(Base):
    """지출 원장. 은행 출금 확정분(transaction_allocation_id)과 현금 수기 입력분(None)을 함께 담는다.

    운영비(임대 순운영수익에 반영): common_electricity | water | cleaning | repair | other_operating
    운영비 아님(별도 집계):        owner_household | personal
    """
    __tablename__ = "expenses"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_expenses_amount"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("properties.id"), index=True)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"))
    transaction_allocation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transaction_allocations.id"), index=True
    )
    category: Mapped[str] = mapped_column(String(30))
    amount: Mapped[int] = mapped_column(BigInteger)
    spent_on: Mapped[date] = mapped_column("date", Date, index=True)
    memo: Mapped[str | None] = mapped_column(String(200))
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at()


class ExpenseRule(Base):
    """거래처 → 분류(비율). 관리자가 확정하며 '기억'을 고른 것만 저장 → 이후 자동 확정.

    splits: [{"category": "personal", "bp": 7000}, {"category": "owner_household", "bp": 3000}]
    bp = 만분율, 합계 10000.
    """
    __tablename__ = "expense_rules"
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_expense_rules_key"),)
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(200))  # normalize_name(거래처 또는 적요)
    label: Mapped[str] = mapped_column(String(200))  # 화면 표시용 원문
    splits: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = created_at()


class Deposit(Base):
    """보증금 = 반환의무(부채). 임대수입에 포함하지 않는다."""
    __tablename__ = "deposits"
    id: Mapped[uuid.UUID] = pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    received_at: Mapped[date | None] = mapped_column(Date)
    returned_at: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = created_at()


# ── 세무 ────────────────────────────────────────────────────

class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("properties.id"))
    type: Mapped[str] = mapped_column(String(30))
    ownership_share: Mapped[float | None] = mapped_column(Numeric(5, 4))  # 0~1, 모르면 null
    assessed_value: Mapped[int | None] = mapped_column(BigInteger)  # 기준시가, 모르면 null
    created_at: Mapped[datetime] = created_at()


class TaxCase(Base):
    """세액은 추정. 귀속연도·법령 버전·입력자료를 함께 남긴다."""
    __tablename__ = "tax_cases"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    tax_type: Mapped[str] = mapped_column(String(30))
    rule_version: Mapped[str | None] = mapped_column(String(50))
    input_snapshot: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="estimate")  # estimate | reviewed
    created_at: Mapped[datetime] = created_at()


# ── 메시지·유지보수·감사 ─────────────────────────────────────

class Notification(Base):
    """임차인에게 보낼 메시지. approved_at 없이 발송하지 않는다 (자동 독촉 금지 — PRD §4).
    알림톡이 연결되기 전에는 승인 후 문구를 복사해 직접 보내고 '직접 보냄'으로 표시한다."""
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id"))
    lease_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leases.id"))
    charge_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("charges.id"), index=True)
    term_end: Mapped[date | None] = mapped_column(Date)  # 계약 만료 안내가 가리키는 만료일 (갱신되면 새 안내 필요)
    channel: Mapped[str] = mapped_column(String(20))  # sms | alimtalk
    template: Mapped[str] = mapped_column(String(100))  # rent_notice | overdue_notice | renewal_notice
    body: Mapped[str | None] = mapped_column(Text)  # 만들 때 채운 문구 (초안에서 고칠 수 있음)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | sent | failed | discarded
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_via: Mapped[str | None] = mapped_column(String(20))  # manual | 알림톡 업체 이름
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class NotificationSetting(Base):
    """사업장별 알림 설정. 유예기간·문구는 관리자가 정한다 (기본값 없음 — 비어 있으면 그 알림은 만들지 않음)."""
    __tablename__ = "notification_settings"
    id: Mapped[uuid.UUID] = pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), unique=True)
    grace_days: Mapped[int | None] = mapped_column(Integer)
    rent_template: Mapped[str | None] = mapped_column(Text)
    overdue_template: Mapped[str | None] = mapped_column(Text)
    renewal_template: Mapped[str | None] = mapped_column(Text)  # 계약 만료 안내 (주임법 §6 갱신 통지)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Fixture(Base):
    """자산대장 — 호실 옵션·집기와 건물 공용 설비. unit_id 가 없으면 건물 공용.
    수명·교체 시기를 시스템이 추정하지 않는다: 교체 예정월(replace_by)은 관리자가 정한 값만."""
    __tablename__ = "fixtures"
    __table_args__ = (
        CheckConstraint("price IS NULL OR price >= 0", name="ck_fixtures_price"),
        CheckConstraint("owner IN ('landlord', 'tenant')", name="ck_fixtures_owner"),
    )
    id: Mapped[uuid.UUID] = pk()
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), index=True)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"), index=True)
    category: Mapped[str] = mapped_column(String(30))  # services/fixtures.CATEGORIES
    name: Mapped[str] = mapped_column(String(100))
    brand: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    manufactured: Mapped[str | None] = mapped_column(String(7))  # 제조연월 YYYY-MM (명판)
    installed_on: Mapped[date | None] = mapped_column(Date)  # 설치·구입일
    price: Mapped[int | None] = mapped_column(BigInteger)  # 구입가 (원)
    warranty_until: Mapped[date | None] = mapped_column(Date)
    owner: Mapped[str] = mapped_column(String(20), default="landlord")  # landlord: 임대인 옵션 | tenant: 임차인 소유
    replace_by: Mapped[str | None] = mapped_column(String(7))  # 교체 예정월 YYYY-MM (관리자가 정함)
    status: Mapped[str] = mapped_column(String(20), default="in_use")  # in_use | removed
    removed_on: Mapped[date | None] = mapped_column(Date)
    removed_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class MaintenanceTicket(Base):
    """수리 이력. 비용은 기록용 — 결산(NOI)에는 은행 출금을 '수리비'로 분류한 것만 들어간다 (이중 계산 방지)."""
    __tablename__ = "maintenance_tickets"
    __table_args__ = (
        CheckConstraint("cost IS NULL OR cost >= 0", name="ck_maintenance_cost"),
        CheckConstraint("payer IN ('landlord', 'tenant', 'undecided')", name="ck_maintenance_payer"),
    )
    id: Mapped[uuid.UUID] = pk()
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), index=True)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"), index=True)  # 없으면 건물 공용
    fixture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fixtures.id"), index=True)
    reported_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done
    completed_on: Mapped[date | None] = mapped_column(Date)
    vendor: Mapped[str | None] = mapped_column(String(100))
    cost: Mapped[int | None] = mapped_column(BigInteger)
    payer: Mapped[str] = mapped_column(String(20), default="undecided")  # 부담: landlord | tenant | undecided
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class Inspection(Base):
    """입주·퇴실 점검. 계약마다 입주 1번, 퇴실 1번. 상태·계량기·사진을 남겨 퇴실 정산의 근거로 쓴다."""
    __tablename__ = "inspections"
    __table_args__ = (UniqueConstraint("lease_id", "kind"),
                      CheckConstraint("kind IN ('move_in', 'move_out')", name="ck_inspections_kind"))
    id: Mapped[uuid.UUID] = pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # move_in | move_out
    inspected_on: Mapped[date] = mapped_column(Date)
    tenant_confirmed_on: Mapped[date | None] = mapped_column(Date)  # 임차인과 함께 확인한 날
    confirm_note: Mapped[str | None] = mapped_column(Text)  # 확인 방법 (예: 현장 동행, 사진 문자 전송)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class InspectionItem(Base):
    """점검 항목 하나 (방·벽지·바닥·옵션 품목·계량기 등). 상태를 모르면 비워 둔다."""
    __tablename__ = "inspection_items"
    id: Mapped[uuid.UUID] = pk()
    inspection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inspections.id"), index=True)
    fixture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fixtures.id"))
    area: Mapped[str] = mapped_column(String(50))
    condition: Mapped[str | None] = mapped_column(String(20))  # good | worn | dirty | damaged | missing
    reading: Mapped[str | None] = mapped_column(String(30))  # 계량기 숫자 (글자 그대로)
    note: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_at()


class InspectionPhoto(Base):
    """점검 사진. 파일은 계약서처럼 암호화해 보관 (services/storage). 올린 시각(UTC)이 증빙 시각."""
    __tablename__ = "inspection_photos"
    id: Mapped[uuid.UUID] = pk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inspection_items.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(50))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()


class MoveOutSettlement(Base):
    """퇴실 정산서. 확정하면 그때 숫자를 남겨 두고(스냅숏) 공제 항목을 잠근다. 실제 반환은 은행 출금 '보증금 반환'."""
    __tablename__ = "move_out_settlements"
    id: Mapped[uuid.UUID] = pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | confirmed
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict | None] = mapped_column(JSON)  # 확정 때 계산 결과
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class SettlementDeduction(Base):
    """보증금에서 뺄 항목 (관리자가 적음). 다툼이 있는 금액(disputed)은 먼저 돌려줄 금액에서 빼고 따로 보관."""
    __tablename__ = "settlement_deductions"
    __table_args__ = (CheckConstraint("amount >= 0", name="ck_settlement_deductions_amount"),)
    id: Mapped[uuid.UUID] = pk()
    settlement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("move_out_settlements.id"), index=True)
    category: Mapped[str] = mapped_column(String(20))  # damage | cleaning | utility | other
    label: Mapped[str] = mapped_column(String(100))
    amount: Mapped[int] = mapped_column(BigInteger)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False)
    inspection_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inspection_items.id"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class LeaseCheck(Base):
    """계약 법정 체크 항목의 처리 기록 (정보 제시·납세증명서·임대차 신고). done: 했음 | na: 해당 없음."""
    __tablename__ = "lease_checks"
    __table_args__ = (UniqueConstraint("lease_id", "key"),
                      CheckConstraint("status IN ('done', 'na')", name="ck_lease_checks_status"))
    id: Mapped[uuid.UUID] = pk()
    lease_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leases.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10))
    done_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class ExpenseReceipt(Base):
    """지출 증빙(영수증·세금계산서 사진·PDF). 파일은 암호화 보관(services/storage), 백업에 포함."""
    __tablename__ = "expense_receipts"
    id: Mapped[uuid.UUID] = pk()
    expense_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expenses.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(50))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    original_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_at()


class RoutineTask(Base):
    """정기 점검·소모품 일정 (소방·청소·설비 점검·보험 갱신 등). unit_id 가 없으면 건물 공용.
    주기·다음 예정일은 관리자가 정한 값만 — 법정 주기도 시스템이 정하지 않는다."""
    __tablename__ = "routine_tasks"
    __table_args__ = (CheckConstraint("interval_months IS NULL OR interval_months BETWEEN 1 AND 120",
                                      name="ck_routine_tasks_interval"),)
    id: Mapped[uuid.UUID] = pk()
    property_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("properties.id"), index=True)
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id"), index=True)
    fixture_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("fixtures.id"), index=True)
    title: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(30))  # services/routines.CATEGORIES
    interval_months: Mapped[int | None] = mapped_column(Integer)  # 없으면 한 번만 (예: 이번 보험 갱신)
    next_due_on: Mapped[date | None] = mapped_column(Date)  # 모르면 비움
    vendor: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | stopped
    created_at: Mapped[datetime] = created_at()


class RoutineLog(Base):
    """정기 점검 한 번 한 기록. 지우면 다음 예정일을 이 기록 전 값으로 되돌린다."""
    __tablename__ = "routine_logs"
    __table_args__ = (CheckConstraint("cost IS NULL OR cost >= 0", name="ck_routine_logs_cost"),)
    id: Mapped[uuid.UUID] = pk()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routine_tasks.id"), index=True)
    done_on: Mapped[date] = mapped_column(Date)
    cost: Mapped[int | None] = mapped_column(BigInteger)  # 기록용 — 결산은 은행 출금 분류로만
    vendor: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    prev_next_due_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = created_at()


class BankAlert(Base):
    """받은 입금 알림 원문과 처리 결과 (형식 보강·문제 확인용)."""
    __tablename__ = "bank_alerts"
    id: Mapped[uuid.UUID] = pk()
    bank_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bank_accounts.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))  # created | duplicate | unparsed | outgoing
    parsed: Mapped[dict | None] = mapped_column(JSON)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transactions.id"))
    created_at: Mapped[datetime] = created_at()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)  # 개인정보 넣지 말 것
    created_at: Mapped[datetime] = created_at()
