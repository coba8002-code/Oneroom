"""백업 · 복구.

서버 1대: 백업 파일을 요청·응답 본문으로 바로 주고받는다.
Supabase 보관소(Vercel): 본문 한도(약 4.5MB) 때문에 브라우저가 Storage 와 직접 주고받는다 —
내려받기는 서명된 다운로드 주소, 복구는 서명된 업로드 주소로 올린 뒤 그 키(key)로 열어 보기·복구.
"""
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import Member, org_guard, require_owner
from app.db import get_session
from app.services import backup, blobs

router = APIRouter(prefix="/api/v1/backups", tags=["backups"])


class ExportIn(BaseModel):
    passphrase: str


TRANSFER_KEY = re.compile(r"^upload-\d{14}-[0-9a-f]{32}\.roomaxbak$")
TRANSFER_TTL = 600  # 서명 주소 유효 10분


def transfer_key(kind: str) -> str:
    """export-/upload- 임시 파일 이름 — 시각이 들어 있어 매일 작업이 하루 지난 것을 지운다."""
    return f"{kind}-{datetime.now(backup.KST):%Y%m%d%H%M%S}-{uuid.uuid4().hex}.roomaxbak"


async def _read(file: UploadFile | None, key: str | None) -> bytes:
    if key:
        if not (blobs.direct_transfer() and TRANSFER_KEY.match(key)):
            raise HTTPException(422, "잘못된 업로드 키")
        try:
            raw = blobs.store("backups").get(key)
        except FileNotFoundError:
            raise HTTPException(410, "올린 파일을 찾을 수 없습니다. 다시 올려 주세요")
    elif file is not None:
        raw = await file.read(backup.MAX_BACKUP_BYTES + 1)
    else:
        raise HTTPException(422, "백업 파일이 없습니다")
    if len(raw) > backup.MAX_BACKUP_BYTES:
        raise HTTPException(413, "백업 파일이 너무 큽니다")
    return raw


@router.get("/status")
def status(organization_id: uuid.UUID, member: Member = Depends(org_guard),
           session: Session = Depends(get_session)) -> dict:
    return {"last_backup_at": backup.last_backup_at(session, organization_id),
            "schema_revision": backup.SCHEMA_REVISION, "direct_transfer": blobs.direct_transfer()}


@router.post("/export")
def export(organization_id: uuid.UUID, body: ExportIn, member: Member = Depends(require_owner),
           session: Session = Depends(get_session)):
    try:
        blob, manifest = backup.export(session, organization_id, body.passphrase)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except backup.BackupError as e:
        raise HTTPException(422, str(e))
    name = backup.filename(manifest)
    if blobs.direct_transfer():
        key = transfer_key("export")
        store = blobs.store("backups")
        store.put(key, blob)
        return {"download_url": store.signed_download_url(key, TRANSFER_TTL, name), "filename": name, "size": len(blob)}
    return Response(blob, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store",
    })


@router.post("/upload-url")
def upload_url(member: Member = Depends(require_owner)) -> dict:
    """복구할 백업을 브라우저가 Storage 에 직접 올릴 주소 (Supabase 보관소일 때만)."""
    if not blobs.direct_transfer():
        raise HTTPException(404, "이 서버는 파일을 바로 받습니다")
    key = transfer_key("upload")
    return {"upload_url": blobs.store("backups").signed_upload_url(key), "key": key}


@router.post("/inspect")
async def inspect(file: UploadFile | None = File(None), key: str | None = Form(None), passphrase: str = Form(...),
                  member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    try:
        return backup.inspect(session, await _read(file, key), passphrase, member.organization_id)
    except backup.BackupError as e:
        raise HTTPException(422, str(e))


@router.post("/restore")
async def restore(file: UploadFile | None = File(None), key: str | None = Form(None), passphrase: str = Form(...),
                  confirm_name: str | None = Form(None), member: Member = Depends(require_owner),
                  session: Session = Depends(get_session)) -> dict:
    raw = await _read(file, key)
    try:
        result = backup.restore(session, raw, passphrase, member.organization_id, confirm_name)
        if key:
            blobs.store("backups").delete([key])  # 다 쓴 업로드 파일
        return result
    except backup.BackupConflict as e:
        raise HTTPException(409, str(e))
    except backup.BackupError as e:
        raise HTTPException(422, str(e))
    except IntegrityError:
        raise HTTPException(409, "이 백업의 데이터가 이 서버의 다른 사업장에 이미 있어 복구하지 못했습니다. "
                                 "아무것도 바뀌지 않았습니다")
