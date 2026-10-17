"""월세 납부 확인서 — 계약·연도별, 장부에 월세로 확정된 입금만."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.routers.assets import _today
from app.services import rent_certificate as svc

router = APIRouter(prefix="/api/v1", tags=["rent-certificate"])


@router.get("/leases/{lease_id}/rent-certificate")
def certificate(lease_id: uuid.UUID, year: int = Query(ge=2000, le=2100), member: Member = Depends(org_guard),
                session: Session = Depends(get_session)) -> dict:
    try:
        return svc.build(session, member.organization_id, lease_id, year, _today(), member.user_id)
    except svc.CertificateError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
