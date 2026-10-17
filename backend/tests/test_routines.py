"""정기 점검·소모품 일정 — 주기는 관리자가 정한 값만, 모르면 비움, 기록 → 다음 예정일, 되돌리기."""
from datetime import date

import pytest

from app.routers import routines as router_mod
from app.services import routines as svc

TODAY = date(2026, 10, 17)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(router_mod, "_today", lambda: TODAY)


@pytest.fixture
def units(client, onboarded):
    return {u["unit_no"]: u["unit_id"] for u in client.get("/api/v1/units",
                                                          params={"organization_id": onboarded["organization_id"]}).json()}


def _list(client, **params):
    return client.get("/api/v1/routine-tasks", params=params).json()


def _new(client, **body):
    res = client.post("/api/v1/routine-tasks", json={"category": "safety", **body})
    assert res.status_code == 201, res.text
    return res.json()["ids"]


def test_suggestions_have_no_default_interval(client, onboarded):
    codes = client.get("/api/v1/routine-codes").json()
    assert codes["suggestions"] and all(set(s) == {"title", "category"} for s in codes["suggestions"])  # 주기 없음
    assert set(codes["categories"]) == set(svc.CATEGORIES)


def test_add_months_clamps_to_month_end():
    assert svc.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert svc.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert svc.add_months(date(2026, 10, 17), 12) == date(2027, 10, 17)


def test_states_and_ordering(client, units):
    _new(client, title="소화기 점검", interval_months=6, next_due_on="2026-10-10")  # 지남
    _new(client, title="정화조 청소", category="cleaning", interval_months=12, next_due_on="2026-10-25")  # 14일 안
    _new(client, title="보일러 점검", category="equipment", interval_months=12, next_due_on="2027-03-01")
    _new(client, title="화재보험 갱신", category="insurance")  # 날짜 모름
    _new(client, title="도어락 건전지", category="consumable", interval_months=12,
         unit_ids=[units["101"], units["102"], units["101"]])  # 같은 호실 두 번 → 한 번
    rows = _list(client)
    assert [(r["title"], r["unit_no"], r["state"]) for r in rows] == [
        ("소화기 점검", None, "overdue"), ("정화조 청소", None, "soon"),
        ("화재보험 갱신", None, "no_date"), ("도어락 건전지", "101", "no_date"), ("도어락 건전지", "102", "no_date"),
        ("보일러 점검", None, "ok")]
    assert rows[0]["days_left"] == -7 and rows[3]["next_due_on"] is None and rows[3]["days_left"] is None
    assert rows[0]["last_done_on"] is None and rows[0]["cost_total"] is None  # 모르면 비움


def test_done_moves_next_due_and_undo_restores(client, units):
    tid = _new(client, title="소화기 점검", interval_months=6, next_due_on="2026-10-10")[0]
    res = client.post(f"/api/v1/routine-tasks/{tid}/done", json={"done_on": "2026-10-15", "cost": 30000, "vendor": "OO소방"})
    assert res.status_code == 201 and res.json()["next_due_on"] == "2027-04-15"
    row = _list(client)[0]
    assert (row["state"], row["last_done_on"], row["done_count"], row["cost_total"]) == ("ok", "2026-10-15", 1, 30000)
    # 비용 모르는 기록이 섞이면 합계 없음
    client.post(f"/api/v1/routine-tasks/{tid}/done", json={"done_on": "2026-10-16"})
    assert _list(client)[0]["cost_total"] is None and _list(client)[0]["next_due_on"] == "2027-04-16"

    logs = client.get(f"/api/v1/routine-tasks/{tid}/logs").json()
    assert [g["done_on"] for g in logs] == ["2026-10-16", "2026-10-15"] and logs[1]["vendor"] == "OO소방"
    assert client.delete(f"/api/v1/routine-logs/{logs[1]['id']}").status_code == 409  # 최근 것만
    assert client.delete(f"/api/v1/routine-logs/{logs[0]['id']}").json()["next_due_on"] == "2027-04-15"
    assert client.delete(f"/api/v1/routine-logs/{logs[1]['id']}").json()["next_due_on"] == "2026-10-10"


