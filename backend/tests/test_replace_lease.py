"""계약 바꾸기 — 사진·다른 앱에서 옮겨 온 계약으로 지금 계약을 대신한다. 장부 사실은 지우지 않는다."""
import pytest
from sqlalchemy import select

from app.models import AuditLog, Deposit, Lease, Tenant


@pytest.fixture
def org(onboarded):
    return onboarded["organization_id"]


def _unit(client, unit_no):
    return next(u for u in client.get("/api/v1/lease-history").json() if u["unit_no"] == unit_no)


NEW = {"tenant_name": "김동수", "tenant_phone": "010-0000-0000", "deposit": 35_000_000, "rent": 0, "mgmt_fee": 50_000,
       "due_day": 3, "start_date": "2026-09-06", "end_date": "2027-09-07"}


def test_delete_wrong_lease_and_put_new_one(client, org, session):
    u = _unit(client, "101")
    old = next(l for l in u["leases"] if l["status"] == "active")
    res = client.post(f"/api/v1/units/{u['unit_id']}/replace-lease", json={**NEW, "mode": "delete"})
    # 샘플 101호는 보증금을 받은 기록이 있다 → 지우면 장부 사실이 사라지므로 거절
    assert res.status_code == 409 and "받은 보증금" in res.json()["detail"]

    v = _unit(client, "203")  # 공실 → 잘못 넣은 계약 하나를 만든 뒤 바꾼다
    wrong = client.post(f"/api/v1/units/{v['unit_id']}/leases", json={**NEW, "tenant_name": "잘못", "start_date": "2026-10-29"}).json()
    res = client.post(f"/api/v1/units/{v['unit_id']}/replace-lease", json={**NEW, "mode": "delete"})
    assert res.status_code == 201, res.text
    assert session.get(Lease, __import__("uuid").UUID(wrong["lease_id"])) is None
    assert session.scalar(select(Tenant).where(Tenant.name == "잘못")) is None  # 다른 계약 없는 임차인도 정리
    h = _unit(client, "203")
    assert [(l["tenant_name"], l["status"], l["deposit"]) for l in h["leases"]] == [("김동수", "active", 35_000_000)]
    assert session.scalar(select(AuditLog).where(AuditLog.action == "lease.delete")) is not None
    assert old["status"] == "active"


def test_end_then_new_keeps_history(client, org):
    u = _unit(client, "102")
    res = client.post(f"/api/v1/units/{u['unit_id']}/replace-lease", json={**NEW, "mode": "end", "start_date": "2026-11-01"})
    assert res.status_code == 201, res.text
    leases = _unit(client, "102")["leases"]
    assert [l["status"] for l in leases] == ["active", "ended"]
    assert leases[1]["ended_on"] == "2026-10-31"


def test_invalid_new_lease_changes_nothing(client, org, session):
    v = _unit(client, "203")
    client.post(f"/api/v1/units/{v['unit_id']}/leases", json={**NEW, "start_date": "2026-10-29"})
    res = client.post(f"/api/v1/units/{v['unit_id']}/replace-lease", json={**NEW, "mode": "delete", "due_day": 40})
    assert res.status_code == 409
    assert [l["status"] for l in _unit(client, "203")["leases"]] == ["active"]  # 그대로
    u = _unit(client, "102")
    res = client.post(f"/api/v1/units/{u['unit_id']}/replace-lease", json={**NEW, "mode": "end", "start_date": "2020-01-01"})
    assert res.status_code == 409 and [l["status"] for l in _unit(client, "102")["leases"]] == ["active"]


def test_charges_block_delete(client, org):
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    u = _unit(client, "102")
    res = client.post(f"/api/v1/units/{u['unit_id']}/replace-lease", json={**NEW, "mode": "delete"})
    assert res.status_code == 409 and "청구" in res.json()["detail"]


def test_vacant_unit_has_nothing_to_replace(client, org):
    v = _unit(client, "203")
    assert client.post(f"/api/v1/units/{v['unit_id']}/replace-lease", json={**NEW, "mode": "delete"}).status_code == 404


def test_future_deposit_date_does_not_block_delete(client, org, session):
    """예전 화면 오류로 '받은 날'이 미래로 들어간 보증금은 사실이 아니므로 잘못 넣은 계약 지우기를 막지 않는다."""
    from datetime import date
    v = _unit(client, "203")
    lid = client.post(f"/api/v1/units/{v['unit_id']}/leases", json={**NEW, "start_date": "2026-10-29"}).json()["lease_id"]
    dep = session.scalar(select(Deposit).where(Deposit.lease_id == __import__("uuid").UUID(lid)))
    dep.received_at = date(2099, 1, 3)
    session.commit()
    res = client.post(f"/api/v1/units/{v['unit_id']}/replace-lease", json={**NEW, "mode": "delete"})
    assert res.status_code == 201, res.text
