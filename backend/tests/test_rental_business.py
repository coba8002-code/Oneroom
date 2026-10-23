"""등록임대사업자 모드 — 관리자가 적은 값만, 법령 기준은 바꿀 수 있는 기본값, 모르면 비움."""
from datetime import date

import pytest

from app.routers import rental_business as router_mod
from app.services import rental_business as svc

TODAY = date(2026, 11, 20)


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    monkeypatch.setattr(router_mod, "_today", lambda: TODAY)


@pytest.fixture
def org(onboarded):
    return onboarded["organization_id"]


@pytest.fixture
def ids(client, org):
    units = client.get("/api/v1/units", params={"organization_id": org}).json()
    prop = client.get("/api/v1/rental-business").json()["buildings"][0]["property_id"]
    return {"property": prop, **{u["unit_no"]: u["unit_id"] for u in units}}


def _ov(client):
    return client.get("/api/v1/rental-business").json()


def _register(client, ids, unit_no=None, **kw):
    body = {"property_id": ids["property"], "unit_id": ids[unit_no] if unit_no else None,
            "housing_type": "multi_household", "rental_type": "long_term", **kw}
    res = client.post("/api/v1/registered-rentals", json=body)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _lease(client, org, unit_no):
    return next(c["lease_id"] for c in client.get("/api/v1/contracts", params={"organization_id": org}).json()
                if c["unit_no"] == unit_no)


def _kinds(ov):
    return {(o["kind"], o["place"]) for o in ov["obligations"]}


def test_empty_until_registered(client, org):
    ov = _ov(client)
    assert ov["profile"] is None and ov["registrations"] == [] and ov["obligations"] == []
    assert ov["rules"]["increase_cap_pct"] == "5" and ov["rules"]["report_months"] == 3  # 법령 문언 기본값
    assert "확인" in ov["rules"]["note"]
    lid = _lease(client, org, "101")
    keys = [i["key"] for i in client.get(f"/api/v1/leases/{lid}/checklist").json()["items"]]
    assert "rental_contract_report" not in keys  # 등록 안 한 호실엔 민특법 항목 없음
    assert client.put(f"/api/v1/leases/{lid}/checks/standard_contract", json={"status": "done"}).status_code == 409
    dash = client.get("/api/v1/dashboard", params={"organization_id": org}).json()
    assert not any(a["kind"].startswith("rental_") for a in dash["attention"])


def test_profile_rules_are_editable(client, org):
    assert client.put("/api/v1/rental-business", json={"registration_no": " 2026-서울-0001 ", "increase_cap_pct": "4.5",
                                                       "report_months": 2}).status_code == 200
    ov = _ov(client)
    assert ov["profile"]["registration_no"] == "2026-서울-0001" and ov["rules"]["increase_cap_pct"] == "4.5"
    assert ov["rules"]["report_months"] == 2
    assert client.put("/api/v1/rental-business", json={"increase_cap_pct": "다섯"}).status_code == 409
    assert client.put("/api/v1/rental-business", json={"report_months": 0}).status_code == 409


def test_whole_building_registration_obligations(client, org, ids):
    rid = _register(client, ids)
    ov = _ov(client)
    reg = ov["registrations"][0]
    assert reg["place"] == "테스트 다가구 전체" and reg["obligation_end_on"] is None  # 기간 모름 → 계산 안 함
    assert len(reg["leases"]) == 8  # 진행 중 임대 계약 전부
    assert {k for k, _ in _kinds(ov)} == {"guarantee_missing", "lien_missing", "obligation_unknown"}
    dash = client.get("/api/v1/dashboard", params={"organization_id": org}).json()
    kinds = {a["kind"] for a in dash["attention"]}
    assert {"rental_guarantee_missing", "rental_lien_missing"} <= kinds and "rental_obligation_unknown" not in kinds

    # 겹치는 등록 막기 (건물 전체 + 그 안 호실)
    body = {"property_id": ids["property"], "unit_id": ids["101"], "housing_type": "multi_household", "rental_type": "long_term"}
    assert client.post("/api/v1/registered-rentals", json=body).status_code == 409

    # 보증·부기등기·의무기간을 적으면 경고가 사라지고, 끝나는 날은 달력으로 계산
    assert client.post(f"/api/v1/registered-rentals/{rid}/guarantees", json={
        "provider": "hug", "policy_no": "P-1", "start_on": "2026-01-01", "end_on": "2027-01-10"}).status_code == 201
    upd = {**body, "unit_id": None, "lien_status": "done", "lien_done_on": "2026-02-01",
           "rental_start_on": "2017-02-28", "obligation_years": 10}
    assert client.put(f"/api/v1/registered-rentals/{rid}", json=upd).status_code == 200
    ov = _ov(client)
    reg = ov["registrations"][0]
    assert reg["obligation_end_on"] == "2027-02-28" and reg["guarantee_state"] == "expiring"
    assert {k for k, _ in _kinds(ov)} == {"guarantee_expiring", "obligation_ending"}
    assert all(o["level"] == "info" for o in ov["obligations"])


