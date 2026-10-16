"""백업 · 복구 — PRD §8 "사용자 데이터 내보내기/백업/복구 성공"."""
import dataclasses
import json
import re
from datetime import date
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.crypto
import app.services.storage
from app import backup_cli
from app.config import settings
from app.models import AuditLog, Base, Expense, Tenant
from app.services import backup, dashboard, storage
from tests.conftest import SAMPLES

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
    return onboarded


def _snapshot(session, org_id):
    rows = backup.collect(session, org_id)
    rows["audit_logs"] = [r for r in rows["audit_logs"] if not r["action"].startswith("backup.")]
    return json.loads(json.dumps({k: sorted(([{c: backup._enc(v) for c, v in r.items()} for r in rs]),
                                            key=lambda r: r["id"]) for k, rs in rows.items()}, default=str))


def _dash(session, org_id):
    d = dashboard.build(session, org_id, date(2026, 11, 26))
    d["attention"] = [a for a in d["attention"] if not a["kind"].startswith("backup")]
    return json.loads(json.dumps(d, default=str))


# ── 구조 ──

def test_every_table_is_covered():
    """새 테이블을 만들고 backup.ORG_COLUMN / CHILDREN 에 안 넣으면 여기서 실패한다."""
    assert set(Base.metadata.tables) == backup.COVERED


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

def test_round_trip_to_new_server_with_different_key(rich, session, monkeypatch, tmp_path):
    import uuid
    org_id = uuid.UUID(rich["organization_id"])
    before = _snapshot(session, org_id)
    dash_before = _dash(session, org_id)
    blob, manifest = backup.export(session, org_id, PASS)
    assert manifest["counts"]["lease_documents"] == 1 and manifest["files"] == 1
    assert b"010-0000" not in blob and PNG not in blob  # 연락처·계약서가 평문으로 보이지 않음

    # 새 서버: 빈 DB · 다른 암호화 키 · 다른 파일 저장소
    new = dataclasses.replace(settings, field_key=Fernet.generate_key().decode(), upload_dir=str(tmp_path / "up"))
    monkeypatch.setattr(app.crypto, "settings", new)
    monkeypatch.setattr(app.services.storage, "settings", new)
    app.crypto._fernet.cache_clear()
    try:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine, expire_on_commit=False)() as s2:
            info = backup.inspect(s2, blob, PASS)
            assert info["exists"] is False and info["compatible"] and info["counts"] == manifest["counts"]
            res = backup.restore(s2, blob, PASS)
            assert res["replaced"] is False and res["safety_backup"] is None

            assert _snapshot(s2, org_id) == before
            assert _dash(s2, org_id) == dash_before
            phone = s2.scalar(select(Tenant.phone).limit(1))
            assert phone.startswith("010-")  # 새 키로 다시 암호화돼 읽힘
            doc = backup.collect(s2, org_id)["lease_documents"][0]
            assert storage.load(doc["file_path"]) == PNG
            assert not list(Path(new.upload_dir).glob(".*.restore"))
            assert s2.scalar(select(AuditLog).where(AuditLog.action == "backup.restore")) is not None
    finally:
        app.crypto._fernet.cache_clear()


def test_replace_needs_name_and_keeps_safety_backup(rich, session, monkeypatch, tmp_path):
    import uuid
    monkeypatch.setattr(backup, "settings", dataclasses.replace(settings, backup_dir=str(tmp_path / "bk")))
    org_id = uuid.UUID(rich["organization_id"])
    blob, _ = backup.export(session, org_id, PASS)
    before = _snapshot(session, org_id)

    # 백업 뒤에 생긴 변경 (현금 지출)
    session.add(Expense(organization_id=org_id, category="repair", amount=12345, spent_on=date(2026, 11, 29)))
    session.commit()

    with pytest.raises(backup.BackupConflict, match="사업장 이름"):
        backup.restore(session, blob, PASS)
    with pytest.raises(backup.BackupConflict):
        backup.restore(session, blob, PASS, confirm_name="다른 이름")
    session.add(AuditLog(action="note.after_backup", entity_type="organization", entity_id=str(org_id)))
    session.commit()
    res = backup.restore(session, blob, PASS, confirm_name="내 임대사업")
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
    import uuid
    monkeypatch.setattr(backup, "settings", dataclasses.replace(settings, backup_dir=str(tmp_path / "bk")))
    org_id = uuid.UUID(rich["organization_id"])
    blob, _ = backup.export(session, org_id, PASS)
    session.add(Expense(organization_id=org_id, category="repair", amount=777, spent_on=date(2026, 11, 29)))
    session.commit()
    before = _snapshot(session, org_id)

    def boom(*a, **k):
        raise OSError("디스크 가득 참")
    monkeypatch.setattr(storage, "stage", boom)
    with pytest.raises(OSError):
        backup.restore(session, blob, PASS, confirm_name="내 임대사업")
    session.expire_all()
    assert _snapshot(session, org_id) == before  # 지운 것도 되돌아옴
    doc = backup.collect(session, org_id)["lease_documents"][0]
    assert storage.load(doc["file_path"]) == PNG


def test_different_schema_revision_refused(rich, session, monkeypatch):
    import uuid
    blob, _ = backup.export(session, uuid.UUID(rich["organization_id"]), PASS)
    monkeypatch.setattr(backup, "SCHEMA_REVISION", "9999")
    assert backup.inspect(session, blob, PASS)["compatible"] is False
    with pytest.raises(backup.BackupConflict, match="다른 버전"):
        backup.restore(session, blob, PASS, confirm_name="내 임대사업")


# ── API · CLI · 대시보드 ──

def test_api_export_inspect_restore(client, rich, monkeypatch, tmp_path):
    monkeypatch.setattr(backup, "settings", dataclasses.replace(settings, backup_dir=str(tmp_path / "bk")))
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
    assert info["exists"] is True and info["existing_name"] == "내 임대사업"
    assert client.post("/api/v1/backups/restore", files=files, data={"passphrase": PASS}).status_code == 409
    ok = client.post("/api/v1/backups/restore", files=files, data={"passphrase": PASS, "confirm_name": "내 임대사업"})
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


def test_dashboard_reminds_backup(client, rich):
    org = rich["organization_id"]
    d = client.get("/api/v1/dashboard", params=_p(org, as_of="2026-11-26")).json()
    assert "backup_none" in {a["kind"] for a in d["attention"]}
    client.post("/api/v1/backups/export", params=_p(org), json={"passphrase": PASS})
    today = date.today().isoformat()
    d = client.get("/api/v1/dashboard", params=_p(org, as_of=today)).json()
    assert not {"backup_none", "backup_old"} & {a["kind"] for a in d["attention"]}
