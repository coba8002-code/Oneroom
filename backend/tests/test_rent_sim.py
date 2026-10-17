"""전월세 시뮬레이션 — 사실값에서 시작, 넣지 않은 값은 비움, 세금 계산 없음."""
from datetime import date


def _sim(client, **kw):
    res = client.post("/api/v1/rent-sim", json={"as_of": "2026-11-01", **kw})
    assert res.status_code == 200, res.text
    return res.json()


def test_baseline_from_active_leases_and_unknowns_stay_empty(client, onboarded):
    d = _sim(client)
    assert len(d["rows"]) == 8  # 샘플: 임대 9실 중 공실 1
    cur = d["current"]
    assert cur["annual_rent"] == sum(r["rent"] for r in d["rows"]) * 12
    assert cur["deposit_income"] is None and cur["annual_net"] is None and cur["equity_yield_pct"] is None
    assert d["scenario"] == cur  # 바꾼 것이 없으면 같음
    assert "계산하지 않습니다" in d["tax_note"]
    assert d["reference"]["operating_total"] is None  # 은행 내역 없음 → 참고값도 비움


def test_scenario_conversion_and_liquidity(client, onboarded):
    rows = _sim(client)["rows"]
    r101 = next(r for r in rows if r["unit_no"] == "101")  # 보증금 5,000,000 · 월세 450,000 · 만료 2027-02-28
    d = _sim(client, rows=[{"lease_id": r101["lease_id"], "deposit": 1_000_000, "rent": 466_666}],
             deposit_yield_pct="3", annual_opex=6_000_000, cash_on_hand=4_000_000, property_value=1_000_000_000)
    cur, sc = d["current"], d["scenario"]
    assert sc["deposit_total"] == cur["deposit_total"] - 4_000_000
    assert sc["annual_rent"] == cur["annual_rent"] + 16_666 * 12
    assert cur["deposit_income"] == cur["deposit_total"] * 3 // 100
    assert sc["annual_net"] == sc["annual_rent"] + sc["deposit_income"] - 6_000_000
    assert sc["equity"] == 1_000_000_000 - sc["deposit_total"] and sc["equity_yield_pct"] is not None
    liq = d["liquidity"]
    feb = next(m for m in liq["months"] if m["month"] == "2027-02")
    assert feb["due"] == 1_000_000  # 시나리오 보증금 기준
    assert liq["max_cumulative_due"] == liq["months"][-1]["cumulative"]
    assert all(m["month"] <= "2027-10" for m in liq["months"])  # 12개월 안만
    assert liq["covered"] == (4_000_000 >= liq["max_cumulative_due"])


def test_validation(client, onboarded):
    rows = _sim(client)["rows"]
    bad = [({"rows": [{"lease_id": "nope", "deposit": 1, "rent": 1}]}, 409),
           ({"rows": [{"lease_id": rows[0]["lease_id"], "deposit": -1, "rent": 1}]}, 409),
           ({"deposit_yield_pct": "많이"}, 409), ({"annual_opex": -5}, 409)]
    for body, code in bad:
        assert client.post("/api/v1/rent-sim", json=body).status_code == code, body
    assert date(2026, 11, 1)
