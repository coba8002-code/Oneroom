"""자산대장(옵션·집기·공용 설비)과 수리 이력."""
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.services import fixtures as svc

router = APIRouter(prefix="/api/v1", tags=["assets"])
KST = ZoneInfo("Asia/Seoul")


def _today() -> date:
    return datetime.now(KST).date()


def _run(fn):
    try:
        return fn()
    except svc.FixtureError as e:
        raise HTTPException(409, str(e)) from e
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


class FixtureIn(BaseModel):
    category: str
    name: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    manufactured: str | None = Field(default=None, max_length=7)
    installed_on: date | None = None
    price: int | None = None
    warranty_until: date | None = None
    owner: str = "landlord"
    replace_by: str | None = Field(default=None, max_length=7)
    note: str | None = Field(default=None, max_length=1000)

    def fields(self) -> svc.FixtureFields:
        return svc.FixtureFields(**self.model_dump(include=set(FixtureIn.model_fields)))


class FixtureCreateIn(FixtureIn):
    unit_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)  # 비우면 건물 공용
    property_id: uuid.UUID | None = None


class FixtureUpdateIn(FixtureIn):
    unit_id: uuid.UUID | None = None  # None 이면 건물 공용


class RemoveIn(BaseModel):
    removed_on: date | None = None
    reason: str | None = Field(default=None, max_length=500)


class RepairIn(BaseModel):
    description: str = Field(max_length=1000)
    reported_on: date | None = None
    unit_id: uuid.UUID | None = None
    fixture_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    vendor: str | None = Field(default=None, max_length=100)
    cost: int | None = None
    payer: str = "undecided"
    completed_on: date | None = None
    note: str | None = Field(default=None, max_length=1000)

    def fields(self) -> svc.RepairFields:
        return svc.RepairFields(**{**self.model_dump(), "reported_on": self.reported_on or _today()})


@router.get("/fixture-codes")
def codes() -> dict:
    return {"categories": svc.CATEGORIES, "owners": svc.OWNERS, "payers": svc.PAYERS}


@router.get("/fixtures")
def list_fixtures(unit_id: uuid.UUID | None = None, common: bool = False, include_removed: bool = False,
                  member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> list[dict]:
    return svc.list_fixtures(session, member.organization_id, _today(), unit_id=unit_id, common_only=common,
                             include_removed=include_removed)


@router.post("/fixtures", status_code=201)
def create_fixtures(body: FixtureCreateIn, member: Member = Depends(org_guard),
                    session: Session = Depends(get_session)) -> dict:
    rows = _run(lambda: svc.create_fixtures(session, member.organization_id, member.user_id, body.fields(),
                                            body.unit_ids, body.property_id))
    return {"created": len(rows), "ids": [str(f.id) for f in rows]}


@router.get("/fixtures/replacement-plan")
def replacement_plan(months: int = 12, member: Member = Depends(org_guard),
                     session: Session = Depends(get_session)) -> dict:
    if not 1 <= months <= 36:
        raise HTTPException(422, "기간은 1~36개월")
    return svc.replacement_plan(session, member.organization_id, _today(), months)


@router.get("/fixtures/export.csv")
def export_csv(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> Response:
    body = svc.export_csv(session, member.organization_id, _today())
    name = f"roomax-assets-{_today():%Y%m%d}.csv"
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.put("/fixtures/{fixture_id}")
def update_fixture(fixture_id: uuid.UUID, body: FixtureUpdateIn, member: Member = Depends(org_guard),
                   session: Session = Depends(get_session)) -> dict:
    f = _run(lambda: svc.get_fixture(session, member.organization_id, fixture_id))
    _run(lambda: svc.update_fixture(session, f, member.user_id, body.fields(), body.unit_id, member.organization_id))
    return {"id": str(f.id)}


@router.post("/fixtures/{fixture_id}/remove")
def remove_fixture(fixture_id: uuid.UUID, body: RemoveIn, member: Member = Depends(org_guard),
                   session: Session = Depends(get_session)) -> dict:
    f = _run(lambda: svc.get_fixture(session, member.organization_id, fixture_id))
    _run(lambda: svc.remove_fixture(session, f, member.user_id, body.removed_on or _today(), body.reason))
    return {"id": str(f.id), "status": f.status}


@router.delete("/fixtures/{fixture_id}", status_code=204)
def delete_fixture(fixture_id: uuid.UUID, member: Member = Depends(org_guard),
                   session: Session = Depends(get_session)) -> None:
    f = _run(lambda: svc.get_fixture(session, member.organization_id, fixture_id))
    _run(lambda: svc.delete_fixture(session, f, member.user_id))


@router.get("/repairs")
def list_repairs(status: str | None = None, fixture_id: uuid.UUID | None = None,
                 member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> list[dict]:
    return svc.list_repairs(session, member.organization_id, status=status, fixture_id=fixture_id)


@router.post("/repairs", status_code=201)
def create_repair(body: RepairIn, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    t = _run(lambda: svc.create_repair(session, member.organization_id, member.user_id, body.fields()))
    return {"id": str(t.id), "status": t.status}


@router.put("/repairs/{repair_id}")
def update_repair(repair_id: uuid.UUID, body: RepairIn, member: Member = Depends(org_guard),
                  session: Session = Depends(get_session)) -> dict:
    t = _run(lambda: svc.get_repair(session, member.organization_id, repair_id))
    _run(lambda: svc.update_repair(session, member.organization_id, t, member.user_id, body.fields()))
    return {"id": str(t.id), "status": t.status}


@router.delete("/repairs/{repair_id}", status_code=204)
def delete_repair(repair_id: uuid.UUID, member: Member = Depends(org_guard),
                  session: Session = Depends(get_session)) -> None:
    t = _run(lambda: svc.get_repair(session, member.organization_id, repair_id))
    _run(lambda: svc.delete_repair(session, t, member.user_id))
