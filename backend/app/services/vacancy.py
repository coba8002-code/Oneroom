"""공실 관리 — 공실 기간, 놓친 월세(직전 계약 조건 기준), 모집 조건·광고 문구, 중개사·문의·방 보기 기록.

규칙 (CLAUDE.md 규칙 7)
- 공실 시작일은 직전 계약의 실제 종료일(없으면 만료일). 직전 계약 기록이 없으면 모름(비움).
- '놓친 월세'는 직전 계약 조건(월세·납부일)이었다면 공실 기간에 돌아왔을 납부일 수 × 월세 — 사실값으로 센 참고치.
  시세·적정 월세를 추정하지 않는다. 모집 조건은 관리자가 정한 값만.
- 광고 문구는 호실·옵션(자산대장)·모집 조건에 적힌 값만으로 만든다. 없는 값은 빼고 지어내지 않는다.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fixture, Lease, Property, Unit, VacancyActivity, VacancyListing
from app.services.charges import due_date_for
from app.services.fixtures import _audit, _text

KINDS = {"agent": "중개사 등록·연락", "inquiry": "문의", "viewing": "방 보기", "other": "기타"}


class VacancyError(Exception):
    pass


def _unit(session: Session, organization_id: uuid.UUID, unit_id: uuid.UUID) -> tuple[Unit, Property]:
    row = session.execute(select(Unit, Property).join(Property, Unit.property_id == Property.id)
                          .where(Unit.id == unit_id, Property.organization_id == organization_id)).first()
    if row is None:
        raise LookupError("호실을 찾을 수 없습니다")
    return row[0], row[1]


def _previous_lease(session: Session, unit_id: uuid.UUID) -> Lease | None:
    leases = session.scalars(select(Lease).where(Lease.unit_id == unit_id, Lease.status != "active")).all()
    ended = [le for le in leases if (le.ended_on or le.end_date)]
    return max(ended, key=lambda le: le.ended_on or le.end_date) if ended else None


def missed_due_dates(since: date, as_of: date, due_day: int) -> list[date]:
    """since 다음 날부터 as_of 까지 돌아온 납부일 (그 달에 없는 날은 말일)."""
    out = []
    y, m = since.year, since.month
    while (y, m) <= (as_of.year, as_of.month):
        d = due_date_for(f"{y:04d}-{m:02d}", due_day)
        if since < d <= as_of:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _won(n: int) -> str:
    return f"{n // 10000:,}만원" if n % 10000 == 0 else f"{n:,}원"


def ad_text(prop: Property, unit: Unit, listing: VacancyListing | None, options: list[str]) -> str:
    head = f"[{prop.name}] {unit.unit_no}호" + (f" ({unit.floor}층)" if unit.floor is not None else "")
    lines = [head]
    if listing and (listing.asking_deposit is not None or listing.asking_rent is not None):
        terms = []
        if listing.asking_deposit is not None:
            terms.append(f"보증금 {_won(listing.asking_deposit)}")
        if listing.asking_rent is not None:
            terms.append(f"월세 {_won(listing.asking_rent)}")
        lines.append(" / ".join(terms))
    if listing and listing.available_on:
        lines.append(f"입주 가능: {listing.available_on:%Y-%m-%d}부터")
    if unit.area_m2 is not None:
        lines.append(f"전용 {format(Decimal(str(unit.area_m2)).normalize(), 'f')}㎡")
    if options:
        lines.append("옵션: " + ", ".join(options))
    if prop.address:
        lines.append(f"위치: {prop.address}")
    if listing and listing.note:
        lines.append(listing.note)
    return "\n".join(lines)


def _options(session: Session, unit_id: uuid.UUID) -> list[str]:
    names = session.scalars(select(Fixture.name).where(Fixture.unit_id == unit_id, Fixture.owner == "landlord",
                                                       Fixture.status == "in_use").order_by(Fixture.created_at))
    return list(dict.fromkeys(names))


def summary(session: Session, organization_id: uuid.UUID, as_of: date) -> dict:
    rows = session.execute(select(Unit, Property).join(Property, Unit.property_id == Property.id)
                           .where(Property.organization_id == organization_id, Unit.use_type == "rental",
                                  Unit.status == "vacant").order_by(Unit.label)).all()
    units = []
    for unit, prop in rows:
        prev = _previous_lease(session, unit.id)
        since = (prev.ended_on or prev.end_date) if prev else None
        missed = missed_due_dates(since, as_of, prev.due_day) if prev and since and since <= as_of else []
        listing = session.scalar(select(VacancyListing).where(VacancyListing.unit_id == unit.id))
        acts = session.scalars(select(VacancyActivity).where(VacancyActivity.unit_id == unit.id)).all()
        if since:
            acts = [a for a in acts if a.happened_on >= since]  # 이번 공실 기간 것만 센다
        units.append({
            "unit_id": unit.id, "unit_no": unit.label, "floor": unit.floor,
            "vacant_since": since, "days_vacant": (as_of - since).days if since and since <= as_of else None,
            "previous_rent": prev.rent if prev else None, "previous_deposit": prev.deposit if prev else None,
            "missed_due_dates": len(missed) if prev else None,
            "missed_rent": len(missed) * prev.rent if prev and since else None,
            "asking_deposit": listing.asking_deposit if listing else None,
            "asking_rent": listing.asking_rent if listing else None,
            "available_on": listing.available_on if listing else None,
            "activity": {k: sum(1 for a in acts if a.kind == k) for k in KINDS},
        })
    known = [u["missed_rent"] for u in units if u["missed_rent"] is not None]
    return {"as_of": as_of, "units": units, "missed_rent_total_known": int(sum(known)) if known else None,
            "units_without_history": [u["unit_no"] for u in units if u["vacant_since"] is None]}


def detail(session: Session, organization_id: uuid.UUID, unit_id: uuid.UUID) -> dict:
    unit, prop = _unit(session, organization_id, unit_id)
    listing = session.scalar(select(VacancyListing).where(VacancyListing.unit_id == unit.id))
    acts = session.scalars(select(VacancyActivity).where(VacancyActivity.unit_id == unit.id)
                           .order_by(VacancyActivity.happened_on.desc(), VacancyActivity.created_at.desc())).all()
    options = _options(session, unit.id)
    return {
        "unit_id": unit.id, "unit_no": unit.label, "status": unit.status,
        "listing": {"asking_deposit": listing.asking_deposit, "asking_rent": listing.asking_rent,
                    "available_on": listing.available_on, "note": listing.note} if listing else None,
        "options": options, "ad_text": ad_text(prop, unit, listing, options),
        "activities": [{"id": a.id, "kind": a.kind, "happened_on": a.happened_on, "agent_name": a.agent_name,
                        "agent_phone": a.agent_phone, "note": a.note} for a in acts],
    }


@dataclass
class ListingFields:
    asking_deposit: int | None = None
    asking_rent: int | None = None
    available_on: date | None = None
    note: str | None = None


def save_listing(session: Session, organization_id: uuid.UUID, unit_id: uuid.UUID, user_id, f: ListingFields) -> None:
    unit, _ = _unit(session, organization_id, unit_id)
    if any(v is not None and v < 0 for v in (f.asking_deposit, f.asking_rent)):
        raise VacancyError("금액은 0원 이상입니다")
    listing = session.scalar(select(VacancyListing).where(VacancyListing.unit_id == unit.id))
    if listing is None:
        listing = VacancyListing(unit_id=unit.id)
        session.add(listing)
    listing.asking_deposit, listing.asking_rent = f.asking_deposit, f.asking_rent
    listing.available_on, listing.note = f.available_on, _text(f.note)
    listing.updated_at = datetime.now(timezone.utc)
    session.flush()
    _audit(session, user_id, "vacancy.listing", "unit", unit.id)
    session.commit()


def add_activity(session: Session, organization_id: uuid.UUID, unit_id: uuid.UUID, user_id, kind: str,
                 happened_on: date, today: date, agent_name: str | None = None, agent_phone: str | None = None,
                 note: str | None = None) -> VacancyActivity:
    unit, _ = _unit(session, organization_id, unit_id)
    if kind not in KINDS:
        raise VacancyError("종류를 고르세요")
    if happened_on > today:
        raise VacancyError("앞으로의 날짜로는 기록할 수 없습니다")
    a = VacancyActivity(unit_id=unit.id, kind=kind, happened_on=happened_on, agent_name=_text(agent_name),
                        agent_phone=_text(agent_phone), note=_text(note))
    session.add(a)
    session.flush()
    _audit(session, user_id, "vacancy.activity", "vacancy_activity", a.id, {"kind": kind})  # 연락처는 남기지 않음
    session.commit()
    return a


def delete_activity(session: Session, organization_id: uuid.UUID, activity_id: uuid.UUID, user_id) -> None:
    a = session.get(VacancyActivity, activity_id)
    if a is None:
        raise LookupError("기록을 찾을 수 없습니다")
    _unit(session, organization_id, a.unit_id)
    _audit(session, user_id, "vacancy.activity_delete", "vacancy_activity", a.id)
    session.delete(a)
    session.commit()
