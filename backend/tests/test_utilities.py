"""공과금 — 건물·항목별 처리 방식(포함/나눔/직접 납부), 나누는 방법(균등·면적·직접 입력), 공실·주인세대 몫,
원 단위 끝수(합이 고지서와 정확히 같게), 청구·취소, 월세 집계와 분리."""
from datetime import date

import pytest
from sqlalchemy import text

from app.routers import rent_certificate as cert_router
from tests.conftest import SAMPLES

# 샘플: 임대 9실(203 공실) + 주인세대 401(66㎡). 면적 19.8 ×6, 23.1 ×3


@pytest.fixture
def pid(client, onboarded):
    return client.get("/api/v1/utility-settings").json()["buildings"][0]["property_id"]


def _set(client, pid, item, **body):
    return client.put(f"/api/v1/properties/{pid}/utility-settings/{item}", json=body)


def _bill(client, pid, item="water", period="2026-11", total=100_000, **kw):
    res = client.post("/api/v1/utility-bills", json={"property_id": pid, "item": item, "period": period,
                                                     "total": total, **kw})
    assert res.status_code == 201, res.text
    return res.json()


def _shares(bill):
    return {s["unit_no"]: (s["amount"], s["billed"]) for s in bill["split"]["shares"]}


def test_settings_are_explicit_choices(client, pid):
    s = client.get("/api/v1/utility-settings").json()
    assert s["buildings"][0]["settings"] == {"electricity": None, "water": None, "gas": None, "internet": None}
    # 정하지 않은 항목은 고지서를 받지 않는다
    res = client.post("/api/v1/utility-bills", json={"property_id": pid, "item": "water", "period": "2026-11",
                                                     "total": 1000})
    assert res.status_code == 409 and "나눠서 청구" in res.json()["detail"]
    assert _set(client, pid, "water", mode="split").status_code == 409  # 나누는 방법 필요
    assert _set(client, pid, "water", mode="split", method="equal").status_code == 409  # 공실·주인세대 몫 필요
    assert _set(client, pid, "electricity", mode="included").status_code == 200  # 관리비에 포함
    assert _set(client, pid, "gas", mode="direct").status_code == 200  # 임차인 직접 납부
    assert _set(client, pid, "water", mode="split", method="equal", vacant="landlord", owner="landlord").status_code == 200
    got = client.get("/api/v1/utility-settings").json()["buildings"][0]["settings"]
    assert got["electricity"]["mode"] == "included" and got["water"]["method"] == "equal"
    assert client.post("/api/v1/utility-bills", json={"property_id": pid, "item": "electricity",
                                                     "period": "2026-11", "total": 1000}).status_code == 409


def test_equal_split_landlord_bears_vacant_and_owner(client, pid):
    _set(client, pid, "water", mode="split", method="equal", vacant="landlord", owner="landlord")
    b = _bill(client, pid)
    sh = _shares(b)
    assert sh["101"] == (10_000, True) and sh["203"] == (10_000, False) and sh["401"] == (10_000, False)
    assert (b["split"]["billed_total"], b["split"]["landlord_total"]) == (80_000, 20_000)


def test_equal_split_excluding_and_remainder_is_exact(client, pid):
    _set(client, pid, "water", mode="split", method="equal", vacant="exclude", owner="exclude")
    b = _bill(client, pid, total=100_003)
    sh = _shares(b)
    assert sh["203"] == (None, False) and sh["401"] == (None, False)  # 빼고 나눔
    billed = [a for a, ok in sh.values() if ok]
    assert len(billed) == 8 and sum(billed) == 100_003 and sorted(set(billed)) == [12_500, 12_501]
    assert (sh["101"][0], sh["102"][0], sh["103"][0], sh["201"][0]) == (12_501, 12_501, 12_501, 12_500)
    assert b["split"]["landlord_total"] == 0


def test_area_split_sums_to_total_and_needs_area(client, pid, session):
    _set(client, pid, "water", mode="split", method="area", vacant="landlord", owner="landlord")
    b = _bill(client, pid, total=100_000)
    sh = _shares(b)
    assert sum(a for a, _ in sh.values()) == 100_000
    assert sh["101"][0] in (7_792, 7_793) and sh["401"][0] in (25_974, 25_975)  # 19.8/254.1, 66/254.1 (끝수 1원)
    assert sh["401"][1] is False
    session.execute(text("update units set area_m2 = null where unit_no = '103'"))
    session.commit()
    again = client.get("/api/v1/utility-bills").json()[0]
    assert again["split"] is None and "103" in again["problem"]  # 모르면 계산하지 않음


def test_manual_split(client, pid, units):
    _set(client, pid, "water", mode="split", method="manual")
    b = _bill(client, pid, total=50_000, manual={units["101"]: 30_000, units["102"]: 15_000})
    sh = _shares(b)
    assert sh["101"] == (30_000, True) and sh["102"] == (15_000, True) and sh["103"] == (None, False)
    assert b["split"]["landlord_total"] == 5_000
    bad = client.put(f"/api/v1/utility-bills/{b['id']}", json={"total": 50_000, "manual": {units["203"]: 1000}}).json()
    assert "203" in bad["problem"]  # 공실에는 넣을 수 없음
    over = client.put(f"/api/v1/utility-bills/{b['id']}", json={"total": 1_000, "manual": {units["101"]: 2_000}}).json()
    assert "고지서 금액" in over["problem"]


