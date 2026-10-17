"""월간 운영 보고서."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.routers.assets import _today
from app.services import monthly_report as svc

router = APIRouter(prefix="/api/v1/reports/monthly-summary", tags=["reports"])


def _build(session: Session, member: Member, period: str) -> dict:
    try:
        return svc.build(session, member.organization_id, period, _today())
    except svc.ReportError as e:
        raise HTTPException(422, str(e)) from e


@router.get("")
def summary(period: str, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return _build(session, member, period)


@router.get("/export.xlsx")
def export(period: str, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> Response:
    body = svc.to_xlsx(_build(session, member, period))
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="roomax-report-{period}.xlsx"'})
