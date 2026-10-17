"""자산대장(옵션·집기·공용 설비)과 수리 이력.

규칙
- 모르는 값은 비워 둔다 (CLAUDE.md 규칙 7). 수명·교체 시기를 추정하지 않는다 — 경과 기간은 적힌 제조연월(없으면
  설치일)로 센 사실값, 교체 예정월은 관리자가 정한 값만 쓴다.
- 옵션(임대인 소유)과 임차인 소유를 구분한다 — 퇴실 때 두고 가는지·수리 책임이 누구인지가 여기서 갈린다.
- 수리 비용은 기록용. 결산(NOI)에는 은행 출금을 '수리비'로 분류한 것만 들어간다 (이중 계산 방지).
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Fixture, MaintenanceTicket, Property, RoutineTask, Unit

CATEGORIES = {
    "aircon": "에어컨", "washer": "세탁기", "fridge": "냉장고", "cooktop": "인덕션·가스레인지",
    "microwave": "전자레인지", "boiler": "보일러", "water_heater": "온수기", "tv": "TV",
    "bed": "침대", "desk": "책상·의자", "wardrobe": "옷장·수납장", "curtain": "커튼·블라인드",
    "doorlock": "도어락", "extinguisher": "소화기", "detector": "화재감지기", "cctv": "CCTV", "other": "기타",
}
OWNERS = {"landlord": "옵션(임대인)", "tenant": "임차인 소유"}
PAYERS = {"landlord": "임대인", "tenant": "임차인", "undecided": "미정"}
YM_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PLAN_MONTHS = 12


class FixtureError(Exception):
    pass


def _ym(value: str | None, label: str) -> str | None:
    value = (value or "").strip() or None
    if value is not None and not YM_RE.match(value):
        raise FixtureError(f"{label}은 YYYY-MM 형식으로 적으세요")
    return value


def _text(value: str | None) -> str | None:
    return (value or "").strip() or None


def _audit(session: Session, user_id, action: str, entity: str, entity_id, detail: dict | None = None) -> None:
    session.add(AuditLog(user_id=user_id, action=action, entity_type=entity, entity_id=str(entity_id), detail=detail))


# ── 위치 (건물·호실) ──────────────────────────────────────────

def _properties(session: Session, organization_id: uuid.UUID) -> list[Property]:
    return list(session.scalars(select(Property).where(Property.organization_id == organization_id)
                                .order_by(Property.created_at)))


def _units(session: Session, organization_id: uuid.UUID) -> dict[uuid.UUID, Unit]:
    return {u.id: u for u in session.scalars(
        select(Unit).join(Property, Unit.property_id == Property.id).where(Property.organization_id == organization_id))}


def _place(session: Session, organization_id: uuid.UUID, unit_id: uuid.UUID | None,
           property_id: uuid.UUID | None) -> tuple[uuid.UUID, uuid.UUID | None]:
    """(property_id, unit_id). 호실이 있으면 그 건물, 없으면 건물 공용 — 건물이 하나면 그 건물."""
    if unit_id is not None:
        unit = _units(session, organization_id).get(unit_id)
        if unit is None:
            raise LookupError("호실을 찾을 수 없습니다")
        return unit.property_id, unit.id
    props = _properties(session, organization_id)
    if property_id is not None:
        if property_id not in {p.id for p in props}:
            raise LookupError("건물을 찾을 수 없습니다")
        return property_id, None
    if len(props) != 1:
        raise FixtureError("건물 공용 품목은 건물을 골라 주세요" if props else "건물을 먼저 등록하세요")
    return props[0].id, None


# ── 자산대장 ─────────────────────────────────────────────────

@dataclass
class FixtureFields:
    category: str
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    manufactured: str | None = None
    installed_on: date | None = None
    price: int | None = None
    warranty_until: date | None = None
    owner: str = "landlord"
    replace_by: str | None = None
    note: str | None = None

    def clean(self) -> dict:
        if self.category not in CATEGORIES:
            raise FixtureError("품목 종류를 고르세요")
        if self.owner not in OWNERS:
            raise FixtureError("소유 구분은 옵션(임대인) 또는 임차인 소유입니다")
        if self.price is not None and self.price < 0:
            raise FixtureError("구입가는 0원 이상입니다")
        return {"category": self.category, "name": _text(self.name) or CATEGORIES[self.category],
                "brand": _text(self.brand), "model": _text(self.model),
                "manufactured": _ym(self.manufactured, "제조연월"), "installed_on": self.installed_on,
                "price": self.price, "warranty_until": self.warranty_until, "owner": self.owner,
                "replace_by": _ym(self.replace_by, "교체 예정월"), "note": _text(self.note)}


def create_fixtures(session: Session, organization_id: uuid.UUID, user_id, fields: FixtureFields,
                    unit_ids: list[uuid.UUID], property_id: uuid.UUID | None = None) -> list[Fixture]:
    """같은 품목을 여러 호실에 한 번에. unit_ids 가 비면 건물 공용 1개."""
    values = fields.clean()
    places = [_place(session, organization_id, u, property_id) for u in dict.fromkeys(unit_ids)] \
        or [_place(session, organization_id, None, property_id)]
    rows = [Fixture(property_id=p, unit_id=u, **values) for p, u in places]
    session.add_all(rows)
    session.flush()
    for f in rows:
        _audit(session, user_id, "fixture.create", "fixture", f.id, {"category": f.category})
    session.commit()
    return rows


def get_fixture(session: Session, organization_id: uuid.UUID, fixture_id: uuid.UUID) -> Fixture:
    f = session.scalar(select(Fixture).join(Property, Fixture.property_id == Property.id)
                       .where(Fixture.id == fixture_id, Property.organization_id == organization_id))
    if f is None:
        raise LookupError("품목을 찾을 수 없습니다")
    return f


def update_fixture(session: Session, f: Fixture, user_id, fields: FixtureFields,
                   unit_id: uuid.UUID | None, organization_id: uuid.UUID) -> Fixture:
    values = fields.clean()
    f.property_id, f.unit_id = _place(session, organization_id, unit_id, f.property_id if unit_id is None else None)
    for k, v in values.items():
        setattr(f, k, v)
    _audit(session, user_id, "fixture.update", "fixture", f.id)
    session.commit()
    return f


def remove_fixture(session: Session, f: Fixture, user_id, removed_on: date, reason: str | None) -> Fixture:
    """철거·폐기·교체로 빼기. 기록은 남는다 (수리 이력과 함께)."""
    if f.status == "removed":
        raise FixtureError("이미 뺀 품목입니다")
    f.status, f.removed_on, f.removed_reason = "removed", removed_on, _text(reason)
    _audit(session, user_id, "fixture.remove", "fixture", f.id, {"reason": f.removed_reason})
    session.commit()
    return f


def delete_fixture(session: Session, f: Fixture, user_id) -> None:
    """잘못 넣은 품목 지우기. 수리 기록이 있으면 지우지 않고 '빼기'로 처리하게 한다."""
    if session.scalar(select(MaintenanceTicket.id).where(MaintenanceTicket.fixture_id == f.id).limit(1)):
        raise FixtureError("수리 기록이 있는 품목은 지울 수 없습니다. '빼기'로 처리하세요")
    if session.scalar(select(RoutineTask.id).where(RoutineTask.fixture_id == f.id).limit(1)):
        raise FixtureError("정기 점검이 걸린 품목은 지울 수 없습니다. '빼기'로 처리하세요")
    _audit(session, user_id, "fixture.delete", "fixture", f.id, {"category": f.category})
    session.delete(f)
    session.commit()


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)


def age_months(f: Fixture, as_of: date) -> int | None:
    """제조연월(없으면 설치일)부터 지난 개월 수. 둘 다 없으면 None — 추정하지 않는다."""
    if f.manufactured:
        y, m = map(int, f.manufactured.split("-"))
        return max(0, (as_of.year - y) * 12 + as_of.month - m)
    if f.installed_on:
        return max(0, _months_between(f.installed_on, as_of))
    return None


def _repair_stats(session: Session, fixture_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    stats: dict[uuid.UUID, dict] = defaultdict(lambda: {"count": 0, "cost": 0, "cost_unknown": 0})
    if not fixture_ids:
        return stats
    for t in session.scalars(select(MaintenanceTicket).where(MaintenanceTicket.fixture_id.in_(fixture_ids))):
        s = stats[t.fixture_id]
        s["count"] += 1
        if t.cost is None:
            s["cost_unknown"] += 1
        else:
            s["cost"] += t.cost
    return stats


def fixture_out(f: Fixture, unit_no: str | None, as_of: date, stats: dict) -> dict:
    s = stats.get(f.id, {"count": 0, "cost": 0, "cost_unknown": 0})
    return {
        "id": str(f.id), "property_id": str(f.property_id), "unit_id": str(f.unit_id) if f.unit_id else None,
        "unit_no": unit_no, "category": f.category, "category_label": CATEGORIES.get(f.category, f.category),
        "name": f.name, "brand": f.brand, "model": f.model, "manufactured": f.manufactured,
        "installed_on": f.installed_on, "price": f.price, "warranty_until": f.warranty_until,
        "warranty_active": (f.warranty_until >= as_of) if f.warranty_until else None,
        "owner": f.owner, "replace_by": f.replace_by, "status": f.status, "removed_on": f.removed_on,
        "removed_reason": f.removed_reason, "note": f.note, "age_months": age_months(f, as_of),
        "repair_count": s["count"],
        # 비용을 모르는 수리가 섞여 있으면 합계를 내지 않는다 (모르는 것을 0으로 치지 않음)
        "repair_cost": s["cost"] if s["count"] and not s["cost_unknown"] else None,
    }


def list_fixtures(session: Session, organization_id: uuid.UUID, as_of: date, *,
                  unit_id: uuid.UUID | None = None, common_only: bool = False,
                  include_removed: bool = False) -> list[dict]:
    q = (select(Fixture, Unit.unit_no).join(Property, Fixture.property_id == Property.id)
         .outerjoin(Unit, Fixture.unit_id == Unit.id).where(Property.organization_id == organization_id))
    if unit_id is not None:
        q = q.where(Fixture.unit_id == unit_id)
    elif common_only:
        q = q.where(Fixture.unit_id.is_(None))
    if not include_removed:
        q = q.where(Fixture.status == "in_use")
    rows = session.execute(q).all()
    stats = _repair_stats(session, [f.id for f, _ in rows])
    order = list(CATEGORIES)
    rows.sort(key=lambda r: (r[1] is None, r[1] or "", order.index(r[0].category) if r[0].category in order else 99,
                             r[0].created_at))
    return [fixture_out(f, unit_no, as_of, stats) for f, unit_no in rows]


def _add_months(ym: str, n: int) -> str:
    y, m = map(int, ym.split("-"))
    y, m = divmod(y * 12 + m - 1 + n, 12)
    return f"{y:04d}-{m + 1:02d}"


def replacement_plan(session: Session, organization_id: uuid.UUID, as_of: date, months: int = PLAN_MONTHS) -> dict:
    """관리자가 적은 교체 예정월 기준으로, 앞으로 months 개월 동안 바꿀 품목을 달·종류별로 묶는다.
    같은 달 같은 종류가 여럿이면 함께 사는(공동구매) 근거가 된다. 예정월이 지난 것도 따로 보인다."""
    start = as_of.strftime("%Y-%m")
    end = _add_months(start, months - 1)
    items = [f for f in list_fixtures(session, organization_id, as_of) if f["owner"] == "landlord"]
    planned = [f for f in items if f["replace_by"] and f["replace_by"] <= end]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for f in planned:
        month = f["replace_by"] if f["replace_by"] >= start else "overdue"
        groups[(month, f["category"])].append(f)
    out = [{"month": month, "category": cat, "category_label": CATEGORIES.get(cat, cat), "count": len(fs),
            "units": [f["unit_no"] or "공용" for f in fs],
            "models": sorted({" ".join(x for x in (f["brand"], f["model"]) if x) for f in fs} - {""})}
           for (month, cat), fs in groups.items()]
    out.sort(key=lambda g: ("0" if g["month"] == "overdue" else g["month"], g["category"]))
    return {"from": start, "to": end, "groups": out,
            "unplanned": sum(1 for f in items if not f["replace_by"]),
            "warranty_ending": [f for f in items if f["warranty_until"] and as_of <= f["warranty_until"]
                                and (f["warranty_until"] - as_of).days <= 60]}


def export_csv(session: Session, organization_id: uuid.UUID, as_of: date) -> str:
    """엑셀에서 바로 열리게 UTF-8 BOM. 빈 값은 빈 칸."""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(["위치", "종류", "이름", "제조사", "모델", "제조연월", "설치일", "구입가", "보증 만료", "소유",
                "교체 예정월", "상태", "수리 건수", "수리비 합계", "메모"])
    for f in list_fixtures(session, organization_id, as_of, include_removed=True):
        w.writerow([f["unit_no"] or "공용", f["category_label"], f["name"], f["brand"] or "", f["model"] or "",
                    f["manufactured"] or "", f["installed_on"] or "", f["price"] if f["price"] is not None else "",
                    f["warranty_until"] or "", OWNERS[f["owner"]], f["replace_by"] or "",
                    "사용 중" if f["status"] == "in_use" else f"뺌 {f['removed_on'] or ''}".strip(),
                    f["repair_count"], f["repair_cost"] if f["repair_cost"] is not None else "", f["note"] or ""])
    return buf.getvalue()


# ── 수리 이력 ─────────────────────────────────────────────────

@dataclass
class RepairFields:
    description: str
    reported_on: date
    unit_id: uuid.UUID | None = None
    fixture_id: uuid.UUID | None = None
    property_id: uuid.UUID | None = None
    vendor: str | None = None
    cost: int | None = None
    payer: str = "undecided"
    completed_on: date | None = None
    note: str | None = None


def _repair_values(session: Session, organization_id: uuid.UUID, r: RepairFields) -> dict:
    if not r.description.strip():
        raise FixtureError("무엇을 고치는지 적어 주세요")
    if r.payer not in PAYERS:
        raise FixtureError("비용 부담은 임대인·임차인·미정 중 하나입니다")
    if r.cost is not None and r.cost < 0:
        raise FixtureError("비용은 0원 이상입니다")
    if r.completed_on and r.completed_on < r.reported_on:
        raise FixtureError("완료일이 접수일보다 앞설 수 없습니다")
    unit_id = r.unit_id
    if r.fixture_id is not None:  # 품목을 고르면 위치는 그 품목의 위치
        f = get_fixture(session, organization_id, r.fixture_id)
        prop, unit_id = f.property_id, f.unit_id
    else:
        prop, unit_id = _place(session, organization_id, unit_id, r.property_id)
    return {"property_id": prop, "unit_id": unit_id, "fixture_id": r.fixture_id,
            "description": r.description.strip(), "reported_on": r.reported_on, "vendor": _text(r.vendor),
            "cost": r.cost, "payer": r.payer, "completed_on": r.completed_on, "note": _text(r.note),
            "status": "done" if r.completed_on else "open"}


def create_repair(session: Session, organization_id: uuid.UUID, user_id, r: RepairFields) -> MaintenanceTicket:
    t = MaintenanceTicket(**_repair_values(session, organization_id, r))
    session.add(t)
    session.flush()
    _audit(session, user_id, "repair.create", "maintenance_ticket", t.id)
    session.commit()
    return t


def get_repair(session: Session, organization_id: uuid.UUID, repair_id: uuid.UUID) -> MaintenanceTicket:
    t = session.scalar(select(MaintenanceTicket).join(Property, MaintenanceTicket.property_id == Property.id)
                       .where(MaintenanceTicket.id == repair_id, Property.organization_id == organization_id))
    if t is None:
        raise LookupError("수리 기록을 찾을 수 없습니다")
    return t


def update_repair(session: Session, organization_id: uuid.UUID, t: MaintenanceTicket, user_id,
                  r: RepairFields) -> MaintenanceTicket:
    for k, v in _repair_values(session, organization_id, r).items():
        setattr(t, k, v)
    _audit(session, user_id, "repair.update", "maintenance_ticket", t.id, {"status": t.status})
    session.commit()
    return t


def delete_repair(session: Session, t: MaintenanceTicket, user_id) -> None:
    _audit(session, user_id, "repair.delete", "maintenance_ticket", t.id)
    session.delete(t)
    session.commit()


def list_repairs(session: Session, organization_id: uuid.UUID, *, status: str | None = None,
                 fixture_id: uuid.UUID | None = None) -> list[dict]:
    q = (select(MaintenanceTicket, Unit.unit_no, Fixture.name, Fixture.category)
         .join(Property, MaintenanceTicket.property_id == Property.id)
         .outerjoin(Unit, MaintenanceTicket.unit_id == Unit.id)
         .outerjoin(Fixture, MaintenanceTicket.fixture_id == Fixture.id)
         .where(Property.organization_id == organization_id))
    if status:
        q = q.where(MaintenanceTicket.status == status)
    if fixture_id:
        q = q.where(MaintenanceTicket.fixture_id == fixture_id)
    q = q.order_by(MaintenanceTicket.status.desc(), MaintenanceTicket.reported_on.desc(),
                   MaintenanceTicket.created_at.desc())  # 진행 중(open) 먼저
    return [{"id": str(t.id), "unit_id": str(t.unit_id) if t.unit_id else None, "unit_no": unit_no,
             "fixture_id": str(t.fixture_id) if t.fixture_id else None, "fixture_name": fname,
             "fixture_category": fcat, "description": t.description, "reported_on": t.reported_on,
             "status": t.status, "completed_on": t.completed_on, "vendor": t.vendor, "cost": t.cost,
             "payer": t.payer, "note": t.note}
            for t, unit_no, fname, fcat in session.execute(q).all()]


def open_repair_count(session: Session, organization_id: uuid.UUID) -> int:
    return len(session.scalars(select(MaintenanceTicket.id).join(Property, MaintenanceTicket.property_id == Property.id)
                               .where(Property.organization_id == organization_id,
                                      MaintenanceTicket.status == "open")).all())
