"""자산대장(옵션·집기·공용 설비)과 수리 이력."""
from datetime import date

import pytest

from app.models import Fixture
from app.services import fixtures as svc


@pytest.fixture
def units(client, onboarded):
    return {u["unit_no"]: u["unit_id"] for u in client.get("/api/v1/units",
                                                          params={"organization_id": onboarded["organization_id"]}).json()}


def _list(client, **params):
    return client.get("/api/v1/fixtures", params=params).json()


def test_codes_and_bulk_create_for_units_and_common(client, units):
    codes = client.get("/api/v1/fixture-codes").json()
    assert codes["categories"]["aircon"] == "에어컨" and set(codes["owners"]) == {"landlord", "tenant"}
    res = client.post("/api/v1/fixtures", json={"category": "aircon", "brand": "LG", "model": "SQ06",
                                                "manufactured": "2019-06", "unit_ids": [units["101"], units["102"],
                                                                                        units["101"]]})
    assert res.status_code == 201 and res.json()["created"] == 2  # 같은 호실을 두 번 골라도 한 번
    assert client.post("/api/v1/fixtures", json={"category": "cctv", "name": "현관 CCTV"}).json()["created"] == 1
    rows = _list(client)
    assert [(r["unit_no"], r["name"]) for r in rows] == [("101", "에어컨"), ("102", "에어컨"), (None, "현관 CCTV")]
    r = rows[0]
    assert r["owner"] == "landlord" and r["age_months"] is not None and r["repair_count"] == 0
    assert r["price"] is None and r["warranty_active"] is None and r["repair_cost"] is None  # 모르면 비움
    assert [x["name"] for x in _list(client, common=True)] == ["현관 CCTV"]
    assert len(_list(client, unit_id=units["101"])) == 1


def test_validation_and_isolation(client, make_client, units):
    bad = [({"category": "spaceship"}, 409), ({"category": "tv", "manufactured": "2019/06"}, 409),
           ({"category": "tv", "replace_by": "2027-13"}, 409), ({"category": "tv", "price": -1}, 409),
           ({"category": "tv", "owner": "nobody"}, 409)]
    for body, code in bad:
        assert client.post("/api/v1/fixtures", json=body).status_code == code, body
    other, _ = make_client(org_name="남의 건물")
    other.post("/api/v1/onboarding", json={"property": {"name": "남"}, "units": [
        {"unit_no": "901", "tenant_name": "x", "rent": 1, "due_day": 1, "start_date": "2026-01-01"}]})
    # 남의 호실에는 못 넣고, 남의 품목은 안 보임
    assert other.post("/api/v1/fixtures", json={"category": "tv", "unit_ids": [units["101"]]}).status_code == 404
    fid = client.post("/api/v1/fixtures", json={"category": "tv", "unit_ids": [units["101"]]}).json()["ids"][0]
    assert other.put(f"/api/v1/fixtures/{fid}", json={"category": "tv"}).status_code == 404
    assert other.get("/api/v1/fixtures").json() == []


def test_age_is_counted_from_known_dates_only():
    as_of = date(2026, 10, 17)
    assert svc.age_months(Fixture(manufactured="2019-06"), as_of) == 88
    assert svc.age_months(Fixture(installed_on=date(2025, 10, 18)), as_of) == 11  # 하루 모자라면 덜 찬 달
    assert svc.age_months(Fixture(installed_on=date(2025, 10, 17)), as_of) == 12
    assert svc.age_months(Fixture(), as_of) is None


def test_update_remove_and_delete(client, units):
    fid = client.post("/api/v1/fixtures", json={"category": "washer", "unit_ids": [units["101"]]}).json()["ids"][0]
    res = client.put(f"/api/v1/fixtures/{fid}", json={"category": "washer", "owner": "tenant", "unit_id": units["103"],
                                                      "note": "전 세입자가 두고 감"})
    assert res.status_code == 200
    row = _list(client)[0]
    assert (row["unit_no"], row["owner"], row["note"]) == ("103", "tenant", "전 세입자가 두고 감")
    client.post("/api/v1/repairs", json={"description": "배수 막힘", "fixture_id": fid})
    assert client.delete(f"/api/v1/fixtures/{fid}").status_code == 409  # 수리 기록이 있으면 지우지 않음
    assert client.post(f"/api/v1/fixtures/{fid}/remove", json={"reason": "고장으로 폐기"}).json()["status"] == "removed"
    assert client.post(f"/api/v1/fixtures/{fid}/remove", json={}).status_code == 409
    assert _list(client) == [] and _list(client, include_removed=True)[0]["removed_reason"] == "고장으로 폐기"
    other = client.post("/api/v1/fixtures", json={"category": "tv"}).json()["ids"][0]
    assert client.delete(f"/api/v1/fixtures/{other}").status_code == 204


