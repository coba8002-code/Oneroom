"""요금제·정기결제(토스 빌링 가짜) · 셀프 신고 도우미 · 세무사 공유 링크."""
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from app.models import BillingPayment, Subscription
from app.services import billing, self_filing
from tests.conftest import SAMPLES


class FakeToss:
    """토스페이먼츠 빌링 API 흉내. fail=True 면 결제를 거절한다."""

    def __init__(self):
        self.fail = False
        self.charges: list[dict] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert req.headers["Authorization"].startswith("Basic ")
        if req.url.path == "/v1/billing/authorizations/issue":
            return httpx.Response(200, json={"billingKey": "bk_test_1", "customerKey": body["customerKey"],
                                             "cardCompany": "신한", "cardNumber": "43301234****123*4321"})
        if self.fail:
            return httpx.Response(400, json={"code": "REJECT_CARD_PAYMENT", "message": "한도 초과"})
        self.charges.append(body)
        return httpx.Response(200, json={"status": "DONE", "paymentKey": f"pk_{len(self.charges)}"})


@pytest.fixture
def toss(monkeypatch):
    fake = FakeToss()
    monkeypatch.setattr(billing, "enabled", lambda: True)
    monkeypatch.setattr(billing, "client", lambda: billing.TossClient("test_sk", "https://api.test",
                                                                         httpx.MockTransport(fake.handler)))
    return fake


def _units(n: int, start: int = 1) -> list[dict]:
    return [{"unit_no": str(100 + start + i), "use_type": "rental"} for i in range(n)]


def _onboard(client, units, name="건물"):
    return client.post("/api/v1/onboarding", json={"property": {"name": name}, "units": units})


def _expire_trial(session_factory):
    with session_factory() as s:
        for sub in s.query(Subscription).all():
            sub.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        s.commit()


def test_prices():
    assert billing.monthly_price(3) == 9_900
    assert billing.monthly_price(10) == 9_900
    assert billing.monthly_price(12) == 9_900 + 2 * 800
    assert billing.price(12, "yearly") == (9_900 + 1_600) * 10
    assert billing.add_months(datetime(2026, 1, 31, tzinfo=timezone.utc), 1).day == 28


def test_billing_off_means_no_limits(client):
    assert _onboard(client, _units(5)).status_code == 201  # 결제 키가 없으면 한도 없음
    st = client.get("/api/v1/billing").json()
    assert st["enabled"] is False and st["unlimited"] is True


def test_trial_then_free_limit(client, toss, session_factory):
    st = client.get("/api/v1/billing").json()
    assert st["effective"] == "trial" and st["unlimited"] is True
    assert _onboard(client, _units(5)).status_code == 201  # 체험 중엔 한도 없음
    _expire_trial(session_factory)
    res = _onboard(client, _units(1, 10), name="2동")
    assert res.status_code == 402 and "3개" in res.json()["detail"]
    # 이미 넣은 장부는 계속 볼 수 있다
    assert client.get("/api/v1/billing").json()["units"] == 5


def test_free_allows_three_units(client, toss, session_factory):
    client.get("/api/v1/billing")
    _expire_trial(session_factory)
    owner_unit = [{"unit_no": "401", "use_type": "owner"}]
    assert _onboard(client, _units(3) + owner_unit).status_code == 201  # 주인세대는 세지 않음
    assert _onboard(client, _units(1, 20), name="2동").status_code == 402


def test_subscribe_renew_cancel(client, toss, session_factory):
    st = client.get("/api/v1/billing").json()
    assert client.post("/api/v1/billing/subscribe", json={"cycle": "monthly"}).status_code == 409  # 카드 먼저
    assert client.post("/api/v1/billing/card", json={"auth_key": "a", "customer_key": "wrong"}).status_code == 409
    assert client.post("/api/v1/billing/card", json={"auth_key": "a", "customer_key": st["customer_key"]}).status_code == 200
    _onboard(client, _units(12))
    res = client.post("/api/v1/billing/subscribe", json={"cycle": "monthly"})
    assert res.status_code == 200 and res.json()["amount"] == 9_900 + 2 * 800
    assert toss.charges[-1]["amount"] == 11_500 and toss.charges[-1]["orderName"] == "ROOMAX 월 이용료"
    st = client.get("/api/v1/billing").json()
    assert st["effective"] == "basic" and st["card"] == "신한 ****4321" and st["payments"][0]["status"] == "done"
    assert "billing_key" not in json.dumps(st) and "bk_test" not in json.dumps(st)

    # 기간이 끝나면 매일 작업이 다시 결제
    with session_factory() as s:
        sub = s.query(Subscription).one()
        sub.current_period_end = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
        assert billing.renew_due(s, datetime.now(timezone.utc)) == {"renewed": 1, "failed": 0}
        assert s.query(Subscription).one().current_period_end.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    # 결제 실패 → 유예(그대로 사용) → 7일 뒤 무료 한도
    toss.fail = True
    with session_factory() as s:
        sub = s.query(Subscription).one()
        sub.current_period_end = datetime.now(timezone.utc) - timedelta(minutes=1)
        sub.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        s.commit()
        assert billing.renew_due(s, datetime.now(timezone.utc)) == {"renewed": 0, "failed": 1}
    assert client.get("/api/v1/billing").json()["effective"] == "grace"
    with session_factory() as s:
        sub = s.query(Subscription).one()
        sub.past_due_since = datetime.now(timezone.utc) - timedelta(days=8)
        s.commit()
        assert s.query(BillingPayment).filter_by(status="failed").count() == 1
    assert client.get("/api/v1/billing").json()["effective"] == "free"

    # 해지 예약 → 다음 결제 안 함
    toss.fail = False
    assert client.post("/api/v1/billing/subscribe", json={"cycle": "yearly"}).status_code == 200
    assert client.post("/api/v1/billing/cancel").status_code == 200
    with session_factory() as s:
        sub = s.query(Subscription).one()
        sub.current_period_end = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
        assert billing.renew_due(s, datetime.now(timezone.utc)) == {"renewed": 0, "failed": 0}


