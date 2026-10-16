"""백업 · 복구."""
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.services import backup

router = APIRouter(prefix="/api/v1/backups", tags=["backups"])


class ExportIn(BaseModel):
    passphrase: str


async def _read(file: UploadFile) -> bytes:
    raw = await file.read(backup.MAX_BACKUP_BYTES + 1)
    if len(raw) > backup.MAX_BACKUP_BYTES:
        raise HTTPException(413, "백업 파일이 너무 큽니다")
    return raw


@router.get("/status")
def status(organization_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    return {"last_backup_at": backup.last_backup_at(session, organization_id),
            "schema_revision": backup.SCHEMA_REVISION}


@router.post("/export")
def export(organization_id: uuid.UUID, body: ExportIn, session: Session = Depends(get_session)) -> Response:
    try:
        blob, manifest = backup.export(session, organization_id, body.passphrase)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except backup.BackupError as e:
        raise HTTPException(422, str(e))
    return Response(blob, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{backup.filename(manifest)}"',
        "Cache-Control": "no-store",
    })


@router.post("/inspect")
async def inspect(file: UploadFile = File(...), passphrase: str = Form(...),
                  session: Session = Depends(get_session)) -> dict:
    try:
        return backup.inspect(session, await _read(file), passphrase)
    except backup.BackupError as e:
        raise HTTPException(422, str(e))


@router.post("/restore")
async def restore(file: UploadFile = File(...), passphrase: str = Form(...), confirm_name: str | None = Form(None),
                  session: Session = Depends(get_session)) -> dict:
    raw = await _read(file)
    try:
        return backup.restore(session, raw, passphrase, confirm_name)
    except backup.BackupConflict as e:
        raise HTTPException(409, str(e))
    except backup.BackupError as e:
        raise HTTPException(422, str(e))
    except IntegrityError:
        raise HTTPException(409, "이 서버의 다른 데이터와 충돌해 복구하지 못했습니다. 아무것도 바뀌지 않았습니다")
