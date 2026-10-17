"""임차인 공지·집주인 연락처 — 임차인 화면(초대 링크)에만 보인다. 문자·알림톡으로 자동 발송하지 않는다.

- 공지는 건물 전체 또는 한 호실. 게시 시작일~끝날(없으면 지울 때까지) 사이에만 보인다
- 연락처는 관리자가 넣은 값만 (저장 시 암호화). 비우면 임차인 화면에도 없다
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Property, TenantNotice, Unit


class NoticeError(ValueError):
    pass


def _text(value: str | None) -> str | None:
    return (value or "").strip() or None


def _property(session: Session, organization_id: uuid.UUID, property_id: uuid.UUID) -> Property:
    prop = session.get(Property, property_id)
    if prop is None or prop.organization_id != organization_id:
        raise LookupError("건물을 찾을 수 없습니다")
    return prop


def state(n: TenantNotice, today: date) -> str:
    if n.starts_on > today:
        return "scheduled"
    if n.ends_on and n.ends_on < today:
        return "ended"
    return "showing"


def overview(session: Session, organization_id: uuid.UUID, today: date) -> dict:
    props = session.scalars(select(Property).where(Property.organization_id == organization_id)
                            .order_by(Property.created_at)).all()
    units = {u.id: u for u in session.scalars(select(Unit).where(Unit.property_id.in_([p.id for p in props])))}
    notices = session.scalars(select(TenantNotice).where(TenantNotice.property_id.in_([p.id for p in props]))
                              .order_by(TenantNotice.starts_on.desc(), TenantNotice.created_at.desc())).all()
    return {
        "buildings": [{"property_id": p.id, "name": p.name, "contact_phone": p.contact_phone,
                       "contact_note": p.contact_note,
                       "units": [{"unit_id": u.id, "unit_no": u.label} for u in sorted(
                           (u for u in units.values() if u.property_id == p.id and u.use_type == "rental"),
                           key=lambda u: u.label)]}
                      for p in props],
        "notices": [{"id": n.id, "property_id": n.property_id, "unit_id": n.unit_id,
                     "unit_no": units[n.unit_id].label if n.unit_id else None, "title": n.title, "body": n.body,
                     "starts_on": n.starts_on, "ends_on": n.ends_on, "state": state(n, today)} for n in notices],
    }


def save_contact(session: Session, organization_id: uuid.UUID, property_id: uuid.UUID, user_id,
                 phone: str | None, note: str | None) -> None:
    prop = _property(session, organization_id, property_id)
    prop.contact_phone, prop.contact_note = _text(phone), _text(note)
    session.add(AuditLog(user_id=user_id, action="tenant_contact.save", entity_type="property",
                         entity_id=str(prop.id)))  # 번호는 남기지 않음
    session.commit()


@dataclass
class NoticeFields:
    property_id: uuid.UUID
    unit_id: uuid.UUID | None
    title: str
    body: str | None
    starts_on: date
    ends_on: date | None


def create_notice(session: Session, organization_id: uuid.UUID, user_id, f: NoticeFields) -> TenantNotice:
    prop = _property(session, organization_id, f.property_id)
    if f.unit_id is not None:
        unit = session.get(Unit, f.unit_id)
        if unit is None or unit.property_id != prop.id:
            raise LookupError("호실을 찾을 수 없습니다")
    title = _text(f.title)
    if not title:
        raise NoticeError("제목을 적어 주세요")
    if f.ends_on and f.ends_on < f.starts_on:
        raise NoticeError("끝나는 날이 시작일보다 앞입니다")
    n = TenantNotice(property_id=prop.id, unit_id=f.unit_id, title=title, body=_text(f.body),
                     starts_on=f.starts_on, ends_on=f.ends_on)
    session.add(n)
    session.flush()
    session.add(AuditLog(user_id=user_id, action="tenant_notice.create", entity_type="tenant_notice",
                         entity_id=str(n.id)))
    session.commit()
    return n


def delete_notice(session: Session, organization_id: uuid.UUID, notice_id: uuid.UUID, user_id) -> None:
    n = session.get(TenantNotice, notice_id)
    if n is None:
        raise LookupError("공지를 찾을 수 없습니다")
    _property(session, organization_id, n.property_id)
    session.add(AuditLog(user_id=user_id, action="tenant_notice.delete", entity_type="tenant_notice",
                         entity_id=str(n.id)))
    session.delete(n)
    session.commit()


def for_unit(session: Session, unit: Unit, today: date) -> list[dict]:
    """임차인 화면용 — 지금 게시 중인 그 건물 전체 공지와 그 호실 공지."""
    rows = session.scalars(select(TenantNotice).where(
        TenantNotice.property_id == unit.property_id,
        or_(TenantNotice.unit_id.is_(None), TenantNotice.unit_id == unit.id),
        TenantNotice.starts_on <= today,
        or_(TenantNotice.ends_on.is_(None), TenantNotice.ends_on >= today))
        .order_by(TenantNotice.starts_on.desc(), TenantNotice.created_at.desc())).all()
    return [{"title": n.title, "body": n.body, "starts_on": n.starts_on, "ends_on": n.ends_on,
             "for_unit": n.unit_id is not None} for n in rows]
