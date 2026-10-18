"""공과금 — 건물·항목별 처리 방식, 고지서, 배분 청구."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.services import utilities as svc

router = APIRouter(prefix="/api/v1", tags=["utilities"])


def _run(fn):
    try:
        return fn()
    except svc.UtilityError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/utility-settings")
def get_settings(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return svc.settings(session, member.organization_id)


class SettingIn(BaseModel):
    mode: str
    method: str | None = None
    vacant: str | None = None
    owner: str | None = None


@router.put("/properties/{property_id}/utility-settings/{item}")
def save_setting(property_id: uuid.UUID, item: str, body: SettingIn, member: Member = Depends(org_guard),
                 session: Session = Depends(get_session)) -> dict:
    _run(lambda: svc.save_setting(session, member.organization_id, property_id, item, member.user_id,
                                  svc.SettingFields(**body.model_dump())))
    return {"ok": True}


@router.get("/utility-bills")
def list_bills(period: str | None = None, member: Member = Depends(org_guard),
               session: Session = Depends(get_session)) -> list[dict]:
    return svc.list_bills(session, member.organization_id, period)


class BillIn(BaseModel):
    property_id: uuid.UUID
    item: str
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    total: int
    note: str | None = Field(default=None, max_length=200)
    manual: dict[str, int | None] | None = None  # 직접 입력 방식: {unit_id: 원}


class BillUpdateIn(BaseModel):
    total: int
    note: str | None = Field(default=None, max_length=200)
    manual: dict[str, int | None] | None = None


@router.post("/utility-bills", status_code=201)
def create_bill(body: BillIn, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    b = _run(lambda: svc.create_bill(session, member.organization_id, member.user_id,
                                     svc.BillFields(**body.model_dump())))
    return svc.bill_out(session, b)


@router.put("/utility-bills/{bill_id}")
def update_bill(bill_id: uuid.UUID, body: BillUpdateIn, member: Member = Depends(org_guard),
                session: Session = Depends(get_session)) -> dict:
    b = _run(lambda: svc.update_bill(session, member.organization_id, bill_id, member.user_id,
                                     body.total, body.note, body.manual))
    return svc.bill_out(session, b)


@router.delete("/utility-bills/{bill_id}", status_code=204)
def delete_bill(bill_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> None:
    _run(lambda: svc.delete_bill(session, member.organization_id, bill_id, member.user_id))


@router.post("/utility-bills/{bill_id}/charge")
def charge_bill(bill_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    b = _run(lambda: svc.charge_bill(session, member.organization_id, bill_id, member.user_id))
    return svc.bill_out(session, b)


@router.post("/utility-bills/{bill_id}/uncharge")
def uncharge_bill(bill_id: uuid.UUID, member: Member = Depends(org_guard),
                  session: Session = Depends(get_session)) -> dict:
    b = _run(lambda: svc.uncharge_bill(session, member.organization_id, bill_id, member.user_id))
    return svc.bill_out(session, b)
