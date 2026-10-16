"""홈 대시보드."""
from datetime import date

from app.services import tax_calendar
from tests.conftest import SAMPLES


def _dash(client, org, as_of):
    res = client.get("/api/v1/dashboard", params={"organization_id": org, "as_of": as_of})
    assert res.status_code == 200, res.text
    return res.json()


def _kinds(d):
    return {a["kind"] for a in d["attention"]}


def test_fresh_onboarding_flags_missing_data(client, onboarded):
    d = _dash(client, onboarded["organization_id"], "2026-11-12")
    assert d["counts"] == {"total": 10, "rental": 9, "occupied": 8, "vacant": 1, "owner": 1}
    assert {"bank_none", "charges_missing", "vacant"} <= _kinds(d)
    u101 = next(u for u in d["units"] if u["unit_no"] == "101")
    assert u101["charge_status"] == "none" and u101["outstanding"] is None  # 청구 전 → 모름, 0 아님
    owner = next(u for u in d["units"] if u["unit_no"] == "401")
    assert owner["charge_status"] is None and owner["tenant_name"] is None
    assert d["money"]["rent_charged"] == 0 and d["money"]["complete"] is True


def test_after_matching(client, onboarded):
    org = onboarded["organization_id"]
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", files={"file": ("s.csv", raw)})
    client.post("/api/v1/matching/run", params={"organization_id": org})

    d = _dash(client, org, "2026-11-26")
    st = {u["unit_no"]: u["charge_status"] for u in d["units"]}
    assert st["101"] == "paid" and st["103"] == "open" and st["203"] is None
    u = {x["unit_no"]: x for x in d["units"]}
    assert (u["101"]["paid_on"], u["101"]["due_date"]) == ("2026-11-01", "2026-11-01")
    assert (u["303"]["due_date"], u["103"]["paid_on"]) == ("2026-11-30", None)  # 31일 → 말일, 미납은 완납일 없음
    recent = d["recent_transactions"]
    assert len(recent) == 6 and recent[0]["label"] == "303호 월세 입금" and recent[0]["direction"] == "in"
    assert any(r["label"] == "마트 · 확인 전" and not r["confirmed"] for r in recent)
    assert d["money"]["rent_charged"] == 3_610_000
    assert d["money"]["rent_received"] == 2_260_000
    # 26일 기준 납부일 지난 미수: 103(10일) · 301(25일)
    assert d["money"]["overdue_count"] == 2 and d["money"]["overdue_total"] == 420_000 + 480_000
    # 7일 안 납부 예정: 302(28일). 303(30일)은 이미 완납 → 예정 아님
    assert d["due_soon"] == [{"unit_no": "302", "due_date": "2026-11-28", "outstanding": 450000}]
    k = _kinds(d)
    assert {"review_in", "review_out", "overdue"} <= k
    assert "bank_none" not in k and "charges_missing" not in k
    assert d["money"]["complete"] is False


def test_stale_bank_data_warning(client, onboarded):
    org = onboarded["organization_id"]
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import",
                files={"file": ("a.csv", "거래일시,입금자,출금,입금\n2026-11-01 09:00,X,,1000\n".encode())})
    assert "bank_stale" not in _kinds(_dash(client, org, "2026-11-08"))
    stale = _dash(client, org, "2026-11-20")
    msg = next(a["message"] for a in stale["attention"] if a["kind"] == "bank_stale")
    assert "19일" in msg


def test_lease_ending_and_deposit_return(client):
    res = client.post("/api/v1/onboarding", json={
        "property": {"name": "만료 테스트"},
        "units": [
            {"unit_no": "101", "tenant_name": "곧퇴거", "rent": 400000, "due_day": 10,
             "start_date": "2024-12-15", "end_date": "2026-12-14", "deposit": 5000000,
             "deposit_received_on": "2024-12-10"},
            {"unit_no": "102", "tenant_name": "미수령", "rent": 400000, "due_day": 10,
             "start_date": "2026-11-01", "deposit": 3000000},
        ]}).json()
    d = _dash(client, res["organization_id"], "2026-11-12")
    assert d["lease_endings"] == [{"unit_no": "101", "tenant_name": "곧퇴거", "end_date": "2026-12-14",
                                   "days_left": 32, "deposit_to_return": 5000000}]
    msgs = [a["message"] for a in d["attention"]]
    assert any("101 계약 32일 후 만료, 보증금 5,000,000원 반환 예정" in m for m in msgs)
    assert any("102 보증금 3,000,000원 수령 기록 없음" in m for m in msgs)
    # 만료일이 지났어도 보증금을 안 돌려줬으면 계속 보인다
    late = _dash(client, res["organization_id"], "2026-12-20")
    assert late["lease_endings"][0]["days_left"] == -6


def test_tax_calendar_is_general_and_upcoming():
    ev = tax_calendar.upcoming(date(2026, 11, 12))
    names = [e["name"] for e in ev]
    assert names[0] == "종합소득세 중간예납 (고지분)" and ev[0]["in_progress"]
    assert "종합부동산세" in names and "사업장현황신고 (면세 개인사업자)" in names
    assert all(e["end"] >= date(2026, 11, 12) for e in ev)
    assert "종합소득세 확정신고·납부" not in names  # 120일 밖 (2027-05)


def test_bank_accounts_list(client, onboarded):
    accts = client.get("/api/v1/bank-accounts", params={"organization_id": onboarded["organization_id"]}).json()
    assert [a["id"] for a in accts] == [onboarded["bank_account_id"]]