def test_one_off_task_finishes(client, onboarded):
    tid = _new(client, title="화재보험 갱신", category="insurance", next_due_on="2026-11-01")[0]
    assert client.post(f"/api/v1/routine-tasks/{tid}/done", json={}).json()["next_due_on"] is None
    assert _list(client)[0]["state"] == "finished" and _list(client)[0]["last_done_on"] == "2026-10-17"


def test_validation(client, onboarded):
    bad = [{"title": " "}, {"title": "x", "category": "nope"}, {"title": "x", "interval_months": 0},
           {"title": "x", "interval_months": 121}]
    for body in bad:
        assert client.post("/api/v1/routine-tasks", json={"category": "safety", **body}).status_code == 409, body
    tid = _new(client, title="소화기", interval_months=6)[0]
    assert client.post(f"/api/v1/routine-tasks/{tid}/done", json={"done_on": "2026-10-18"}).status_code == 409  # 미래
    assert client.post(f"/api/v1/routine-tasks/{tid}/done", json={"cost": -1}).status_code == 409
    client.post(f"/api/v1/routine-tasks/{tid}/done", json={"done_on": "2026-10-10"})
    assert client.post(f"/api/v1/routine-tasks/{tid}/done", json={"done_on": "2026-10-01"}).status_code == 409  # 역순


def test_stop_delete_and_fixture_link(client, units):
    fid = client.post("/api/v1/fixtures", json={"category": "boiler", "unit_ids": [units["201"]]}).json()["ids"][0]
    tid = _new(client, title="보일러 점검", category="equipment", interval_months=12, fixture_id=fid)[0]
    row = _list(client)[0]
    assert (row["unit_no"], row["fixture_name"]) == ("201", "보일러")  # 품목 자리를 따라감
    assert client.delete(f"/api/v1/fixtures/{fid}").status_code == 409  # 점검이 걸린 품목은 못 지움

    client.post(f"/api/v1/routine-tasks/{tid}/done", json={})
    assert client.delete(f"/api/v1/routine-tasks/{tid}").status_code == 409  # 기록 있으면 멈춤으로
    assert client.post(f"/api/v1/routine-tasks/{tid}/status", json={"status": "stopped"}).json()["status"] == "stopped"
    assert _list(client) == [] and _list(client, include_stopped=True)[0]["state"] == "stopped"

    tid2 = _new(client, title="잘못 넣음")[0]
    assert client.delete(f"/api/v1/routine-tasks/{tid2}").status_code == 204


def test_update_moves_place(client, units):
    tid = _new(client, title="감지기", unit_ids=[units["101"]])[0]
    res = client.put(f"/api/v1/routine-tasks/{tid}", json={"title": "감지기 건전지", "category": "consumable",
                                                          "interval_months": 12, "next_due_on": "2027-01-01",
                                                          "unit_id": units["102"]})
    assert res.status_code == 200
    row = _list(client)[0]
    assert (row["title"], row["unit_no"], row["interval_months"], row["next_due_on"]) == ("감지기 건전지", "102", 12, "2027-01-01")


def test_isolation(client, make_client, onboarded):
    tid = _new(client, title="소화기")[0]
    other, _ = make_client(email="other@example.com", org_name="남의 사업장")
    assert other.post(f"/api/v1/routine-tasks/{tid}/done", json={}).status_code == 404
    assert other.get(f"/api/v1/routine-tasks/{tid}/logs").status_code == 404
    assert other.get("/api/v1/routine-tasks").json() == []


def test_dashboard_alerts(client, onboarded):
    _new(client, title="소화기 점검", interval_months=6, next_due_on="2026-10-10")
    _new(client, title="정화조 청소", category="cleaning", interval_months=12, next_due_on="2026-10-25")
    dash = client.get("/api/v1/dashboard", params={"organization_id": onboarded["organization_id"],
                                                   "as_of": "2026-10-17"}).json()
    kinds = {a["kind"]: a for a in dash["attention"]}
    assert kinds["routine_overdue"]["level"] == "warn" and "소화기 점검" in kinds["routine_overdue"]["message"]
    assert "정화조 청소 10-25" in kinds["routine_soon"]["message"]
