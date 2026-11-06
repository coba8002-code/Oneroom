"""세무사 공유 링크 · 셀프 신고 도우미.

GET  /api/v1/accountant/{token}               — 세무사가 링크로 여는 세무 준비 자료 (로그인 없음, 읽기 전용)
GET  /api/v1/accountant/{token}/export.xlsx   — 같은 자료 엑셀
  모르는 토큰·만료·회수는 모두 같은 404.
GET|POST|DELETE /api/v1/tax-prep/{year}/accountant-link  — 링크 상태·만들기·회수 (대표만 만들고 회수)
GET  /api/v1/tax-prep/{year}/self-filing      — 셀프 신고 도우미 추정치 (이용권 또는 체험 중)
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import Member, org_guard, require_owner
from app.db import get_session
from app.routers.tax_prep import _today
from app.services import accountant as svc, billing, self_filing, tax_prep

public = APIRouter(prefix="/api/v1/accountant", tags=["accountant"], include_in_schema=False)
router = APIRouter(prefix="/api/v1/tax-prep", tags=["accountant"])

GONE = "링크가 만료되었거나 더 이상 쓸 수 없습니다. 건물주에게 새 링크를 요청하세요."
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _open(session: Session, token: str):
    link = svc.open_link(session, token, _now())
    if link is None:
        raise HTTPException(404, GONE)
    return link


@public.get("/{token}")
def view(token: str, session: Session = Depends(get_session)) -> dict:
    return svc.data(session, _open(session, token), _today())


@public.get("/{token}/export.xlsx")
def export(token: str, session: Session = Depends(get_session)) -> Response:
    link = _open(session, token)
    return Response(tax_prep.to_xlsx(svc.data(session, link, _today())), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="roomax-tax-{link.year}.xlsx"'})


@router.get("/{year}/accountant-link")
def link_status(year: int, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return svc.status(session, member.organization_id, year, _now())


class LinkIn(BaseModel):
    days: int = 90


@router.post("/{year}/accountant-link")
def create_link(year: int, body: LinkIn, member: Member = Depends(require_owner),
                session: Session = Depends(get_session)) -> dict:
    try:
        token, expires = svc.create(session, member.organization_id, member.user_id, year, body.days, _today(), _now())
    except svc.LinkError as e:
        raise HTTPException(409, str(e)) from e
    return {"token": token, "expires_at": expires}


@router.delete("/{year}/accountant-link")
def revoke_link(year: int, member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    return {"revoked": svc.revoke(session, member.organization_id, member.user_id, year, _now())}


@router.get("/{year}/self-filing")
def self_filing_estimate(year: int, registered: bool = False, other_income: int | None = None,
                         member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    sub = billing.get(session, member.organization_id, _now())
    session.commit()
    if not billing.tax_helper_active(sub, _now(), _today()):
        raise HTTPException(402, f"셀프 신고 도우미는 이용권(연 {billing.TAX_HELPER_PRICE:,}원)이 필요합니다. "
                                 "설정 → 요금제에서 살 수 있습니다")
    if other_income is not None and not 0 <= other_income <= 10_000_000_000:
        raise HTTPException(422, "다른 종합소득금액을 확인하세요")
    try:
        return self_filing.estimate(session, member.organization_id, year, registered, other_income, _today())
    except tax_prep.TaxPrepError as e:
        raise HTTPException(409, str(e)) from e
