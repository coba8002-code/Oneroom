"""백업 · 복구 — PRD §8 "사용자 데이터 내보내기/백업/복구 성공"."""
import dataclasses
import json
import re
import uuid
from datetime import date
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.crypto
import app.services.blobs
import app.services.storage
from app import backup_cli
from app.config import settings
from app.models import AuditLog, Base, Expense, Organization, Tenant
from app.services import backup, dashboard, storage
from tests.conftest import ORG_NAME, SAMPLES

PASS = "correct horse battery"
PNG = b"\x89PNG\r\n\x1a\n" + b"contract-image" * 20
ALEMBIC = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _p(org, **kw):
    return {"organization_id": org, **kw}


@pytest.fixture
def rich(client, onboarded):
    """수납·운영비·계약서까지 채운 상태."""
    org = onboarded["organization_id"]
    client.post("/api/v1/charges/generate", params=_p(org, period="2026-11"))
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    client.post(f"/api/v1/bank-accounts/{onboarded['bank_account_id']}/import", files={"file": ("s.csv", raw)})
    client.post("/api/v1/matching/run", params=_p(org))
    q = client.get("/api/v1/matching/queue", params=_p(org)).json()
    kim = next(x for x in q if x["transaction"]["counterparty"] == "김OO")
    l302 = next(x["lease_id"] for x in client.get("/api/v1/leases", params=_p(org)).json() if x["unit_no"] == "302")
    client.post(f"/api/v1/transactions/{kim['transaction']['id']}/decision", params=_p(org),
                json={"lease_id": l302, "category": "rent", "remember_alias": True})
    client.post("/api/v1/expenses/classify", params=_p(org))
    mart = next(x for x in client.get("/api/v1/expenses/queue", params=_p(org)).json()
                if x["transaction"]["counterparty"] == "마트")
    client.post(f"/api/v1/transactions/{mart['transaction']['id']}/expense-decision", params=_p(org), json={
        "splits": [{"category": "personal", "amount": 60000}, {"category": "owner_household", "amount": 27400}],
        "remember": True})
    lease = client.get("/api/v1/contracts", params=_p(org)).json()[0]["lease_id"]
    doc = client.post(f"/api/v1/leases/{lease}/documents", params=_p(org), files={"file": ("c.png", PNG)}).json()
    client.post(f"/api/v1/documents/{doc['id']}/verify", params=_p(org), json={
        "deposit": 5_000_000, "rent": 470_000, "due_day": 3, "start_date": "2025-03-01", "end_date": "2027-02-28"})
    # 자산대장·수리 이력 (호실 품목 + 건물 공용)
    units = {u["unit_no"]: u["unit_id"] for u in client.get("/api/v1/units", params=_p(org)).json()}
    fx = client.post("/api/v1/fixtures", json={"category": "aircon", "brand": "LG", "manufactured": "2019-06",
                                               "price": 650_000, "unit_ids": [units["101"]]}).json()
    client.post("/api/v1/fixtures", json={"category": "cctv"})
    client.post("/api/v1/repairs", json={"description": "냉매 보충", "fixture_id": fx["ids"][0], "cost": 80_000,
                                         "reported_on": "2026-08-01", "completed_on": "2026-08-02", "payer": "landlord"})
    client.post("/api/v1/repairs", json={"description": "복도 누수", "reported_on": "2026-09-01"})
    return onboarded


def _snapshot(session, org_id):
    """사업장 데이터 비교용. 사업장 행 자체와 사업장 id 는 빼고 비교 (다른 사업장으로 복구해도 같아야 함)."""
    rows = backup.collect(session, org_id)
    rows.pop("organizations")
    # 계정은 백업에 없어 복구하면 감사 기록의 사용자 연결이 끊긴다 (backup.restore) — 그 열은 비교하지 않음
    rows["audit_logs"] = [{**r, "user_id": None} for r in rows["audit_logs"] if not r["action"].startswith("backup.")]
    text = json.dumps({k: sorted(([{c: backup._enc(v) for c, v in r.items()} for r in rs]), key=lambda r: r["id"])
                       for k, rs in rows.items()}, default=str)
    return json.loads(text.replace(str(org_id), "ORG"))


def _dash(session, org_id):
    d = dashboard.build(session, org_id, date(2026, 11, 26))
    d["attention"] = [a for a in d["attention"] if not a["kind"].startswith("backup")]
    return json.loads(json.dumps(d, default=str))


# ── 구조 ──

def test_every_table_is_covered():
    """새 테이블을 만들고 backup.ORG_COLUMN / CHILDREN / EXCLUDED 에 안 넣으면 여기서 실패한다."""
    assert set(Base.metadata.tables) == backup.COVERED | backup.EXCLUDED
    assert not backup.COVERED & backup.EXCLUDED


