import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Charge, Lease, Property, Unit
from app.schemas import ChargeOut, GenerateChargesOut
from app.services.charges import generate_charges, parse_period

router = APIRouter(prefix="/api/v1/charges", tags=["charges"])


@router.post("/generate", response_model=GenerateChargesOut)
def generate(
    organization_id: uuid.UUID,
    period: str = Query(..., examples=["2026-11"]),
    session: Session = Depends(get_session),
) -> GenerateChargesOut:
    try:
        rows, already = generate_charges(session, organization_id, period)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return GenerateChargesOut(
        period=period, created=len(rows) - already, already_existed=already,
        charges=[_out(c, unit_no) for c, unit_no in rows],
    )


@router.get("", response_model=list[ChargeOut])
def list_charges(
    organization_id: uuid.UUID, period: str, session: Session = Depends(get_session)
) -> list[ChargeOut]:
    try:
        parse_period(period)
    except ValueError as e:
        raise HTTPException(422, str(e))
    rows = session.execute(
        select(Charge, Unit.label)
        .join(Lease, Charge.lease_id == Lease.id)
        .join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .where(Property.organization_id == organization_id, Charge.period == period)
        .order_by(Charge.due_date, Unit.label)
    ).all()
    return [_out(c, unit_no) for c, unit_no in rows]


def _out(c: Charge, unit_no: str) -> ChargeOut:
    return ChargeOut(
        id=c.id, lease_id=c.lease_id, unit_no=unit_no, period=c.period,
        due_date=c.due_date, amount=c.amount, status=c.status,
    )
