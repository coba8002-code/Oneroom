"""회원 탈퇴 · 사업장 해지 · 파기."""
import dataclasses
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import auth
from app.config import settings
from app.models import AuditLog, AuthSession, Base, EmailToken, Organization, User
from app.services import backup, storage
from tests.conftest import ORG_NAME, PASSWORD, SAMPLES

PNG = b"\x89PNG\r\n\x1a\n" + b"lease" * 30


def _fill(c, org):
    """호실·계약·청구·은행 거래·매칭·운영비·계약서까지 채운다."""
    raw = (SAMPLES / "onboarding_units.csv").read_bytes()
    units = c.post("/api/v1/onboarding/csv-preview", files={"file": ("u.csv", raw)}).json()["units"]
    ob = c.post("/api/v1/onboarding", json={"property": {"name": "건물"}, "units": units}).json()
    c.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    bank = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    c.post(f"/api/v1/bank-accounts/{ob['bank_account_id']}/import", files={"file": ("b.csv", bank)})
    c.post("/api/v1/matching/run", params={"organization_id": org})
    c.post("/api/v1/expenses/classify", params={"organization_id": org})
    lease = c.get("/api/v1/contracts", params={"organization_id": org}).json()[0]["lease_id"]
    c.post(f"/api/v1/leases/{lease}/documents", params={"organization_id": org}, files={"file": ("c.png", PNG)})


def _rows_for(session, org_id):
    rows = backup.collect(session, org_id)
    return {k: len(v) for k, v in rows.items() if v}


def _delete(c, **kw):
    return c.post("/api/v1/auth/account/delete", json={"password": PASSWORD, **kw})


def test_owner_deletion_wipes_org_only(make_client, session, mailbox):
    a, me_a = make_client(email="a@example.com")
    b, me_b = make_client(email="b@example.com", org_name="남의 사업장")
    org_a, org_b = me_a["organization"]["id"], me_b["organization"]["id"]
    _fill(a, org_a)
    _fill(b, org_b)
    before_b = _rows_for(session, uuid.UUID(org_b))
    files_a = [d["file_path"] for d in backup.collect(session, uuid.UUID(org_a))["lease_documents"]]
    assert files_a and all((Path(settings.upload_dir) / f).exists() for f in files_a)

    preview = a.get("/api/v1/auth/account/deletion-preview").json()
    assert preview["scope"] == "organization" and preview["counts"]["units"] == 10
    assert preview["counts"]["transactions"] == 14 and preview["counts"]["documents"] == 1

    res = _delete(a, confirm_name=ORG_NAME)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "organization" and body["files"] == 1 and body["deleted"]["transactions"] == 14

    session.expire_all()
    assert _rows_for(session, uuid.UUID(org_a)) == {}  # 업무 데이터 0건
    assert session.get(Organization, uuid.UUID(org_a)) is None
    assert session.scalar(select(func.count()).select_from(User).where(User.email == "a@example.com")) == 0
    uid_rows = session.scalars(select(AuthSession.user_id)).all() + session.scalars(select(EmailToken.user_id)).all()
    assert all(session.get(User, u) is not None for u in uid_rows)  # 지워진 계정의 세션·토큰 없음
    assert not any((Path(settings.upload_dir) / f).exists() for f in files_a)  # 계약서 파일 삭제
    assert _rows_for(session, uuid.UUID(org_b)) == before_b  # 다른 사업장은 그대로
    assert a.get("/api/v1/auth/me").status_code == 401  # 세션도 끝


def test_deletion_record_has_no_personal_data(make_client, session):
    a, me = make_client(email="rec@example.com")
    _fill(a, me["organization"]["id"])
    _delete(a, confirm_name=ORG_NAME)
    logs = session.scalars(select(AuditLog)).all()
    assert [log.action for log in logs] == ["organization.deleted"]  # 남는 건 파기 기록 한 줄뿐
    text = str(logs[0].detail)
    assert "rec@example.com" not in text and "임차인" not in text and "010-" not in text
    assert logs[0].user_id is None


