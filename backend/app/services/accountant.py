"""세무사 공유 링크 — 건물주가 세무사에게 귀속연도 하나의 세무 준비 자료를 보낸다 (세무사는 가입·결제 없이).

규칙
- 링크 = 비밀 토큰. DB 에는 sha256 만 저장, 원문은 만들 때 한 번만 보여 준다. 사업장·연도마다 하나만 유효
  (새로 만들면 이전 것은 바로 무효). 만료·회수면 열리지 않는다 — 어느 경우든 같은 응답
- 보여 주는 것: 세무 준비 자료(tax_prep.annual)와 같은 값, 엑셀 내려받기. 읽기 전용
- 임차인 이름은 넣지 않는다 (보증금 표는 호실·금액·날짜만). 증빙 파일은 링크로 열지 않는다
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountantLink, AuditLog, Organization
from app.services import tax_prep

DAYS = (30, 90, 180)
SEEN_EVERY = timedelta(minutes=10)


class LinkError(ValueError):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _active(session: Session, organization_id: uuid.UUID, year: int, now: datetime) -> AccountantLink | None:
    return session.scalar(select(AccountantLink).where(
        AccountantLink.organization_id == organization_id, AccountantLink.year == year,
        AccountantLink.revoked_at.is_(None), AccountantLink.expires_at > now).order_by(AccountantLink.created_at.desc()))


def status(session: Session, organization_id: uuid.UUID, year: int, now: datetime) -> dict:
    link = _active(session, organization_id, year, now)
    return {"days": list(DAYS), "link": {"created_at": link.created_at, "expires_at": link.expires_at,
                                         "last_seen_at": link.last_seen_at} if link else None}


def _revoke_all(session: Session, organization_id: uuid.UUID, year: int, now: datetime) -> int:
    links = session.scalars(select(AccountantLink).where(AccountantLink.organization_id == organization_id,
                                                         AccountantLink.year == year,
                                                         AccountantLink.revoked_at.is_(None))).all()
    for link in links:
        link.revoked_at = now
    return len(links)


def create(session: Session, organization_id: uuid.UUID, user_id, year: int, days: int, today: date,
           now: datetime) -> tuple[str, datetime]:
    if days not in DAYS:
        raise LinkError(f"유효 기간은 {', '.join(map(str, DAYS))}일 중에서 고르세요")
    if not 2000 <= year <= today.year:
        raise LinkError("귀속연도를 확인하세요")
    _revoke_all(session, organization_id, year, now)
    token = secrets.token_urlsafe(32)
    link = AccountantLink(organization_id=organization_id, year=year, token_hash=_hash(token),
                          expires_at=now + timedelta(days=days), created_by=user_id)
    session.add(link)
    session.add(AuditLog(user_id=user_id, action="accountant_link.create", entity_type="organization",
                         entity_id=str(organization_id), detail={"year": year, "days": days}))
    session.commit()
    return token, link.expires_at


def revoke(session: Session, organization_id: uuid.UUID, user_id, year: int, now: datetime) -> int:
    n = _revoke_all(session, organization_id, year, now)
    session.add(AuditLog(user_id=user_id, action="accountant_link.revoke", entity_type="organization",
                         entity_id=str(organization_id), detail={"year": year, "revoked": n}))
    session.commit()
    return n


def open_link(session: Session, token: str, now: datetime) -> AccountantLink | None:
    if not token or len(token) > 100:
        return None
    link = session.scalar(select(AccountantLink).where(AccountantLink.token_hash == _hash(token)))
    if link is None or link.revoked_at is not None or _aware(link.expires_at) <= now:
        return None
    if link.last_seen_at is None or now - _aware(link.last_seen_at) > SEEN_EVERY:
        link.last_seen_at = now
        session.commit()
    return link


def data(session: Session, link: AccountantLink, today: date) -> dict:
    out = tax_prep.annual(session, link.organization_id, link.year, today)
    for d in out["deposits"]:
        d["tenant_name"] = ""  # 세무사에게는 임차인 이름을 보내지 않는다
    for e in out["expenses"]:
        e["receipts"] = [{"name": r["name"]} for r in e["receipts"]]  # 증빙은 이름만 — 파일은 링크로 열지 않음
    org = session.get(Organization, link.organization_id)
    out["organization_name"] = org.name if org else ""
    out["link_expires_at"] = link.expires_at
    return out
