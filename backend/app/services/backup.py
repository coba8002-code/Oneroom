"""백업 · 복구 (PRD §3-10, §8 "사용자 데이터 내보내기/백업/복구 성공").

백업 파일 = 조직 하나의 모든 데이터 + 계약서 원본을 zip 으로 묶고, 사용자가 정한
비밀번호로 암호화한 것 (scrypt → AES-256-GCM).
- 서버 키(ROOMAX_FIELD_KEY)와 무관 → 다른 서버·새 키로도 복구 가능
- 연락처·계약서는 zip 안에서는 평문이므로 반드시 파일 전체를 암호화한다
- 비밀번호를 잃으면 복구할 수 없다 (서버에 남기지 않음)

파일 구조: b"ROOMAXBK" | 버전(1B) | salt(16B) | nonce(12B) | AES-GCM 암호문(zip)
zip 안:   manifest.json · data/<테이블>.json · files/<문서 파일명>
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import Date, DateTime, Numeric, Table, Uuid, delete, func, insert, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog, Base, Organization
from app.services import storage

MAGIC = b"ROOMAXBK"
FILE_VERSION = 1
FORMAT = 1
# 백업을 만든 DB 스키마. 마이그레이션을 추가하면 같이 올린다 (test_backup 이 alembic head 와 비교)
SCHEMA_REVISION = "0007"
MIN_PASSPHRASE = 8
KST = ZoneInfo("Asia/Seoul")
MAX_BACKUP_BYTES = 300_000_000

# 조직 기준으로 테이블을 고르는 방법. 새 테이블을 만들면 반드시 여기나 EXCLUDED 에 추가 (test_backup 이 검사)
ORG_COLUMN = ("properties", "tenants", "bank_accounts", "assets", "tax_cases", "notifications",
              "payer_aliases", "expense_rules", "expenses")
CHILDREN = (  # (테이블, 외래키 열, 부모 테이블)
    ("units", "property_id", "properties"),
    ("leases", "unit_id", "units"),
    ("lease_documents", "lease_id", "leases"),
    ("deposits", "lease_id", "leases"),
    ("charges", "lease_id", "leases"),
    ("maintenance_tickets", "unit_id", "units"),
    ("transactions", "bank_account_id", "bank_accounts"),
    ("transaction_allocations", "transaction_id", "transactions"),
    ("payments", "charge_id", "charges"),
)
COVERED = {"organizations", "audit_logs", *ORG_COLUMN, *(c[0] for c in CHILDREN)}
# 계정 정보(비밀번호 해시·세션·MFA 키)는 백업에 넣지 않는다 — 데이터가 아니라 로그인 수단
EXCLUDED = {"users", "auth_sessions", "email_tokens", "invitations"}


class BackupError(ValueError):
    """잘못된 파일·비밀번호 등 (422)."""


class BackupConflict(BackupError):
    """이 서버 상태 때문에 못 하는 복구: 같은 건물 데이터 있음, 다른 스키마 버전 (409)."""


# ── 암호화 ──────────────────────────────────────────────────

def _key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())


def encrypt(plain: bytes, passphrase: str) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE:
        raise BackupError(f"백업 비밀번호는 {MIN_PASSPHRASE}자 이상이어야 합니다")
    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + bytes([FILE_VERSION]) + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, plain, MAGIC)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 1 + 16 + 12 + 16:
        raise BackupError("ROOMAX 백업 파일이 아닙니다")
    if blob[len(MAGIC)] != FILE_VERSION:
        raise BackupError("지원하지 않는 백업 파일 버전입니다")
    i = len(MAGIC) + 1
    salt, nonce, body = blob[i:i + 16], blob[i + 16:i + 28], blob[i + 28:]
    try:
        return AESGCM(_key(passphrase, salt)).decrypt(nonce, body, MAGIC)
    except InvalidTag:
        raise BackupError("비밀번호가 틀렸거나 파일이 손상되었습니다") from None


# ── 조직 데이터 모으기 ──────────────────────────────────────

def _tables() -> dict[str, Table]:
    return Base.metadata.tables  # type: ignore[return-value]


def collect(session: Session, organization_id: uuid.UUID) -> dict[str, list[dict]]:
    t = _tables()
    rows: dict[str, list[dict]] = {}

    def take(name: str, cond) -> None:
        rows[name] = [dict(r._mapping) for r in session.execute(select(t[name]).where(cond))]

    def ids(name: str) -> list:
        return [r["id"] for r in rows[name]]

    take("organizations", t["organizations"].c.id == organization_id)
    for name in ORG_COLUMN:
        take(name, t[name].c.organization_id == organization_id)
    for name, col, parent in CHILDREN:
        take(name, t[name].c[col].in_(ids(parent)))
    # 감사 기록은 조직 열이 없다 → 이 조직 데이터의 id 를 가리키는 기록만
    all_ids = {str(i) for name in rows for i in ids(name)}
    take("audit_logs", t["audit_logs"].c.entity_id.in_(all_ids))
    return rows


def _enc(v):
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def _dec(table: Table, row: dict) -> dict:
    out = {}
    for k, v in row.items():
        col = table.c[k]
        if v is not None:
            if isinstance(col.type, Uuid):
                v = uuid.UUID(v)
            elif isinstance(col.type, DateTime):
                v = datetime.fromisoformat(v)
            elif isinstance(col.type, Date):
                v = date.fromisoformat(v)
            elif isinstance(col.type, Numeric):
                v = Decimal(v)
        out[k] = v
    return out


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ── 내보내기 ────────────────────────────────────────────────

def build(session: Session, organization_id: uuid.UUID, passphrase: str) -> tuple[bytes, dict]:
    org = session.get(Organization, organization_id)
    if org is None:
        raise LookupError("조직을 찾을 수 없습니다")
    if len(passphrase) < MIN_PASSPHRASE:
        raise BackupError(f"백업 비밀번호는 {MIN_PASSPHRASE}자 이상이어야 합니다")
    rows = collect(session, organization_id)

    buf = io.BytesIO()
    checksums: dict[str, str] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in rows.items():
            raw = json.dumps([{k: _enc(v) for k, v in r.items()} for r in data], ensure_ascii=False).encode()
            z.writestr(f"data/{name}.json", raw)
            checksums[f"data/{name}.json"] = _sha(raw)
        for doc in rows["lease_documents"]:
            raw = storage.load(doc["file_path"])
            z.writestr(f"files/{doc['file_path']}", raw)
            checksums[f"files/{doc['file_path']}"] = _sha(raw)
        manifest = {
            "format": FORMAT,
            "schema_revision": SCHEMA_REVISION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "organization": {"id": str(org.id), "name": org.name},
            "counts": {name: len(data) for name, data in rows.items()},
            "files": len(rows["lease_documents"]),
            "checksums": checksums,
        }
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return encrypt(buf.getvalue(), passphrase), manifest


def export(session: Session, organization_id: uuid.UUID, passphrase: str) -> tuple[bytes, dict]:
    blob, manifest = build(session, organization_id, passphrase)
    session.add(AuditLog(action="backup.export", entity_type="organization", entity_id=str(organization_id),
                         detail={"counts": manifest["counts"], "bytes": len(blob)}))
    session.commit()
    return blob, manifest


def filename(manifest: dict, prefix: str = "roomax", full_id: bool = False) -> str:
    """full_id=True 면 사업장 id 전체 (서버에 남기는 안전 백업 — 사업장 해지 때 정확히 찾아 지우기 위해)."""
    ts = datetime.fromisoformat(manifest["created_at"]).astimezone(KST).strftime("%Y%m%d-%H%M%S")  # 파일 이름은 한국 시각
    org = manifest["organization"]["id"]
    return f"{prefix}-{org if full_id else org[:8]}-{ts}.roomaxbak"


def safety_backups(organization_id: uuid.UUID) -> list[Path]:
    """복구 직전에 서버에 만든 이 사업장의 안전 백업 파일들."""
    d = Path(settings.backup_dir)
    return sorted(d.glob(f"pre-restore-{organization_id}-*.roomaxbak")) if d.exists() else []


def last_backup_at(session: Session, organization_id: uuid.UUID) -> datetime | None:
    return session.scalar(select(func.max(AuditLog.created_at)).where(
        AuditLog.action == "backup.export", AuditLog.entity_id == str(organization_id)))


# ── 열어 보기 · 복구 ────────────────────────────────────────

def open_backup(blob: bytes, passphrase: str) -> tuple[dict, zipfile.ZipFile]:
    try:
        z = zipfile.ZipFile(io.BytesIO(decrypt(blob, passphrase)))
        manifest = json.loads(z.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise BackupError("백업 파일 내용이 올바르지 않습니다") from None
    if manifest.get("format") != FORMAT:
        raise BackupError("지원하지 않는 백업 형식입니다")
    for path, digest in manifest["checksums"].items():
        if _sha(z.read(path)) != digest:
            raise BackupError(f"백업 파일이 손상되었습니다 ({path})")
    return manifest, z


def _has_data(rows: dict[str, list[dict]]) -> bool:
    return any(rs for name, rs in rows.items() if name not in ("organizations", "audit_logs"))


def inspect(session: Session, blob: bytes, passphrase: str, target_org_id: uuid.UUID) -> dict:
    manifest, _ = open_backup(blob, passphrase)
    target = session.get(Organization, target_org_id)
    return {
        "organization": manifest["organization"],
        "created_at": manifest["created_at"],
        "schema_revision": manifest["schema_revision"],
        "compatible": manifest["schema_revision"] == SCHEMA_REVISION,
        "counts": manifest["counts"],
        "files": manifest["files"],
        "same_organization": manifest["organization"]["id"] == str(target_org_id),
        "exists": _has_data(collect(session, target_org_id)),  # 덮어쓰게 되는지
        "existing_name": target.name,
    }


def restore(session: Session, blob: bytes, passphrase: str, target_org_id: uuid.UUID,
            confirm_name: str | None = None) -> dict:
    """백업을 로그인한 사업장(target_org_id)으로 되살린다.

    - 다른 사업장(다른 서버 포함)에서 만든 백업이면 사업장 id 를 이 사업장으로 바꿔 넣는다.
    - 이 사업장에 이미 데이터가 있으면 confirm_name(사업장 이름)을 맞게 넣어야 덮어쓰고,
      직전 상태를 같은 비밀번호로 ROOMAX_BACKUP_DIR 에 자동 백업한다.
    - 업무 데이터는 백업 시점으로 돌아가지만 감사 기록은 지우지 않는다 — 이력이므로.
    - 같은 데이터가 이 서버의 다른 사업장에 이미 있으면 (id 충돌) 아무것도 바꾸지 않고 실패한다.
    - DB 는 한 트랜잭션 — 중간에 실패하면 아무것도 바뀌지 않는다.
    """
    manifest, z = open_backup(blob, passphrase)
    if manifest["schema_revision"] != SCHEMA_REVISION:
        raise BackupConflict(f"다른 버전에서 만든 백업입니다 (백업 {manifest['schema_revision']}, 이 서버 "
                             f"{SCHEMA_REVISION}). 같은 버전 서버에서 복구하세요")
    source = manifest["organization"]["id"]
    target = session.get(Organization, target_org_id)
    t = _tables()
    data: dict[str, list[dict]] = {}
    for name in manifest["counts"]:
        if name == "organizations" or name in EXCLUDED:
            continue  # 사업장 행은 가입 때 만들어진 것을 그대로 쓴다
        rows = json.loads(z.read(f"data/{name}.json"))
        for r in rows:
            if r.get("organization_id") == source:
                r["organization_id"] = str(target_org_id)
            if name == "audit_logs" and r.get("entity_id") == source:
                r["entity_id"] = str(target_org_id)
        data[name] = [_dec(t[name], r) for r in rows]

    # 사용자(계정)는 백업에 없다 → 이 사업장에 없는 사용자를 가리키면 연결만 끊는다
    users = set(session.scalars(select(t["users"].c.id).where(t["users"].c.organization_id == target_org_id)))
    for name, rows in data.items():
        for col in t[name].c:
            if any(fk.column.table.name == "users" for fk in col.foreign_keys):
                for r in rows:
                    if r.get(col.name) is not None and r[col.name] not in users:
                        r[col.name] = None

    current = collect(session, target_org_id)
    replacing = _has_data(current)
    safety = None
    old_files: set[str] = set()
    if replacing:
        if confirm_name is None or confirm_name.strip() != target.name:
            raise BackupConflict(f"이 사업장에 이미 데이터가 있습니다. 덮어쓰려면 사업장 이름 "
                                 f"'{target.name}' 을 그대로 입력하세요")
        safety_blob, safety_manifest = build(session, target_org_id, passphrase)
        backup_dir = Path(settings.backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        safety = filename(safety_manifest, "pre-restore", full_id=True)
        (backup_dir / safety).write_bytes(safety_blob)

        old_files = {d["file_path"] for d in current["lease_documents"]}
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in ("organizations", "audit_logs") or table.name in EXCLUDED:
                continue  # 감사 기록은 되감지 않는다 (아래에서 빠진 것만 보탬)
            ids = [r["id"] for r in current.get(table.name, [])]
            if ids:
                session.execute(delete(table).where(table.c.id.in_(ids)))
    # 백업 뒤에 생긴 기록도 이력이므로 그대로 두고, 백업에만 있는 기록만 더한다
    kept = {r["id"] for r in current["audit_logs"]}
    data["audit_logs"] = [r for r in data.get("audit_logs", []) if r["id"] not in kept]

    staged: list[str] = []
    try:
        for doc in data.get("lease_documents", []):
            storage.stage(doc["file_path"], z.read(f"files/{doc['file_path']}"))
            staged.append(doc["file_path"])
        for table in Base.metadata.sorted_tables:
            rows = data.get(table.name)
            if rows:
                session.execute(insert(table), rows)
        session.add(AuditLog(action="backup.restore", entity_type="organization", entity_id=str(target_org_id),
                             detail={"counts": manifest["counts"], "backup_created_at": manifest["created_at"],
                                     "replaced": replacing, "from_other_organization": source != str(target_org_id),
                                     "safety_backup": safety}))
        session.commit()
    except Exception:
        session.rollback()
        for name in staged:
            storage.discard(name)
        raise

    for name in staged:
        storage.promote(name)
    for name in old_files - set(staged):
        storage.delete(name)
    return {"organization": {"id": str(target.id), "name": target.name}, "counts": manifest["counts"],
            "replaced": replacing, "safety_backup": safety}