@pytest.fixture
def units(client, onboarded):
    return {u["unit_no"]: u["unit_id"] for u in client.get("/api/v1/units",
                                                          params={"organization_id": onboarded["organization_id"]}).json()}


def test_charge_creates_utility_charges_beside_rent(client, onboarded, pid):
    org = onboarded["organization_id"]
    _set(client, pid, "water", mode="split", method="equal", vacant="exclude", owner="exclude")
    b = _bill(client, pid, period="2026-11", total=100_000)
    res = client.post(f"/api/v1/utility-bills/{b['id']}/charge")
    assert res.status_code == 200 and res.json()["status"] == "charged"
    assert client.put(f"/api/v1/utility-bills/{b['id']}", json={"total": 1}).status_code == 409  # 청구 뒤엔 못 고침
    # 월세 청구는 따로 만들어진다 (공과금 청구가 막지 않음)
    gen = client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"}).json()
    assert gen["created"] == 8
    rows = client.get("/api/v1/charges", params={"organization_id": org, "period": "2026-11"}).json()
    water = [c for c in rows if c["kind"] == "water"]
    assert len(water) == 8 and {c["amount"] for c in water} == {12_500}
    w101 = next(c for c in water if c["unit_no"] == "101")
    assert w101["due_date"] == "2026-11-01"  # 월세와 같은 납부일
    # 결산: 월세 청구는 월세만, 공과금은 따로
    m = client.get("/api/v1/reports/monthly", params={"organization_id": org, "period": "2026-11"}).json()
    assert m["rent_charged"] == 3_610_000 and m["utility_charged"] == 100_000
    # 취소하면 공과금 청구만 사라진다
    assert client.post(f"/api/v1/utility-bills/{b['id']}/uncharge").json()["status"] == "draft"
    rows = client.get("/api/v1/charges", params={"organization_id": org, "period": "2026-11"}).json()
    assert {c["kind"] for c in rows} == {"rent"} and len(rows) == 8


def test_payment_covering_rent_and_water(client, onboarded, pid, monkeypatch):
    org = onboarded["organization_id"]
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    _set(client, pid, "water", mode="split", method="equal", vacant="exclude", owner="exclude")
    b = _bill(client, pid, period="2026-11", total=100_000)
    client.post(f"/api/v1/utility-bills/{b['id']}/charge")
    raw = (SAMPLES / "bank_transactions_sample.csv").read_text(encoding="utf-8").replace(
        "2026-11-01 09:12:33,타행이체,임차인A,,450000,", "2026-11-01 09:12:33,타행이체,임차인A,,462500,")
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", files={"file": ("s.csv", raw.encode())})
    client.post("/api/v1/matching/run", params={"organization_id": org})
    q = client.get("/api/v1/matching/queue", params={"organization_id": org}).json()
    item = next(i for i in q if i["transaction"]["counterparty"] == "임차인A")  # 금액이 달라 자동 확정 안 됨 (규칙 1)
    lease = item["suggestion"]["lease_id"]
    client.post(f"/api/v1/transactions/{item['transaction']['id']}/decision", params={"organization_id": org},
                json={"lease_id": lease, "category": "rent"})
    rows = {(c["unit_no"], c["kind"]): c["status"] for c in
            client.get("/api/v1/charges", params={"organization_id": org, "period": "2026-11"}).json()}
    assert rows[("101", "rent")] == "paid" and rows[("101", "water")] == "paid"  # 월세 먼저, 남은 돈으로 수도
    m = client.get("/api/v1/reports/monthly", params={"organization_id": org, "period": "2026-11"}).json()
    assert m["utility_received"] == 12_500
    # 입금이 배분된 공과금 청구는 취소할 수 없다
    assert client.post(f"/api/v1/utility-bills/{b['id']}/uncharge").status_code == 409
    # 납부 확인서에는 월세 몫만
    monkeypatch.setattr(cert_router, "_today", lambda: date(2027, 1, 10))
    c = client.get(f"/api/v1/leases/{lease}/rent-certificate", params={"year": 2026}).json()
    assert c["lines"] == [{"paid_on": "2026-11-01", "amount": 450_000, "periods": ["2026-11"]}]


def test_duplicate_period_and_other_org(client, make_client, pid):
    _set(client, pid, "water", mode="split", method="equal", vacant="exclude", owner="exclude")
    _bill(client, pid)
    dup = client.post("/api/v1/utility-bills", json={"property_id": pid, "item": "water", "period": "2026-11",
                                                     "total": 5})
    assert dup.status_code == 409
    other, _ = make_client(org_name="남의 사업장")
    assert other.put(f"/api/v1/properties/{pid}/utility-settings/water", json={"mode": "included"}).status_code == 404
    assert other.get("/api/v1/utility-bills").json() == []
