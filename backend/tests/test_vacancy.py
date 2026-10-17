"""공실 관리 — 공실 기간·놓친 월세(직전 조건 기준), 모집 조건·광고 문구(적힌 값만), 활동 기록, 연락처 암호화."""
from datetime import date

import pytest
from sqlalchemy import text

from app.routers import vacancy as router_mod
from app.services import vacancy as svc

TODAY = date(2026, 12, 31)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(router_mod, "_today", lambda: TODAY)


@pytest.fixture
def units(client, onboarded):
    return {u["unit_no"]: u["unit_id"] for u in client.get("/api/v1/units",
                                                          params={"organization_id": onboarded["organization_id"]}).json()}


def _lease(client, org, unit_no):
    return next(x["lease_id"] for x in client.get("/api/v1/leases", params={"organization_id": org}).json()
                if x["unit_no"] == unit_no)


def test_missed_due_dates_clamp_month_end():
    assert svc.missed_due_dates(date(2026, 1, 31), date(2026, 3, 31), 31) == [date(2026, 2, 28), date(2026, 3, 31)]
    assert svc.missed_due_dates(date(2026, 11, 20), date(2026, 12, 31), 5) == [date(2026, 12, 5)]
    assert svc.missed_due_dates(date(2026, 11, 20), date(2026, 11, 20), 25) == []


def test_summary_counts_vacancy_and_missed_rent(client, onboarded, units):
    org = onboarded["organization_id"]
    # 102호(월세 450,000, 납부일 5일) 2026-11-20 종료 → 공실
    res = client.post(f"/api/v1/leases/{_lease(client, org, '102')}/end", params={"organization_id": org},
                      json={"ended_on": "2026-11-20", "reason": "퇴거"})
    assert res.status_code == 200, res.text
    s = client.get("/api/v1/vacancies").json()
    by = {u["unit_no"]: u for u in s["units"]}
    assert set(by) == {"102", "203"}  # 203은 처음부터 공실(이력 없음)
    u = by["102"]
    assert (u["vacant_since"], u["days_vacant"], u["previous_rent"], u["missed_due_dates"], u["missed_rent"]) == \
        ("2026-11-20", 41, 450000, 1, 450000)  # 12/5 한 번 (11/25 아님 — 납부일 5일)
    assert by["203"]["vacant_since"] is None and by["203"]["missed_rent"] is None  # 모르면 비움
    assert s["missed_rent_total_known"] == 450000 and s["units_without_history"] == ["203"]


def test_listing_and_ad_text_only_uses_given_values(client, onboarded, units):
    uid = units["203"]
    d = client.get(f"/api/v1/vacancies/{uid}").json()
    assert d["listing"] is None and "보증금" not in d["ad_text"] and d["ad_text"].startswith("[테스트 다가구] 203호 (2층)")
    client.post("/api/v1/fixtures", json={"category": "aircon", "unit_ids": [uid]})
    client.post("/api/v1/fixtures", json={"category": "washer", "unit_ids": [uid], "owner": "tenant"})  # 임차인 소유는 빠짐
    d = client.put(f"/api/v1/vacancies/{uid}/listing", json={"asking_deposit": 5000000, "asking_rent": 455000,
                                                             "available_on": "2027-01-10", "note": "남향, 역 5분"}).json()
    lines = d["ad_text"].splitlines()
    assert "보증금 500만원 / 월세 455,000원" in lines and "입주 가능: 2027-01-10부터" in lines
    assert "옵션: 에어컨" in lines and "전용 23.1㎡" in lines and lines[-1] == "남향, 역 5분"
    assert client.put(f"/api/v1/vacancies/{uid}/listing", json={"asking_rent": -1}).status_code == 409


def test_activities_and_phone_encrypted(client, onboarded, units, session):
    uid = units["203"]
    res = client.post(f"/api/v1/vacancies/{uid}/activities",
                      json={"kind": "agent", "happened_on": "2026-12-20", "agent_name": "행복공인중개사", "agent_phone": "010-1111-2222"})
    assert res.status_code == 201
    client.post(f"/api/v1/vacancies/{uid}/activities", json={"kind": "viewing"})
    assert client.post(f"/api/v1/vacancies/{uid}/activities", json={"kind": "viewing", "happened_on": "2027-01-01"}).status_code == 409
    assert client.post(f"/api/v1/vacancies/{uid}/activities", json={"kind": "spam"}).status_code == 409
    d = client.get(f"/api/v1/vacancies/{uid}").json()
    assert [(a["kind"], a["happened_on"]) for a in d["activities"]] == [("viewing", "2026-12-31"), ("agent", "2026-12-20")]
    assert d["activities"][1]["agent_phone"] == "010-1111-2222"
    raw = session.execute(text("SELECT agent_phone FROM vacancy_activities WHERE agent_phone IS NOT NULL")).scalar()
    assert raw and "010" not in raw  # 저장은 암호문
    summary = {u["unit_no"]: u for u in client.get("/api/v1/vacancies").json()["units"]}
    assert summary["203"]["activity"] == {"agent": 1, "inquiry": 0, "viewing": 1, "other": 0}
    assert client.delete(f"/api/v1/vacancy-activities/{d['activities'][0]['id']}").status_code == 204


def test_isolation(client, make_client, units):
    other, _ = make_client(email="other@example.com", org_name="남의 사업장")
    assert other.get(f"/api/v1/vacancies/{units['203']}").status_code == 404
    assert other.put(f"/api/v1/vacancies/{units['203']}/listing", json={}).status_code == 404
