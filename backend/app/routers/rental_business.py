"""등록임대사업자 모드 — 사업자 정보·등록 임대주택·임대보증금 보증·의무 점검."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.routers.assets import _today
from app.services import rental_business as svc

router = APIRouter(prefix="/api/v1", tags=["rental-business"])


def _run(fn):
    try:
        return fn()
    except svc.RentalBusinessError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/rental-business")
def overview(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return svc.overview(session, member.organization_id, _today())


class ProfileIn(BaseModel):
    registration_no: str | None = Field(default=None, max_length=50)
    registered_on: date | None = None
    tax_business_no: str | None = Field(default=None, max_length=20)
    increase_cap_pct: str | None = Field(default=None, max_length=10)
    report_months: int | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.put("/rental-business")
def save_profile(body: ProfileIn, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    _run(lambda: svc.save_profile(session, member.organization_id, member.user_id, svc.ProfileFields(**body.model_dump())))
    return {"ok": True}


class RegistrationIn(BaseModel):
    property_id: uuid.UUID
    unit_id: uuid.UUID | None = None  # 비우면 건물 전체
    housing_type: str
    rental_type: str
    registered_on: date | None = None
    rental_start_on: date | None = None
    obligation_years: int | None = None
    lien_status: str | None = None
    lien_done_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.post("/registered-rentals", status_code=201)
def create_registration(body: RegistrationIn, member: Member = Depends(org_guard),
                        session: Session = Depends(get_session)) -> dict:
    r = _run(lambda: svc.save_registration(session, member.organization_id, member.user_id,
                                           svc.RegistrationFields(**body.model_dump())))
    return {"id": str(r.id)}


@router.put("/registered-rentals/{reg_id}")
def update_registration(reg_id: uuid.UUID, body: RegistrationIn, member: Member = Depends(org_guard),
                        session: Session = Depends(get_session)) -> dict:
    r = _run(lambda: svc.save_registration(session, member.organization_id, member.user_id,
                                           svc.RegistrationFields(**body.model_dump()), reg_id))
    return {"id": str(r.id)}


@router.delete("/registered-rentals/{reg_id}", status_code=204)
def delete_registration(reg_id: uuid.UUID, member: Member = Depends(org_guard),
                        session: Session = Depends(get_session)) -> None:
    _run(lambda: svc.delete_registration(session, member.organization_id, member.user_id, reg_id))


class GuaranteeIn(BaseModel):
    provider: str
    policy_no: str | None = Field(default=None, max_length=50)
    start_on: date | None = None
    end_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.post("/registered-rentals/{reg_id}/guarantees", status_code=201)
def add_guarantee(reg_id: uuid.UUID, body: GuaranteeIn, member: Member = Depends(org_guard),
                  session: Session = Depends(get_session)) -> dict:
    g = _run(lambda: svc.add_guarantee(session, member.organization_id, member.user_id, reg_id,
                                       svc.GuaranteeFields(**body.model_dump())))
    return {"id": str(g.id)}


@router.delete("/rental-guarantees/{guarantee_id}", status_code=204)
def delete_guarantee(guarantee_id: uuid.UUID, member: Member = Depends(org_guard),
                     session: Session = Depends(get_session)) -> None:
    _run(lambda: svc.delete_guarantee(session, member.organization_id, member.user_id, guarantee_id))
