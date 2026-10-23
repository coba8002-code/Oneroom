"""사진·스캔 판독 (계약서·호실 목록·통장 내역) → 표. 저장하지 않는다 — 화면에서 확인 후 넣기."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.models import BankAccount
from app.routers.assets import _today
from app.schemas import ImportOut
from app.services import vision
from app.services.bank_import import import_rows

router = APIRouter(prefix="/api/v1", tags=["vision"])


@router.get("/vision/status")
def status(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return {"configured": vision.configured(), "daily_limit": vision.DAILY_LIMIT, "max_files": vision.MAX_FILES,
            "used_today": vision.used_today(session, member.organization_id, _today())}


async def _files(files: list[UploadFile]) -> list[tuple[bytes, str]]:
    out = []
    for f in files[:vision.MAX_FILES + 1]:
        out.append((await f.read(vision.MAX_TOTAL_BYTES + 1), (f.content_type or "").lower()))
    return out


def _read(session: Session, member: Member, kind: str, files: list[tuple[bytes, str]]) -> dict:
    try:
        return vision.read(session, member.organization_id, member.user_id, kind, files, _today())
    except vision.NotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except vision.VisionError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/vision/units")
async def read_units(files: list[UploadFile] = File(...), member: Member = Depends(org_guard),
                     session: Session = Depends(get_session)) -> dict:
    return _read(session, member, "units", await _files(files))


@router.post("/vision/bank")
async def read_bank(files: list[UploadFile] = File(...), member: Member = Depends(org_guard),
                    session: Session = Depends(get_session)) -> dict:
    return _read(session, member, "bank", await _files(files))


class BankRowIn(BaseModel):
    date: date
    time: str | None = Field(default=None, max_length=8)
    direction: str = Field(pattern="^(in|out)$")
    amount: int = Field(gt=0)
    counterparty: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    balance_after: int | None = None


class BankRowsIn(BaseModel):
    rows: list[BankRowIn] = Field(min_length=1, max_length=500)


@router.post("/bank-accounts/{account_id}/import-rows", response_model=ImportOut)
def import_confirmed_rows(account_id: uuid.UUID, body: BankRowsIn, member: Member = Depends(org_guard),
                          session: Session = Depends(get_session)) -> ImportOut:
    """사진에서 읽고 관리자가 확인한 거래 → 통장 내역 (파일 가져오기와 같은 규칙·중복 방지)."""
    account = session.get(BankAccount, account_id)
    if account is None or account.organization_id != member.organization_id:
        raise HTTPException(404, "계좌를 찾을 수 없습니다")
    rows = [{**r.model_dump(), "date": r.date.isoformat()} for r in body.rows]
    try:
        return import_rows(session, account, rows)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