def test_exempt_guarantee_and_bad_input(client, org, ids):
    rid = _register(client, ids, "101", housing_type="officetel")
    assert client.post(f"/api/v1/registered-rentals/{rid}/guarantees", json={"provider": "exempt"}).status_code == 201
    assert _ov(client)["registrations"][0]["guarantee_state"] == "exempt"
    assert "guarantee_missing" not in {k for k, _ in _kinds(_ov(client))}
    assert client.post(f"/api/v1/registered-rentals/{rid}/guarantees", json={"provider": "x"}).status_code == 409
    assert client.post(f"/api/v1/registered-rentals/{rid}/guarantees", json={
        "provider": "sgi", "start_on": "2026-02-01", "end_on": "2026-01-01"}).status_code == 409
    bad = {"property_id": ids["property"], "unit_id": ids["102"], "rental_type": "long_term"}
    assert client.post("/api/v1/registered-rentals", json={**bad, "housing_type": "castle"}).status_code == 409
    assert client.post("/api/v1/registered-rentals", json={**bad, "housing_type": "other", "obligation_years": 0}).status_code == 409


def test_contract_checklist_and_report_deadline(client, org, ids):
    _register(client, ids, "201")
    lid = _lease(client, org, "201")
    client.put(f"/api/v1/leases/{lid}/signed-on", json={"signed_on": "2026-08-10"})
    items = {i["key"]: i for i in client.get(f"/api/v1/leases/{lid}/checklist", params={"as_of": "2026-11-20"}).json()["items"]}
    rep = items["rental_contract_report"]
    assert rep["due_on"] == "2026-11-10" and rep["overdue"] is True and "standard_contract" in items
    assert ("contract_report", "201") in _kinds(_ov(client))
    assert client.put(f"/api/v1/leases/{lid}/checks/rental_contract_report",
                      json={"status": "done", "done_on": "2026-11-20", "note": "렌트홈"}).status_code == 200
    ov = _ov(client)
    assert ("contract_report", "201") not in _kinds(ov)
    assert ov["registrations"][0]["leases"][0]["report_status"] == "done"


def test_increase_over_cap_against_previous_lease(client, org, ids):
    _register(client, ids, "201")
    _register(client, ids, "103")
    for unit_no, rent in (("201", 480_000), ("103", 430_000)):
        client.post(f"/api/v1/leases/{_lease(client, org, unit_no)}/end", json={"ended_on": "2026-11-15"})
        res = client.post(f"/api/v1/units/{ids[unit_no]}/leases", json={
            "tenant_name": "다음", "deposit": 5_000_000, "rent": rent, "due_day": 16, "start_date": "2026-11-16"})
        assert res.status_code == 201, res.text
    ov = _ov(client)
    kinds = _kinds(ov)
    # 201: 월세 45만 → 48만 (6.67%) 상한 초과, 계약 시작 1년 지남
    assert ("increase_over_cap", "201") in kinds and ("increase_too_soon", "201") not in kinds
    inc = next(r for r in ov["registrations"] if r["place"] == "201")["leases"][0]["increase"]
    assert inc["rent_pct"] == "6.67" and inc["deposit_pct"] == "0.00" and inc["previous_rent"] == 450_000
    # 103: 월세 2.4% 인상이지만 직전 계약 시작(2026-01-10) 뒤 1년 안
    assert ("increase_too_soon", "103") in kinds and ("increase_over_cap", "103") not in kinds
    # 상한을 7%로 바꾸면 201 경고가 사라짐 (관리자 확인 값)
    client.put("/api/v1/rental-business", json={"increase_cap_pct": "7"})
    assert ("increase_over_cap", "201") not in _kinds(_ov(client))


def test_delete_registration_removes_guarantees(client, org, ids, session):
    rid = _register(client, ids, "101")
    client.post(f"/api/v1/registered-rentals/{rid}/guarantees", json={"provider": "hug"})
    assert client.delete(f"/api/v1/registered-rentals/{rid}").status_code == 204
    assert _ov(client)["registrations"] == []
    assert client.delete(f"/api/v1/registered-rentals/{rid}").status_code == 404


def test_other_org_cannot_touch(make_client, client, ids):
    rid = _register(client, ids, "101")
    other, _ = make_client(org_name="다른 사업장", email="other@example.com")
    assert other.put(f"/api/v1/registered-rentals/{rid}", json={
        "property_id": ids["property"], "housing_type": "other", "rental_type": "other"}).status_code == 404
    assert other.post(f"/api/v1/registered-rentals/{rid}/guarantees", json={"provider": "hug"}).status_code == 404
    assert other.post("/api/v1/registered-rentals", json={
        "property_id": ids["property"], "housing_type": "other", "rental_type": "other"}).status_code == 404


def test_add_years_clamps_leap_day():
    assert svc.add_years(date(2016, 2, 29), 10) == date(2026, 2, 28)
