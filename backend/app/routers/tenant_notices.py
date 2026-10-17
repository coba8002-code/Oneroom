"""임차인 공지·집주인 연락처 (관리자). 임차인은 초대 링크 화면에서만 본다."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.routers.assets import _today
from app.services import tenant_notices as svc

router = APIRouter(prefix="/api/v1", tags=["tenant-notices"])


def _run(fn):
    try:
        return fn()
    except svc.NoticeError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/tenant-notices")
def overview(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return svc.overview(session, member.organization_id, _today())


class ContactIn(BaseModel):
    phone: str | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=200)


@router.put("/properties/{property_id}/tenant-contact")
def save_contact(property_id: uuid.UUID, body: ContactIn, member: Member = Depends(org_guard),
                 session: Session = Depends(get_session)) -> dict:
    _run(lambda: svc.save_contact(session, member.organization_id, property_id, member.user_id, body.phone, body.note))
    return {"ok": True}


class NoticeIn(BaseModel):
    property_id: uuid.UUID
    unit_id: uuid.UUID | None = None  # 비우면 건물 전체
    title: str = Field(max_length=100)
    body: str | None = Field(default=None, max_length=2000)
    starts_on: date | None = None
    ends_on: date | None = None


@router.post("/tenant-notices", status_code=201)
def create_notice(body: NoticeIn, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    n = _run(lambda: svc.create_notice(session, member.organization_id, member.user_id, svc.NoticeFields(
        property_id=body.property_id, unit_id=body.unit_id, title=body.title, body=body.body,
        starts_on=body.starts_on or _today(), ends_on=body.ends_on)))
    return {"id": str(n.id)}


@router.delete("/tenant-notices/{notice_id}", status_code=204)
def delete_notice(notice_id: uuid.UUID, member: Member = Depends(org_guard),
                  session: Session = Depends(get_session)) -> None:
    _run(lambda: svc.delete_notice(session, member.organization_id, notice_id, member.user_id))
