"""입주·퇴실 점검(항목·사진·잠금)과 퇴실 정산."""
import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services import backup, move_out as svc
from app.services import storage

PNG = b"\x89PNG\r\n\x1a\n" + b"room-photo" * 30
PDF = b"%PDF-1.4 not a photo"


@pytest.fixture
def org(onboarded):
    return onboarded["organization_id"]


@pytest.fixture
def leases(client, org):
    return {c["unit_no"]: c["lease_id"] for c in client.get("/api/v1/contracts", params={"organization_id": org}).json()}


def _view(client, lease_id):
    return client.get(f"/api/v1/leases/{lease_id}/inspections").json()


def _create(client, lease_id, kind, on="2025-03-01"):
    res = client.post(f"/api/v1/leases/{lease_id}/inspections", json={"kind": kind, "inspected_on": on})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_template_uses_standard_areas_and_unit_fixtures(client, org, leases):
    units = {u["unit_no"]: u["unit_id"] for u in client.get("/api/v1/units", params={"organization_id": org}).json()}
    client.post("/api/v1/fixtures", json={"category": "aircon", "unit_ids": [units["101"]]})
    client.post("/api/v1/fixtures", json={"category": "washer", "owner": "tenant", "unit_ids": [units["101"]]})
    client.post("/api/v1/fixtures", json={"category": "fridge", "unit_ids": [units["102"]]})  # 다른 호실
    _create(client, leases["101"], "move_in")
    areas = [i["area"] for i in _view(client, leases["101"])["move_in"]["items"]]
    assert areas[:3] == list(svc.STANDARD_AREAS[:3]) and "수도 계량기" in areas
    assert areas[-2:] == ["에어컨", "세탁기 (임차인 소유)"] and "냉장고" not in areas
    res = client.post(f"/api/v1/leases/{leases['101']}/inspections", json={"kind": "move_in"})
    assert res.status_code == 409  # 입주 점검은 한 번
    assert client.post(f"/api/v1/leases/{leases['101']}/inspections", json={"kind": "moving"}).status_code == 409


def test_move_out_copies_move_in_items_in_same_order(client, leases):
    iid = _create(client, leases["102"], "move_in")
    client.post(f"/api/v1/inspections/{iid}/items", json={"area": "베란다 타일"})
    _create(client, leases["102"], "move_out", "2027-07-04")
    v = _view(client, leases["102"])
    assert [i["area"] for i in v["move_out"]["items"]] == [i["area"] for i in v["move_in"]["items"]]
    assert v["move_out"]["items"][-1]["area"] == "베란다 타일"
    assert all(i["condition"] is None for i in v["move_out"]["items"])  # 상태는 비어서 시작 (추정 안 함)


def test_items_photos_and_lock_after_tenant_confirmation(client, leases, make_client):
    iid = _create(client, leases["101"], "move_in")
    item = _view(client, leases["101"])["move_in"]["items"][2]  # 벽지
    url = f"/api/v1/inspection-items/{item['id']}"
    assert client.put(url, json={"condition": "great"}).status_code == 409
    assert client.put(url, json={"condition": "good", "note": "새로 도배", "reading": " "}).status_code == 200
    ph = client.post(f"{url}/photos", files={"file": ("w.png", PNG)})
    assert ph.status_code == 201
    assert client.post(f"{url}/photos", files={"file": ("w.png", PNG)}).status_code == 409  # 같은 사진
    assert client.post(f"{url}/photos", files={"file": ("x.pdf", PDF)}).status_code == 415
    big = PNG + b"0" * svc.MAX_PHOTO_BYTES
    assert client.post(f"{url}/photos", files={"file": ("b.png", big)}).status_code == 413
    pid = ph.json()["id"]
    got = client.get(f"/api/v1/inspection-photos/{pid}")
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
    other, _ = make_client(org_name="남의 건물")
    assert other.get(f"/api/v1/inspection-photos/{pid}").status_code == 404
    assert other.put(url, json={"condition": "damaged"}).status_code == 404
    it = _view(client, leases["101"])["move_in"]["items"][2]
    assert (it["condition"], it["note"], it["reading"], len(it["photos"])) == ("good", "새로 도배", None, 1)

    # 임차인과 확인하면 잠김
    res = client.post(f"/api/v1/inspections/{iid}/confirm", json={"confirmed_on": "2025-03-01", "note": "현장 동행"})
    assert res.status_code == 200
    for call in (lambda: client.put(url, json={"condition": "damaged"}),
                 lambda: client.post(f"{url}/photos", files={"file": ("n.png", PNG + b"1")}),
                 lambda: client.delete(f"/api/v1/inspection-photos/{pid}"),
                 lambda: client.post(f"/api/v1/inspections/{iid}/items", json={"area": "x"}),
                 lambda: client.delete(f"/api/v1/inspections/{iid}")):
        assert call().status_code == 409
    assert _view(client, leases["101"])["move_in"]["locked"] is True
    assert client.post(f"/api/v1/inspections/{iid}/unconfirm", json={"reason": "사진 추가"}).status_code == 200
    assert client.put(url, json={"condition": "worn"}).status_code == 200
    assert client.delete(f"/api/v1/inspection-photos/{pid}").status_code == 204