def test_email_can_sign_up_again(make_client, anon_client):
    a, _ = make_client(email="again@example.com")
    _delete(a, confirm_name=ORG_NAME)
    res = anon_client.post("/api/v1/auth/signup", json={
        "email": "again@example.com", "password": PASSWORD, "name": "다시", "organization_name": "새 사업장",
        "agree_terms": True, "agree_privacy": True})
    assert res.status_code == 201


@pytest.mark.parametrize("kw,status,msg", [
    ({"password": "wrong-pass-1", "confirm_name": ORG_NAME}, 401, "비밀번호"),
    ({"confirm_name": "다른 이름"}, 422, "사업장 이름"),
    ({}, 422, "사업장 이름"),
])
def test_confirmations_required(client, kw, status, msg):
    res = client.post("/api/v1/auth/account/delete", json={"password": PASSWORD, **kw})
    assert res.status_code == status and msg in res.json()["detail"]
    assert client.get("/api/v1/auth/me").status_code == 200  # 아무것도 안 지워짐


def test_mfa_code_required(make_client):
    c, _ = make_client(email="m@example.com")
    secret = c.post("/api/v1/auth/mfa/setup").json()["secret"]
    c.post("/api/v1/auth/mfa/enable", json={"code": auth.totp_now(secret)})
    assert _delete(c, confirm_name=ORG_NAME).status_code == 401
    assert _delete(c, confirm_name=ORG_NAME, otp=auth.totp_now(secret)).status_code == 200


def test_safety_backups_removed(make_client, session, monkeypatch, tmp_path):
    from app.services import blobs
    monkeypatch.setattr(blobs, "settings", dataclasses.replace(settings, backup_dir=str(tmp_path)))
    blobs.store.cache_clear()
    a, me = make_client(email="s@example.com")
    org = uuid.UUID(me["organization"]["id"])
    _fill(a, str(org))
    blob, _ = backup.export(session, org, "safety-pass-123")
    backup.restore(session, blob, "safety-pass-123", org, confirm_name=ORG_NAME)  # 안전 백업 생성
    other = tmp_path / f"pre-restore-{uuid.uuid4()}-20260101-000000.roomaxbak"
    other.write_bytes(b"x")  # 다른 사업장의 안전 백업
    assert len(backup.safety_backups(org)) == 1
    res = _delete(a, confirm_name=ORG_NAME).json()
    assert res["safety_backups"] == 1 and backup.safety_backups(org) == [] and other.exists()


def test_member_deletion_keeps_org(client, onboarded, session, anon_client):
    org = onboarded["organization_id"]
    session.add(User(organization_id=uuid.UUID(org), email="mgr@example.com", name="관리자", role="manager",
                     password_hash=auth.hash_password(PASSWORD)))
    session.commit()
    anon_client.post("/api/v1/auth/login", json={"email": "mgr@example.com", "password": PASSWORD})
    anon_client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    mgr_id = session.scalar(select(User.id).where(User.email == "mgr@example.com"))
    assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.user_id == mgr_id)) >= 1

    assert anon_client.get("/api/v1/auth/account/deletion-preview").json()["scope"] == "member"
    res = anon_client.post("/api/v1/auth/account/delete", json={"password": PASSWORD})
    assert res.json()["scope"] == "member"

    session.expire_all()
    assert session.get(User, mgr_id) is None
    assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.user_id == mgr_id)) == 0
    assert session.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.entity_type == "user", AuditLog.entity_id == str(mgr_id))) == 0  # 계정 자체 기록 삭제
    assert client.get("/api/v1/dashboard", params={"organization_id": org}).status_code == 200  # 사업장 그대로
    assert anon_client.post("/api/v1/auth/login", json={"email": "mgr@example.com", "password": PASSWORD}).status_code == 401


def test_storage_delete_ignores_bad_names(tmp_path):
    storage.delete("../../etc/passwd")  # 경로 조작은 무시
    storage.delete("not-a-file.bin")


def test_every_table_is_handled_by_deletion():
    """새 테이블이 생기면 backup.COVERED/EXCLUDED 에 들어가야 하고, 그래야 해지 때도 지워진다."""
    handled = backup.COVERED | backup.EXCLUDED
    assert set(Base.metadata.tables) == handled
