"""임차인 화면.

GET  /api/v1/tenant/{token}          — 임차인이 링크로 여는 화면 자료. 로그인 대신 계약별 비밀 토큰
POST /api/v1/tenant/{token}/repairs  — 수리 요청
  모르는 토큰·만료·회수·계약 종료는 모두 같은 404 (어느 경우인지 알려 주지 않음).
나머지(링크 만들기·상태·회수)는 로그인 필요 (main.py 에서 PROTECTED 로 묶음).
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.routers.assets import _today
from app.services import tenant_portal as svc

public = APIRouter(prefix="/api/v1/tenant", tags=["tenant"], include_in_schema=False)
router = APIRouter(prefix="/api/v1", tags=["tenant"])

GONE = "링크가 만료되었거나 더 이상 쓸 수 없습니다. 집주인에게 새 링크를 요청하세요."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _open(session: Session, token: str):
    found = svc.open_link(session, token, _now())
    if found is None:
        raise HTTPException(404, GONE)
    return found


def _run(fn):
    try:
        return fn()
    except svc.PortalError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@public.get("/{token}")
def tenant_view(token: str, session: Session = Depends(get_session)) -> dict:
    link, lease = _open(session, token)
    return svc.view(session, link, lease, _today(), _now())


class RepairIn(BaseModel):
    description: str = Field(max_length=1000)


@public.post("/{token}/repairs")
def tenant_repair(token: str, body: RepairIn, session: Session = Depends(get_session)) -> dict:
    link, lease = _open(session, token)
    _run(lambda: svc.request_repair(session, link, lease, body.description, _today(), _now()))
    return {"ok": True}


@router.get("/leases/{lease_id}/tenant-link")
def link_status(lease_id: uuid.UUID, member: Member = Depends(org_guard),
                session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.link_status(session, member.organization_id, lease_id, _now()))


class LinkIn(BaseModel):
    days: int


@router.post("/leases/{lease_id}/tenant-link")
def create_link(lease_id: uuid.UUID, body: LinkIn, member: Member = Depends(org_guard),
                session: Session = Depends(get_session)) -> dict:
    token, expires = _run(lambda: svc.create_link(session, member.organization_id, lease_id, member.user_id,
                                                  body.days, _now()))
    return {"path": f"/t/{token}", "expires_at": expires}  # 원문은 이번 한 번만


@router.delete("/leases/{lease_id}/tenant-link")
def revoke_link(lease_id: uuid.UUID, member: Member = Depends(org_guard),
                session: Session = Depends(get_session)) -> dict:
    return {"revoked": _run(lambda: svc.revoke_link(session, member.organization_id, lease_id, member.user_id,
                                                     _now()))}
