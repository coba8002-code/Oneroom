"""입주·퇴실 점검과 퇴실 정산."""
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.services import move_out as svc, storage
from app.services.contracts import UploadError

router = APIRouter(prefix="/api/v1", tags=["move-out"])
KST = ZoneInfo("Asia/Seoul")


def _today() -> date:
    return datetime.now(KST).date()


def _run(fn):
    try:
        return fn()
    except UploadError as e:
        raise HTTPException(e.status, str(e)) from e
    except svc.MoveOutError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


class InspectionIn(BaseModel):
    kind: str
    inspected_on: date | None = None


class InspectionUpdateIn(BaseModel):
    inspected_on: date
    note: str | None = Field(default=None, max_length=2000)


class ConfirmIn(BaseModel):
    confirmed_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ItemIn(BaseModel):
    area: str = Field(max_length=50)


class ItemUpdateIn(BaseModel):
    condition: str | None = None
    reading: str | None = Field(default=None, max_length=30)
    note: str | None = Field(default=None, max_length=1000)


class DeductionIn(BaseModel):
    category: str
    label: str = Field(max_length=100)
    amount: int
    disputed: bool = False
    inspection_item_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)


class SettlementConfirmIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


@router.get("/move-out/codes")
def codes() -> dict:
    return {"kinds": svc.KINDS, "conditions": svc.CONDITIONS, "deduction_categories": svc.DEDUCTION_CATEGORIES}


