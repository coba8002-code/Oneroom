"""정기 점검·소모품 일정 — 소방시설·청소·설비 점검·보험 갱신·소모품 교체.

규칙
- 주기와 다음 예정일은 관리자가 정한 값만 쓴다 (CLAUDE.md 규칙 7). 법정 주기도 시스템이 정하지 않는다 —
  항목 예시는 이름만 제안하고, 주기는 관할 기관·계약서로 확인해 적게 한다.
- 다음 예정일을 모르면 비워 두고 '날짜 없음'으로 보여 준다 (지난 기록·평균으로 채우지 않음).
- 한 번 했다고 기록하면: 주기가 있으면 다음 예정일 = 한 날 + 주기(달력, 없는 날은 말일), 없으면 끝(비움).
  기록을 지우면 예정일을 그 기록 전 값으로 되돌린다 (가장 최근 기록만 지울 수 있음).
- 비용은 기록용. 결산(NOI)에는 은행 출금 분류만 들어간다 (이중 계산 방지).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Fixture, Property, RoutineLog, RoutineTask, Unit
from app.services import fixtures
from app.services.fixtures import _audit, _place, _text
from app.services.lease_renewal import months_before

CATEGORIES = {"safety": "소방·안전", "cleaning": "청소·위생", "equipment": "설비 점검",
              "consumable": "소모품 교체", "insurance": "보험·계약", "other": "기타"}
# 이름만 제안 — 주기는 비워 두고 관리자가 정한다
SUGGESTIONS = [
    ("소화기 점검 (압력·위치)", "safety"), ("단독경보형 감지기 작동·건전지", "safety"), ("공용 비상등·유도등 점검", "safety"),
    ("정화조 청소", "cleaning"), ("저수조·물탱크 청소", "cleaning"), ("공용 계단·복도 청소", "cleaning"),
    ("방역·소독", "cleaning"), ("에어컨 필터·실내기 청소", "cleaning"),
    ("보일러 점검", "equipment"), ("가스 시설 점검", "equipment"), ("전기 안전 점검", "equipment"),
    ("CCTV 녹화 확인", "equipment"), ("옥상 방수·배수구 확인", "equipment"),
    ("도어락 건전지 교체", "consumable"), ("공용 전등 교체", "consumable"), ("정수기 필터 교체", "consumable"),
    ("화재보험 갱신", "insurance"), ("시설물 배상책임보험 갱신", "insurance"), ("관리·청소 업체 계약 갱신", "insurance"),
]
SOON_DAYS = 14


class RoutineError(fixtures.FixtureError):
    pass


def add_months(d: date, months: int) -> date:
    return months_before(d, -months)


@dataclass
class TaskFields:
    title: str
    category: str
    interval_months: int | None = None
    next_due_on: date | None = None
    vendor: str | None = None
    note: str | None = None

    def clean(self) -> dict:
        title = _text(self.title)
        if not title:
            raise RoutineError("할 일 이름을 적으세요")
        if self.category not in CATEGORIES:
            raise RoutineError("분류를 고르세요")
        if self.interval_months is not None and not 1 <= self.interval_months <= 120:
            raise RoutineError("주기는 1~120개월입니다 (한 번만이면 비워 두세요)")
        return {"title": title, "category": self.category, "interval_months": self.interval_months,
                "next_due_on": self.next_due_on, "vendor": _text(self.vendor), "note": _text(self.note)}


def _fixture_place(session: Session, organization_id: uuid.UUID, fixture_id: uuid.UUID | None) -> Fixture | None:
    return fixtures.get_fixture(session, organization_id, fixture_id) if fixture_id else None


def create_tasks(session: Session, organization_id: uuid.UUID, user_id, fields: TaskFields,
                 unit_ids: list[uuid.UUID], property_id: uuid.UUID | None = None,
                 fixture_id: uuid.UUID | None = None) -> list[RoutineTask]:
    """같은 일을 여러 호실에 한 번에 (예: 호실마다 도어락 건전지). unit_ids 가 비면 건물 공용 1건.
    품목을 고르면 그 품목 자리에 1건."""
    values = fields.clean()
    f = _fixture_place(session, organization_id, fixture_id)
    if f is not None:
        places = [(f.property_id, f.unit_id)]
    else:
        places = [_place(session, organization_id, u, property_id) for u in dict.fromkeys(unit_ids)] \
            or [_place(session, organization_id, None, property_id)]
    rows = [RoutineTask(property_id=p, unit_id=u, fixture_id=f.id if f else None, **values) for p, u in places]
    session.add_all(rows)
    session.flush()
    for t in rows:
        _audit(session, user_id, "routine.create", "routine_task", t.id, {"category": t.category})
    session.commit()
    return rows


def get_task(session: Session, organization_id: uuid.UUID, task_id: uuid.UUID) -> RoutineTask:
    t = session.scalar(select(RoutineTask).join(Property, RoutineTask.property_id == Property.id)
                       .where(RoutineTask.id == task_id, Property.organization_id == organization_id))
    if t is None:
        raise LookupError("할 일을 찾을 수 없습니다")
    return t


def update_task(session: Session, organization_id: uuid.UUID, t: RoutineTask, user_id, fields: TaskFields,
                unit_id: uuid.UUID | None, fixture_id: uuid.UUID | None) -> RoutineTask:
    values = fields.clean()
    f = _fixture_place(session, organization_id, fixture_id)
    if f is not None:
        t.property_id, t.unit_id, t.fixture_id = f.property_id, f.unit_id, f.id
    else:
        t.property_id, t.unit_id = _place(session, organization_id, unit_id, t.property_id if unit_id is None else None)
        t.fixture_id = None
    for k, v in values.items():
        setattr(t, k, v)
    _audit(session, user_id, "routine.update", "routine_task", t.id)
    session.commit()
    return t


def set_status(session: Session, t: RoutineTask, user_id, status: str) -> RoutineTask:
    if status not in ("active", "stopped"):
        raise RoutineError("상태는 진행 또는 멈춤입니다")
    t.status = status
    _audit(session, user_id, "routine.status", "routine_task", t.id, {"status": status})
    session.commit()
    return t


def delete_task(session: Session, t: RoutineTask, user_id) -> None:
    if session.scalar(select(RoutineLog.id).where(RoutineLog.task_id == t.id).limit(1)):
        raise RoutineError("한 기록이 있는 일은 지울 수 없습니다. '멈춤'으로 두세요")
    _audit(session, user_id, "routine.delete", "routine_task", t.id, {"category": t.category})
    session.delete(t)
    session.commit()


def complete(session: Session, t: RoutineTask, user_id, done_on: date, today: date, *, cost: int | None = None,
             vendor: str | None = None, note: str | None = None) -> RoutineLog:
    if done_on > today:
        raise RoutineError("앞으로의 날짜로는 기록할 수 없습니다")
    if cost is not None and cost < 0:
        raise RoutineError("비용은 0원 이상입니다")
    last = _last_log(session, t.id)
    if last is not None and done_on < last.done_on:
        raise RoutineError(f"마지막 기록({last.done_on:%Y-%m-%d})보다 앞선 날짜입니다")
    log = RoutineLog(task_id=t.id, done_on=done_on, cost=cost, vendor=_text(vendor) or t.vendor, note=_text(note),
                     prev_next_due_on=t.next_due_on)
    t.next_due_on = add_months(done_on, t.interval_months) if t.interval_months else None
    session.add(log)
    session.flush()
    _audit(session, user_id, "routine.done", "routine_log", log.id, {"task_id": str(t.id), "cost": cost})
    session.commit()
    return log


def _last_log(session: Session, task_id: uuid.UUID) -> RoutineLog | None:
    return session.scalar(select(RoutineLog).where(RoutineLog.task_id == task_id)
                          .order_by(RoutineLog.done_on.desc(), RoutineLog.created_at.desc()).limit(1))


def delete_log(session: Session, organization_id: uuid.UUID, log_id: uuid.UUID, user_id) -> RoutineTask:
    log = session.get(RoutineLog, log_id)
    t = get_task(session, organization_id, log.task_id) if log else None
    if log is None or t is None:
        raise LookupError("기록을 찾을 수 없습니다")
    if _last_log(session, t.id).id != log.id:
        raise RoutineError("가장 최근 기록만 지울 수 있습니다")
    t.next_due_on = log.prev_next_due_on
    _audit(session, user_id, "routine.undo", "routine_log", log.id, {"task_id": str(t.id)})
    session.delete(log)
    session.commit()
    return t


def logs(session: Session, organization_id: uuid.UUID, task_id: uuid.UUID) -> list[dict]:
    get_task(session, organization_id, task_id)
    return [{"id": g.id, "done_on": g.done_on, "cost": g.cost, "vendor": g.vendor, "note": g.note}
            for g in session.scalars(select(RoutineLog).where(RoutineLog.task_id == task_id)
                                     .order_by(RoutineLog.done_on.desc(), RoutineLog.created_at.desc()))]


def state(t: RoutineTask, as_of: date, has_log: bool) -> str:
    if t.status == "stopped":
        return "stopped"
    if t.next_due_on is None:
        return "finished" if (has_log and not t.interval_months) else "no_date"
    if t.next_due_on < as_of:
        return "overdue"
    return "soon" if t.next_due_on <= as_of + timedelta(days=SOON_DAYS) else "ok"


def list_tasks(session: Session, organization_id: uuid.UUID, as_of: date, include_stopped: bool = False) -> list[dict]:
    q = (select(RoutineTask, Unit.label, Fixture.name)
         .join(Property, RoutineTask.property_id == Property.id)
         .outerjoin(Unit, RoutineTask.unit_id == Unit.id)
         .outerjoin(Fixture, RoutineTask.fixture_id == Fixture.id)
         .where(Property.organization_id == organization_id))
    if not include_stopped:
        q = q.where(RoutineTask.status == "active")
    rows = session.execute(q).all()
    ids = [t.id for t, _, _ in rows]
    stats = {tid: (last, n, total, costs) for tid, last, n, total, costs in session.execute(
        select(RoutineLog.task_id, func.max(RoutineLog.done_on), func.count(RoutineLog.id),
               func.sum(RoutineLog.cost), func.count(RoutineLog.cost))
        .where(RoutineLog.task_id.in_(ids)).group_by(RoutineLog.task_id))} if ids else {}
    out = []
    for t, unit_no, fixture_name in rows:
        last, n, total, known = stats.get(t.id, (None, 0, None, 0))
        st = state(t, as_of, n > 0)
        out.append({
            "id": t.id, "title": t.title, "category": t.category, "unit_id": t.unit_id, "unit_no": unit_no,
            "fixture_id": t.fixture_id, "fixture_name": fixture_name, "interval_months": t.interval_months,
            "next_due_on": t.next_due_on, "days_left": (t.next_due_on - as_of).days if t.next_due_on else None,
            "last_done_on": last, "done_count": n, "vendor": t.vendor, "note": t.note, "status": t.status, "state": st,
            # 비용을 모르는 기록이 섞이면 합계를 내지 않는다 (모르는 금액을 0원으로 치지 않음)
            "cost_total": int(total) if n and known == n else None,
        })
    order = {"overdue": 0, "soon": 1, "no_date": 2, "ok": 3, "finished": 4, "stopped": 5}
    out.sort(key=lambda x: (order[x["state"]], x["next_due_on"] or date.max, x["unit_no"] or "", x["title"]))
    return out


def due(session: Session, organization_id: uuid.UUID, as_of: date) -> tuple[list[dict], list[dict]]:
    """(지난 것, SOON_DAYS 안). 홈 알림용."""
    rows = list_tasks(session, organization_id, as_of)
    return [r for r in rows if r["state"] == "overdue"], [r for r in rows if r["state"] == "soon"]
