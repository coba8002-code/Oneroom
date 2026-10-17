"""임차인 메시지 — 초안 → 승인 → (연결 전) 직접 보냄 표시. 자동 독촉 금지 규칙."""
import uuid

import pytest
from sqlalchemy import func, select

from app.models import Notification
from app.services import messaging
from tests.conftest import ORG_NAME, PASSWORD, SAMPLES

RENT_T = "{임차인}님, {청구월} 월세 {금액}원 납부일은 {납부일}입니다."
OVERDUE_T = "{호실}호 {임차인}님, {청구월} 월세 중 {미납액}원이 {경과일}일 지났습니다."


def _p(org, **kw):
    return {"organization_id": org, **kw}


@pytest.fixture
def org(client, onboarded):
    o = onboarded["organization_id"]
    client.post("/api/v1/charges/generate", params=_p(o, period="2026-11"))
    return o


def _settings(client, org, **kw):
    body = {"grace_days": 5, "rent_template": RENT_T, "overdue_template": OVERDUE_T, **kw}
    return client.put("/api/v1/notification-settings", params=_p(org), json=body)


def _bank_and_review(client, onboarded, org):
    """샘플 은행 내역 + 매칭, 검토 대기 4건을 모두 확정 (301 3,000,000 은 '기타')."""
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", params=_p(org),
                files={"file": ("s.csv", (SAMPLES / "bank_transactions_sample.csv").read_bytes())})
    client.post("/api/v1/matching/run", params=_p(org))
    leases = {c["unit_no"]: c["lease_id"] for c in client.get("/api/v1/contracts", params=_p(org)).json()}
    for q in client.get("/api/v1/matching/queue", params=_p(org)).json():
        who = q["transaction"]["counterparty"]
        body = {"김OO": {"lease_id": leases["302"], "category": "rent"},
                "임차인C": {"lease_id": leases["103"], "category": "rent"},
                "임차인D": {"lease_id": leases["201"], "category": "rent"},
                "임차인F": {"lease_id": None, "category": "other"}}[who]
        res = client.post(f"/api/v1/transactions/{q['transaction']['id']}/decision", params=_p(org),
                          json={**body, "remember_alias": False})
        assert res.status_code == 200, res.text


def test_settings_have_no_defaults_and_validate(client, org):
    s = client.get("/api/v1/notification-settings", params=_p(org)).json()
    assert s["grace_days"] is None and s["rent_template"] is None and s["overdue_template"] is None
    assert s["provider"] == {"connected": False, "name": None}
    assert "미납액" in s["variables"]
    res = client.post("/api/v1/notifications/rent-notices", params=_p(org, period="2026-11"))
    assert res.status_code == 409 and "문구를 먼저" in res.json()["detail"]
    res = _settings(client, org, rent_template="{임차인}님 {계좌번호}로")
    assert res.status_code == 409 and "{계좌번호}" in res.json()["detail"]
    assert _settings(client, org, grace_days=99).status_code == 409
    assert _settings(client, org).status_code == 200


def test_rent_notices_drafted_once_per_charge(client, org):
    _settings(client, org)
    res = client.post("/api/v1/notifications/rent-notices", params=_p(org, period="2026-11")).json()
    assert res["created"] == 8
    again = client.post("/api/v1/notifications/rent-notices", params=_p(org, period="2026-11")).json()
    assert again["created"] == 0 and len(again["skipped"]) == 8
    items = client.get("/api/v1/notifications", params=_p(org)).json()
    n101 = next(i for i in items if i["unit_no"] == "101")
    assert n101["status"] == "draft" and n101["body"] == "임차인A님, 2026-11 월세 450,000원 납부일은 11월 1일입니다."
    assert n101["phone"] == "010-0000-0101"  # 직접 보낼 때 쓰도록 (저장은 암호화)
    assert client.post("/api/v1/notifications/rent-notices", params=_p(org, period="2026-12")).status_code == 409


def test_overdue_needs_grace_bank_and_no_pending_review(client, onboarded, org):
    _settings(client, org, grace_days=None)
    assert "유예기간" in client.post("/api/v1/notifications/overdue-notices",
                                    params=_p(org, as_of="2026-12-01")).json()["detail"]
    _settings(client, org)
    res = client.post("/api/v1/notifications/overdue-notices", params=_p(org, as_of="2026-12-01"))
    assert res.status_code == 409 and "은행 거래내역이 없습니다" in res.json()["detail"]

    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", params=_p(org),
                files={"file": ("s.csv", (SAMPLES / "bank_transactions_sample.csv").read_bytes())})
    client.post("/api/v1/matching/run", params=_p(org))
    res = client.post("/api/v1/notifications/overdue-notices", params=_p(org, as_of="2026-12-01"))
    assert res.status_code == 409 and "검토 대기" in res.json()["detail"]  # 실제로는 낸 돈일 수 있음


