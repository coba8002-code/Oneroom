"""월세 납부 확인서 — 월세로 확정된 입금만, 입금일(KST) 기준 연도, 검토 대기·보증금 제외, 공제 판정 없음."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.routers import rent_certificate as router_mod
from tests.conftest import SAMPLES


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(router_mod, "_today", lambda: date(2027, 1, 20))


@pytest.fixture
def org(client, onboarded):
    o = onboarded["organization_id"]
    client.post("/api/v1/charges/generate", params={"organization_id": o, "period": "2026-11"})
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", files={"file": ("s.csv", raw)})
    client.post("/api/v1/matching/run", params={"organization_id": o})
    return o


def _lease(client, org, unit_no):
    return next(x["lease_id"] for x in client.get("/api/v1/leases", params={"organization_id": org}).json()
                if x["unit_no"] == unit_no)


def _cert(client, lease, year):
    return client.get(f"/api/v1/leases/{lease}/rent-certificate", params={"year": year})


def test_confirmed_rent_only(client, org, session_factory):
    r = _cert(client, _lease(client, org, "101"), 2026)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["tenant_name"] == "임차인A" and c["unit_no"] == "101"
    assert c["lines"] == [{"paid_on": "2026-11-01", "amount": 450000, "periods": ["2026-11"]}]
    assert (c["total"], c["count"]) == (450000, 1)
    assert c["pending_review_in_year"] == 4  # 아직 누구 것인지 모르는 입금 — 합계에는 없음
    assert c["bank_complete"] is False and c["bank_data_to"] is not None  # 11월 내역뿐 → 12월 말까지 없음
    assert "신고 확정 자료가 아닙니다" in c["notice"] and "95조의2" in c["law"]
    assert "010-" not in str(c)  # 연락처 없음
    with session_factory() as s:
        assert s.scalar(select(AuditLog).where(AuditLog.action == "rent_certificate.view")).detail == {"year": 2026}


def test_pending_partial_appears_after_approval(client, org):
    lease = _lease(client, org, "103")
    assert _cert(client, lease, 2026).json()["lines"] == []  # 검토 대기 20만 원은 넣지 않음
    q = client.get("/api/v1/matching/queue", params={"organization_id": org}).json()
    item = next(i for i in q if i["transaction"]["counterparty"] == "임차인C")
    client.post(f"/api/v1/transactions/{item['transaction']['id']}/decision", params={"organization_id": org},
                json={"lease_id": lease, "category": "rent"})
    c = _cert(client, lease, 2026).json()
    assert c["lines"] == [{"paid_on": "2026-11-10", "amount": 200000, "periods": ["2026-11"]}] and c["total"] == 200000


def test_year_without_payments_and_bad_years(client, org):
    lease = _lease(client, org, "101")  # 2025-03-01 ~ 2027-02-28
    c = _cert(client, lease, 2025).json()
    assert (c["lines"], c["total"]) == ([], 0)  # 그 해 확정 입금 없음 (지어내지 않음)
    assert _cert(client, lease, 2028).status_code == 409  # 오지 않은 해
    assert _cert(client, lease, 2020).status_code == 409  # 계약과 겹치지 않는 해


def test_other_org_cannot_issue(client, make_client, org):
    other, _ = make_client(org_name="남의 사업장")
    assert other.get(f"/api/v1/leases/{_lease(client, org, '101')}/rent-certificate",
                     params={"year": 2026}).status_code == 404
