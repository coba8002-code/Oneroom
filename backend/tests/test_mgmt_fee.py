"""정액 관리비 — 계약에 월세와 따로 적고(모르면 비움), 같은 납부일에 관리비 청구를 따로 만든다.
한 달 치(월세+관리비)를 한 번에 보내면 자동 확정, 납부 확인서는 월세만, 결산은 관리비를 따로."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.routers import rent_certificate as cert_router
from app.services.contract_extract import extract
from tests.conftest import SAMPLES
from tests.test_contracts import PNG, _upload

P = "2026-11"


def _p(org, **kw):
    return {"organization_id": org, **kw}


def _lease(client, org, unit_no):
    return next(x["lease_id"] for x in client.get("/api/v1/leases", params=_p(org)).json() if x["unit_no"] == unit_no)


def _amounts(client, lease_id, rent, mgmt_fee):
    return client.put(f"/api/v1/leases/{lease_id}/amounts", json={"rent": rent, "mgmt_fee": mgmt_fee})


def _charges(client, org, period=P):
    return {(c["unit_no"], c["kind"]): c for c in client.get("/api/v1/charges", params=_p(org, period=period)).json()}


@pytest.fixture
def org(client, onboarded):
    return onboarded["organization_id"]


def test_split_existing_rent_into_rent_and_mgmt(client, org, session):
    lease = _lease(client, org, "101")
    res = _amounts(client, lease, 400_000, 50_000)  # 관리비가 섞여 있던 450,000 을 나눠 적기
    assert res.status_code == 200 and res.json()["mgmt_fee"] == 50_000
    log = session.scalar(select(AuditLog).where(AuditLog.action == "lease.amounts"))
    assert log.detail == {"before": {"rent": 450_000, "mgmt_fee": None}, "after": {"rent": 400_000, "mgmt_fee": 50_000}}
    client.post("/api/v1/charges/generate", params=_p(org, period=P))
    rows = _charges(client, org)
    assert rows[("101", "rent")]["amount"] == 400_000 and rows[("101", "mgmt")]["amount"] == 50_000
    assert rows[("101", "mgmt")]["due_date"] == rows[("101", "rent")]["due_date"]
    assert ("102", "mgmt") not in rows  # 따로 적지 않은 계약은 관리비 청구 없음 (모름)
    m = client.get("/api/v1/reports/monthly", params=_p(org, period=P)).json()
    assert (m["rent_charged"], m["mgmt_charged"]) == (3_560_000, 50_000)
    # 다시 만들어도 중복 없음
    again = client.post("/api/v1/charges/generate", params=_p(org, period=P)).json()
    assert again["created"] == 0 and len(_charges(client, org)) == 9


def test_zero_or_unknown_makes_no_mgmt_charge(client, org):
    assert _amounts(client, _lease(client, org, "101"), 450_000, 0).status_code == 200  # 관리비 없음
    client.post("/api/v1/charges/generate", params=_p(org, period=P))
    assert {k for k in _charges(client, org) if k[1] == "mgmt"} == set()
    assert client.get("/api/v1/reports/monthly", params=_p(org, period=P)).json()["mgmt_charged"] is None


def test_amounts_validation_and_isolation(client, make_client, org):
    lease = _lease(client, org, "101")
    assert _amounts(client, lease, 400_000, -1).status_code == 409
    other, _ = make_client(org_name="남의 사업장")
    assert _amounts(other, lease, 1, 1).status_code == 404


def test_amounts_apply_from_next_charge(client, org):
    client.post("/api/v1/charges/generate", params=_p(org, period=P))
    _amounts(client, _lease(client, org, "101"), 400_000, 50_000)
    client.post("/api/v1/charges/generate", params=_p(org, period=P))
    rows = _charges(client, org)
    assert rows[("101", "rent")]["amount"] == 450_000 and ("101", "mgmt") not in rows  # 이미 청구한 달은 그대로
    client.post("/api/v1/charges/generate", params=_p(org, period="2026-12"))
    dec = _charges(client, org, "2026-12")
    assert (dec[("101", "rent")]["amount"], dec[("101", "mgmt")]["amount"]) == (400_000, 50_000)


def test_one_payment_for_rent_and_mgmt_auto_confirms(client, onboarded, org, monkeypatch):
    lease = _lease(client, org, "101")
    _amounts(client, lease, 400_000, 50_000)
    client.post("/api/v1/charges/generate", params=_p(org, period=P))
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import",
                files={"file": ("s.csv", (SAMPLES / "bank_transactions_sample.csv").read_bytes())})
    client.post("/api/v1/matching/run", params=_p(org))
    queue = client.get("/api/v1/matching/queue", params=_p(org)).json()
    assert not any(i["transaction"]["counterparty"] == "임차인A" for i in queue)  # 450,000 = 월세+관리비 → 자동 확정
    rows = _charges(client, org)
    assert rows[("101", "rent")]["status"] == "paid" and rows[("101", "mgmt")]["status"] == "paid"
    m = client.get("/api/v1/reports/monthly", params=_p(org, period=P)).json()
    assert m["mgmt_received"] == 50_000
    # 확정 목록은 한 번에 들어온 돈을 월세·관리비로 나눈 결과를 함께 보여 준다 (관리는 따로, 보기는 함께)
    a = next(x for x in client.get("/api/v1/allocations", params=_p(org)).json()
             if x["transaction"]["counterparty"] == "임차인A")
    assert a["amount"] == 450_000 and a["applied"] == [
        {"period": P, "kind": "rent", "amount": 400_000}, {"period": P, "kind": "mgmt", "amount": 50_000}]
    # 납부 확인서는 월세 몫만 (관리비는 월세 세액공제 대상이 아님)
    monkeypatch.setattr(cert_router, "_today", lambda: date(2027, 1, 10))
    c = client.get(f"/api/v1/leases/{lease}/rent-certificate", params={"year": 2026}).json()
    assert c["lines"] == [{"paid_on": "2026-11-01", "amount": 400_000, "periods": [P]}] and c["mgmt_unknown"] is False
    c102 = client.get(f"/api/v1/leases/{_lease(client, org, '102')}/rent-certificate", params={"year": 2026}).json()
    assert c102["mgmt_unknown"] is True  # 따로 적지 않음 → 월세에 관리비가 섞여 있을 수 있다고 알림


def test_rent_only_payment_waits_for_review(client, onboarded, org):
    _amounts(client, _lease(client, org, "101"), 400_000, 50_000)
    client.post("/api/v1/charges/generate", params=_p(org, period=P))
    raw = (SAMPLES / "bank_transactions_sample.csv").read_text(encoding="utf-8").replace(
        "2026-11-01 09:12:33,타행이체,임차인A,,450000,", "2026-11-01 09:12:33,타행이체,임차인A,,400000,")
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", files={"file": ("s.csv", raw.encode())})
    client.post("/api/v1/matching/run", params=_p(org))
    item = next(i for i in client.get("/api/v1/matching/queue", params=_p(org)).json()
                if i["transaction"]["counterparty"] == "임차인A")
    assert "부분납부" in item["suggestion"]["reason"]  # 한 달 치보다 적음 → 확정은 관리자가 (규칙 1)


def test_notice_variables_include_mgmt(client, org):
    _amounts(client, _lease(client, org, "101"), 400_000, 50_000)
    client.post("/api/v1/charges/generate", params=_p(org, period=P))
    client.put("/api/v1/notification-settings", params=_p(org), json={
        "grace_days": 5, "rent_template": "{호실} 월세 {금액} 관리비 {관리비} 합계 {합계}", "overdue_template": "{미납액}"})
    client.post("/api/v1/notifications/rent-notices", params=_p(org, period=P))
    bodies = {n["unit_no"]: n["body"] for n in client.get("/api/v1/notifications", params=_p(org)).json()}
    assert bodies["101"] == "101 월세 400,000 관리비 50,000 합계 450,000"
    assert bodies["102"] == "102 월세 450,000 관리비 — 합계 —"  # 모르면 0 으로 쓰지 않는다


def test_ocr_candidate_and_verify(client, org):
    f = extract("월세 금 사십만원정 매월 1일 지급. 관리비 (정액인 경우) 총액 금 50,000원 (수도료, 인터넷 사용료)")
    assert f["rent"]["value"] == 400_000 and f["mgmt_fee"]["value"] == 50_000
    assert extract("월세 금 사십만원정")["mgmt_fee"]["value"] is None  # 없으면 비움
    lease = _lease(client, org, "101")
    body = {"deposit": 5_000_000, "rent": 400_000, "due_day": 1, "start_date": "2025-03-01", "end_date": "2027-02-28"}
    doc = _upload(client, org, lease).json()
    res = client.post(f"/api/v1/documents/{doc['id']}/verify", params=_p(org), json={**body, "mgmt_fee": 50_000})
    assert res.status_code == 200 and "mgmt_fee" in res.json()["verified_fields"]["changed"]
    # 관리비를 보내지 않은 검수는 기존 값을 지우지 않는다
    doc2 = _upload(client, org, lease, PNG + b"2").json()
    client.post(f"/api/v1/documents/{doc2['id']}/verify", params=_p(org), json=body)
    c = next(x for x in client.get("/api/v1/contracts", params=_p(org)).json() if x["unit_no"] == "101")
    assert (c["rent"], c["mgmt_fee"]) == (400_000, 50_000)


def test_new_lease_and_vacancy_ad(client, org):
    units = {u["unit_no"]: u["unit_id"] for u in client.get("/api/v1/units", params=_p(org)).json()}
    d = client.put(f"/api/v1/vacancies/{units['203']}/listing", json={
        "asking_deposit": 5_000_000, "asking_rent": 400_000, "asking_mgmt_fee": 50_000,
        "mgmt_includes": "수도·인터넷"}).json()
    assert "관리비 5만원 (포함: 수도·인터넷)" in d["ad_text"]
    res = client.post(f"/api/v1/units/{units['203']}/leases", json={
        "tenant_name": "새임차인", "deposit": 5_000_000, "rent": 400_000, "mgmt_fee": 50_000, "due_day": 10,
        "start_date": "2026-11-01"})
    assert res.status_code == 201, res.text
    client.post("/api/v1/charges/generate", params=_p(org, period=P))
    assert _charges(client, org)[("203", "mgmt")]["amount"] == 50_000


def test_onboarding_csv_mgmt_column_is_optional(make_client):
    c, _ = make_client(org_name="새 사업장", email="new@example.com")
    raw = ("호실,용도,임차인,보증금,월세,관리비,납부일,계약시작\n"
           "101,임대,가,1000000,400000,50000,1,2026-01-01\n"
           "102,임대,나,1000000,450000,,5,2026-01-01\n").encode()
    units = {u["unit_no"]: u for u in c.post("/api/v1/onboarding/csv-preview", files={"file": ("u.csv", raw)}).json()["units"]}
    assert (units["101"]["mgmt_fee"], units["102"]["mgmt_fee"]) == (50_000, None)
