"""서버에서 정기 백업 (cron 등).

  ROOMAX_BACKUP_PASSPHRASE='…' python -m app.backup_cli --out /backup/roomax --keep 30

- 모든 조직을 각각 백업 파일 하나로 저장하고, 조직마다 최근 --keep 개만 남긴다
- 비밀번호는 환경변수로만 받는다 (명령줄에 쓰면 프로세스 목록에 남음)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Organization
from app.services import backup


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ROOMAX 백업")
    ap.add_argument("--out", required=True, help="백업 파일을 둘 폴더")
    ap.add_argument("--keep", type=int, default=30, help="조직마다 남길 최근 백업 수")
    args = ap.parse_args(argv)

    passphrase = os.environ.get("ROOMAX_BACKUP_PASSPHRASE", "")
    if len(passphrase) < backup.MIN_PASSPHRASE:
        print(f"ROOMAX_BACKUP_PASSPHRASE 를 {backup.MIN_PASSPHRASE}자 이상으로 설정하세요", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as session:
        for org_id in session.scalars(select(Organization.id)):
            blob, manifest = backup.export(session, org_id, passphrase)
            name = backup.filename(manifest)
            (out / name).write_bytes(blob)
            print(f"{name}  {len(blob):,} bytes")
            prefix = name.rsplit("-", 2)[0]
            old = sorted(out.glob(f"{prefix}-*.roomaxbak"))[:-args.keep] if args.keep > 0 else []
            for p in old:
                p.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
