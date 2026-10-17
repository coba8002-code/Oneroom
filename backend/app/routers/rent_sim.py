"""전월세 시뮬레이션."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.services import rent_sim as svc

router = APIRouter(prefix="/api/v1", tags=["rent-sim"])
KST = ZoneInfo("Asia/Seoul")


class RowIn(BaseModel):
    lease_id: str
    deposit: int
    rent: int


class SimIn(BaseModel):
    rows: list[RowIn] = Field(default_factory=list, max_length=500)
    deposit_yield_pct: str | None = Field(default=None, max_length=10)
    annual_opex: int | None = None
    cash_on_hand: int | None = None
    property_value: int | None = None
    as_of: date | None = None


@router.post("/rent-sim")
def simulate(body: SimIn, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    try:
        return svc.simulate(session, member.organization_id, body.as_of or datetime.now(KST).date(),
                            [svc.Row(**r.model_dump()) for r in body.rows], deposit_yield_pct=body.deposit_yield_pct,
                            annual_opex=body.annual_opex, cash_on_hand=body.cash_on_hand,
                            property_value=body.property_value)
    except svc.SimError as e:
        raise HTTPException(409, str(e)) from e
