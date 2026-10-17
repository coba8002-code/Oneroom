"""공실 관리."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.routers.assets import _today
from app.services import vacancy as svc

router = APIRouter(prefix="/api/v1", tags=["vacancy"])


def _run(fn):
    try:
        return fn()
    except svc.VacancyError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


class ListingIn(BaseModel):
    asking_deposit: int | None = None
    asking_rent: int | None = None
    available_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class ActivityIn(BaseModel):
    kind: str
    happened_on: date | None = None
    agent_name: str | None = Field(default=None, max_length=100)
    agent_phone: str | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=1000)


@router.get("/vacancies")
def summary(as_of: date | None = None, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return {**svc.summary(session, member.organization_id, as_of or _today()), "kinds": svc.KINDS}


@router.get("/vacancies/{unit_id}")
def detail(unit_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.detail(session, member.organization_id, unit_id))


@router.put("/vacancies/{unit_id}/listing")
def save_listing(unit_id: uuid.UUID, body: ListingIn, member: Member = Depends(org_guard),
                 session: Session = Depends(get_session)) -> dict:
    _run(lambda: svc.save_listing(session, member.organization_id, unit_id, member.user_id,
                                  svc.ListingFields(**body.model_dump())))
    return _run(lambda: svc.detail(session, member.organization_id, unit_id))


@router.post("/vacancies/{unit_id}/activities", status_code=201)
def add_activity(unit_id: uuid.UUID, body: ActivityIn, member: Member = Depends(org_guard),
                 session: Session = Depends(get_session)) -> dict:
    today = _today()
    a = _run(lambda: svc.add_activity(session, member.organization_id, unit_id, member.user_id, body.kind,
                                      body.happened_on or today, today, body.agent_name, body.agent_phone, body.note))
    return {"id": str(a.id)}


@router.delete("/vacancy-activities/{activity_id}", status_code=204)
def delete_activity(activity_id: uuid.UUID, member: Member = Depends(org_guard),
                    session: Session = Depends(get_session)) -> None:
    _run(lambda: svc.delete_activity(session, member.organization_id, activity_id, member.user_id))