def test_only_owner_pays(make_client, client, toss):
    c2, _ = make_client(org_name="다른 사업장")
    # 다른 사업장 대표는 내 요금제를 못 본다 (organization_id 검사)
    me = client.get("/api/v1/billing").json()
    assert me["customer_key"] != c2.get("/api/v1/billing").json()["customer_key"]


def test_progressive_tax():
    assert self_filing.progressive_tax(0) == 0
    assert self_filing.progressive_tax(14_000_000) == 840_000
    assert self_filing.progressive_tax(50_000_000) == 6_240_000


def test_self_filing_estimate(client, onboarded, toss, session_factory):
    # 샘플 은행 내역(2026-11)으로 월세 입금 확정 → 2026년 추정
    org = onboarded["organization_id"]
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", files={"file": ("s.csv", raw)})
    client.post("/api/v1/matching/run", params={"organization_id": org})
    res = client.get("/api/v1/tax-prep/2026/self-filing", params={"registered": True, "other_income": 10_000_000})
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["revenue"] is not None and d["separate_available"]
    sep = d["separate"]
    assert sep["deduction"] == 4_000_000 and sep["expense_rate"] == 0.6
    assert sep["income_tax"] == int(max(0, int(d["revenue"] * 0.4) - 4_000_000) * 0.14)
    assert "추정" in d["notice"] and d["hometax_steps"]
    # 다른 소득이 2천만 원 넘으면 기본공제 없음
    d2 = client.get("/api/v1/tax-prep/2026/self-filing", params={"registered": False, "other_income": 30_000_000}).json()
    assert d2["separate"]["deduction"] == 0 and d2["separate"]["expense_rate"] == 0.5

    # 체험이 끝나고 이용권이 없으면 402
    _expire_trial(session_factory)
    assert client.get("/api/v1/tax-prep/2026/self-filing").status_code == 402
    st = client.get("/api/v1/billing").json()
    client.post("/api/v1/billing/card", json={"auth_key": "a", "customer_key": st["customer_key"]})
    res = client.post("/api/v1/billing/tax-helper")
    assert res.status_code == 200 and toss.charges[-1]["amount"] == 50_000
    assert date.fromisoformat(res.json()["tax_helper_until"]) > date.today() + timedelta(days=360)
    assert client.get("/api/v1/tax-prep/2026/self-filing").status_code == 200


def test_accountant_link(client, onboarded, anon_client):
    assert client.get("/api/v1/tax-prep/2026/accountant-link").json()["link"] is None
    assert client.post("/api/v1/tax-prep/2026/accountant-link", json={"days": 7}).status_code == 409
    token = client.post("/api/v1/tax-prep/2026/accountant-link", json={"days": 90}).json()["token"]
    res = anon_client.get(f"/api/v1/accountant/{token}")  # 세무사: 로그인 없이
    assert res.status_code == 200
    d = res.json()
    assert d["year"] == 2026 and d["organization_name"]
    assert all(x["tenant_name"] == "" for x in d["deposits"])  # 임차인 이름 없음
    assert "임차인" not in json.dumps(d["deposits"], ensure_ascii=False)
    x = anon_client.get(f"/api/v1/accountant/{token}/export.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    # 새로 만들면 이전 링크는 바로 무효, 회수하면 새 링크도 무효
    token2 = client.post("/api/v1/tax-prep/2026/accountant-link", json={"days": 30}).json()["token"]
    assert anon_client.get(f"/api/v1/accountant/{token}").status_code == 404
    assert client.delete("/api/v1/tax-prep/2026/accountant-link").json()["revoked"] == 1
    assert anon_client.get(f"/api/v1/accountant/{token2}").status_code == 404
    assert anon_client.get("/api/v1/accountant/nope").status_code == 404
