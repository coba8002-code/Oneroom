"""임차인 화면 — 계약별 초대 링크(해시 저장·한 번만 보여 줌·만료·회수·재발급), 장부 값만, 이름·다른 호실 없음, 수리 요청."""
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import AuditLog, TenantLink
from app.routers import tenant_portal as router_mod
from tests.conftest import SAMPLES

NOW = datetime(2026, 12, 15, 3, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    clock = {"now": NOW}
    monkeypatch.setattr(router_mod, "_now", lambda: clock["now"])
    monkeypatch.setattr(router_mod, "_today", lambda: date(2026, 12, 15))
    return clock


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


def _make(client, lease_id, days=90):
    res = client.post(f"/api/v1/leases/{lease_id}/tenant-link", json={"days": days})
    assert res.status_code == 200, res.text
    return res.json()["path"].removeprefix("/t/")


def test_tenant_sees_own_ledger_only(client, anon_client, org, session_factory):
    lease = _lease(client, org, "101")
    token = _make(client, lease)
    with session_factory() as s:  # 원문은 저장하지 않는다
        link = s.scalar(select(TenantLink))
        assert link.token_hash != token and len(link.token_hash) == 64

    v = anon_client.get(f"/api/v1/tenant/{token}").json()
    assert v["unit_no"] == "101"
    assert v["lease"] == {"start_date": "2025-03-01", "end_date": "2027-02-28", "rent": 450000, "mgmt_fee": None, "due_day": 1,
                          "deposit": 5_000_000, "deposit_received": 5_000_000}
    nov = next(c for c in v["charges"] if c["period"] == "2026-11")
    assert (nov["amount"], nov["paid"], nov["state"], nov["state_label"]) == (450000, 450000, "paid", "입금 확인")
    assert v["bank_data_as_of"] is not None and "통장 내역" in v["notice"]
    assert not re.search(r"임차인[A-H]|010-|미납", str(v))  # 이름·연락처·독촉 표현 없음
    assert {c["period"] for c in v["charges"]} == {"2026-11"}  # 다른 호실 청구 없음

    status = client.get(f"/api/v1/leases/{lease}/tenant-link").json()
    assert status["link"]["last_seen_at"] is not None and token not in str(status)  # 원문은 다시 보여 주지 않음


def test_unconfirmed_is_not_called_overdue(client, anon_client, org):
    # 103호: 20만 원 부분 입금은 아직 관리자 검토 대기 — 임차인에게는 '미납'이 아니라 '입금 확인 전'
    v = anon_client.get(f"/api/v1/tenant/{_make(client, _lease(client, org, '103'))}").json()
    assert (v["charges"][0]["paid"], v["charges"][0]["state_label"]) == (0, "입금 확인 전")


def test_reissue_revoke_expire_and_end(client, anon_client, org, _clock):
    lease = _lease(client, org, "101")
    old = _make(client, lease)
    new = _make(client, lease, days=30)
    assert anon_client.get(f"/api/v1/tenant/{old}").status_code == 404  # 새로 만들면 이전 링크 무효
    assert anon_client.get(f"/api/v1/tenant/{new}").status_code == 200

    _clock["now"] = NOW + timedelta(days=31)
    gone = anon_client.get(f"/api/v1/tenant/{new}")
    assert gone.status_code == 404 and "새 링크" in gone.json()["detail"]
    assert client.get(f"/api/v1/leases/{lease}/tenant-link").json()["link"] is None
    _clock["now"] = NOW

    assert client.delete(f"/api/v1/leases/{lease}/tenant-link").json() == {"revoked": 1}
    assert anon_client.get(f"/api/v1/tenant/{new}").status_code == 404

    again = _make(client, lease)
    client.post(f"/api/v1/leases/{lease}/end", params={"organization_id": org},
                json={"ended_on": "2026-12-10", "reason": "퇴거"})
    assert anon_client.get(f"/api/v1/tenant/{again}").status_code == 404  # 계약이 끝나면 닫힘
    assert client.post(f"/api/v1/leases/{lease}/tenant-link", json={"days": 90}).status_code == 409
    assert anon_client.get("/api/v1/tenant/" + "x" * 43).status_code == 404


def test_link_rules(client, make_client, org):
    lease = _lease(client, org, "101")
    assert client.post(f"/api/v1/leases/{lease}/tenant-link", json={"days": 7}).status_code == 409  # 정해진 기간만
    other, _ = make_client(org_name="남의 사업장")
    assert other.post(f"/api/v1/leases/{lease}/tenant-link", json={"days": 90}).status_code == 404


def test_repair_request_flow(client, anon_client, org, session_factory):
    token = _make(client, _lease(client, org, "102"))
    res = anon_client.post(f"/api/v1/tenant/{token}/repairs", json={"description": "  보일러 온수가 안 나와요  "})
    assert res.status_code == 200, res.text
    assert anon_client.post(f"/api/v1/tenant/{token}/repairs", json={"description": "   "}).status_code == 409

    repairs = client.get("/api/v1/repairs").json()
    r = next(x for x in repairs if x["source"] == "tenant")
    assert (r["unit_no"], r["description"], r["status"], r["payer"]) == ("102", "보일러 온수가 안 나와요", "open", "undecided")
    home = client.get("/api/v1/dashboard", params={"organization_id": org, "as_of": "2026-12-15"}).json()
    assert any(a["kind"] == "tenant_repair" and "102" in a["message"] for a in home["attention"])

    # 관리자 메모·비용은 임차인에게 보이지 않는다
    client.put(f"/api/v1/repairs/{r['id']}", json={**{k: r[k] for k in ("unit_id", "fixture_id", "reported_on",
                                                                       "description", "vendor", "payer")},
                                                    "status": "done", "completed_on": "2026-12-16", "cost": 150000,
                                                    "note": "임차인 과실 의심"})
    v = anon_client.get(f"/api/v1/tenant/{token}").json()
    assert v["repairs"] == [{"reported_on": "2026-12-15", "description": "보일러 온수가 안 나와요", "status": "done",
                             "completed_on": "2026-12-16"}]
    assert "과실" not in str(v) and "150000" not in str(v)

    for i in range(4):
        assert anon_client.post(f"/api/v1/tenant/{token}/repairs", json={"description": f"요청 {i}"}).status_code == 200
    assert anon_client.post(f"/api/v1/tenant/{token}/repairs", json={"description": "또"}).status_code == 409  # 하루 5건

    with session_factory() as s:
        logged = s.scalars(select(AuditLog).where(AuditLog.action == "tenant.repair_request")).all()
        assert len(logged) == 5 and all(a.detail is None for a in logged)  # 요청 글은 감사 기록에 넣지 않음


def test_other_lease_cannot_see_previous_tenant_requests(client, anon_client, org):
    lease = _lease(client, org, "102")
    token = _make(client, lease)
    anon_client.post(f"/api/v1/tenant/{token}/repairs", json={"description": "창문이 안 닫혀요"})
    client.post(f"/api/v1/leases/{lease}/end", params={"organization_id": org},
                json={"ended_on": "2026-12-15", "reason": "퇴거"})
    units = {u["unit_no"]: u["unit_id"] for u in client.get("/api/v1/units", params={"organization_id": org}).json()}
    res = client.post(f"/api/v1/units/{units['102']}/leases", json={
        "tenant_name": "새임차인", "deposit": 5000000, "rent": 460000, "due_day": 20, "start_date": "2027-01-01"})
    assert res.status_code in (200, 201), res.text
    v = anon_client.get(f"/api/v1/tenant/{_make(client, _lease(client, org, '102'))}").json()
    assert v["repairs"] == [] and v["charges"] == [] and v["lease"]["deposit_received"] is None  # 모르면 비움
