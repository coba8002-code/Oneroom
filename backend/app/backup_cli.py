"""서버에서 정기 백업 (cron 등).

  ROOMAX_BACKUP_PASSPHRASE='…' python -m app.backup_cli --out /backup/roomax --keep 30

- 모든 조직을 각각 백업 파일 하나로 저장하고, 조직마다 최근 --keep 개만 남긴다
- 비밀번호는 환경변수로만 받는다 (명령줄에 쓰면 프로세스 목록에 남음)
- 해지된(이제 없는) 사업장의 백업은 마지막 파일이 --orphan-days 일 지나면 지운다 (처리방침의 보관 기간)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Organization
from app.services import backup


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ROOMAX 백업")
    ap.add_argument("--out", required=True, help="백업 파일을 둘 폴더")
    ap.add_argument("--keep", type=int, default=30, help="조직마다 남길 최근 백업 수")
    ap.add_argument("--orphan-days", type=int, default=30, help="해지된 사업장의 백업을 지우기까지 둘 일수")
    args = ap.parse_args(argv)
    os.umask(0o077)  # 백업 파일은 소유자만 읽고 쓰기

    passphrase = os.environ.get("ROOMAX_BACKUP_PASSPHRASE", "")
    if len(passphrase) < backup.MIN_PASSPHRASE:
        print(f"ROOMAX_BACKUP_PASSPHRASE 를 {backup.MIN_PASSPHRASE}자 이상으로 설정하세요", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        org_ids = list(session.scalars(select(Organization.id)))
        for org_id in org_ids:
            blob, manifest = backup.export(session, org_id, passphrase)
            name = backup.filename(manifest)
            (out / name).write_bytes(blob)
            print(f"{name}  {len(blob):,} bytes")
            prefix = name.rsplit("-", 2)[0]
            old = sorted(out.glob(f"{prefix}-*.roomaxbak"))[:-args.keep] if args.keep > 0 else []
            for p in old:
                p.unlink()
    _remove_orphans(out, {str(o)[:8] for o in org_ids}, args.orphan_days)
    return 0


def _remove_orphans(out: Path, live: set[str], days: int) -> None:
    """없는 사업장의 백업: 그 사업장의 가장 최근 파일이 days 일보다 오래됐으면 전부 지운다."""
    groups: dict[str, list[Path]] = {}
    for p in out.glob("roomax-*-*.roomaxbak"):
        org = p.name.split("-")[1]
        if org not in live:
            groups.setdefault(org, []).append(p)
    cutoff = time.time() - days * 86400
    for org, files in groups.items():
        if max(f.stat().st_mtime for f in files) < cutoff:
            for f in files:
                f.unlink()
            print(f"해지된 사업장 {org} 백업 {len(files)}개 삭제")


if __name__ == "__main__":
    sys.exit(main())
