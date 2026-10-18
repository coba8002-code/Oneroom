"""건물·호실·임차인·계약·보증금 초기 등록."""
from __future__ import annotations

import csv
import io
import uuid
from datetime import date

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, BankAccount, Deposit, Lease, Organization, Property, Tenant, Unit
from app.schemas import OnboardingIn, OnboardingOut, RowError, UnitIn

# 온보딩 CSV 헤더 (samples/onboarding_units.csv)
CSV_COLUMNS = {
    "호실": "unit_no",
    "층": "floor",
    "면적㎡": "area_m2",
    "용도": "use_type",
    "임차인": "tenant_name",
    "연락처": "tenant_phone",
    "보증금": "deposit",
    "월세": "rent",
    "관리비": "mgmt_fee",  # 선택 열 — 비우면 '따로 적지 않음'
    "납부일": "due_day",
    "계약시작": "start_date",
    "계약종료": "end_date",
    "보증금수령일": "deposit_received_on",
}
USE_TYPE_LABELS = {"임대": "rental", "주인": "owner", "주인세대": "owner", "rental": "rental", "owner": "owner"}


class OnboardingError(ValueError):
    pass


def onboard(session: Session, organization_id: uuid.UUID, data: OnboardingIn) -> OnboardingOut:
    """로그인한 사업장에 건물·호실·계약을 등록한다 (사업장은 회원가입 때 만들어짐)."""
    org = session.get(Organization, organization_id)
    # 건물이 여러 동이면 호실을 '건물 이름 + 호실'로 구분한다 → 사업장 안에서 건물 이름이 겹치면 안 됨
    name = " ".join(data.property.name.split())
    taken = {" ".join(n.split()) for n in session.scalars(
        select(Property.name).where(Property.organization_id == org.id))}
    if name in taken:
        raise OnboardingError(f"이미 '{name}' 건물이 있습니다. 다른 이름을 쓰세요 (예: 행복빌라 2동)")
    prop = Property(organization_id=org.id, **{**data.property.model_dump(), "name": name})
    if data.bank_account_id is not None:
        account = session.get(BankAccount, data.bank_account_id)
        if account is None or account.organization_id != org.id:
            raise OnboardingError("계좌를 찾을 수 없습니다")
        session.add(prop)
    else:
        account = BankAccount(organization_id=org.id, alias=data.bank_account_alias)
        session.add_all([prop, account])
    session.flush()

    leases = vacant = deposits_total = 0
    for u in data.units:
        if u.use_type == "owner":
            status = "owner"
        elif u.tenant_name:
            status = "occupied"
        else:
            status = "vacant"
            vacant += 1
        unit = Unit(
            property_id=prop.id, unit_no=u.unit_no, floor=u.floor,
            area_m2=u.area_m2, use_type=u.use_type, status=status,
        )
        session.add(unit)
        session.flush()
        if status != "occupied":
            continue

        tenant = Tenant(organization_id=org.id, name=u.tenant_name, phone=u.tenant_phone or None)
        session.add(tenant)
        session.flush()
        lease = Lease(
            unit_id=unit.id, tenant_id=tenant.id, start_date=u.start_date, end_date=u.end_date,
            deposit=u.deposit or 0, rent=u.rent, mgmt_fee=u.mgmt_fee, due_day=u.due_day, status="active",
        )
        session.add(lease)
        session.flush()
        leases += 1
        if u.deposit:
            # 보증금은 반환의무(부채)로 별도 기록 — 임대수입 아님
            session.add(Deposit(lease_id=lease.id, amount=u.deposit, received_at=u.deposit_received_on))
            deposits_total += u.deposit

    session.add(AuditLog(
        action="onboarding.create", entity_type="property", entity_id=str(prop.id),
        detail={"units": len(data.units), "leases": leases, "vacant": vacant},
    ))
    session.commit()
    return OnboardingOut(
        organization_id=org.id, property_id=prop.id, bank_account_id=account.id,
        units=len(data.units), leases=leases, vacant=vacant, deposits_total=deposits_total,
    )


def _int(value: str) -> int | None:
    v = value.replace(",", "").replace("원", "").strip()
    return int(v) if v else None


def _date(value: str) -> date | None:
    v = value.strip().replace(".", "-").replace("/", "-")
    return date.fromisoformat(v) if v else None


def decode_text(raw: bytes) -> str:
    """UTF-8(BOM 포함) 우선, 실패하면 엑셀 기본 저장 형식인 CP949."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("파일 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949)")


def parse_onboarding_csv(raw: bytes) -> tuple[list[UnitIn], list[RowError]]:
    """CSV 를 호실 목록으로 바꾼다. 저장하지 않음 — 화면에서 검수 후 onboard() 로 등록."""
    reader = csv.DictReader(io.StringIO(decode_text(raw)))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    if "호실" not in headers:
        return [], [RowError(row=1, message=f"'호실' 열이 없습니다. 필요한 열: {', '.join(CSV_COLUMNS)}")]

    units: list[UnitIn] = []
    errors: list[RowError] = []
    for i, row in enumerate(reader, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        if not any(row.values()):
            continue
        try:
            fields: dict = {}
            for label, key in CSV_COLUMNS.items():
                value = row.get(label, "")
                if not value:
                    continue
                if key in ("floor", "deposit", "rent", "mgmt_fee", "due_day"):
                    fields[key] = _int(value)
                elif key == "area_m2":
                    fields[key] = float(value)
                elif key in ("start_date", "end_date", "deposit_received_on"):
                    fields[key] = _date(value)
                elif key == "use_type":
                    if value not in USE_TYPE_LABELS:
                        raise ValueError(f"용도는 '임대' 또는 '주인' 이어야 합니다: {value}")
                    fields[key] = USE_TYPE_LABELS[value]
                else:
                    fields[key] = value
            units.append(UnitIn(**fields))
        except ValidationError as e:
            errors.append(RowError(row=i, message="; ".join(err["msg"] for err in e.errors())))
        except ValueError as e:
            errors.append(RowError(row=i, message=str(e)))
    return units, errors
