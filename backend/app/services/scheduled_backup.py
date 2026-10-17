"""정기 백업 — 모든 사업장을 백업 파일 하나씩으로 보관소에 저장하고 오래된 것을 정리한다.

서버 1대(docker): backup_cli 가 매일 /backups 폴더(LocalStore)에.
Vercel: 매일 작업 주소(/api/v1/internal/cron/daily)가 Supabase Storage 'backups' 영역에.
- 사업장마다 최근 keep 개만 남긴다
- 해지된(없는) 사업장의 백업은 그 사업장의 가장 최근 파일이 orphan_days 일보다 오래되면 전부 지운다
  (나이는 파일 이름의 한국 시각으로 판단 — 보관소 종류와 관계없이 같게)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Organization
from app.services import backup
from app.services.backup import KST
from app.services.blobs import BlobStore

NAME_RE = re.compile(r"^roomax-([0-9a-f]{8})-(\d{8}-\d{6})\.roomaxbak$")


def run(session: Session, store: BlobStore, passphrase: str, *, keep: int = 30, orphan_days: int = 30,
        now: datetime | None = None) -> list[str]:
    if len(passphrase) < backup.MIN_PASSPHRASE:
        raise ValueError(f"ROOMAX_BACKUP_PASSPHRASE 를 {backup.MIN_PASSPHRASE}자 이상으로 설정하세요")
    report = []
    org_ids = list(session.scalars(select(Organization.id)))
    for org_id in org_ids:
        blob, manifest = backup.export(session, org_id, passphrase)
        name = backup.filename(manifest)
        store.put(name, blob)
        report.append(f"{name}  {len(blob):,} bytes")
        prefix = name.rsplit("-", 2)[0]
        old = store.list(f"{prefix}-")[:-keep] if keep > 0 else []
        store.delete(old)
    now = now or datetime.now(KST)
    report += _remove_orphans(store, {str(o)[:8] for o in org_ids}, orphan_days, now)
    report += remove_transfers(store, now)
    return report


TRANSFER_RE = re.compile(r"^(export|upload)-(\d{14})-[0-9a-f]{32}\.roomaxbak$")


def remove_transfers(store: BlobStore, now: datetime | None = None) -> list[str]:
    """내려받기·복구용으로 잠깐 둔 파일(export-/upload-)은 하루 지나면 지운다."""
    now = now or datetime.now(KST)
    old = []
    for kind in ("export-", "upload-"):
        for key in store.list(kind):
            m = TRANSFER_RE.match(key)
            if m and datetime.strptime(m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=KST) < now - timedelta(days=1):
                old.append(key)
    store.delete(old)
    return [f"임시 전송 파일 {len(old)}개 삭제"] if old else []


def _remove_orphans(store: BlobStore, live: set[str], days: int, now: datetime) -> list[str]:
    groups: dict[str, list[tuple[str, datetime]]] = {}
    for key in store.list("roomax-"):
        m = NAME_RE.match(key)
        if m and m.group(1) not in live:
            at = datetime.strptime(m.group(2), "%Y%m%d-%H%M%S").replace(tzinfo=KST)
            groups.setdefault(m.group(1), []).append((key, at))
    out = []
    for org, files in groups.items():
        if max(at for _, at in files) < now - timedelta(days=days):
            store.delete([k for k, _ in files])
            out.append(f"해지된 사업장 {org} 백업 {len(files)}개 삭제")
    return out
