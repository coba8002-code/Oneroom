"""요금제·정기결제 (토스페이먼츠 빌링) — 규칙은 app/services/billing.py.

GET  /api/v1/billing                   — 요금제 상태·가격·결제 기록 (멤버 누구나)
POST /api/v1/billing/card              — 카드 등록 (결제창에서 받은 authKey → 빌링키) · 대표만
POST /api/v1/billing/subscribe         — 유료 시작 (바로 첫 결제) · 대표만
POST /api/v1/billing/cancel | resume   — 해지 예약 / 해지 취소 · 대표만
POST /api/v1/billing/tax-helper        — 셀프 신고 도우미 1년 결제 · 대표만
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard, require_owner
from app.db import get_session
from app.routers.assets import _today
from app.services import billing

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run(session: Session, fn):
    try:
        return fn()
    except billing.BillingError as e:
        session.rollback()
        raise HTTPException(409, str(e)) from e


@router.get("")
def status(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    out = billing.state(session, member.organization_id, _now(), _today())
    session.commit()  # 처음 보는 사업장이면 체험이 시작된다
    if member.role != "owner":
        out.pop("customer_key")
    return out


class CardIn(BaseModel):
    auth_key: str = Field(min_length=1, max_length=300)
    customer_key: str = Field(min_length=1, max_length=64)


@router.post("/card")
def register_card(body: CardIn, member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    _run(session, lambda: billing.register_card(session, member.organization_id, member.user_id, body.auth_key,
                                                body.customer_key, _now()))
    return {"ok": True}


class SubscribeIn(BaseModel):
    cycle: str


@router.post("/subscribe")
def subscribe(body: SubscribeIn, member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    return _run(session, lambda: billing.subscribe(session, member.organization_id, member.user_id, body.cycle, _now()))


@router.post("/cancel")
def cancel(member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    _run(session, lambda: billing.set_canceled(session, member.organization_id, member.user_id, True, _now()))
    return {"ok": True}


@router.post("/resume")
def resume(member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    _run(session, lambda: billing.set_canceled(session, member.organization_id, member.user_id, False, _now()))
    return {"ok": True}


@router.post("/tax-helper")
def tax_helper(member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    until = _run(session, lambda: billing.buy_tax_helper(session, member.organization_id, member.user_id, _now(), _today()))
    return {"tax_helper_until": until}