def test_photos_follow_backup_and_organization_deletion(client, org, leases, session):
    _create(client, leases["101"], "move_in")
    item = _view(client, leases["101"])["move_in"]["items"][0]
    client.post(f"/api/v1/inspection-items/{item['id']}/photos", files={"file": ("d.png", PNG)})
    import uuid
    rows = backup.collect(session, uuid.UUID(org))
    names = backup.file_names(rows)
    assert len(rows["inspection_photos"]) == 1 and len(names) == 1
    _, manifest = backup.build(session, uuid.UUID(org), "long enough pass")
    assert manifest["files"] == 1 and manifest["counts"]["inspection_items"] == len(svc.STANDARD_AREAS)
    assert storage.load(names[0]) == PNG
    from app.services import account_deletion
    res = account_deletion.delete_organization(session, uuid.UUID(org))
    assert res["files"] == 1
    with pytest.raises(Exception):
        storage.load(names[0])


def _settle(client, lease_id, as_of="2026-11-05"):
    return client.get(f"/api/v1/leases/{lease_id}/settlement", params={"as_of": as_of}).json()


def test_settlement_uses_ledger_facts_and_holds_disputed(client, org, leases, session):
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    lid = leases["101"]  # 보증금 5,000,000 수령, 월세 450,000 납부일 1일
    s = _settle(client, lid)
    assert s["deposit_unreturned"] == 5_000_000 and s["prepaid_credit"] == 0
    assert s["unpaid"] == [{"period": "2026-11", "due_date": "2026-11-01", "amount": 450_000}]
    assert s["return_now"] == 4_550_000 and s["status"] == "draft"
    assert any("은행 거래내역이 없습니다" in w for w in s["warnings"])
    assert any("퇴실 점검 기록이 없습니다" in w for w in s["warnings"])
    assert _settle(client, lid, "2026-10-31")["unpaid"] == []  # 납부일 전이면 미납 아님

    _create(client, lid, "move_out", "2026-11-05")
    wall = _view(client, lid)["move_out"]["items"][2]
    client.put(f"/api/v1/inspection-items/{wall['id']}", json={"condition": "worn"})
    url = f"/api/v1/leases/{lid}/settlement/deductions"
    assert client.post(url, json={"category": "cleaning", "label": "입주 청소", "amount": 100_000}).status_code == 201
    dmg = client.post(url, json={"category": "damage", "label": "벽지 전체 도배", "amount": 200_000, "disputed": True,
                                 "inspection_item_id": wall["id"]}).json()["id"]
    assert client.post(url, json={"category": "fine", "label": "x", "amount": 1}).status_code == 409
    assert client.post(url, json={"category": "other", "label": "x", "amount": -1}).status_code == 409
    other_item = _view(client, leases["101"])["move_out"]["items"][0]["id"]
    assert client.post(f"/api/v1/leases/{leases['102']}/settlement/deductions",
                       json={"category": "other", "label": "x", "amount": 1, "inspection_item_id": other_item}).status_code == 404
    s = _settle(client, lid)
    assert (s["agreed_deductions"], s["disputed_held"]) == (100_000, 200_000)
    assert s["return_now"] == 5_000_000 - 450_000 - 100_000 - 200_000  # 다툼 있는 금액은 먼저 돌려줄 금액에서 빼 둠
    assert any("생활 마모" in w for w in s["warnings"])
    assert s["deductions"][1]["inspection_item_area"] == "벽지"

    done = client.post(f"/api/v1/leases/{lid}/settlement/confirm", params={"as_of": "2026-11-05"}, json={"note": "합의"})
    assert done.status_code == 200 and done.json()["status"] == "confirmed" and done.json()["return_now"] == 4_250_000
    assert client.post(url, json={"category": "other", "label": "늦게", "amount": 1}).status_code == 409  # 잠김
    assert client.delete(f"/api/v1/settlement-deductions/{dmg}").status_code == 409
    # 확정 뒤 장부가 바뀌어도 정산서 숫자는 그대로 (스냅숏)
    client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-12"})
    assert _settle(client, lid, "2026-12-31")["return_now"] == 4_250_000
    assert client.post(f"/api/v1/leases/{lid}/settlement/reopen", json={"reason": "도배비 합의"}).status_code == 200
    assert _settle(client, lid, "2026-12-31")["return_now"] == 4_250_000 - 450_000
    assert client.delete(f"/api/v1/settlement-deductions/{dmg}").status_code == 204
    assert session.scalar(select(AuditLog).where(AuditLog.action == "settlement.reopen")) is not None


def test_settlement_without_received_deposit_is_unknown(client):
    org = client.post("/api/v1/onboarding", json={"property": {"name": "x"}, "units": [
        {"unit_no": "101", "tenant_name": "미수령", "rent": 400000, "due_day": 5, "start_date": "2026-01-01",
         "deposit": 3_000_000}]}).json()["organization_id"]
    lid = client.get("/api/v1/contracts", params={"organization_id": org}).json()[0]["lease_id"]
    s = _settle(client, lid)
    assert s["deposit_unreturned"] is None and s["return_now"] is None
    assert any("보증금 수령 기록이 없어" in w for w in s["warnings"])
    assert client.post(f"/api/v1/leases/{lid}/settlement/confirm", json={}).status_code == 409


def test_lease_list_shows_progress(client, leases):
    _create(client, leases["101"], "move_in")
    rows = {r["unit_no"]: r for r in client.get("/api/v1/move-out/leases").json()}
    assert rows["101"]["move_in"] is True and rows["101"]["move_out"] is False and rows["101"]["settlement"] is None
    assert "203" not in rows  # 공실은 계약이 없음
