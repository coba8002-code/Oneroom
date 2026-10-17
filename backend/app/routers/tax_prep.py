"""세무 준비 — 귀속연도 자료 · 엑셀 · 지출 증빙."""
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.services import storage, tax_prep as svc
from app.services.contracts import UploadError

router = APIRouter(prefix="/api/v1", tags=["tax-prep"])
KST = ZoneInfo("Asia/Seoul")


def _run(fn):
    try:
        return fn()
    except UploadError as e:
        raise HTTPException(e.status, str(e)) from e
    except svc.TaxPrepError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


def _today() -> date:
    return datetime.now(KST).date()


@router.get("/tax-prep/{year}")
def annual(year: int, as_of: date | None = None, member: Member = Depends(org_guard),
           session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.annual(session, member.organization_id, year, as_of or _today()))


@router.get("/tax-prep/{year}/export.xlsx")
def export(year: int, as_of: date | None = None, member: Member = Depends(org_guard),
           session: Session = Depends(get_session)) -> Response:
    data = _run(lambda: svc.annual(session, member.organization_id, year, as_of or _today()))
    return Response(svc.to_xlsx(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="roomax-tax-{year}.xlsx"'})


@router.post("/expenses/{expense_id}/receipts", status_code=201)
async def add_receipt(expense_id: uuid.UUID, file: UploadFile = File(...), member: Member = Depends(org_guard),
                      session: Session = Depends(get_session)) -> dict:
    raw = await file.read(svc.MAX_RECEIPT_BYTES + 1)
    r = _run(lambda: svc.add_receipt(session, member.organization_id, member.user_id, expense_id, raw, file.filename))
    return {"id": str(r.id)}


@router.get("/expense-receipts/{receipt_id}")
def get_receipt(receipt_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> Response:
    r = _run(lambda: svc.get_receipt(session, member.organization_id, receipt_id))
    return Response(storage.load(r.file_path), media_type=r.content_type,
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.delete("/expense-receipts/{receipt_id}", status_code=204)
def delete_receipt(receipt_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> None:
    r = _run(lambda: svc.get_receipt(session, member.organization_id, receipt_id))
    _run(lambda: svc.delete_receipt(session, r, member.user_id))