def test_overdue_drafts_only_after_grace_and_bank_coverage(client, onboarded, org):
    _settings(client, org)
    _bank_and_review(client, onboarded, org)
    # 11-28: 103(11-10 + 5일 지남) 만. 301 은 11-25 + 5일 = 11-30 까지 유예
    r = client.post("/api/v1/notifications/overdue-notices", params=_p(org, as_of="2026-11-28")).json()
    assert r["created"] == 1 and any("301" in s and "유예기간 중" in s for s in r["skipped"])
    # 12-10: 301 도. 은행 내역(11-30)이 유예기간 끝(11-30)까지 있음
    r = client.post("/api/v1/notifications/overdue-notices", params=_p(org, as_of="2026-12-10")).json()
    assert r["created"] == 1
    bodies = {i["unit_no"]: i["body"] for i in client.get("/api/v1/notifications", params=_p(org)).json()}
    assert bodies["103"] == "103호 임차인C님, 2026-11 월세 중 220,000원이 18일 지났습니다."
    # 유예기간을 늘리면 은행 내역이 모자라 만들지 않음
    _settings(client, org, grace_days=20)
    client.post("/api/v1/charges/generate", params=_p(org, period="2026-12"))
    r = client.post("/api/v1/notifications/overdue-notices", params=_p(org, as_of="2026-12-30")).json()
    assert any("은행 내역이 2026-11-30까지" in s for s in r["skipped"])


def test_approve_then_mark_sent_manually(client, org, session):
    _settings(client, org)
    client.post("/api/v1/notifications/rent-notices", params=_p(org, period="2026-11"))
    nid = client.get("/api/v1/notifications", params=_p(org)).json()[0]["id"]
    assert client.post(f"/api/v1/notifications/{nid}/mark-sent", params=_p(org)).status_code == 409  # 승인 전
    assert client.patch(f"/api/v1/notifications/{nid}", params=_p(org), json={"body": "고친 문구"}).json()["body"] == "고친 문구"
    assert client.post(f"/api/v1/notifications/{nid}/approve", params=_p(org)).json()["status"] == "approved"
    assert client.patch(f"/api/v1/notifications/{nid}", params=_p(org), json={"body": "x"}).status_code == 409
    assert client.post(f"/api/v1/notifications/{nid}/mark-sent", params=_p(org)).json()["status"] == "sent"
    n = session.get(Notification, uuid.UUID(nid))
    session.refresh(n)
    assert n.approved_at and n.sent_at and n.sent_via == "manual"
    assert client.post(f"/api/v1/notifications/{nid}/discard", params=_p(org)).status_code == 409


def test_connected_provider_sends_on_approval(client, org, monkeypatch):
    sent = []

    class Fake:
        name = "fake"

        def send(self, m):
            if m.body.startswith("임차인B"):
                raise messaging.SendError("수신 거부")
            sent.append(m)

    monkeypatch.setattr(messaging, "get_provider", lambda: Fake())
    _settings(client, org)
    client.post("/api/v1/notifications/rent-notices", params=_p(org, period="2026-11"))
    items = {i["unit_no"]: i["id"] for i in client.get("/api/v1/notifications", params=_p(org)).json()}
    ok = client.post(f"/api/v1/notifications/{items['101']}/approve", params=_p(org)).json()
    assert ok["status"] == "sent" and sent[0].phone == "010-0000-0101" and sent[0].template == "rent_notice"
    bad = client.post(f"/api/v1/notifications/{items['102']}/approve", params=_p(org)).json()
    assert bad == {"id": items["102"], "status": "failed", "error": "수신 거부"}
    assert client.post(f"/api/v1/notifications/{items['102']}/mark-sent", params=_p(org)).json()["status"] == "sent"


def test_viewer_cannot_approve_and_other_org_is_404(client, org, make_client, session):
    _settings(client, org)
    client.post("/api/v1/notifications/rent-notices", params=_p(org, period="2026-11"))
    nid = client.get("/api/v1/notifications", params=_p(org)).json()[0]["id"]
    other, _ = make_client(email="other@example.com", org_name="남의 사업장")
    assert other.post(f"/api/v1/notifications/{nid}/approve").status_code == 404
    from tests.test_auth import _member
    _member(session, org, "viewer", "viewer@example.com")
    from fastapi.testclient import TestClient
    from app.main import app
    v = TestClient(app)
    v.post("/api/v1/auth/login", json={"email": "viewer@example.com", "password": PASSWORD})
    assert v.get("/api/v1/notifications").status_code == 200
    assert v.post(f"/api/v1/notifications/{nid}/approve").status_code == 403