@router.get("/move-out/leases")
def leases(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> list[dict]:
    return svc.leases_for_move(session, member.organization_id)


@router.get("/leases/{lease_id}/inspections")
def overview(lease_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.overview(session, member.organization_id, lease_id))


@router.post("/leases/{lease_id}/inspections", status_code=201)
def create_inspection(lease_id: uuid.UUID, body: InspectionIn, member: Member = Depends(org_guard),
                      session: Session = Depends(get_session)) -> dict:
    insp = _run(lambda: svc.create_inspection(session, member.organization_id, member.user_id, lease_id, body.kind,
                                              body.inspected_on or _today()))
    return {"id": str(insp.id)}


def _insp(session, member, inspection_id):
    return _run(lambda: svc.get_inspection(session, member.organization_id, inspection_id))


@router.put("/inspections/{inspection_id}")
def update_inspection(inspection_id: uuid.UUID, body: InspectionUpdateIn, member: Member = Depends(org_guard),
                      session: Session = Depends(get_session)) -> dict:
    insp = _insp(session, member, inspection_id)
    _run(lambda: svc.update_inspection(session, insp, member.user_id, inspected_on=body.inspected_on, note=body.note))
    return {"id": str(insp.id)}


@router.post("/inspections/{inspection_id}/confirm")
def confirm(inspection_id: uuid.UUID, body: ConfirmIn, member: Member = Depends(org_guard),
            session: Session = Depends(get_session)) -> dict:
    insp = _insp(session, member, inspection_id)
    _run(lambda: svc.confirm_inspection(session, insp, member.user_id, body.confirmed_on or _today(), body.note))
    return {"id": str(insp.id), "tenant_confirmed_on": insp.tenant_confirmed_on}


@router.post("/inspections/{inspection_id}/unconfirm")
def unconfirm(inspection_id: uuid.UUID, body: ReasonIn, member: Member = Depends(org_guard),
              session: Session = Depends(get_session)) -> dict:
    insp = _insp(session, member, inspection_id)
    _run(lambda: svc.unconfirm_inspection(session, insp, member.user_id, body.reason))
    return {"id": str(insp.id)}


@router.delete("/inspections/{inspection_id}", status_code=204)
def delete_inspection(inspection_id: uuid.UUID, member: Member = Depends(org_guard),
                      session: Session = Depends(get_session)) -> None:
    insp = _insp(session, member, inspection_id)
    _run(lambda: svc.delete_inspection(session, insp, member.user_id))


@router.post("/inspections/{inspection_id}/items", status_code=201)
def add_item(inspection_id: uuid.UUID, body: ItemIn, member: Member = Depends(org_guard),
             session: Session = Depends(get_session)) -> dict:
    insp = _insp(session, member, inspection_id)
    item = _run(lambda: svc.add_item(session, insp, member.user_id, body.area))
    return {"id": str(item.id)}


@router.put("/inspection-items/{item_id}")
def update_item(item_id: uuid.UUID, body: ItemUpdateIn, member: Member = Depends(org_guard),
                session: Session = Depends(get_session)) -> dict:
    item, insp = _run(lambda: svc.get_item(session, member.organization_id, item_id))
    _run(lambda: svc.update_item(session, item, insp, condition=body.condition, reading=body.reading, note=body.note))
    return {"id": str(item.id)}


@router.delete("/inspection-items/{item_id}", status_code=204)
def delete_item(item_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> None:
    item, insp = _run(lambda: svc.get_item(session, member.organization_id, item_id))
    _run(lambda: svc.delete_item(session, item, insp, member.user_id))


@router.post("/inspection-items/{item_id}/photos", status_code=201)
async def add_photo(item_id: uuid.UUID, file: UploadFile = File(...), member: Member = Depends(org_guard),
                    session: Session = Depends(get_session)) -> dict:
    raw = await file.read(svc.MAX_PHOTO_BYTES + 1)
    item, insp = _run(lambda: svc.get_item(session, member.organization_id, item_id))
    photo = _run(lambda: svc.add_photo(session, item, insp, member.user_id, raw))
    return {"id": str(photo.id), "uploaded_at": photo.created_at}


@router.get("/inspection-photos/{photo_id}")
def get_photo(photo_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> Response:
    photo, _ = _run(lambda: svc.get_photo(session, member.organization_id, photo_id))
    return Response(storage.load(photo.file_path), media_type=photo.content_type,
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.delete("/inspection-photos/{photo_id}", status_code=204)
def delete_photo(photo_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> None:
    photo, insp = _run(lambda: svc.get_photo(session, member.organization_id, photo_id))
    _run(lambda: svc.delete_photo(session, photo, insp, member.user_id))


@router.get("/leases/{lease_id}/settlement")
def settlement(lease_id: uuid.UUID, as_of: date | None = None, member: Member = Depends(org_guard),
               session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.compute(session, member.organization_id, lease_id, as_of or _today()))


@router.post("/leases/{lease_id}/settlement/deductions", status_code=201)
def add_deduction(lease_id: uuid.UUID, body: DeductionIn, member: Member = Depends(org_guard),
                  session: Session = Depends(get_session)) -> dict:
    d = _run(lambda: svc.add_deduction(session, member.organization_id, member.user_id, lease_id, **body.model_dump()))
    return {"id": str(d.id)}


@router.put("/settlement-deductions/{deduction_id}")
def update_deduction(deduction_id: uuid.UUID, body: DeductionIn, member: Member = Depends(org_guard),
                     session: Session = Depends(get_session)) -> dict:
    d, s = _run(lambda: svc.get_deduction(session, member.organization_id, deduction_id))
    _run(lambda: svc.update_deduction(session, d, s, member.user_id, **body.model_dump()))
    return {"id": str(d.id)}


@router.delete("/settlement-deductions/{deduction_id}", status_code=204)
def delete_deduction(deduction_id: uuid.UUID, member: Member = Depends(org_guard),
                     session: Session = Depends(get_session)) -> None:
    d, s = _run(lambda: svc.get_deduction(session, member.organization_id, deduction_id))
    _run(lambda: svc.delete_deduction(session, d, s, member.user_id))


@router.post("/leases/{lease_id}/settlement/confirm")
def confirm_settlement(lease_id: uuid.UUID, body: SettlementConfirmIn, as_of: date | None = None,
                       member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return _run(lambda: svc.confirm_settlement(session, member.organization_id, member.user_id, lease_id,
                                               as_of or _today(), body.note))


@router.post("/leases/{lease_id}/settlement/reopen")
def reopen_settlement(lease_id: uuid.UUID, body: ReasonIn, member: Member = Depends(org_guard),
                      session: Session = Depends(get_session)) -> dict:
    _run(lambda: svc.reopen_settlement(session, member.organization_id, member.user_id, lease_id, body.reason))
    return {"status": "draft"}
