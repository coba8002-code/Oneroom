"""임차인 화면 — 관리자가 계약마다 만든 초대 링크로 로그인 없이 연다 (문자 인증 업체 없이).

규칙
- 링크 = 비밀 토큰. DB 에는 sha256 만 저장, 원문은 만들 때 한 번만 보여 준다. 계약마다 하나만 유효 (새로 만들면 이전 것은 바로 무효)
- 만료·회수·계약 종료면 열리지 않는다 — 어느 경우든 같은 응답 (토큰이 있었는지 알려 주지 않음)
- 보여 주는 것: 그 계약의 호실·기간·월세·납부일·보증금, 최근 청구와 '확인된' 입금, 그 계약 기간에 임차인이 요청한 수리
  · 장부 값만. 입금이 확인되지 않은 청구는 '미납'이 아니라 '입금 확인 전' — 은행 내역 반영 시각을 같이 보여 준다 (자동 독촉 금지)
  · 다른 호실·이전 임차인·관리자 메모·비용 부담·연락처는 넣지 않는다
- 관리자가 쓴 공지(게시 기간 안)와 집주인 연락처(관리자가 넣은 것만)도 보여 준다
- 임차인이 할 수 있는 일은 수리 요청뿐 (하루 횟수 제한). 요청은 수리 이력에 '임차인 요청'으로 들어가고 관리자가 처리한다
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Charge, Deposit, Lease, MaintenanceTicket, Property, TenantLink, Unit
from app.services import ledger, receivables, tenant_notices, utilities

DAYS = (30, 90, 180, 365)  # 관리자가 고르는 유효 기간
CHARGE_MONTHS = 12
REQUESTS_PER_DAY = 5  # 링크가 새어 나가도 수리 이력이 넘치지 않게
SEEN_EVERY = timedelta(minutes=10)
STATE = {"paid": "입금 확인", "partial": "일부 확인", "open": "입금 확인 전", "waived": "받지 않음"}
NOTE = ("집주인 장부에 기록된 값입니다. 입금은 집주인이 통장 내역을 반영한 때까지만 확인됩니다 — "
        "그 뒤에 보낸 돈은 아직 '입금 확인 전'으로 보일 수 있습니다.")


class PortalError(ValueError):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(dt: datetime) -> datetime:  # SQLite(테스트)는 시간대 없이 돌려준다
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _lease(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID) -> tuple[Lease, str]:
    row = session.execute(select(Lease, Unit.label).join(Unit, Lease.unit_id == Unit.id)
                          .join(Property, Unit.property_id == Property.id)
                          .where(Lease.id == lease_id, Property.organization_id == organization_id)).first()
    if row is None:
        raise LookupError("계약을 찾을 수 없습니다")
    return row[0], row[1]


def _active(session: Session, lease_id: uuid.UUID, now: datetime) -> TenantLink | None:
    return session.scalar(select(TenantLink).where(TenantLink.lease_id == lease_id, TenantLink.revoked_at.is_(None),
                                                   TenantLink.expires_at > now)
                          .order_by(TenantLink.created_at.desc()))


def link_status(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID, now: datetime) -> dict:
    lease, _ = _lease(session, organization_id, lease_id)
    link = _active(session, lease.id, now) if lease.status == "active" else None
    return {"lease_active": lease.status == "active", "days": list(DAYS),
            "link": {"created_at": link.created_at, "expires_at": link.expires_at, "last_seen_at": link.last_seen_at}
            if link else None}


def _revoke_all(session: Session, lease_id: uuid.UUID, now: datetime) -> int:
    links = session.scalars(select(TenantLink).where(TenantLink.lease_id == lease_id,
                                                     TenantLink.revoked_at.is_(None))).all()
    for link in links:
        link.revoked_at = now
    return len(links)


def create_link(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID, user_id, days: int,
                now: datetime) -> tuple[str, datetime]:
    """새 링크를 만들고(이전 링크는 바로 무효) 토큰 원문을 한 번만 돌려준다."""
    lease, _ = _lease(session, organization_id, lease_id)
    if lease.status != "active":
        raise PortalError("진행 중인 계약에만 링크를 만들 수 있습니다")
    if days not in DAYS:
        raise PortalError(f"유효 기간은 {', '.join(map(str, DAYS))}일 중에서 고르세요")
    _revoke_all(session, lease.id, now)
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(days=days)
    session.add(TenantLink(lease_id=lease.id, token_hash=_hash(token), expires_at=expires, created_at=now))
    session.add(AuditLog(user_id=user_id, action="tenant_link.create", entity_type="lease", entity_id=str(lease.id),
                         detail={"days": days}))
    session.commit()
    return token, expires


def revoke_link(session: Session, organization_id: uuid.UUID, lease_id: uuid.UUID, user_id, now: datetime) -> int:
    lease, _ = _lease(session, organization_id, lease_id)
    n = _revoke_all(session, lease.id, now)
    session.add(AuditLog(user_id=user_id, action="tenant_link.revoke", entity_type="lease", entity_id=str(lease.id)))
    session.commit()
    return n


def open_link(session: Session, token: str, now: datetime) -> tuple[TenantLink, Lease] | None:
    if not token or len(token) > 100:
        return None
    row = session.execute(select(TenantLink, Lease).join(Lease, TenantLink.lease_id == Lease.id)
                          .where(TenantLink.token_hash == _hash(token))).first()
    if row is None:
        return None
    link, lease = row
    if link.revoked_at is not None or _aware(link.expires_at) <= now or lease.status != "active":
        return None
    return link, lease


def _requests(session: Session, lease: Lease) -> list[MaintenanceTicket]:
    since = datetime.combine(lease.start_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(days=1)
    return session.scalars(select(MaintenanceTicket).where(
        MaintenanceTicket.unit_id == lease.unit_id, MaintenanceTicket.source == "tenant",
        MaintenanceTicket.created_at >= since)  # 이전 임차인의 요청은 보이지 않게
        .order_by(MaintenanceTicket.created_at.desc())).all()


def view(session: Session, link: TenantLink, lease: Lease, today: date, now: datetime) -> dict:
    unit, prop = session.execute(select(Unit, Property).join(Property, Unit.property_id == Property.id)
                                 .where(Unit.id == lease.unit_id)).one()
    if link.last_seen_at is None or now - _aware(link.last_seen_at) >= SEEN_EVERY:
        link.last_seen_at = now
        session.commit()

    every = session.scalars(select(Charge).where(Charge.lease_id == lease.id)
                            .order_by(Charge.period.desc(), Charge.kind != "rent", Charge.kind)).all()
    months = sorted({c.period for c in every}, reverse=True)[:CHARGE_MONTHS]  # 최근 12개월 (월세·공과금 모두)
    charges = [c for c in every if c.period in months]
    rows = []
    for c in charges:
        paid = int(ledger.paid_amount(session, c.id))
        rows.append({"period": c.period, "due_date": c.due_date, "amount": c.amount, "paid": paid,
                     "kind": c.kind, "kind_label": "월세" if c.kind == "rent" else utilities.ITEMS.get(c.kind, c.kind),
                     "state": c.status if c.status in STATE else "open", "state_label": STATE.get(c.status, c.status)})
    upcoming = [c for c in charges if c.due_date >= today and c.status in ("open", "partial")]

    received = session.scalars(select(Deposit.amount).where(Deposit.lease_id == lease.id,
                                                            Deposit.received_at.is_not(None),
                                                            Deposit.returned_at.is_(None))).all()
    return {
        "unit_no": unit.label, "building": prop.name,
        "lease": {"start_date": lease.start_date, "end_date": lease.end_date, "rent": lease.rent,
                  "due_day": lease.due_day, "deposit": lease.deposit,
                  "deposit_received": int(sum(received)) if received else None},
        "next_due": min((c.due_date for c in upcoming), default=None),
        "charges": rows,
        "bank_data_as_of": receivables.latest_transaction_at(session, prop.organization_id),
        "repairs": [{"reported_on": t.reported_on, "description": t.description, "status": t.status,
                     "completed_on": t.completed_on} for t in _requests(session, lease)],
        "notices": tenant_notices.for_unit(session, unit, today),
        "contact": {"phone": prop.contact_phone, "note": prop.contact_note} if prop.contact_phone or prop.contact_note
        else None,
        "link_expires_at": link.expires_at,
        "notice": NOTE,
    }


def request_repair(session: Session, link: TenantLink, lease: Lease, description: str, today: date,
                   now: datetime) -> MaintenanceTicket:
    text = (description or "").strip()
    if not text:
        raise PortalError("어디가 어떻게 고장 났는지 적어 주세요")
    if len(text) > 1000:
        raise PortalError("1,000자 안으로 적어 주세요")
    recent = session.scalar(select(func.count()).select_from(MaintenanceTicket).where(
        MaintenanceTicket.unit_id == lease.unit_id, MaintenanceTicket.source == "tenant",
        MaintenanceTicket.created_at >= now - timedelta(days=1)))
    if recent >= REQUESTS_PER_DAY:
        raise PortalError("오늘은 더 요청할 수 없습니다. 급하면 집주인에게 직접 연락하세요")
    unit = session.get(Unit, lease.unit_id)
    t = MaintenanceTicket(property_id=unit.property_id, unit_id=unit.id, reported_on=today, description=text,
                          status="open", payer="undecided", source="tenant", created_at=now)
    session.add(t)
    session.flush()
    session.add(AuditLog(action="tenant.repair_request", entity_type="maintenance_ticket", entity_id=str(t.id)))
    session.commit()
    return t


def open_requests(session: Session, organization_id: uuid.UUID) -> list[str]:
    """관리자 홈 알림용: 진행 중인 임차인 수리 요청의 호실."""
    return list(session.scalars(
        select(Unit.label).join(MaintenanceTicket, MaintenanceTicket.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .where(Property.organization_id == organization_id, MaintenanceTicket.source == "tenant",
               MaintenanceTicket.status == "open").order_by(Unit.label)))
