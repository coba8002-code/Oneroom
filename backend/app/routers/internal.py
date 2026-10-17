"""매일 작업 — 서버리스(Vercel Cron)용. 서버 1대(docker)는 backup 컨테이너가 같은 일을 한다.

GET /api/v1/internal/cron/daily  (Authorization: Bearer <ROOMAX_CRON_SECRET 또는 CRON_SECRET>)
- DB 를 한 번 조회해 무료 DB 의 비활성 정지를 막는다
- ROOMAX_BACKUP_PASSPHRASE 가 있으면 모든 사업장을 정기 백업(보관소 'backups')하고 오래된 것을 정리
- 내려받기·복구용 임시 파일은 비밀번호가 없어도 하루 뒤 정리
비밀값이 설정되지 않았으면 이 주소는 없는 것처럼(404) 동작한다.
"""
import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.services import blobs, scheduled_backup

router = APIRouter(prefix="/api/v1/internal", tags=["internal"], include_in_schema=False)


@router.get("/cron/daily")
def daily(authorization: str | None = Header(default=None), session: Session = Depends(get_session)) -> dict:
    expected = settings.cron_secret
    if not expected:
        raise HTTPException(404, "Not Found")
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {expected}".encode()):
        raise HTTPException(401, "인증 실패")
    session.execute(text("SELECT 1"))
    passphrase = os.environ.get("ROOMAX_BACKUP_PASSPHRASE", "")
    if not passphrase:
        cleaned = scheduled_backup.remove_transfers(blobs.store("backups"))
        return {"db": "ok", "backup": ["건너뜀 (ROOMAX_BACKUP_PASSPHRASE 없음)", *cleaned]}
    report = scheduled_backup.run(session, blobs.store("backups"), passphrase,
                                  keep=int(os.environ.get("BACKUP_KEEP", "30")),
                                  orphan_days=int(os.environ.get("BACKUP_ORPHAN_DAYS", "30")))
    return {"db": "ok", "backup": report}
