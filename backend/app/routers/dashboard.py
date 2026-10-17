import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import BankAccount
from app.schemas import BankAccountOut, DashboardOut
from app.services import dashboard

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
KST = ZoneInfo("Asia/Seoul")


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(organization_id: uuid.UUID, as_of: date | None = None,
                  session: Session = Depends(get_session)) -> DashboardOut:
    return DashboardOut(**dashboard.build(session, organization_id, as_of or datetime.now(KST).date()))


@router.get("/bank-accounts", response_model=list[BankAccountOut])
def bank_accounts(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> list[BankAccountOut]:
    return [BankAccountOut(id=a.id, alias=a.alias) for a in session.scalars(
        select(BankAccount).where(BankAccount.organization_id == organization_id).order_by(BankAccount.created_at))]