def test_schema_revision_matches_alembic_head():
    revs = sorted(re.match(r"^(\d{4})_", p.name).group(1) for p in ALEMBIC.glob("[0-9]*.py"))
    assert backup.SCHEMA_REVISION == revs[-1]


def test_encryption():
    blob = backup.encrypt(b"hello", PASS)
    assert blob.startswith(backup.MAGIC) and b"hello" not in blob
    assert backup.decrypt(blob, PASS) == b"hello"
    with pytest.raises(backup.BackupError, match="비밀번호"):
        backup.decrypt(blob, "wrong passphrase")
    with pytest.raises(backup.BackupError, match="8자"):
        backup.encrypt(b"x", "short")
    with pytest.raises(backup.BackupError, match="ROOMAX 백업 파일이 아닙니다"):
        backup.decrypt(b"PK\x03\x04 zip", PASS)
    tampered = bytearray(blob)
    tampered[-1] ^= 1
    with pytest.raises(backup.BackupError):
        backup.decrypt(bytes(tampered), PASS)


# ── 왕복 ──

def _backup_dir(monkeypatch, path):
    from app.services import blobs
    monkeypatch.setattr(blobs, "settings", dataclasses.replace(blobs.settings, backup_dir=str(path)))
    blobs.store.cache_clear()


def test_round_trip_to_new_server_with_different_key(rich, session, monkeypatch, tmp_path):
    org_id = uuid.UUID(rich["organization_id"])
    before = _snapshot(session, org_id)
    dash_before = _dash(session, org_id)
    blob, manifest = backup.export(session, org_id, PASS)
    assert manifest["counts"]["lease_documents"] == 1 and manifest["files"] == 1
    assert manifest["counts"]["fixtures"] == 2 and manifest["counts"]["maintenance_tickets"] == 2
    assert b"010-0000" not in blob and PNG not in blob  # 연락처·계약서가 평문으로 보이지 않음

    # 새 서버: 빈 DB · 다른 암호화 키 · 다른 파일 저장소
    new = dataclasses.replace(settings, field_key=Fernet.generate_key().decode(), upload_dir=str(tmp_path / "up"))
    monkeypatch.setattr(app.crypto, "settings", new)
    monkeypatch.setattr(app.services.blobs, "settings", new)
    app.services.blobs.store.cache_clear()
    app.crypto._fernet.cache_clear()
    try:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine, expire_on_commit=False)() as s2:
            new_org = Organization(name="새 서버 가입")  # 새 서버에서 회원가입 → 다른 사업장 id
            s2.add(new_org)
            s2.commit()
            info = backup.inspect(s2, blob, PASS, new_org.id)
            assert info["exists"] is False and info["compatible"] and info["counts"] == manifest["counts"]
            assert info["same_organization"] is False
            res = backup.restore(s2, blob, PASS, new_org.id)
            assert res["replaced"] is False and res["safety_backup"] is None

            assert _snapshot(s2, new_org.id) == before
            assert _dash(s2, new_org.id) == dash_before
            assert s2.scalar(select(func.count()).select_from(Organization)) == 1  # 사업장이 새로 생기지 않음
            phone = s2.scalar(select(Tenant.phone).limit(1))
            assert phone.startswith("010-")  # 새 키로 다시 암호화돼 읽힘
            doc = backup.collect(s2, new_org.id)["lease_documents"][0]
            assert storage.load(doc["file_path"]) == PNG
            assert not list(Path(new.upload_dir).glob("restore-*"))
            assert s2.scalar(select(AuditLog).where(AuditLog.action == "backup.restore")) is not None
    finally:
        app.crypto._fernet.cache_clear()


def test_replace_needs_name_and_keeps_safety_backup(rich, session, monkeypatch, tmp_path):
    _backup_dir(monkeypatch, tmp_path / "bk")
    org_id = uuid.UUID(rich["organization_id"])
    blob, _ = backup.export(session, org_id, PASS)
    before = _snapshot(session, org_id)

    # 백업 뒤에 생긴 변경 (현금 지출)
    session.add(Expense(organization_id=org_id, category="repair", amount=12345, spent_on=date(2026, 11, 29)))
    session.commit()

    with pytest.raises(backup.BackupConflict, match="사업장 이름"):
        backup.restore(session, blob, PASS, org_id)
    with pytest.raises(backup.BackupConflict):
        backup.restore(session, blob, PASS, org_id, confirm_name="다른 이름")
    session.add(AuditLog(action="note.after_backup", entity_type="organization", entity_id=str(org_id)))
    session.commit()
    res = backup.restore(session, blob, PASS, org_id, confirm_name=ORG_NAME)
    assert res["replaced"] is True

    session.expire_all()
    after = _snapshot(session, org_id)
    # 업무 데이터는 백업 시점으로, 감사 기록은 되감지 않음 (백업 뒤 기록·내보내기 이력 유지)
    assert {k: v for k, v in after.items() if k != "audit_logs"} == {k: v for k, v in before.items() if k != "audit_logs"}
    assert {r["id"] for r in before["audit_logs"]} <= {r["id"] for r in after["audit_logs"]}
    assert any(r["action"] == "note.after_backup" for r in after["audit_logs"])
    assert backup.last_backup_at(session, org_id) is not None
    assert session.scalar(select(Expense).where(Expense.amount == 12345)) is None

    safety = Path(tmp_path / "bk" / res["safety_backup"])
    manifest, z = backup.open_backup(safety.read_bytes(), PASS)  # 같은 비밀번호로 열림
    assert any(e["amount"] == 12345 for e in json.loads(z.read("data/expenses.json")))
    doc = backup.collect(session, org_id)["lease_documents"][0]
    assert storage.load(doc["file_path"]) == PNG


