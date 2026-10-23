"""AI 비서 — 장부 묻고 답하기 (읽기 전용)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.routers.assets import _today
from app.services import assistant as svc

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])


class Turn(BaseModel):
    role: str
    text: str = Field(max_length=4000)


class AskIn(BaseModel):
    question: str = Field(max_length=svc.MAX_QUESTION)
    history: list[Turn] = Field(default_factory=list, max_length=20)


@router.get("/status")
def status(member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    used = svc.used_today(session, member.organization_id, _today())
    return {"configured": svc.configured(session, member.organization_id), "model": svc.MODEL, "daily_limit": svc.DAILY_LIMIT,
            "remaining_today": max(0, svc.DAILY_LIMIT - used)}


@router.post("/ask")
def ask(body: AskIn, member: Member = Depends(org_guard), session: Session = Depends(get_session)) -> dict:
    try:
        return svc.ask(session, member.organization_id, member.user_id, body.question,
                       [t.model_dump() for t in body.history], _today())
    except svc.NotConfigured as e:
        raise HTTPException(503, str(e)) from e
    except svc.AssistantError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001 — 외부 API 오류는 사용자에게 짧게 (키·원문은 숨김)
        import anthropic

        if isinstance(e, anthropic.AuthenticationError):
            raise HTTPException(502, "AI 비서 키가 맞지 않습니다. ANTHROPIC_API_KEY 를 확인하세요") from e
        if isinstance(e, anthropic.RateLimitError):
            raise HTTPException(503, "AI 서비스 사용량이 많습니다. 잠시 뒤 다시 물어봐 주세요") from e
        if isinstance(e, (anthropic.APIConnectionError, anthropic.APIStatusError)):
            raise HTTPException(502, "AI 서비스에 연결하지 못했습니다. 잠시 뒤 다시 물어봐 주세요") from e
        raise

