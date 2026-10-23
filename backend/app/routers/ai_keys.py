"""설정 → AI 연결: Claude API 키 넣기·지우기 (대표만). 키 전체는 돌려주지 않는다."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard, require_owner
from app.db import get_session
from app.services import ai_keys as svc

router = APIRouter(prefix="/api/v1/settings/ai-key", tags=["settings"])


class KeyIn(BaseModel):
    key: str = Field(max_length=400)


@router.get("")
def status(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    return svc.status(session, member.organization_id)


@router.put("")
def save(body: KeyIn, member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    try:
        return svc.save(session, member.organization_id, member.user_id, body.key)
    except svc.AiKeyError as e:
        raise HTTPException(422, str(e)) from e


@router.delete("")
def delete(member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    return svc.delete(session, member.organization_id, member.user_id)
