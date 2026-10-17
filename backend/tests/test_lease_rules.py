"""계약 법정 체크리스트와 계산기."""
from datetime import date

import pytest

from app.services import lease_rules as rules


def test_report_threshold_is_strictly_over():
    assert not rules.report_required(60_000_000, 300_000)
    assert rules.report_required(60_000_001, 0) and rules.report_required(0, 300_001)


def test_increase_caps_five_percent_and_one_year():
    r = rules.increase_caps(10_000_000, 450_000, date(2025, 3, 1), date(2026, 2, 28))
    assert (r["max_deposit"], r["max_rent"]) == (10_500_000, 472_500)
    assert r["claim_from"] == date(2026, 3, 1) and r["can_claim_now"] is False
    odd = rules.increase_caps(3_333_333, 333_333, date(2024, 2, 29), date(2025, 3, 1))
    assert (odd["max_deposit"], odd["max_rent"]) == (3_499_999, 349_999)  # 원 아래 버림
    assert odd["claim_from"] == date(2025, 2, 28) and odd["can_claim_now"]


def test_conversion_rate_is_lower_of_ten_and_base_plus_two():
    r = rules.conversion(10_000_000, "3.00")
    assert r["rate_pct"] == "5" and r["monthly_max"] == 41_666  # 1천만 × 5% ÷ 12
    assert rules.conversion(10_000_000, "9")["rate_pct"] == "10"
    with pytest.raises(rules.RuleError):
        rules.conversion(1, "삼")
    with pytest.raises(rules.RuleError):
        rules.conversion(1, "25")


@pytest.fixture
def org(onboarded):
    return onboarded["organization_id"]


def _new(client, org, unit_no, **kw):
    unit = next(u for u in client.get("/api/v1/lease-history").json() if u["unit_no"] == unit_no)["unit_id"]
    body = {"tenant_name": "신규", "rent": 450000, "due_day": 5, "start_date": "2026-11-01", **kw}
    res = client.post(f"/api/v1/units/{unit}/leases", json=body)
    assert res.status_code == 201, res.text
    return res.json()["lease_id"]


def test_checklist_items_and_report_deadline(client, org):
    lid = _new(client, org, "203", deposit=70_000_000, signed_on="2026-10-10")
    c = client.get(f"/api/v1/leases/{lid}/checklist", params={"as_of": "2026-11-12"}).json()
    items = {i["key"]: i for i in c["items"]}
    assert list(items) == ["info_disclosure", "tax_certificate", "lease_report", "move_in_inspection", "deposit_received"]
    rep = items["lease_report"]
    assert rep["due_on"] == "2026-11-09" and rep["overdue"] is True and "군 지역 제외" in rep["hint"]
    assert items["deposit_received"]["status"] == "todo" and items["move_in_inspection"]["status"] == "todo"
    dash = client.get("/api/v1/dashboard", params={"organization_id": org, "as_of": "2026-11-12"}).json()
    assert any(a["kind"] == "lease_report" and "203" in a["message"] and "지났습니다" in a["message"] for a in dash["attention"])

    url = f"/api/v1/leases/{lid}/checks/lease_report"
    assert client.put(url, json={"status": "done", "done_on": "2026-11-12", "note": "RTMS 온라인"}).status_code == 200
    items = {i["key"]: i for i in client.get(f"/api/v1/leases/{lid}/checklist").json()["items"]}
    assert items["lease_report"]["status"] == "done" and items["lease_report"]["note"] == "RTMS 온라인"
    dash = client.get("/api/v1/dashboard", params={"organization_id": org, "as_of": "2026-11-12"}).json()
    assert not any(a["kind"] == "lease_report" for a in dash["attention"])
    assert client.put(url, json={"status": None}).status_code == 200  # 되돌리기
    assert client.put(f"/api/v1/leases/{lid}/checks/move_in_inspection", json={"status": "done"}).status_code == 409
    assert client.put(url, json={"status": "maybe"}).status_code == 409


def test_small_lease_is_not_report_target_and_signed_on_editable(client, org):
    lid = _new(client, org, "203", deposit=5_000_000, rent=300_000)
    rep = next(i for i in client.get(f"/api/v1/leases/{lid}/checklist").json()["items"] if i["key"] == "lease_report")
    assert rep["status"] == "na" and "신고 대상이 아닙니다" in rep["hint"]
    assert client.put(f"/api/v1/leases/{lid}/signed-on", json={"signed_on": "2026-10-20"}).status_code == 200
    assert client.get(f"/api/v1/leases/{lid}/checklist").json()["signed_on"] == "2026-10-20"


def test_calculator_endpoints(client):
    r = client.get("/api/v1/rent-rules/increase", params={"deposit": 5000000, "rent": 450000, "since": "2025-03-01"}).json()
    assert r["max_rent"] == 472500
    assert client.get("/api/v1/rent-rules/conversion", params={"amount": 1, "base_rate": "x"}).status_code == 409
