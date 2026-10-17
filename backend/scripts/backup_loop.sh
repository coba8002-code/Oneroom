#!/bin/sh
# 매일 BACKUP_AT(한국 시각, 기본 03:10)에 모든 사업장을 /backups 로 백업한다.
# 비밀번호는 ROOMAX_BACKUP_PASSPHRASE 환경변수로만 받는다 (app/backup_cli.py).
set -eu
umask 077  # 백업 파일은 소유자만 읽기
while :; do
  secs=$(python - <<'PY'
import datetime as dt, os
from zoneinfo import ZoneInfo
h, m = map(int, os.environ.get("BACKUP_AT", "03:10").split(":"))
now = dt.datetime.now(ZoneInfo("Asia/Seoul"))
at = now.replace(hour=h, minute=m, second=0, microsecond=0)
if at <= now:
    at += dt.timedelta(days=1)
print(int((at - now).total_seconds()) + 1)
PY
)
  echo "다음 백업까지 ${secs}초"
  sleep "$secs"
  python -m app.backup_cli --out /backups --keep "${BACKUP_KEEP:-30}" --orphan-days "${BACKUP_ORPHAN_DAYS:-30}" \
    || echo "백업 실패 — 로그를 확인하세요" >&2
done
