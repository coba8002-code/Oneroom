"""임차인 공지·연락처 — 게시 기간·대상 호실만, 연락처 암호화, 남의 사업장 차단."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.routers import tenant_notices as notices_router, tenant_portal as portal_router

TODAY = date(2026, 12, 15)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(notices_router, "_today", lambda: TODAY)
    monkeypatch.setattr(portal_router, "_today", lambda: TODAY)
    monkeypatch.setattr(portal_router, "_now", lambda: datetime(2026, 12, 15, 3, tzinfo=timezone.utc))


@pytest.fixture
def ov(client, onboarded):
    return client.get("/api/v1/tenant-notices").json()


def _link(client, org, unit_no):
    lease = next(x["lease_id"] for x in client.get("/api/v1/leases", params={"organization_id": org}).json()
                 if x["unit_no"] == unit_no)
    return client.post(f"/api/v1/leases/{lease}/tenant-link", json={"days": 90}).json()["path"].removeprefix("/t/")


def _notice(client, **body):
    return client.post("/api/v1/tenant-notices", json=body)


def test_notices_by_period_and_unit(client, anon_client, onboarded, ov):
    b = ov["buildings"][0]
    units = {u["unit_no"]: u["unit_id"] for u in b["units"]}
    pid = b["property_id"]
    assert _notice(client, property_id=pid, title="  12/20 물탱크 청소 ", body="10~12시 단수").status_code == 201
    _notice(client, property_id=pid, unit_id=units["101"], title="101호 보일러 점검", starts_on="2026-12-10")
    _notice(client, property_id=pid, title="지난 공지", starts_on="2026-11-01", ends_on="2026-11-30")
    _notice(client, property_id=pid, title="다음 달 공지", starts_on="2027-01-05")

    v101 = anon_client.get(f"/api/v1/tenant/{_link(client, onboarded['organization_id'], '101')}").json()
    assert [n["title"] for n in v101["notices"]] == ["12/20 물탱크 청소", "101호 보일러 점검"]
    v102 = anon_client.get(f"/api/v1/tenant/{_link(client, onboarded['organization_id'], '102')}").json()
    assert [n["title"] for n in v102["notices"]] == ["12/20 물탱크 청소"]  # 다른 호실 공지는 안 보임
    assert v102["contact"] is None  # 넣지 않은 연락처는 없음

    states = {n["title"]: n["state"] for n in client.get("/api/v1/tenant-notices").json()["notices"]}
    assert states == {"12/20 물탱크 청소": "showing", "101호 보일러 점검": "showing", "지난 공지": "ended",
                      "다음 달 공지": "scheduled"}

    nid = next(n["id"] for n in client.get("/api/v1/tenant-notices").json()["notices"] if n["title"] == "12/20 물탱크 청소")
    assert client.delete(f"/api/v1/tenant-notices/{nid}").status_code == 204
    v102 = anon_client.get(f"/api/v1/tenant/{_link(client, onboarded['organization_id'], '102')}").json()
    assert v102["notices"] == []


def test_contact_encrypted_and_shown(client, anon_client, onboarded, ov, session):
    pid = ov["buildings"][0]["property_id"]
    assert client.put(f"/api/v1/properties/{pid}/tenant-contact",
                      json={"phone": "010-1234-5678", "note": "평일 9~18시"}).status_code == 200
    raw = session.execute(text("select contact_phone from properties")).scalar_one()
    assert raw and "1234" not in raw  # 저장 시 암호화
    v = anon_client.get(f"/api/v1/tenant/{_link(client, onboarded['organization_id'], '101')}").json()
    assert v["contact"] == {"phone": "010-1234-5678", "note": "평일 9~18시"}


def test_rules(client, make_client, onboarded, ov):
    pid = ov["buildings"][0]["property_id"]
    assert _notice(client, property_id=pid, title="   ").status_code == 409
    assert _notice(client, property_id=pid, title="x", starts_on="2026-12-10", ends_on="2026-12-01").status_code == 409
    other, _ = make_client(org_name="남의 사업장")
    assert other.post("/api/v1/tenant-notices", json={"property_id": pid, "title": "x"}).status_code == 404
    assert other.put(f"/api/v1/properties/{pid}/tenant-contact", json={"phone": "1"}).status_code == 404
    nid = _notice(client, property_id=pid, title="내 공지").json()["id"]
    assert other.delete(f"/api/v1/tenant-notices/{nid}").status_code == 404
