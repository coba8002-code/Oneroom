"""운영비 분리 — PRD §8: 생활비가 임대 순운영수익에 포함되지 않음, 보증금 반환."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models import Deposit
from tests.conftest import SAMPLES


def _p(org, **kw):
    return {"organization_id": org, **kw}


def _import(client, account_id, csv_text):
    res = client.post(f"/api/v1/bank-accounts/{account_id}/import", files={"file": ("t.csv", csv_text.encode())}).json()
    assert res["errors"] == [], res
    return res


@pytest.fixture
def org(onboarded):
    return onboarded["organization_id"]


@pytest.fixture
def classified(client, onboarded, org):
    client.post("/api/v1/charges/generate", params=_p(org, period="2026-11"))
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", files={"file": ("s.csv", raw)})
    client.post("/api/v1/matching/run", params=_p(org))
    return client.post("/api/v1/expenses/classify", params=_p(org)).json()


def _queue(client, org):
    return client.get("/api/v1/expenses/queue", params=_p(org)).json()


def _item(client, org, counterparty):
    return next(q for q in _queue(client, org) if q["transaction"]["counterparty"] == counterparty)


def _decide(client, org, txn_id, splits, **kw):
    return client.post(f"/api/v1/transactions/{txn_id}/expense-decision", params=_p(org),
                       json={"splits": splits, **kw})


def _report(client, org, period="2026-11"):
    return client.get("/api/v1/reports/monthly", params=_p(org, period=period)).json()


def test_keywords_only_suggest_never_auto_confirm(client, org, classified):
    assert classified == {"auto_confirmed": 0, "pending": 5}
    s = {q["transaction"]["counterparty"]: q["suggestion"]["category"] for q in _queue(client, org)}
    assert s == {"편의점": "personal", "한국전력공사": "common_electricity", "수도사업소": "water",
                 "청소업체": "cleaning", "마트": "personal"}
    assert "주인세대 전기일 수도" in _item(client, org, "한국전력공사")["suggestion"]["reason"]


def test_personal_and_owner_costs_excluded_from_noi(client, org, classified):
    for name, cat in (("편의점", "personal"), ("한국전력공사", "common_electricity"),
                      ("수도사업소", "water"), ("청소업체", "cleaning")):
        it = _item(client, org, name)
        assert _decide(client, org, it["transaction"]["id"],
                       [{"category": cat, "amount": it["transaction"]["amount"]}]).status_code == 200
    mart = _item(client, org, "마트")  # 87,400 생활비·주인세대 혼합
    res = _decide(client, org, mart["transaction"]["id"],
                  [{"category": "personal", "amount": 60000}, {"category": "owner_household", "amount": 27400}])
    assert res.status_code == 200 and len(res.json()["splits"]) == 2

    r = _report(client, org)
    assert r["operating_total"] == 128300 + 64200 + 150000
    assert r["excluded"]["personal"] == 23500 + 60000
    assert r["excluded"]["owner_household"] == 27400
    assert "personal" not in r["operating"] and "owner_household" not in r["operating"]
    assert r["rent_received"] == 2_260_000  # 자동 확정 5건
    assert r["noi"] == 2_260_000 - 342_500
    assert r["unconfirmed_out"] == 0
    assert r["unconfirmed_in"] == 4 and r["complete"] is False  # 입금 검토 대기 남음 → 확정 전 수치


def test_split_must_add_up(client, org, classified):
    mart = _item(client, org, "마트")
    res = _decide(client, org, mart["transaction"]["id"],
                  [{"category": "personal", "amount": 60000}, {"category": "owner_household", "amount": 20000}])
    assert res.status_code == 409 and "합계" in res.json()["detail"]
    assert _queue(client, org)  # 아무것도 확정 안 됨


def test_remembered_rule_auto_confirms_next_time_with_ratio(client, onboarded, org, classified):
    elec = _item(client, org, "한국전력공사")
    _decide(client, org, elec["transaction"]["id"],
            [{"category": "common_electricity", "amount": 128300}], remember=True)
    mart = _item(client, org, "마트")
    _decide(client, org, mart["transaction"]["id"],
            [{"category": "personal", "amount": 61180}, {"category": "owner_household", "amount": 26220}],
            remember=True)  # 70% / 30%
    rules = {r["label"]: r["splits"] for r in client.get("/api/v1/expense-rules", params=_p(org)).json()}
    assert rules["마트"] == [{"category": "personal", "bp": 7000}, {"category": "owner_household", "bp": 3000}]

    _import(client, onboarded["bank_account_id"],
            "거래일시,적요,입금자,출금,입금\n"
            "2026-12-05 10:00,자동이체,한국전력공사,131000,\n"
            "2026-12-07 18:00,카드결제,마트,10001,\n")
    assert client.post("/api/v1/expenses/classify", params=_p(org)).json() == {"auto_confirmed": 2, "pending": 0}
    dec = {(e["category"], e["amount"]) for e in
           client.get("/api/v1/expenses", params=_p(org, period="2026-12")).json()}
    assert dec == {("common_electricity", 131000), ("personal", 7001), ("owner_household", 3000)}
    assert sum(a for _, a in dec) == 131000 + 10001  # 반올림 차이 없이 합계 보존


def test_cancel_removes_expenses_and_requeues(client, org, classified):
    elec = _item(client, org, "한국전력공사")
    tid = elec["transaction"]["id"]
    _decide(client, org, tid, [{"category": "common_electricity", "amount": 128300}])
    assert _report(client, org)["operating_total"] == 128300
    assert client.post(f"/api/v1/transactions/{tid}/expense-cancel", params=_p(org)).status_code == 204
    assert _report(client, org)["operating_total"] == 0
    back = _item(client, org, "한국전력공사")
    assert back["suggestion"] is None
    # 입금 화면의 취소로는 출금을 취소할 수 없다 (지출 원장이 남는 것 방지)
    _decide(client, org, tid, [{"category": "common_electricity", "amount": 128300}])
    confirmed = client.get("/api/v1/expenses/confirmed", params=_p(org)).json()
    assert confirmed[0]["splits"][0]["category"] == "common_electricity"


def test_inbound_cancel_rejects_outbound_allocation(client, org, classified, session):
    from app.models import TransactionAllocation
    elec = _item(client, org, "한국전력공사")
    _decide(client, org, elec["transaction"]["id"], [{"category": "common_electricity", "amount": 128300}])
    alloc = session.scalar(select(TransactionAllocation).where(
        TransactionAllocation.category == "common_electricity", TransactionAllocation.review_status == "approved"))
    assert client.post(f"/api/v1/allocations/{alloc.id}/cancel", params=_p(org)).status_code == 409


def test_deposit_return_is_not_an_expense(client, session):
    res = client.post("/api/v1/onboarding", json={
        "property": {"name": "반환 테스트"},
        "units": [{"unit_no": "101", "tenant_name": "퇴거자", "rent": 400000, "due_day": 10,
                   "start_date": "2024-12-01", "end_date": "2026-11-30", "deposit": 5000000,
                   "deposit_received_on": "2024-11-25"}],
    }).json()
    org = res["organization_id"]
    _import(client, res["bank_account_id"], "거래일시,적요,입금자,출금,입금\n2026-11-30 15:00,이체,퇴거자,5000000,\n")
    client.post("/api/v1/expenses/classify", params=_p(org))
    it = _queue(client, org)[0]
    assert it["suggestion"]["category"] == "deposit_out"
    lease_id = it["suggestion"]["lease_id"]
    assert _decide(client, org, it["transaction"]["id"],
                   [{"category": "deposit_out", "amount": 5000000}], lease_id=lease_id).status_code == 200

    dep = session.scalar(select(Deposit))
    session.refresh(dep)
    assert dep.returned_at == date(2026, 11, 30)
    r = _report(client, org)
    assert r["operating_total"] == 0 and r["noi"] == 0
    assert r["excluded"]["deposit_out"] == 5000000

    client.post(f"/api/v1/transactions/{it['transaction']['id']}/expense-cancel", params=_p(org))
    session.refresh(dep)
    assert dep.returned_at is None


def test_manual_cash_expense(client, org, classified):
    u203 = next(u["unit_id"] for u in client.get("/api/v1/units", params=_p(org)).json() if u["unit_no"] == "203")
    res = client.post("/api/v1/expenses", params=_p(org), json={
        "category": "repair", "amount": 50000, "spent_on": "2026-11-20", "memo": "203 수전 교체(현금)",
        "unit_id": u203})
    assert res.status_code == 201 and res.json()["unit_no"] == "203"
    assert _report(client, org)["operating"]["repair"] == 50000
    assert client.post("/api/v1/expenses", params=_p(org), json={
        "category": "deposit_out", "amount": 1, "spent_on": "2026-11-20"}).status_code == 422
    assert client.delete(f"/api/v1/expenses/{res.json()['id']}", params=_p(org)).status_code == 204
    assert _report(client, org)["operating"]["repair"] == 0


def test_bank_expense_cannot_be_deleted_as_manual(client, org, classified):
    elec = _item(client, org, "한국전력공사")
    _decide(client, org, elec["transaction"]["id"], [{"category": "common_electricity", "amount": 128300}])
    e = client.get("/api/v1/expenses", params=_p(org, period="2026-11")).json()[0]
    assert e["from_bank"] is True
    assert client.delete(f"/api/v1/expenses/{e['id']}", params=_p(org)).status_code == 409


def test_month_boundary_is_kst(client, onboarded, org):
    _import(client, onboarded["bank_account_id"],
            "거래일시,적요,입금자,출금,입금\n"
            "2026-11-30 23:30,이체,청소업체,1000,\n"
            "2026-12-01 00:10,이체,청소업체,2000,\n")
    client.post("/api/v1/expenses/classify", params=_p(org))
    for it in _queue(client, org):
        _decide(client, org, it["transaction"]["id"],
                [{"category": "cleaning", "amount": it["transaction"]["amount"]}])
    assert _report(client, org, "2026-11")["operating"]["cleaning"] == 1000
    assert _report(client, org, "2026-12")["operating"]["cleaning"] == 2000


def test_rule_delete(client, org, classified):
    elec = _item(client, org, "한국전력공사")
    _decide(client, org, elec["transaction"]["id"], [{"category": "common_electricity", "amount": 128300}],
            remember=True)
    rule = client.get("/api/v1/expense-rules", params=_p(org)).json()[0]
    assert client.delete(f"/api/v1/expense-rules/{rule['id']}", params=_p(org)).status_code == 204
    assert client.get("/api/v1/expense-rules", params=_p(org)).json() == []


def test_inbound_confirmed_list_excludes_expenses(client, org, classified):
    elec = _item(client, org, "한국전력공사")
    _decide(client, org, elec["transaction"]["id"], [{"category": "common_electricity", "amount": 128300}])
    inbound = client.get("/api/v1/allocations", params=_p(org)).json()
    assert inbound and all(a["transaction"]["direction"] == "in" for a in inbound)


def test_month_without_bank_data_or_charges_is_unknown_not_zero(client, onboarded):
    """은행 내역이 그 달에 닿지 않으면 입금·운영비·NOI 는 모름(null). 0 으로 채우지 않는다 (CLAUDE.md 규칙 7)."""
    org = onboarded["organization_id"]
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", params=_p(org), files={"file": ("s.csv", raw)})
    client.post("/api/v1/charges/generate", params=_p(org, period="2026-11"))
    nov = _report(client, org, "2026-11")
    assert nov["bank_covered"] and nov["charges_ready"] and nov["rent_charged"] == 3_610_000
    dec = _report(client, org, "2026-12")  # 은행 내역은 11-30 까지, 12월 청구도 아직
    assert dec["bank_covered"] is False and dec["charges_ready"] is False
    assert dec["rent_charged"] is None and dec["rent_received"] is None
    assert dec["operating_total"] is None and dec["noi"] is None
    assert set(dec["operating"].values()) == {None} and set(dec["excluded"].values()) == {None}
    oct_ = _report(client, org, "2026-10")  # 은행 내역은 11-01 부터 — 그 전 달도 모름
    assert oct_["bank_covered"] is False and oct_["noi"] is None
