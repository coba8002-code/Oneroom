from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.schemas import CsvPreviewOut, OnboardingIn, OnboardingOut
from app.services.onboarding import onboard, parse_onboarding_csv

router = APIRouter(prefix="/api/v1/onboarding", tags=["onboarding"])

MAX_UPLOAD = 1_000_000


@router.post("", response_model=OnboardingOut, status_code=201)
def create(data: OnboardingIn, member: Member = Depends(org_guard),
           session: Session = Depends(get_session)) -> OnboardingOut:
    try:
        return onboard(session, member.organization_id, data)
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "이미 있는 데이터와 충돌합니다")


@router.post("/csv-preview", response_model=CsvPreviewOut)
async def csv_preview(file: UploadFile = File(...)) -> CsvPreviewOut:
    """CSV 를 읽어 호실 목록으로 돌려준다. 저장하지 않는다 — 화면에서 검수 후 등록."""
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "파일이 너무 큽니다 (1MB 이하)")
    try:
        units, errors = parse_onboarding_csv(raw)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return CsvPreviewOut(units=units, errors=errors)