def test_org_deletion_removes_messages(client, org, session):
    _settings(client, org)
    client.post("/api/v1/notifications/rent-notices", params=_p(org, period="2026-11"))
    assert client.post("/api/v1/auth/account/delete", json={"password": PASSWORD, "confirm_name": ORG_NAME}).status_code == 200
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Notification)) == 0


RENEWAL_T = "{호실}호 {임차인}님, 계약이 {만료일}에 끝납니다. 갱신 여부를 {통지마감일} 전에 알려 주세요."


def _renewal_org(client):
    """만료일이 다른 계약 3건: 통지 기간 안 / 통지 기간 지남 / 아직 먼 계약 + 만료일 없는 계약."""
    return client.post("/api/v1/onboarding", json={
        "property": {"name": "갱신 안내"},
        "units": [
            {"unit_no": "101", "tenant_name": "기간안", "rent": 450000, "due_day": 5, "deposit": 10000000,
             "start_date": "2025-09-01", "end_date": "2027-08-31"},
            {"unit_no": "102", "tenant_name": "기간지남", "rent": 450000, "due_day": 5,
             "start_date": "2025-07-01", "end_date": "2027-06-30"},
            {"unit_no": "103", "tenant_name": "먼계약", "rent": 450000, "due_day": 5,
             "start_date": "2026-09-01", "end_date": "2028-08-31"},
            {"unit_no": "104", "tenant_name": "기한없음", "rent": 450000, "due_day": 5, "start_date": "2026-01-01"},
        ]}).json()["organization_id"]


def test_renewal_notice_only_inside_notice_window(client):
    org = _renewal_org(client)
    url = "/api/v1/notifications/renewal-notices"
    res = client.post(url, params=_p(org, as_of="2027-05-10"))
    assert res.status_code == 409 and "계약 만료 안내 문구" in res.json()["detail"]  # 기본 문구 없음
    bad = _settings(client, org, renewal_template="{임차인}님 {미납액}원")  # 청구용 칸은 못 씀
    assert bad.status_code == 409 and "{미납액}" in bad.json()["detail"]
    s = _settings(client, org, renewal_template=RENEWAL_T).json()
    assert s["renewal_template"] == RENEWAL_T and "통지마감일" in s["renewal_variables"]

    r = client.post(url, params=_p(org, as_of="2027-05-10")).json()
    # 101: 통지 기간 2027-02-28~2027-06-30 안 → 초안 / 102: 2027-04-30 까지라 지남 / 103: 아직 멂(조용히) / 104: 만료일 없음
    assert r["created"] == 1
    assert any(x.startswith("102 통지 기간(2027-04-30까지)이 지남") for x in r["skipped"])
    assert "104 만료일 없음" in r["skipped"] and not any(x.startswith("103") for x in r["skipped"])
    n = next(i for i in client.get("/api/v1/notifications", params=_p(org)).json() if i["kind"] == "renewal_notice")
    assert n["body"] == "101호 기간안님, 계약이 2027년 8월 31일에 끝납니다. 갱신 여부를 2027년 6월 30일 전에 알려 주세요."
    assert n["lease_end"] == "2027-08-31" and n["status"] == "draft" and n["period"] is None
    again = client.post(url, params=_p(org, as_of="2027-06-01")).json()
    assert again["created"] == 0 and any("이미 만듦" in x for x in again["skipped"])


def test_sent_renewal_notice_clears_dashboard_warning(client):
    org = _renewal_org(client)
    _settings(client, org, renewal_template=RENEWAL_T)
    dash = lambda: client.get("/api/v1/dashboard", params=_p(org, as_of="2027-05-10")).json()  # noqa: E731
    assert "lease_notice_open" in {a["kind"] for a in dash()["attention"]}
    client.post("/api/v1/notifications/renewal-notices", params=_p(org, as_of="2027-05-10"))
    nid = next(i["id"] for i in client.get("/api/v1/notifications", params=_p(org)).json())
    assert "lease_notice_open" in {a["kind"] for a in dash()["attention"]}  # 초안만으로는 통지가 아님
    client.post(f"/api/v1/notifications/{nid}/approve", params=_p(org))
    client.post(f"/api/v1/notifications/{nid}/mark-sent", params=_p(org))
    d = dash()
    row = next(e for e in d["lease_endings"] if e["unit_no"] == "101")
    assert row["notice_sent_on"] is not None
    assert not any(a["kind"] == "lease_notice_open" and a["message"].startswith("101") for a in d["attention"])
