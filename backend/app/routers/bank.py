import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.models import BankAccount
from app.schemas import ImportOut
from app.services.bank_import import import_transactions

router = APIRouter(prefix="/api/v1/bank-accounts", tags=["bank"])

MAX_UPLOAD = 10_000_000
ALLOWED = (".csv", ".xlsx", ".xlsm", ".xls")


@router.post("/{account_id}/import", response_model=ImportOut)
async def import_file(
    account_id: uuid.UUID, file: UploadFile = File(...), member: Member = Depends(org_guard),
    session: Session = Depends(get_session),
) -> ImportOut:
    account = session.get(BankAccount, account_id)
    if account is None or account.organization_id != member.organization_id:
        raise HTTPException(404, "계좌를 찾을 수 없습니다")
    name = file.filename or ""
    if not name.lower().endswith(ALLOWED):
        raise HTTPException(415, "CSV·XLSX·XLS 파일만 가져올 수 있습니다")
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "파일이 너무 큽니다 (10MB 이하)")
    try:
        return import_transactions(session, account, name, raw)
    except ValueError as e:
        raise HTTPException(422, str(e))
