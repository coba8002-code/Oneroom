"""임차인 메시지 (월세 고지 · 미납 안내 · 계약 만료 안내) — 초안 → 관리자 승인 → 발송(또는 직접 보냄 표시)."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.services import messaging, notifications as svc
from app.services.charges import parse_period

router = APIRouter(prefix="/api/v1", tags=["notifications"])


class SettingsIn(BaseModel):
    grace_days: int | None = None
    rent_template: str | None = Field(default=None, max_length=1000)
    overdue_template: str | None = Field(default=None, max_length=1000)
    renewal_template: str | None = Field(default=None, max_length=1000)


class BodyIn(BaseModel):
    body: str = Field(max_length=1000)


def _settings_out(row) -> dict:
    return {"grace_days": row.grace_days, "rent_template": row.rent_template,
            "overdue_template": row.overdue_template, "renewal_template": row.renewal_template,
            "variables": svc.VARIABLES, "renewal_variables": svc.RENEWAL_VARIABLES}


def _run(fn):
    try:
        return fn()
    except svc.NotifyError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/notification-settings")
def get_settings(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    out = _settings_out(svc.get_settings(session, member.organization_id))
    try:
        provider = messaging.get_provider()
    except RuntimeError:
        provider = None
    out["provider"] = {"connected": provider is not None, "name": provider.name if provider else None}
    return out


@router.put("/notification-settings")
def put_settings(body: SettingsIn, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return _settings_out(_run(lambda: svc.save_settings(
        session, member.organization_id, grace_days=body.grace_days,
        rent_template=body.rent_template, overdue_template=body.overdue_template,
        renewal_template=body.renewal_template)))


@router.get("/notifications")
def list_notifications(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> list[dict]:
    return svc.listing(session, member.organization_id)


@router.post("/notifications/rent-notices")
def rent_notices(period: str, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    try:
        parse_period(period)
    except ValueError as e:
        raise HTTPException(422, "기간은 YYYY-MM") from e
    return _run(lambda: svc.make_rent_notices(session, member.organization_id, period))


@router.post("/notifications/overdue-notices")
def overdue_notices(as_of: date, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.make_overdue_notices(session, member.organization_id, as_of))


@router.post("/notifications/renewal-notices")
def renewal_notices(as_of: date, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.make_renewal_notices(session, member.organization_id, as_of))


def _one(session, member, notification_id):
    return _run(lambda: svc.get(session, member.organization_id, notification_id))


@router.patch("/notifications/{notification_id}")
def edit(notification_id: uuid.UUID, body: BodyIn, member: Member = Depends(org_guard),
         session: Session = Depends(get_session)) -> dict:
    n = _one(session, member, notification_id)
    _run(lambda: svc.edit(session, n, body.body))
    return {"id": str(n.id), "status": n.status, "body": n.body}


@router.post("/notifications/{notification_id}/approve")
def approve(notification_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    n = _one(session, member, notification_id)
    _run(lambda: svc.approve(session, n, member.user_id))
    return {"id": str(n.id), "status": n.status, "error": n.error}


@router.post("/notifications/{notification_id}/mark-sent")
def mark_sent(notification_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    n = _one(session, member, notification_id)
    _run(lambda: svc.mark_sent(session, n, member.user_id))
    return {"id": str(n.id), "status": n.status}


@router.post("/notifications/{notification_id}/discard")
def discard(notification_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    n = _one(session, member, notification_id)
    _run(lambda: svc.discard(session, n, member.user_id))
    return {"id": str(n.id), "status": n.status}
