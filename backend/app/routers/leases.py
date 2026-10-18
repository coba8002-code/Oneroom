"""계약 종료 · 되돌리기 · 새 계약 · 호실별 계약 이력."""
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.services import lease_lifecycle as svc, lease_rules as rules

router = APIRouter(prefix="/api/v1", tags=["leases"])
KST = ZoneInfo("Asia/Seoul")


def _run(fn):
    try:
        return fn()
    except svc.LeaseError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


class EndIn(BaseModel):
    ended_on: date | None = None
    reason: str | None = Field(default=None, max_length=500)


class NewLeaseIn(BaseModel):
    tenant_name: str = Field(max_length=100)
    tenant_phone: str | None = Field(default=None, max_length=30)
    deposit: int = 0
    rent: int
    mgmt_fee: int | None = None  # 정액 관리비. 비우면 '따로 적지 않음'
    due_day: int
    start_date: date
    end_date: date | None = None
    signed_on: date | None = None
    deposit_received_on: date | None = None


@router.get("/lease-history")
def lease_history(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> list[dict]:
    return svc.history(session, member.organization_id)


@router.post("/leases/{lease_id}/end")
def end_lease(lease_id: uuid.UUID, body: EndIn, member: Member = Depends(org_guard),
              session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.end_lease(session, member.organization_id, member.user_id, lease_id,
                                      body.ended_on or datetime.now(KST).date(), body.reason))


@router.post("/leases/{lease_id}/undo-end")
def undo_end(lease_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.undo_end(session, member.organization_id, member.user_id, lease_id))


@router.post("/units/{unit_id}/leases", status_code=201)
def new_lease(unit_id: uuid.UUID, body: NewLeaseIn, member: Member = Depends(org_guard),
              session: Session = Depends(get_session)) -> dict:
    lease = _run(lambda: svc.new_lease(session, member.organization_id, member.user_id, unit_id, **body.model_dump()))
    return {"lease_id": str(lease.id)}


class AmountsIn(BaseModel):
    rent: int
    mgmt_fee: int | None = None


@router.put("/leases/{lease_id}/amounts")
def set_amounts(lease_id: uuid.UUID, body: AmountsIn, member: Member = Depends(org_guard),
                session: Session = Depends(get_session)) -> dict:
    lease = _run(lambda: svc.set_amounts(session, member.organization_id, member.user_id, lease_id,
                                         rent=body.rent, mgmt_fee=body.mgmt_fee))
    return {"lease_id": str(lease.id), "rent": lease.rent, "mgmt_fee": lease.mgmt_fee}


# ── 계약 법정 체크리스트 · 계산기 ─────────────────────────────

class SignedOnIn(BaseModel):
    signed_on: date | None = None


class CheckIn(BaseModel):
    status: str | None = None  # done | na | None(되돌림)
    done_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


def _rule(fn):
    try:
        return fn()
    except rules.RuleError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/leases/{lease_id}/checklist")
def checklist(lease_id: uuid.UUID, as_of: date | None = None, member: Member = Depends(org_guard),
              session: Session = Depends(get_session)) -> dict:
    return _rule(lambda: rules.checklist(session, member.organization_id, lease_id, as_of or datetime.now(KST).date()))


@router.put("/leases/{lease_id}/signed-on")
def signed_on(lease_id: uuid.UUID, body: SignedOnIn, member: Member = Depends(org_guard),
              session: Session = Depends(get_session)) -> dict:
    _rule(lambda: rules.set_signed_on(session, member.organization_id, member.user_id, lease_id, body.signed_on))
    return {"signed_on": body.signed_on}


@router.put("/leases/{lease_id}/checks/{key}")
def set_check(lease_id: uuid.UUID, key: str, body: CheckIn, member: Member = Depends(org_guard),
              session: Session = Depends(get_session)) -> dict:
    _rule(lambda: rules.set_check(session, member.organization_id, member.user_id, lease_id, key,
                                  status=body.status, done_on=body.done_on, note=body.note))
    return {"key": key, "status": body.status}


@router.get("/rent-rules/increase")
def increase(deposit: int, rent: int, since: date, member: Member = Depends(org_guard)) -> dict:
    return _rule(lambda: rules.increase_caps(deposit, rent, since, datetime.now(KST).date()))


@router.get("/rent-rules/conversion")
def conversion(amount: int, base_rate: str, member: Member = Depends(org_guard)) -> dict:
    return _rule(lambda: rules.conversion(amount, base_rate))
