"""휴대폰 입금 알림 — 읽기·연결 주소·중복·매칭·통장 내역과 합치기·오늘 납부일."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import BankAccount, BankAlert, Transaction
from app.services import bank_alerts
from app.services.bank_alerts import parse

RECV = datetime(2026, 11, 5, 6, 0, tzinfo=timezone.utc)  # 2026-11-05 15:00 KST


# ── 문장 읽기 ──
@pytest.mark.parametrize("text, amount, name, balance, at", [
    ("[Web발신]\n[KB]11/05 14:23\n123456**789\n임차인B\n입금\n450,000\n잔액12,876,500",
     450000, "임차인B", 12876500, "2026-11-05T05:23:00+00:00"),
    ("[신한은행] 11/05 14:23 입금 450,000원 임차인B 잔액 12,876,500원", 450000, "임차인B", 12876500,
     "2026-11-05T05:23:00+00:00"),
    ("농협 입금450,000원 11/05 14:23 352-****-1234-56 임차인B 잔액12,876,500", 450000, "임차인B", 12876500,
     "2026-11-05T05:23:00+00:00"),
    ("임차인B님이 450,000원을 입금했어요", 450000, "임차인B", None, "2026-11-05T06:00:00+00:00"),
    ("카카오뱅크 입금 450,000원 임차인B → 내 통장 잔액 1,700,000원", 450000, "임차인B", 1700000,
     "2026-11-05T06:00:00+00:00"),
])
def test_parse_common_shapes(text, amount, name, balance, at):
    p = parse(text, RECV)
    assert (p.direction, p.amount, p.counterparty, p.balance_after, p.problem) == ("in", amount, name, balance, None)
    assert p.occurred_at.isoformat() == at


def test_parse_is_conservative():
    assert parse("광고 50% 할인 쿠폰", RECV).problem == "입금·출금을 알 수 없음"
    assert parse("입금 후 출금 450,000원", RECV).direction is None  # 둘 다 있으면 모름
    assert parse("입금 450,000원 임차인B 김철수", RECV).counterparty is None  # 이름 후보가 둘 → 비움
    assert parse("입금 알림 1,000원 2,000원", RECV).problem == "금액 후보가 여럿"
    assert parse("[우리] 11/05 14:23 출금 30,000원 GS25", RECV).direction == "out"


def test_parse_year_rollover_and_future_dates():
    jan1 = datetime(2027, 1, 1, 0, 5, tzinfo=timezone.utc)
    assert parse("12/31 23:50 입금 450,000원 이영희", jan1).occurred_at.year == 2026
    # 받은 시각보다 미래의 날짜는 잘못 읽은 것 → 받은 시각
    p = parse("12/25 10:00 입금 450,000원 이영희", RECV)
    assert p.occurred_at.year == 2025  # 연도 없는 미래 날짜는 작년으로
    p = parse("2026-12-25 10:00 입금 450,000원 이영희", RECV)
    assert p.occurred_at == RECV and not p.time_from_text


# ── 연결 주소 ──
@pytest.fixture
def org(onboarded):
    return onboarded["organization_id"]


def _token(client, onboarded):
    res = client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/alert-token",
                      params={"organization_id": onboarded["organization_id"]})
    assert res.status_code == 200, res.text
    return res.json()["token"]


def test_token_is_hashed_rotates_and_revokes(client, anon_client, onboarded, session):
    token = _token(client, onboarded)
    acct = session.get(BankAccount, uuid.UUID(onboarded["bank_account_id"]))
    assert acct.alert_token_hash and token not in acct.alert_token_hash  # 원문은 저장하지 않음
    accts = client.get("/api/v1/bank-accounts", params={"organization_id": onboarded["organization_id"]}).json()
    assert accts[0]["alert_since"] is not None

    hook = lambda t: anon_client.post(f"/api/v1/bank-alerts/hook/{t}", json={"text": "입금 1,000원 홍길동"})  # noqa: E731
    assert hook(token).status_code == 200
    assert hook("wrong-token").status_code == 404

    new = _token(client, onboarded)  # 새로 만들면 예전 주소는 끊김
    assert hook(token).status_code == 404 and hook(new).status_code == 200
    client.delete(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/alert-token",
                  params={"organization_id": onboarded["organization_id"]})
    assert hook(new).status_code == 404


def test_webhook_accepts_json_form_and_plain_text(client, anon_client, onboarded, session):
    token = _token(client, onboarded)
    url = f"/api/v1/bank-alerts/hook/{token}"
    r1 = anon_client.post(url, json={"title": "KB국민", "text": "입금 1,000원 홍길동"}).json()
    r2 = anon_client.post(url, data={"text": "입금 2,000원 김영희"}).json()
    r3 = anon_client.post(url, content="입금 3,000원 박철수".encode(), headers={"content-type": "text/plain"}).json()
    assert [r["status"] for r in (r1, r2, r3)] == ["created"] * 3
    assert set(r1) == {"ok", "status"}  # 장부 내용은 돌려주지 않음
    txns = session.scalars(select(Transaction).where(Transaction.source == "alert")).all()
    assert sorted(t.amount for t in txns) == [1000, 2000, 3000]
    assert anon_client.post(url, content=b"x" * 9000).status_code == 413
    assert anon_client.post(url, json={"text": ""}).status_code == 422


# ── 받기 → 매칭 ──
def _account(session, onboarded):
    return session.get(BankAccount, uuid.UUID(onboarded["bank_account_id"]))


def _gen(client, org, period="2026-11"):
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": period})


def test_alert_auto_confirms_only_certain_match(client, onboarded, org, session):
    _gen(client, org)
    acct = _account(session, onboarded)
    a = bank_alerts.receive(session, acct, "[KB]11/05 14:23 입금 450,000원 임차인B 잔액12,876,500", RECV)
    assert a.status == "created"
    allocs = client.get("/api/v1/allocations", params={"organization_id": org}).json()
    assert [x["unit_no"] for x in allocs] == ["102"]  # 이름+금액 → 자동 확정

    b = bank_alerts.receive(session, acct, "임차인님이 450,000원을 입금했어요", RECV)  # 모르는 이름
    assert b.status == "created"
    queue = client.get("/api/v1/matching/queue", params={"organization_id": org}).json()
    assert len(queue) == 1  # 금액만 맞으면 검토 대기


def test_duplicate_alerts_are_ignored(client, onboarded, org, session):
    acct = _account(session, onboarded)
    text = "[KB]11/05 14:23 입금 450,000원 임차인B 잔액12,876,500"
    assert bank_alerts.receive(session, acct, text, RECV).status == "created"
    # 같은 거래의 문자 + 앱 푸시 (문장은 달라도 잔액이 같음)
    soon = datetime(2026, 11, 5, 5, 23, 40, tzinfo=timezone.utc)  # 몇십 초 뒤 도착
    assert bank_alerts.receive(session, acct, "[국민] 임차인B 입금 450,000원 잔액 12,876,500원",
                               soon).status == "duplicate"
    # 잔액 없는 알림이 같은 이름으로 곧바로 또 오면 같은 거래
    assert bank_alerts.receive(session, acct, "임차인B님이 450,000원을 입금했어요", soon).status == "duplicate"
    # 같은 금액·다른 사람·다른 잔액 → 별개 입금
    assert bank_alerts.receive(session, acct, "[KB]11/05 14:24 입금 450,000원 임차인A 잔액13,326,500",
                               RECV).status == "created"
    assert bank_alerts.receive(session, acct, "[KB]11/05 14:25 출금 30,000원 GS25", RECV).status == "outgoing"
    assert bank_alerts.receive(session, acct, "광고", RECV).status == "unparsed"
    assert session.query(Transaction).filter_by(source="alert").count() == 2
    assert session.query(BankAlert).count() == 6
    recent = client.get("/api/v1/bank-alerts", params={"organization_id": org}).json()
    assert recent[0]["status"] in {"created", "duplicate", "outgoing", "unparsed"} and len(recent) == 6


def test_alerts_do_not_count_as_bank_coverage(client, onboarded, org, session):
    """알림은 '들어왔다'의 증거일 뿐 — 은행 내역 기간·미납 판단 근거로 쓰지 않는다."""
    bank_alerts.receive(session, _account(session, onboarded), "입금 450,000원 임차인B", RECV)
    r = client.get("/api/v1/receivables", params={"organization_id": org, "as_of": "2026-11-30"}).json()
    assert r["bank_data_as_of"] is None
    dash = client.get("/api/v1/dashboard", params={"organization_id": org, "as_of": "2026-11-05"}).json()
    assert any(a["kind"] == "bank_none" for a in dash["attention"])
    assert dash["money"]["bank_covered"] is False


def test_preview_does_not_store(client, org, session):
    res = client.post("/api/v1/bank-alerts/preview", params={"organization_id": org},
                      json={"text": "[신한] 입금 450,000원 임차인B"}).json()
    assert (res["direction"], res["amount"], res["counterparty"]) == ("in", 450000, "임차인B")
    assert session.query(BankAlert).count() == 0


# ── 통장 내역 파일과 합치기 ──
HEADER = "거래일시,적요,입금자,출금,입금,잔액\n"


def _import(client, onboarded, body: str):
    res = client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import",
                      files={"file": ("t.csv", (HEADER + body).encode())})
    assert res.status_code == 200, res.text
    return res.json()


def test_statement_merges_into_alert_and_keeps_confirmation(client, onboarded, org, session):
    _gen(client, org)
    bank_alerts.receive(session, _account(session, onboarded), "[KB]11/05 14:23 입금 450,000원 임차인B", RECV)
    res = _import(client, onboarded, "2026-11-05 14:23:41,타행이체,임차인B,,450000,12876500\n"
                                     "2026-11-05 16:00:00,타행이체,임차인A,,450000,13326500\n")
    assert (res["inserted"], res["merged_alerts"], res["alerts_without_statement"]) == (1, 1, 0)
    txns = session.scalars(select(Transaction).order_by(Transaction.occurred_at)).all()
    assert len(txns) == 2 and {t.source for t in txns} == {"statement"}
    assert txns[0].balance_after == 12876500 and txns[0].occurred_at.second == 41  # 내역 값으로 고침
    allocs = client.get("/api/v1/allocations", params={"organization_id": org}).json()
    assert [x["unit_no"] for x in allocs] == ["102"]  # 알림 때 한 확정은 그대로
    # 같은 파일 다시 → 중복
    again = _import(client, onboarded, "2026-11-05 14:23:41,타행이체,임차인B,,450000,12876500\n")
    assert (again["inserted"], again["duplicates"], again["merged_alerts"]) == (0, 1, 0)
    r = client.get("/api/v1/receivables", params={"organization_id": org, "as_of": "2026-11-30"}).json()
    assert r["bank_data_as_of"].startswith("2026-11-05T07:00")  # 이제는 내역이 있으니 기간이 잡힘


def test_date_only_statement_merges_same_day_and_prefers_same_name(client, onboarded, org, session):
    acct = _account(session, onboarded)
    bank_alerts.receive(session, acct, "[KB]11/05 09:00 입금 450,000원 임차인A", RECV)
    bank_alerts.receive(session, acct, "[KB]11/05 14:00 입금 450,000원 임차인B", RECV)
    res = _import(client, onboarded, "2026-11-05,타행이체,임차인B,,450000,1\n")
    assert res["merged_alerts"] == 1 and res["alerts_without_statement"] == 1  # 임차인A 알림은 내역에 없음 → 확인
    left = session.scalar(select(Transaction).where(Transaction.source == "alert"))
    assert left.counterparty == "임차인A"


def test_late_alert_after_statement_is_duplicate(client, onboarded, session):
    _import(client, onboarded, "2026-11-05 14:23:00,타행이체,임차인B,,450000,12876500\n")
    a = bank_alerts.receive(session, _account(session, onboarded), "[KB]11/05 14:23 입금 450,000원 임차인B", RECV)
    assert a.status == "duplicate"
    assert session.query(Transaction).count() == 1


# ── 홈: 오늘 납부일 ──
def test_due_today_shows_alert_payment(client, onboarded, org, session):
    _gen(client, org)
    dash = lambda: client.get("/api/v1/dashboard", params={"organization_id": org, "as_of": "2026-11-05"}).json()  # noqa: E731
    before = dash()["due_today"]
    assert [(d["unit_no"], d["status"]) for d in before] == [("102", "not_yet")]
    bank_alerts.receive(session, _account(session, onboarded), "[KB]11/05 14:23 입금 450,000원 임차인B", RECV)
    after = dash()["due_today"][0]
    assert (after["status"], after["via"], after["paid"]) == ("paid", "alert", 450000)
    assert after["paid_at"].startswith("2026-11-05T05:23")