def test_failed_restore_changes_nothing(rich, session, monkeypatch, tmp_path):
    _backup_dir(monkeypatch, tmp_path / "bk")
    org_id = uuid.UUID(rich["organization_id"])
    blob, _ = backup.export(session, org_id, PASS)
    session.add(Expense(organization_id=org_id, category="repair", amount=777, spent_on=date(2026, 11, 29)))
    session.commit()
    before = _snapshot(session, org_id)

    def boom(*a, **k):
        raise OSError("디스크 가득 참")
    monkeypatch.setattr(storage, "stage", boom)
    with pytest.raises(OSError):
        backup.restore(session, blob, PASS, org_id, confirm_name=ORG_NAME)
    session.expire_all()
    assert _snapshot(session, org_id) == before  # 지운 것도 되돌아옴
    doc = backup.collect(session, org_id)["lease_documents"][0]
    assert storage.load(doc["file_path"]) == PNG


def test_different_schema_revision_refused(rich, session, monkeypatch):
    org_id = uuid.UUID(rich["organization_id"])
    blob, _ = backup.export(session, org_id, PASS)
    monkeypatch.setattr(backup, "SCHEMA_REVISION", "9999")
    assert backup.inspect(session, blob, PASS, org_id)["compatible"] is False
    with pytest.raises(backup.BackupConflict, match="다른 버전"):
        backup.restore(session, blob, PASS, org_id, confirm_name=ORG_NAME)


# ── API · CLI · 대시보드 ──

def test_api_export_inspect_restore(client, rich, monkeypatch, tmp_path):
    _backup_dir(monkeypatch, tmp_path / "bk")
    org = rich["organization_id"]
    assert client.post("/api/v1/backups/export", params=_p(org), json={"passphrase": "short"}).status_code == 422
    res = client.post("/api/v1/backups/export", params=_p(org), json={"passphrase": PASS})
    assert res.status_code == 200 and res.headers["content-disposition"].endswith('.roomaxbak"')
    cors = client.post("/api/v1/backups/export", params=_p(org), json={"passphrase": PASS},
                       headers={"Origin": "http://localhost:3000"})
    assert "content-disposition" in cors.headers["access-control-expose-headers"].lower()
    blob = res.content
    assert client.get("/api/v1/backups/status", params=_p(org)).json()["last_backup_at"] is not None

    files = {"file": ("b.roomaxbak", blob)}
    bad = client.post("/api/v1/backups/inspect", files=files, data={"passphrase": "wrong passphrase"})
    assert bad.status_code == 422 and "비밀번호" in bad.json()["detail"]
    info = client.post("/api/v1/backups/inspect", files=files, data={"passphrase": PASS}).json()
    assert info["exists"] is True and info["existing_name"] == ORG_NAME
    assert client.post("/api/v1/backups/restore", files=files, data={"passphrase": PASS}).status_code == 409
    ok = client.post("/api/v1/backups/restore", files=files, data={"passphrase": PASS, "confirm_name": ORG_NAME})
    assert ok.status_code == 200 and ok.json()["replaced"] is True


