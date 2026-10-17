"""입금 알림 연결.

POST /api/v1/bank-alerts/hook/{token}  — 휴대폰 자동화 앱이 부르는 주소. 로그인 대신 계좌별 비밀 토큰.
  본문: JSON {"text": "..."} (또는 message/body/content), 폼 text=..., 그냥 글자 — 무엇이든 받는다.
  모르는 토큰은 404. 응답에 장부 내용(이름·금액)을 돌려주지 않는다.
나머지는 로그인 필요 (main.py 에서 PROTECTED 로 묶음).
"""
import json
import uuid
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import Member, org_guard
from app.db import get_session
from app.models import BankAccount
from app.services import bank_alerts as svc

public = APIRouter(prefix="/api/v1/bank-alerts/hook", tags=["bank-alerts"], include_in_schema=False)
router = APIRouter(prefix="/api/v1", tags=["bank-alerts"])

MAX_BODY = 8_000
TEXT_KEYS = ("text", "message", "body", "content", "msg", "notification")


def _text(raw: bytes, content_type: str) -> str:
    s = raw.decode("utf-8", errors="replace").strip()
    if "json" in content_type or s.startswith("{"):
        try:
            data = json.loads(s)
        except ValueError:
            return s
        if isinstance(data, dict):
            parts = [str(data[k]) for k in ("title", *TEXT_KEYS) if data.get(k)]
            return "\n".join(parts)
        return s
    if "form" in content_type:
        q = parse_qs(s)
        return "\n".join(q[k][0] for k in ("title", *TEXT_KEYS) if q.get(k))
    return s


@public.post("/{token}")
async def receive(token: str, request: Request, session: Session = Depends(get_session)) -> dict:
    account = svc.account_for_token(session, token)
    if account is None:
        raise HTTPException(404, "Not Found")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "본문이 너무 큽니다")
    try:
        alert = svc.receive(session, account, _text(raw, request.headers.get("content-type", "")))
    except svc.RateLimited as e:
        raise HTTPException(429, str(e)) from e
    except svc.AlertError as e:
        raise HTTPException(422, str(e)) from e
    return {"ok": True, "status": alert.status}


def _account(session: Session, member: Member, account_id: uuid.UUID) -> BankAccount:
    account = session.get(BankAccount, account_id)
    if account is None or account.organization_id != member.organization_id:
        raise HTTPException(404, "계좌를 찾을 수 없습니다")
    return account


@router.post("/bank-accounts/{account_id}/alert-token")
def create_token(account_id: uuid.UUID, member: Member = Depends(org_guard),
                 session: Session = Depends(get_session)) -> dict:
    """새 연결 주소용 토큰 (이전 주소는 바로 끊김). 원문은 이 응답에서 한 번만."""
    return {"token": svc.create_token(session, _account(session, member, account_id)),
            "path": "/api/v1/bank-alerts/hook/"}


@router.delete("/bank-accounts/{account_id}/alert-token", status_code=204)
def revoke_token(account_id: uuid.UUID, member: Member = Depends(org_guard),
                 session: Session = Depends(get_session)) -> None:
    svc.revoke_token(session, _account(session, member, account_id))


@router.get("/bank-alerts")
def recent(limit: int = Query(20, ge=1, le=100), member: Member = Depends(org_guard),
           session: Session = Depends(get_session)) -> list[dict]:
    return svc.recent(session, member.organization_id, limit)


class PreviewIn(BaseModel):
    text: str


@router.post("/bank-alerts/preview")
def preview(body: PreviewIn) -> dict:
    """저장하지 않고 읽어 보기만 — 폰 설정 전에 알림 문장을 붙여 넣어 시험."""
    return svc.parse(body.text[:svc.MAX_TEXT]).as_dict()
