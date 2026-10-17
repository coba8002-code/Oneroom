"""서버에서 정기 백업 (cron 등).

  ROOMAX_BACKUP_PASSPHRASE='…' python -m app.backup_cli --out /backup/roomax --keep 30

- 모든 조직을 각각 백업 파일 하나로 저장하고, 조직마다 최근 --keep 개만 남긴다
- 비밀번호는 환경변수로만 받는다 (명령줄에 쓰면 프로세스 목록에 남음)
- 해지된(이제 없는) 사업장의 백업은 마지막 파일이 --orphan-days 일 지나면 지운다 (처리방침의 보관 기간)
- 실제 일은 app/services/scheduled_backup.py (Vercel 매일 작업과 같은 코드)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.db import SessionLocal
from app.services import scheduled_backup
from app.services.blobs import LocalStore


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ROOMAX 백업")
    ap.add_argument("--out", required=True, help="백업 파일을 둘 폴더")
    ap.add_argument("--keep", type=int, default=30, help="조직마다 남길 최근 백업 수")
    ap.add_argument("--orphan-days", type=int, default=30, help="해지된 사업장의 백업을 지우기까지 둘 일수")
    args = ap.parse_args(argv)
    os.umask(0o077)  # 백업 파일은 소유자만 읽고 쓰기

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        with SessionLocal() as session:
            for line in scheduled_backup.run(session, LocalStore(out), os.environ.get("ROOMAX_BACKUP_PASSPHRASE", ""),
                                             keep=args.keep, orphan_days=args.orphan_days):
                print(line)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
