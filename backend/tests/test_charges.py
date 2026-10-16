from datetime import date

import pytest

from app.services.charges import due_date_for


@pytest.mark.parametrize("period,day,expected", [
    ("2026-11", 1, date(2026, 11, 1)),
    ("2026-11", 31, date(2026, 11, 30)),
    ("2027-02", 31, date(2027, 2, 28)),
    ("2028-02", 30, date(2028, 2, 29)),  # 윤년
    ("2026-12", 31, date(2026, 12, 31)),
])
def test_due_date_clamps_to_month_end(period, day, expected):
    assert due_date_for(period, day) == expected


def test_invalid_period(client, onboarded):
    res = client.post("/api/v1/charges/generate",
                      params={"organization_id": onboarded["organization_id"], "period": "2026-13"})
    assert res.status_code == 422


def test_each_unit_charged_on_its_own_due_day(client, onboarded):
    res = client.post("/api/v1/charges/generate",
                      params={"organization_id": onboarded["organization_id"], "period": "2026-11"}).json()
    by_unit = {c["unit_no"]: (c["due_date"], c["amount"]) for c in res["charges"]}
    assert by_unit == {
        "101": ("2026-11-01", 450000),
        "102": ("2026-11-05", 450000),
        "103": ("2026-11-10", 420000),
        "201": ("2026-11-15", 450000),
        "202": ("2026-11-20", 450000),
        "301": ("2026-11-25", 480000),
        "302": ("2026-11-28", 450000),
        "303": ("2026-11-30", 460000),  # 31일 → 11월 말일
    }
    assert "203" not in by_unit and "401" not in by_unit  # 공실·주인세대


def test_rerun_creates_no_duplicates(client, onboarded):
    params = {"organization_id": onboarded["organization_id"], "period": "2026-11"}
    first = client.post("/api/v1/charges/generate", params=params).json()
    second = client.post("/api/v1/charges/generate", params=params).json()
    assert first["created"] == 8 and first["already_existed"] == 0
    assert second["created"] == 0 and second["already_existed"] == 8
    listed = client.get("/api/v1/charges", params=params).json()
    assert len(listed) == 8


def test_lease_not_yet_started_or_ended_is_not_charged(client, onboarded):
    # 202호 계약시작 2026-04-20 → 2026-04 청구 O (납부일 20일), 2026-03 청구 X
    org = onboarded["organization_id"]
    march = client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-03"}).json()
    april = client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-04"}).json()
    assert "202" not in {c["unit_no"] for c in march["charges"]}
    assert "202" in {c["unit_no"] for c in april["charges"]}
    # 303호 계약종료 2027-05-30, 납부일 31 → 2027-05-31 은 계약 밖
    may27 = client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2027-05"}).json()
    assert "303" not in {c["unit_no"] for c in may27["charges"]}
