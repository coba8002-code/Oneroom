"""정기 점검·소모품 일정."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.routers.assets import _run, _today
from app.services import routines as svc

router = APIRouter(prefix="/api/v1", tags=["routines"])


class TaskIn(BaseModel):
    title: str = Field(max_length=100)
    category: str
    interval_months: int | None = None
    next_due_on: date | None = None
    vendor: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=1000)

    def fields(self) -> svc.TaskFields:
        return svc.TaskFields(**self.model_dump(include=set(TaskIn.model_fields)))


class TaskCreateIn(TaskIn):
    unit_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)  # 비우면 건물 공용
    property_id: uuid.UUID | None = None
    fixture_id: uuid.UUID | None = None


class TaskUpdateIn(TaskIn):
    unit_id: uuid.UUID | None = None
    fixture_id: uuid.UUID | None = None


class StatusIn(BaseModel):
    status: str


class DoneIn(BaseModel):
    done_on: date | None = None
    cost: int | None = None
    vendor: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=1000)


@router.get("/routine-codes")
def codes() -> dict:
    return {"categories": svc.CATEGORIES, "suggestions": [{"title": t, "category": c} for t, c in svc.SUGGESTIONS],
            "soon_days": svc.SOON_DAYS}


@router.get("/routine-tasks")
def list_tasks(include_stopped: bool = False, member: Member = Depends(org_guard),
               session: Session = Depends(get_session)) -> list[dict]:
    return svc.list_tasks(session, member.organization_id, _today(), include_stopped)


@router.post("/routine-tasks", status_code=201)
def create_tasks(body: TaskCreateIn, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    rows = _run(lambda: svc.create_tasks(session, member.organization_id, member.user_id, body.fields(),
                                         body.unit_ids, body.property_id, body.fixture_id))
    return {"created": len(rows), "ids": [str(t.id) for t in rows]}


@router.put("/routine-tasks/{task_id}")
def update_task(task_id: uuid.UUID, body: TaskUpdateIn, member: Member = Depends(org_guard),
                session: Session = Depends(get_session)) -> dict:
    t = _run(lambda: svc.get_task(session, member.organization_id, task_id))
    _run(lambda: svc.update_task(session, member.organization_id, t, member.user_id, body.fields(),
                                 body.unit_id, body.fixture_id))
    return {"id": str(t.id)}


@router.post("/routine-tasks/{task_id}/status")
def set_status(task_id: uuid.UUID, body: StatusIn, member: Member = Depends(org_guard),
               session: Session = Depends(get_session)) -> dict:
    t = _run(lambda: svc.get_task(session, member.organization_id, task_id))
    _run(lambda: svc.set_status(session, t, member.user_id, body.status))
    return {"id": str(t.id), "status": t.status}


@router.delete("/routine-tasks/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> None:
    t = _run(lambda: svc.get_task(session, member.organization_id, task_id))
    _run(lambda: svc.delete_task(session, t, member.user_id))


@router.post("/routine-tasks/{task_id}/done", status_code=201)
def done(task_id: uuid.UUID, body: DoneIn, member: Member = Depends(org_guard),
         session: Session = Depends(get_session)) -> dict:
    t = _run(lambda: svc.get_task(session, member.organization_id, task_id))
    today = _today()
    log = _run(lambda: svc.complete(session, t, member.user_id, body.done_on or today, today,
                                    cost=body.cost, vendor=body.vendor, note=body.note))
    return {"id": str(log.id), "next_due_on": t.next_due_on}


@router.get("/routine-tasks/{task_id}/logs")
def logs(task_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> list[dict]:
    return _run(lambda: svc.logs(session, member.organization_id, task_id))


@router.delete("/routine-logs/{log_id}")
def delete_log(log_id: uuid.UUID, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    t = _run(lambda: svc.delete_log(session, member.organization_id, log_id, member.user_id))
    return {"task_id": str(t.id), "next_due_on": t.next_due_on}
