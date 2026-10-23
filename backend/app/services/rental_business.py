"""등록임대사업자 모드 — 민간임대주택에 관한 특별법(민특법)상 의무를 챙기는 장부.

규칙
- 시스템은 등록 여부·의무를 판정하지 않는다. 관리자가 등록증·보증서로 확인해 적은 값만 쓰고, 법령 기준(증액 상한·
  신고 기한·의무기간)은 화면에 '확인 필요'로 보이며 관리자가 바꿀 수 있다 (시행 시기·주택 유형마다 다름).
- 모르는 값은 비워 둔다 (CLAUDE.md 규칙 7). 의무기간을 모르면 끝나는 날을 계산하지 않는다.
- 범위: 등록 임대주택은 한 호실, 또는 호실 없이 건물 전체(다가구처럼 한 채로 등록). 다가구·다세대·오피스텔·아파트 모두.
- 챙기는 것 (참고 조문, 관리자 확인 필요):
  · 임대보증금 보증 가입 (민특법 §49) — 보증금 있는 진행 중 계약이 있는데 유효한 보증 기록이 없으면 경고
  · 부기등기 (§5조의2) — 했음/해당 없음 기록이 없으면 경고
  · 임대차계약 신고 (§46) — 계약일부터 report_months(기본 3개월) 안
  · 표준임대차계약서 사용 (§47) — 계약 체크리스트 항목
  · 임대료 증액 상한 (§44) — 같은 호실 직전 계약 대비 increase_cap_pct(기본 5%) 초과, 또는 1년 안 증액이면 경고.
    보증금·월세를 따로 비교한다 (전환율 환산 비교는 하지 않음 — 넘었다고 나오면 관리자가 확인)
  · 임대의무기간 끝 (§43) — 시작일·기간을 알 때만, 180일 안이면 안내
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (Lease, LeaseCheck, Property, RegisteredRental, RentalBusinessProfile, RentalGuarantee,
                        Unit)
from app.services.fixtures import _audit, _text
from app.services.lease_renewal import months_before

HOUSING_TYPES = {"multi_household": "다가구주택", "multi_family": "다세대주택", "officetel": "주거용 오피스텔",
                 "apartment": "아파트", "other": "기타"}
RENTAL_TYPES = {"long_term": "장기일반민간임대주택", "public_support": "공공지원민간임대주택",
                "short_term": "단기민간임대주택 (기존 등록분)", "other": "기타"}
# 등록증으로 확인할 값을 미리 채워 주는 제안일 뿐 — 저장되는 것은 관리자가 고른 값
SUGGESTED_YEARS = {"long_term": 10, "public_support": 10, "short_term": 4}
PROVIDERS = {"hug": "주택도시보증공사(HUG)", "sgi": "SGI서울보증", "other": "기타 보증기관",
             "exempt": "가입 면제 (관리자 확인)"}
DEFAULT_CAP_PCT = Decimal(5)
DEFAULT_REPORT_MONTHS = 3
CONTRACT_KEYS = {
    "rental_contract_report": ("임대차계약 신고 (등록임대주택, 지자체)", "민간임대주택에 관한 특별법 §46 — 기한은 확인 필요"),
    "standard_contract": ("표준임대차계약서 사용", "민간임대주택에 관한 특별법 §47"),
}
GUARANTEE_SOON_DAYS = 60
OBLIGATION_SOON_DAYS = 180
REPORT_SOON_DAYS = 14
LAW_NOTE = "법령 기준은 시행 시기·주택 유형마다 다를 수 있습니다 — 관할 지자체·렌트홈에서 확인하세요"


class RentalBusinessError(Exception):
    pass


def add_years(d: date, years: int) -> date:
    return months_before(d, -12 * years)


# ── 사업자 정보 ───────────────────────────────────────────────

def get_profile(session: Session, organization_id: uuid.UUID) -> RentalBusinessProfile | None:
    return session.scalar(select(RentalBusinessProfile).where(RentalBusinessProfile.organization_id == organization_id))


@dataclass
class ProfileFields:
    registration_no: str | None = None
    registered_on: date | None = None
    tax_business_no: str | None = None
    increase_cap_pct: str | None = None
    report_months: int | None = None
    note: str | None = None


def save_profile(session: Session, organization_id: uuid.UUID, user_id, f: ProfileFields) -> RentalBusinessProfile:
    try:
        cap = DEFAULT_CAP_PCT if f.increase_cap_pct in (None, "") else Decimal(str(f.increase_cap_pct).strip())
    except InvalidOperation as e:
        raise RentalBusinessError("증액 상한은 숫자로 적으세요 (예: 5)") from e
    if not Decimal(0) <= cap <= Decimal(100):
        raise RentalBusinessError("증액 상한은 0~100% 사이입니다")
    months = DEFAULT_REPORT_MONTHS if f.report_months is None else f.report_months
    if not 1 <= months <= 24:
        raise RentalBusinessError("신고 기한은 1~24개월입니다")
    p = get_profile(session, organization_id) or RentalBusinessProfile(organization_id=organization_id)
    p.registration_no, p.registered_on = _text(f.registration_no), f.registered_on
    p.tax_business_no, p.note = _text(f.tax_business_no), _text(f.note)
    p.increase_cap_pct, p.report_months = cap, months
    session.add(p)
    session.flush()
    _audit(session, user_id, "rental_business.profile", "rental_business_profile", p.id)
    session.commit()
    return p


def _rules(p: RentalBusinessProfile | None) -> tuple[Decimal, int]:
    return (p.increase_cap_pct, p.report_months) if p else (DEFAULT_CAP_PCT, DEFAULT_REPORT_MONTHS)


# ── 등록 임대주택 ─────────────────────────────────────────────

@dataclass
class RegistrationFields:
    property_id: uuid.UUID
    unit_id: uuid.UUID | None
    housing_type: str
    rental_type: str
    registered_on: date | None = None
    rental_start_on: date | None = None
    obligation_years: int | None = None
    lien_status: str | None = None
    lien_done_on: date | None = None
    note: str | None = None


def _check_place(session: Session, organization_id: uuid.UUID, property_id: uuid.UUID,
                 unit_id: uuid.UUID | None) -> None:
    prop = session.get(Property, property_id)
    if prop is None or prop.organization_id != organization_id:
        raise LookupError("건물을 찾을 수 없습니다")
    if unit_id is not None:
        unit = session.get(Unit, unit_id)
        if unit is None or unit.property_id != property_id:
            raise LookupError("호실을 찾을 수 없습니다")


def _values(f: RegistrationFields) -> dict:
    if f.housing_type not in HOUSING_TYPES:
        raise RentalBusinessError("주택 유형을 고르세요")
    if f.rental_type not in RENTAL_TYPES:
        raise RentalBusinessError("임대 유형을 고르세요")
    if f.obligation_years is not None and not 1 <= f.obligation_years <= 30:
        raise RentalBusinessError("임대의무기간은 1~30년입니다 (모르면 비워 두세요)")
    if f.lien_status not in (None, "done", "na"):
        raise RentalBusinessError("부기등기는 '했음' 또는 '해당 없음'입니다")
    return {"property_id": f.property_id, "unit_id": f.unit_id, "housing_type": f.housing_type,
            "rental_type": f.rental_type, "registered_on": f.registered_on, "rental_start_on": f.rental_start_on,
            "obligation_years": f.obligation_years, "lien_status": f.lien_status,
            "lien_done_on": f.lien_done_on if f.lien_status == "done" else None, "note": _text(f.note)}


def _duplicate(session: Session, organization_id: uuid.UUID, f: RegistrationFields, skip: uuid.UUID | None) -> bool:
    rows = session.scalars(select(RegisteredRental).where(RegisteredRental.organization_id == organization_id,
                                                          RegisteredRental.property_id == f.property_id))
    return any(r.id != skip and (r.unit_id is None or f.unit_id is None or r.unit_id == f.unit_id) for r in rows)


def get_registration(session: Session, organization_id: uuid.UUID, reg_id: uuid.UUID) -> RegisteredRental:
    r = session.get(RegisteredRental, reg_id)
    if r is None or r.organization_id != organization_id:
        raise LookupError("등록 임대주택을 찾을 수 없습니다")
    return r


def save_registration(session: Session, organization_id: uuid.UUID, user_id, f: RegistrationFields,
                      reg_id: uuid.UUID | None = None) -> RegisteredRental:
    _check_place(session, organization_id, f.property_id, f.unit_id)
    values = _values(f)
    if _duplicate(session, organization_id, f, reg_id):
        raise RentalBusinessError("이미 등록한 호실(또는 건물 전체 등록)과 겹칩니다")
    r = get_registration(session, organization_id, reg_id) if reg_id else RegisteredRental(organization_id=organization_id)
    for k, v in values.items():
        setattr(r, k, v)
    session.add(r)
    session.flush()
    _audit(session, user_id, "rental_business.registration", "registered_rental", r.id,
           {"housing_type": r.housing_type, "rental_type": r.rental_type})
    session.commit()
    return r


def delete_registration(session: Session, organization_id: uuid.UUID, user_id, reg_id: uuid.UUID) -> None:
    r = get_registration(session, organization_id, reg_id)
    for g in session.scalars(select(RentalGuarantee).where(RentalGuarantee.registration_id == r.id)):
        session.delete(g)
    session.delete(r)
    _audit(session, user_id, "rental_business.registration_delete", "registered_rental", reg_id)
    session.commit()


@dataclass
class GuaranteeFields:
    provider: str
    policy_no: str | None = None
    start_on: date | None = None
    end_on: date | None = None
    note: str | None = None


def add_guarantee(session: Session, organization_id: uuid.UUID, user_id, reg_id: uuid.UUID,
                  f: GuaranteeFields) -> RentalGuarantee:
    r = get_registration(session, organization_id, reg_id)
    if f.provider not in PROVIDERS:
        raise RentalBusinessError("보증기관을 고르세요")
    if f.start_on and f.end_on and f.end_on < f.start_on:
        raise RentalBusinessError("보증 끝나는 날이 시작일보다 앞섭니다")
    g = RentalGuarantee(registration_id=r.id, provider=f.provider, policy_no=_text(f.policy_no),
                        start_on=f.start_on, end_on=f.end_on, note=_text(f.note))
    session.add(g)
    session.flush()
    _audit(session, user_id, "rental_business.guarantee", "rental_guarantee", g.id, {"provider": g.provider})
    session.commit()
    return g


def delete_guarantee(session: Session, organization_id: uuid.UUID, user_id, guarantee_id: uuid.UUID) -> None:
    g = session.get(RentalGuarantee, guarantee_id)
    if g is None:
        raise LookupError("보증 기록을 찾을 수 없습니다")
    get_registration(session, organization_id, g.registration_id)
    session.delete(g)
    _audit(session, user_id, "rental_business.guarantee_delete", "rental_guarantee", guarantee_id)
    session.commit()


# ── 범위·계약 ─────────────────────────────────────────────────

def _registrations(session: Session, organization_id: uuid.UUID) -> list[RegisteredRental]:
    return list(session.scalars(select(RegisteredRental).where(RegisteredRental.organization_id == organization_id)
                                .order_by(RegisteredRental.created_at)))


def _covers(r: RegisteredRental, unit: Unit) -> bool:
    return r.property_id == unit.property_id and (r.unit_id is None or r.unit_id == unit.id)


def registration_for_lease(session: Session, lease: Lease) -> RegisteredRental | None:
    unit = session.get(Unit, lease.unit_id)
    prop = session.get(Property, unit.property_id)
    return next((r for r in _registrations(session, prop.organization_id) if _covers(r, unit)), None)


def _previous_lease(session: Session, lease: Lease) -> Lease | None:
    return session.scalar(select(Lease).where(Lease.unit_id == lease.unit_id, Lease.id != lease.id,
                                              Lease.status != "draft", Lease.start_date < lease.start_date)
                          .order_by(Lease.start_date.desc()).limit(1))


def increase_check(prev: Lease | None, lease: Lease, cap_pct: Decimal) -> dict | None:
    """같은 호실 직전 계약 대비 증액률. 직전 계약이 없으면 None (비교 근거 없음)."""
    if prev is None:
        return None

    def pct(old: int, new: int) -> Decimal | None:
        return None if old <= 0 else (Decimal(new - old) * 100 / Decimal(old)).quantize(Decimal("0.01"))

    dep, rent = pct(prev.deposit, lease.deposit), pct(prev.rent, lease.rent)
    over = [x for x in (dep, rent) if x is not None and x > cap_pct]
    raised = lease.deposit > prev.deposit or lease.rent > prev.rent
    too_soon = raised and lease.start_date < add_years(prev.start_date, 1)
    return {"previous_lease_id": str(prev.id), "previous_deposit": prev.deposit, "previous_rent": prev.rent,
            "deposit_pct": None if dep is None else format(dep, "f"), "rent_pct": None if rent is None else format(rent, "f"),
            "cap_pct": format(cap_pct.normalize(), "f"), "over_cap": bool(over), "within_a_year": too_soon}


def contract_items(session: Session, lease: Lease, as_of: date, checks: dict[str, LeaseCheck]) -> list[dict]:
    """등록 임대주택 계약이면 계약 체크리스트에 붙일 항목. 아니면 빈 목록."""
    reg = registration_for_lease(session, lease)
    if reg is None:
        return []
    org_id = session.get(Property, reg.property_id).organization_id
    _, months = _rules(get_profile(session, org_id))
    items = []
    for key, (label, basis) in CONTRACT_KEYS.items():
        c = checks.get(key)
        item = {"key": key, "label": label, "basis": basis, "auto": False,
                "status": c.status if c else "todo", "done_on": c.done_on if c else None, "note": c.note if c else None,
                "due_on": None, "overdue": False, "hint": None}
        if key == "rental_contract_report":
            if lease.signed_on:
                item["due_on"] = months_before(lease.signed_on, -months)
                item["overdue"] = item["status"] == "todo" and as_of > item["due_on"]
                item["hint"] = f"계약일부터 {months}개월 (임대사업자 설정에서 바꿀 수 있음). 렌트홈 또는 지자체에 신고"
            elif item["status"] == "todo":
                item["hint"] = "계약일을 넣으면 기한을 계산합니다"
        items.append(item)
    return items


# ── 의무 점검 ─────────────────────────────────────────────────

def _place_label(session: Session, r: RegisteredRental) -> str:
    if r.unit_id:
        return session.get(Unit, r.unit_id).label
    return f"{session.get(Property, r.property_id).name} 전체"


def _active_leases(session: Session, r: RegisteredRental) -> list[tuple[Lease, Unit]]:
    q = select(Lease, Unit).join(Unit, Lease.unit_id == Unit.id).where(
        Unit.property_id == r.property_id, Lease.status == "active")
    if r.unit_id:
        q = q.where(Unit.id == r.unit_id)
    return list(session.execute(q.order_by(Unit.label)).tuples())


def _guarantee_state(gs: list[RentalGuarantee], as_of: date) -> tuple[RentalGuarantee | None, str]:
    """지금 유효한 보증 (끝나는 날을 모르면 유효로 본다 — 관리자가 넣은 기록)."""
    live = [g for g in gs if (g.start_on is None or g.start_on <= as_of) and (g.end_on is None or g.end_on >= as_of)]
    if not live:
        return None, "none"
    g = max(live, key=lambda x: x.end_on or date.max)
    if g.provider == "exempt":
        return g, "exempt"
    if g.end_on and (g.end_on - as_of).days <= GUARANTEE_SOON_DAYS:
        return g, "expiring"
    return g, "ok"


def overview(session: Session, organization_id: uuid.UUID, as_of: date) -> dict:
    profile = get_profile(session, organization_id)
    cap, months = _rules(profile)
    regs = _registrations(session, organization_id)
    guarantees: dict[uuid.UUID, list[RentalGuarantee]] = {r.id: [] for r in regs}
    if regs:
        for g in session.scalars(select(RentalGuarantee).where(RentalGuarantee.registration_id.in_(guarantees))
                                 .order_by(RentalGuarantee.start_on)):
            guarantees[g.registration_id].append(g)

    obligations: list[dict] = []

    def add(level: str, kind: str, place: str, message: str, reg_id: uuid.UUID, lease_id=None) -> None:
        obligations.append({"level": level, "kind": kind, "place": place, "message": message,
                            "registration_id": str(reg_id), "lease_id": str(lease_id) if lease_id else None})

    rows = []
    for r in regs:
        place = _place_label(session, r)
        leases = _active_leases(session, r)
        g, gstate = _guarantee_state(guarantees[r.id], as_of)
        if gstate == "none" and any(le.deposit > 0 for le, _ in leases):
            add("warn", "guarantee_missing", place, "보증금이 있는 진행 중 계약이 있는데 유효한 임대보증금 보증 기록이 없습니다 "
                "(민특법 §49 — 가입 대상·면제 여부 확인 필요).", r.id)
        elif gstate == "expiring":
            add("info", "guarantee_expiring", place, f"임대보증금 보증이 {g.end_on:%Y-%m-%d}에 끝납니다. 갱신을 확인하세요.", r.id)
        if r.lien_status is None:
            add("warn", "lien_missing", place, "부기등기(등록 임대주택임을 등기부에 표시) 기록이 없습니다 (민특법 §5조의2 — 확인 필요).", r.id)
        obligation_end = add_years(r.rental_start_on, r.obligation_years) \
            if r.rental_start_on and r.obligation_years else None
        if obligation_end is None:
            add("info", "obligation_unknown", place, "임대의무기간 시작일·기간을 모릅니다. 등록증을 보고 적으면 끝나는 날을 알려 드립니다.", r.id)
        elif (left := (obligation_end - as_of).days) <= OBLIGATION_SOON_DAYS:
            add("info", "obligation_ending", place, f"임대의무기간이 {obligation_end:%Y-%m-%d}에 끝" +
                ("났습니다" if left < 0 else "납니다") + " — 계속 임대·말소 여부를 정하세요 (민특법 §43·§6, 확인 필요).", r.id)
        lease_rows = []
        for le, unit in leases:
            checks = {c.key: c for c in session.scalars(select(LeaseCheck).where(LeaseCheck.lease_id == le.id))}
            report = checks.get("rental_contract_report")
            due = months_before(le.signed_on, -months) if le.signed_on else None
            if report is None and due and as_of >= due - timedelta(days=REPORT_SOON_DAYS):
                add("warn", "contract_report", unit.label, f"임대차계약 신고 기한 {due:%Y-%m-%d}" +
                    (" 이 지났습니다" if as_of > due else " 입니다") + " (계약일부터 " + f"{months}개월, 확인 필요).", r.id, le.id)
            inc = increase_check(_previous_lease(session, le), le, cap)
            if inc and inc["over_cap"]:
                add("warn", "increase_over_cap", unit.label, f"직전 계약보다 보증금 {inc['deposit_pct'] or '—'}% · 월세 "
                    f"{inc['rent_pct'] or '—'}% 올랐습니다 (상한 {inc['cap_pct']}%, 확인 필요 — 보증금·월세 전환은 따로 계산하세요).",
                    r.id, le.id)
            if inc and inc["within_a_year"]:
                add("warn", "increase_too_soon", unit.label, "직전 계약 시작 뒤 1년 안에 임대료를 올렸습니다 (민특법 §44 — 확인 필요).",
                    r.id, le.id)
            lease_rows.append({"lease_id": str(le.id), "unit_no": unit.label, "deposit": le.deposit, "rent": le.rent,
                               "start_date": le.start_date, "signed_on": le.signed_on, "report_due_on": due,
                               "report_status": report.status if report else None, "increase": inc})
        rows.append({
            "id": str(r.id), "property_id": str(r.property_id), "unit_id": str(r.unit_id) if r.unit_id else None,
            "place": place, "housing_type": r.housing_type, "rental_type": r.rental_type,
            "registered_on": r.registered_on, "rental_start_on": r.rental_start_on, "obligation_years": r.obligation_years,
            "obligation_end_on": obligation_end, "lien_status": r.lien_status, "lien_done_on": r.lien_done_on,
            "note": r.note, "guarantee_state": gstate,
            "guarantees": [{"id": str(x.id), "provider": x.provider, "policy_no": x.policy_no, "start_on": x.start_on,
                            "end_on": x.end_on, "note": x.note} for x in guarantees[r.id]],
            "leases": lease_rows,
        })

    order = {"warn": 0, "info": 1}
    obligations.sort(key=lambda o: order[o["level"]])
    buildings = [{"property_id": str(p.id), "name": p.name,
                  "units": [{"unit_id": str(u.id), "unit_no": u.label} for u in session.scalars(
                      select(Unit).where(Unit.property_id == p.id, Unit.use_type == "rental").order_by(Unit.unit_no))]}
                 for p in session.scalars(select(Property).where(Property.organization_id == organization_id)
                                          .order_by(Property.created_at))]
    return {
        "as_of": as_of,
        "profile": None if profile is None else {
            "registration_no": profile.registration_no, "registered_on": profile.registered_on,
            "tax_business_no": profile.tax_business_no, "note": profile.note,
            "increase_cap_pct": format(profile.increase_cap_pct.normalize(), "f"), "report_months": profile.report_months},
        "rules": {"increase_cap_pct": format(cap.normalize(), "f"), "report_months": months, "note": LAW_NOTE,
                  "default_cap_pct": format(DEFAULT_CAP_PCT, "f"), "default_report_months": DEFAULT_REPORT_MONTHS},
        "registrations": rows,
        "obligations": obligations,
        "buildings": buildings,
        "codes": {"housing_types": HOUSING_TYPES, "rental_types": RENTAL_TYPES, "providers": PROVIDERS,
                  "suggested_years": SUGGESTED_YEARS},
    }


def alerts(session: Session, organization_id: uuid.UUID, as_of: date) -> list[dict]:
    """대시보드용 — 경고(warn)만. 등록 임대주택이 없으면 빈 목록."""
    if not session.scalar(select(RegisteredRental.id).where(RegisteredRental.organization_id == organization_id).limit(1)):
        return []
    return [o for o in overview(session, organization_id, as_of)["obligations"] if o["level"] == "warn"]
