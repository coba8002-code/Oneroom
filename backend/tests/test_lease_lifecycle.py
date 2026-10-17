"""계약 종료 · 되돌리기 · 새 계약."""
import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Charge


@pytest.fixture
def org(onboarded):
    return onboarded["organization_id"]


def _p(org, **kw):
    return {"organization_id": org, **kw}


def _lease(client, org, unit_no):
    return next(c["lease_id"] for c in client.get("/api/v1/contracts", params=_p(org)).json() if c["unit_no"] == unit_no)


def _u(s):
    return uuid.UUID(s)


def _history(client, unit_no):
    return next(u for u in client.get("/api/v1/lease-history").json() if u["unit_no"] == unit_no)


def test_end_waives_unpaid_charges_after_move_out_and_vacates(client, org, session):
    for period in ("2026-11", "2026-12"):
        client.post("/api/v1/charges/generate", params=_p(org, period=period))
    lid = _lease(client, org, "102")  # 납부일 5일, 보증금 5,000,000 수령
    res = client.post(f"/api/v1/leases/{lid}/end", json={"ended_on": "2026-11-20", "reason": "만기 전 퇴거 합의"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["waived"] == ["2026-12"] and body["unit_status"] == "vacant"  # 11월(납부일 11/5)은 받을 돈
    assert any("남은 미납 450,000원 (2026-11)" in w for w in body["warnings"])
    assert any("돌려줄 보증금 5,000,000원" in w for w in body["warnings"])
    assert any("정산서를 확정하지 않았습니다" in w for w in body["warnings"])
    statuses = {c.period: c.status for c in session.scalars(select(Charge).where(Charge.lease_id == _u(lid)))}
    assert statuses == {"2026-11": "open", "2026-12": "waived"}
    assert client.post(f"/api/v1/leases/{lid}/end", json={}).status_code == 409
    h = _history(client, "102")
    assert h["status"] == "vacant" and h["leases"][0]["ended_on"] == "2026-11-20"
    assert all(c["unit_no"] != "102" for c in client.get("/api/v1/contracts", params=_p(org)).json())
    # 다음 달 청구를 만들어도 종료된 계약은 빠짐
    gen = client.post("/api/v1/charges/generate", params=_p(org, period="2027-01")).json()
    assert all(c["unit_no"] != "102" for c in gen["charges"])
    # 보증금을 아직 안 돌려줬으니 홈에서 계속 알림
    dash = client.get("/api/v1/dashboard", params=_p(org, as_of="2026-12-01")).json()
    assert any(a["kind"] == "deposit_unreturned_ended" and "102" in a["message"] for a in dash["attention"])
    assert dash["counts"]["vacant"] == 2
    assert session.scalar(select(AuditLog).where(AuditLog.action == "lease.end")).detail["ended_on"] == "2026-11-20"


def test_partly_paid_future_charge_is_kept(client, org, session):
    client.post("/api/v1/charges/generate", params=_p(org, period="2026-12"))
    lid = _lease(client, org, "101")
    from app.models import Payment, TransactionAllocation, Transaction, BankAccount
    from datetime import datetime, timezone
    acct = session.scalar(select(BankAccount))
    t = Transaction(bank_account_id=acct.id, occurred_at=datetime(2026, 11, 30, tzinfo=timezone.utc), amount=100000,
                    direction="in", counterparty="임차인A", description="", fingerprint="x1")
    session.add(t); session.flush()
    a = TransactionAllocation(transaction_id=t.id, lease_id=_u(lid), category="rent", amount=100000, review_status="approved")
    session.add(a); session.flush()
    charge = session.scalar(select(Charge).where(Charge.lease_id == _u(lid), Charge.period == "2026-12"))
    session.add(Payment(charge_id=charge.id, transaction_allocation_id=a.id, amount=100000))
    charge.status = "partial"
    session.commit()
    body = client.post(f"/api/v1/leases/{lid}/end", json={"ended_on": "2026-11-25"}).json()
    assert body["waived"] == [] and any("일부 입금된 청구" in w and "2026-12" in w for w in body["warnings"])
    session.refresh(charge)
    assert charge.status == "partial"


def test_undo_end_restores_lease_and_waived_charges(client, org, session):
    client.post("/api/v1/charges/generate", params=_p(org, period="2026-12"))
    lid = _lease(client, org, "103")
    client.post(f"/api/v1/leases/{lid}/end", json={"ended_on": "2026-11-30"})
    res = client.post(f"/api/v1/leases/{lid}/undo-end")
    assert res.status_code == 200 and res.json()["status"] == "active"
    assert session.scalar(select(Charge.status).where(Charge.lease_id == _u(lid), Charge.period == "2026-12")) == "open"
    assert _history(client, "103")["status"] == "occupied"
    assert client.post(f"/api/v1/leases/{lid}/undo-end").status_code == 409


def test_new_lease_on_vacant_unit(client, org):
    units = {u["unit_no"]: u for u in client.get("/api/v1/lease-history").json()}
    vacant = units["203"]["unit_id"]
    assert units["203"]["status"] == "vacant" and units["203"]["leases"] == []
    body = {"tenant_name": "새임차인", "tenant_phone": "010-1234-5678", "deposit": 3000000, "rent": 430000,
            "due_day": 10, "start_date": "2026-12-01", "end_date": "2028-11-30"}
    assert client.post(f"/api/v1/units/{units['401']['unit_id']}/leases", json=body).status_code == 409  # 주인세대
    assert client.post(f"/api/v1/units/{units['101']['unit_id']}/leases", json=body).status_code == 409  # 계약 중
    assert client.post(f"/api/v1/units/{vacant}/leases", json={**body, "due_day": 32}).status_code == 409
    assert client.post(f"/api/v1/units/{vacant}/leases", json={**body, "end_date": "2026-11-01"}).status_code == 409
    res = client.post(f"/api/v1/units/{vacant}/leases", json=body)
    assert res.status_code == 201
    h = _history(client, "203")
    assert h["status"] == "occupied" and h["leases"][0]["tenant_name"] == "새임차인"
    assert h["leases"][0]["deposit_unreturned"] == 0  # 보증금은 아직 '받을 보증금' (수령 기록 없음)
    gen = client.post("/api/v1/charges/generate", params=_p(org, period="2026-12")).json()
    assert any(c["unit_no"] == "203" and c["amount"] == 430000 for c in gen["charges"])
    dash = client.get("/api/v1/dashboard", params=_p(org, as_of="2026-12-01")).json()
    assert any(a["kind"] == "deposit_unreturned" or "203 보증금 3,000,000원 수령 기록 없음" in a["message"]
               for a in dash["attention"])


def test_relet_after_end_must_start_after_previous_end(client, org):
    lid = _lease(client, org, "201")
    client.post(f"/api/v1/leases/{lid}/end", json={"ended_on": "2026-11-15"})
    unit = _history(client, "201")["unit_id"]
    body = {"tenant_name": "다음", "rent": 450000, "due_day": 15, "start_date": "2026-11-15"}
    assert client.post(f"/api/v1/units/{unit}/leases", json=body).status_code == 409
    assert client.post(f"/api/v1/units/{unit}/leases", json={**body, "start_date": "2026-11-16"}).status_code == 201
    assert len(_history(client, "201")["leases"]) == 2
    assert client.post(f"/api/v1/leases/{lid}/undo-end").status_code == 409  # 새 계약이 있으면 되돌릴 수 없음
