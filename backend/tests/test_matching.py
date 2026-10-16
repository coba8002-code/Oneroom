"""입금 매칭 — PRD §8: 동일 금액/다른 입금자, 부분납부, 선납, 연체, 보증금 수령."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models import Deposit, Lease, Unit
from tests.conftest import SAMPLES


def _import(client, account_id, csv_text: str):
    res = client.post(f"/api/v1/bank-accounts/{account_id}/import",
                      files={"file": ("t.csv", csv_text.encode())}).json()
    assert res["errors"] == [], res
    return res


@pytest.fixture
def org(onboarded):
    return onboarded["organization_id"]


@pytest.fixture
def matched(client, onboarded, org):
    """2026-11 청구 생성 → 샘플 거래 가져오기 → 매칭 실행."""
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", files={"file": ("s.csv", raw)})
    return client.post("/api/v1/matching/run", params={"organization_id": org}).json()


def _queue(client, org):
    return client.get("/api/v1/matching/queue", params={"organization_id": org}).json()


def _find(queue, counterparty, amount=None):
    hits = [q for q in queue if q["transaction"]["counterparty"] == counterparty
            and (amount is None or q["transaction"]["amount"] == amount)]
    assert hits, f"{counterparty} 없음"
    return hits[0]


def _lease(client, org, unit_no):
    return next(x["lease_id"] for x in client.get("/api/v1/leases", params={"organization_id": org}).json()
                if x["unit_no"] == unit_no)


def _decide(client, org, txn_id, **body):
    return client.post(f"/api/v1/transactions/{txn_id}/decision", params={"organization_id": org}, json=body)


def _recv(client, org, as_of="2026-11-30"):
    return client.get("/api/v1/receivables", params={"organization_id": org, "as_of": as_of}).json()


def test_only_certain_matches_are_auto_confirmed(client, org, matched):
    # 이름+금액 일치: 101·102·201·202·303 → 자동. 나머지 4건은 검토 대기
    assert matched == {"auto_confirmed": 5, "pending": 4}
    q = _queue(client, org)
    assert len(q) == 4
    auto = client.get("/api/v1/allocations", params={"organization_id": org}).json()
    assert sorted(a["unit_no"] for a in auto) == ["101", "102", "201", "202", "303"]
    assert all(a["reason"].startswith("자동 확정") and a["confidence"] == 0.95 for a in auto)


def test_rerun_does_not_duplicate(client, org, matched):
    again = client.post("/api/v1/matching/run", params={"organization_id": org}).json()
    assert again == {"auto_confirmed": 0, "pending": 0}


def test_receivables_show_data_freshness_and_pending(client, org, matched):
    r = _recv(client, org)
    assert {i["unit_no"]: i["outstanding"] for i in r["items"]} == {"103": 420000, "301": 480000, "302": 450000}
    assert r["pending_review"] == 4  # 검토 대기가 있으면 '미납'이 아닐 수 있다
    assert r["bank_data_as_of"].startswith("2026-11-30T00:30")  # KST 09:30 → UTC
    late = next(i for i in r["items"] if i["unit_no"] == "103")
    assert late["days_past_due"] == 20  # 연체: 11-10 납부일, 11-30 기준


def test_same_amount_unknown_payer_needs_review_then_alias_learned(client, onboarded, org, matched):
    item = _find(_queue(client, org), "김OO")
    assert item["suggestion"]["lease_id"] is None
    assert "같은 금액 청구 여러 건" in item["suggestion"]["reason"]  # 201·202·302 → 추측하지 않음

    l302 = _lease(client, org, "302")
    res = _decide(client, org, item["transaction"]["id"], lease_id=l302, category="rent", remember_alias=True)
    assert res.status_code == 200, res.text
    assert "302" not in {i["unit_no"] for i in _recv(client, org)["items"]}

    # 다음 달: 같은 입금자명이면 별칭으로 자동 확정
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-12"})
    _import(client, onboarded["bank_account_id"], "거래일시,입금자,출금,입금\n2026-12-28 10:00,김 OO,,450000\n")
    assert client.post("/api/v1/matching/run", params={"organization_id": org}).json()["auto_confirmed"] == 1
    latest = client.get("/api/v1/allocations", params={"organization_id": org}).json()[0]
    assert latest["unit_no"] == "302" and "별칭" in latest["reason"]


def test_partial_payment_then_remainder(client, onboarded, org, matched):
    item = _find(_queue(client, org), "임차인C")
    s = item["suggestion"]
    assert s["unit_no"] == "103" and "부분납부" in s["reason"]
    assert _decide(client, org, item["transaction"]["id"], lease_id=s["lease_id"], category="rent").status_code == 200
    c103 = next(i for i in _recv(client, org)["items"] if i["unit_no"] == "103")
    assert (c103["paid"], c103["outstanding"]) == (200000, 220000)

    # 나머지 220,000 → 잔액과 같으므로 자동 확정, 청구 완납
    _import(client, onboarded["bank_account_id"], "거래일시,입금자,출금,입금\n2026-11-30 20:00,임차인C,,220000\n")
    assert client.post("/api/v1/matching/run", params={"organization_id": org}).json()["auto_confirmed"] == 1
    assert "103" not in {i["unit_no"] for i in _recv(client, org)["items"]}


def test_prepayment_becomes_credit_and_pays_next_month(client, org, matched):
    item = _find(_queue(client, org), "임차인D")  # 같은 날 두 번째 450,000
    assert "선납" in item["suggestion"]["reason"]
    _decide(client, org, item["transaction"]["id"], lease_id=item["suggestion"]["lease_id"], category="rent")
    assert {"unit_no": "201", "credit": 450000} in _recv(client, org)["credits"]

    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-12"})
    dec = _recv(client, org, "2026-12-31")
    assert "201" not in {i["unit_no"] for i in dec["items"] if i["period"] == "2026-12"}
    assert all(c["unit_no"] != "201" for c in dec["credits"])


def test_deposit_received_and_cancel(client, session):
    res = client.post("/api/v1/onboarding", json={
        "property": {"name": "보증금 테스트"},
        "units": [{"unit_no": "101", "tenant_name": "새임차인", "rent": 400000, "due_day": 10,
                   "start_date": "2026-12-01", "deposit": 5000000}],  # 보증금 아직 안 받음
    }).json()
    org = res["organization_id"]
    _import(client, res["bank_account_id"], "거래일시,입금자,출금,입금\n2026-11-30 23:30,새임차인,,5000000\n")  # KST
    client.post("/api/v1/matching/run", params={"organization_id": org})
    item = _queue(client, org)[0]
    assert item["suggestion"]["category"] == "deposit_in"
    alloc = _decide(client, org, item["transaction"]["id"], lease_id=item["suggestion"]["lease_id"],
                    category="deposit_in").json()

    dep = session.scalar(select(Deposit))
    session.refresh(dep)
    assert dep.received_at == date(2026, 11, 30)  # 통장 시각(KST) 그대로의 날짜
    assert _recv(client, org, "2026-12-31")["credits"] == []  # 보증금은 월세 선납이 아니다

    assert client.post(f"/api/v1/allocations/{alloc['id']}/cancel",
                       params={"organization_id": org}).status_code == 204
    session.refresh(dep)
    assert dep.received_at is None
    assert _queue(client, org)[0]["suggestion"] is None  # 다시 검토 대기, 제안 없이


def test_cancel_auto_confirmation_reopens_charge(client, org, matched):
    a101 = next(a for a in client.get("/api/v1/allocations", params={"organization_id": org}).json()
                if a["unit_no"] == "101")
    client.post(f"/api/v1/allocations/{a101['id']}/cancel", params={"organization_id": org})
    assert "101" in {i["unit_no"] for i in _recv(client, org)["items"]}
    item = _find(_queue(client, org), "임차인A")
    assert item["suggestion"] is None
    # 취소한 거래는 다시 돌려도 자동 확정하지 않는다
    assert client.post("/api/v1/matching/run", params={"organization_id": org}).json()["auto_confirmed"] == 0
    _decide(client, org, item["transaction"]["id"], lease_id=a101["lease_id"], category="rent")
    assert "101" not in {i["unit_no"] for i in _recv(client, org)["items"]}


def test_decision_guards(client, org, matched):
    item = _find(_queue(client, org), "김OO")
    tid = item["transaction"]["id"]
    assert _decide(client, org, tid, category="rent").status_code == 409  # 호실 없이 월세 불가
    assert _decide(client, "00000000-0000-0000-0000-000000000000", tid,
                   category="other").status_code == 404  # 다른 조직의 거래
    assert _decide(client, org, tid, category="personal").status_code == 200
    assert _decide(client, org, tid, category="other").status_code == 409  # 이미 확정


def test_ended_lease_not_matched(client, org, matched, session):
    lease = session.scalar(select(Lease).join(Unit).where(Unit.unit_no == "102"))
    lease.status = "ended"
    session.commit()
    assert all(x["unit_no"] != "102" for x in client.get("/api/v1/leases", params={"organization_id": org}).json())