def test_repairs_location_cost_and_dashboard(client, onboarded, units):
    fid = client.post("/api/v1/fixtures", json={"category": "aircon", "unit_ids": [units["201"]]}).json()["ids"][0]
    r1 = client.post("/api/v1/repairs", json={"description": "냉매 보충", "fixture_id": fid, "unit_id": units["101"],
                                              "reported_on": "2026-07-01", "cost": 80000, "payer": "landlord",
                                              "completed_on": "2026-07-02", "vendor": "OO냉열"})
    assert r1.status_code == 201 and r1.json()["status"] == "done"
    rep = client.get("/api/v1/repairs").json()[0]
    assert rep["unit_no"] == "201" and rep["fixture_name"] == "에어컨"  # 품목을 고르면 위치는 품목의 위치
    assert _list(client)[0]["repair_cost"] == 80000
    client.post("/api/v1/repairs", json={"description": "리모컨 분실", "fixture_id": fid, "payer": "tenant"})
    row = _list(client)[0]
    assert row["repair_count"] == 2 and row["repair_cost"] is None  # 비용 모르는 수리가 있으면 합계 안 냄

    assert client.post("/api/v1/repairs", json={"description": "x", "reported_on": "2026-07-05",
                                                "completed_on": "2026-07-01"}).status_code == 409
    assert client.post("/api/v1/repairs", json={"description": " "}).status_code == 409
    assert client.post("/api/v1/repairs", json={"description": "x", "payer": "nobody"}).status_code == 409
    leak = client.post("/api/v1/repairs", json={"description": "복도 누수", "reported_on": "2026-10-01"}).json()
    assert client.get("/api/v1/repairs", params={"status": "open"}).json()[0]["unit_no"] in (None, "201")

    dash = client.get("/api/v1/dashboard", params={"organization_id": onboarded["organization_id"]}).json()
    assert any(a["kind"] == "repair_open" and "2건" in a["message"] for a in dash["attention"])
    done = client.put(f"/api/v1/repairs/{leak['id']}", json={"description": "복도 누수", "reported_on": "2026-10-01",
                                                             "completed_on": "2026-10-03", "cost": 150000})
    assert done.json()["status"] == "done"
    assert client.delete(f"/api/v1/repairs/{leak['id']}").status_code == 204


def test_replacement_plan_groups_by_month_and_kind(client, units):
    today = date.today()
    this = today.strftime("%Y-%m")
    next_y = f"{today.year + 1}-{today.month:02d}"
    for u in ("101", "102", "103"):
        client.post("/api/v1/fixtures", json={"category": "aircon", "brand": "LG", "replace_by": this, "unit_ids": [units[u]]})
    client.post("/api/v1/fixtures", json={"category": "washer", "replace_by": "2020-01", "unit_ids": [units["201"]]})
    client.post("/api/v1/fixtures", json={"category": "fridge", "replace_by": next_y, "unit_ids": [units["202"]]})
    client.post("/api/v1/fixtures", json={"category": "tv", "owner": "tenant", "replace_by": this})  # 임차인 소유 제외
    client.post("/api/v1/fixtures", json={"category": "bed", "unit_ids": [units["203"]]})
    plan = client.get("/api/v1/fixtures/replacement-plan").json()
    got = [(g["month"], g["category"], g["count"]) for g in plan["groups"]]
    assert got == [("overdue", "washer", 1), (this, "aircon", 3)]  # 12개월 뒤(같은 달 내년)는 범위 밖
    assert plan["groups"][1]["units"] == ["101", "102", "103"] and plan["groups"][1]["models"] == ["LG"]
    assert plan["unplanned"] == 1
    assert any(g["category"] == "fridge" for g in client.get("/api/v1/fixtures/replacement-plan",
                                                             params={"months": 13}).json()["groups"])


def test_csv_export_opens_in_excel(client, units):
    client.post("/api/v1/fixtures", json={"category": "aircon", "price": 650000, "unit_ids": [units["101"]]})
    client.post("/api/v1/fixtures", json={"category": "cctv"})
    res = client.get("/api/v1/fixtures/export.csv")
    assert res.status_code == 200 and "attachment" in res.headers["content-disposition"]
    text = res.content.decode("utf-8")
    assert text.startswith("﻿위치,종류")
    assert "101,에어컨,에어컨,,,,,650000" in text and "\n공용,CCTV" in text.replace("\r\n", "\n")