def test_cli_backs_up_every_org_and_rotates(rich, session_factory, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(backup_cli, "SessionLocal", session_factory)
    monkeypatch.delenv("ROOMAX_BACKUP_PASSPHRASE", raising=False)
    assert backup_cli.main(["--out", str(tmp_path)]) == 2  # 비밀번호 없으면 거부
    monkeypatch.setenv("ROOMAX_BACKUP_PASSPHRASE", PASS)
    names = []
    for i in range(3):
        monkeypatch.setattr(backup, "filename", lambda m, prefix="roomax", i=i: f"roomax-{m['organization']['id'][:8]}-2026111{i}-000000.roomaxbak")
        assert backup_cli.main(["--out", str(tmp_path), "--keep", "2"]) == 0
    names = sorted(p.name for p in tmp_path.glob("*.roomaxbak"))
    assert len(names) == 2 and names[0].endswith("20261111-000000.roomaxbak")
    backup.open_backup((tmp_path / names[-1]).read_bytes(), PASS)


def test_cli_removes_backups_of_deleted_orgs_after_grace(rich, session_factory, monkeypatch, tmp_path):
    import os
    import time
    monkeypatch.setattr(backup_cli, "SessionLocal", session_factory)
    monkeypatch.setenv("ROOMAX_BACKUP_PASSPHRASE", PASS)
    gone_recent = tmp_path / "roomax-deadbeef-20261101-000000.roomaxbak"
    gone_old = [tmp_path / f"roomax-0dc0de00-2026090{i}-000000.roomaxbak" for i in (1, 2)]
    for p in [gone_recent, *gone_old]:
        p.write_bytes(b"x")
    old = time.time() - 40 * 86400
    for p in gone_old:
        os.utime(p, (old, old))
    assert backup_cli.main(["--out", str(tmp_path), "--orphan-days", "30"]) == 0
    assert gone_recent.exists()  # 해지 30일 안 — 아직 둔다
    assert not any(p.exists() for p in gone_old)
    live = rich["organization_id"][:8]
    assert [p for p in tmp_path.glob(f"roomax-{live}-*.roomaxbak")]  # 살아 있는 사업장 백업은 그대로


def test_dashboard_reminds_backup(client, rich):
    org = rich["organization_id"]
    d = client.get("/api/v1/dashboard", params=_p(org, as_of="2026-11-26")).json()
    assert "backup_none" in {a["kind"] for a in d["attention"]}
    client.post("/api/v1/backups/export", params=_p(org), json={"passphrase": PASS})
    today = date.today().isoformat()
    d = client.get("/api/v1/dashboard", params=_p(org, as_of=today)).json()
    assert not {"backup_none", "backup_old"} & {a["kind"] for a in d["attention"]}


class _MemStore:
    """Supabase 보관소 흉내 (서명 주소 포함)."""
    def __init__(self):
        self.obj = {}

    def put(self, key, data): self.obj[key] = data
    def get(self, key):
        if key not in self.obj:
            raise FileNotFoundError(key)
        return self.obj[key]
    def delete(self, keys): [self.obj.pop(k, None) for k in keys]
    def list(self, prefix): return sorted(k for k in self.obj if k.startswith(prefix))
    def move(self, src, dst): self.obj[dst] = self.obj.pop(src)
    def signed_download_url(self, key, expires, name): return f"https://sb/sign/{key}?download={name}"
    def signed_upload_url(self, key): return f"https://sb/upload/{key}?token=t"


def test_direct_transfer_export_and_restore(client, rich, monkeypatch):
    """서버리스: 백업 파일은 브라우저가 Storage 와 직접 주고받고, 서버는 키로 연다."""
    from datetime import datetime, timedelta

    from app.services import blobs, scheduled_backup
    mem = _MemStore()
    monkeypatch.setattr(blobs, "direct_transfer", lambda: True)
    real = blobs.store
    monkeypatch.setattr(blobs, "store", lambda area: mem if area == "backups" else real(area))
    org = rich["organization_id"]
    assert client.get("/api/v1/backups/status", params=_p(org)).json()["direct_transfer"] is True

    out = client.post("/api/v1/backups/export", params=_p(org), json={"passphrase": PASS}).json()
    key = next(k for k in mem.obj if k.startswith("export-"))
    assert out["download_url"] == f"https://sb/sign/{key}?download={out['filename']}" and out["size"] == len(mem.obj[key])

    up = client.post("/api/v1/backups/upload-url", params=_p(org)).json()
    assert up["upload_url"].startswith("https://sb/upload/upload-")
    mem.put(up["key"], mem.obj[key])  # 브라우저가 서명 주소로 올린 셈
    info = client.post("/api/v1/backups/inspect", data={"key": up["key"], "passphrase": PASS}).json()
    assert info["compatible"] is True and info["exists"] is True
    assert client.post("/api/v1/backups/inspect", data={"key": "../etc/passwd", "passphrase": PASS}).status_code == 422
    res = client.post("/api/v1/backups/restore", data={"key": up["key"], "passphrase": PASS, "confirm_name": ORG_NAME})
    assert res.status_code == 200, res.text
    assert up["key"] not in mem.obj  # 다 쓴 업로드 파일은 지움
    assert any(k.startswith("pre-restore-") for k in mem.obj)  # 안전 백업도 보관소에

    # 매일 작업이 하루 지난 임시 전송 파일을 지운다
    mem.put("upload-20200101000000-" + "0" * 32 + ".roomaxbak", b"x")
    removed = scheduled_backup.remove_transfers(mem, datetime.now(backup.KST) + timedelta(days=2))
    assert removed and not any(k.startswith(("export-", "upload-")) for k in mem.obj)
