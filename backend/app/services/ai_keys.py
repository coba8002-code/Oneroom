"""사업장이 설정 화면에서 넣는 Claude(Anthropic) API 키.

- 대표(owner)만 넣고 지운다. 저장은 암호화(ROOMAX_FIELD_KEY), 화면·응답에는 끝 4자리만 — 키 전체는 다시 보여 주지 않는다.
- 넣을 때 Anthropic 에 모델 목록을 한 번 물어 키가 맞는지 확인한다 (요금 없음).
- 서버 환경변수 ANTHROPIC_API_KEY 가 있으면 그쪽이 우선이다 (assistant.api_key).
- 비밀값이라 백업에 넣지 않고(backup.EXCLUDED), 감사 기록에도 키를 남기지 않는다.
"""
from __future__ import annotations

import os
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, OrgApiKey
from app.services import assistant

PROVIDER = "anthropic"
KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,300}$")


class AiKeyError(Exception):
    pass


def _row(session: Session, org: uuid.UUID) -> OrgApiKey | None:
    return session.scalar(select(OrgApiKey).where(OrgApiKey.organization_id == org, OrgApiKey.provider == PROVIDER))


def status(session: Session, org: uuid.UUID) -> dict:
    row = _row(session, org)
    source = "server" if os.getenv("ANTHROPIC_API_KEY") else ("organization" if row else None)
    return {"configured": source is not None, "source": source,
            "last4": row.last4 if row else None, "set_at": row.created_at if row else None}


def verify(key: str) -> None:
    """키가 맞는지 Anthropic 에 확인 (모델 목록 1건 — 요금 없음)."""
    import anthropic

    try:
        assistant._client(key).models.list(limit=1)
    except anthropic.AuthenticationError as e:
        raise AiKeyError("Anthropic 이 이 키를 받아들이지 않습니다. 콘솔에서 복사한 키 전체를 다시 붙여 넣어 주세요") from e
    except anthropic.PermissionDeniedError as e:
        raise AiKeyError("이 키로는 API 를 쓸 수 없습니다. 콘솔의 결제(Billing)·권한을 확인해 주세요") from e
    except anthropic.APIError as e:
        raise AiKeyError("지금 Anthropic 에 연결해 확인하지 못했습니다. 잠시 뒤 다시 시도해 주세요") from e


def save(session: Session, org: uuid.UUID, user_id, key: str) -> dict:
    key = (key or "").strip()
    if not KEY_RE.match(key):
        raise AiKeyError("Claude API 키는 'sk-ant-' 로 시작합니다. 콘솔에서 복사한 키 전체를 붙여 넣어 주세요")
    verify(key)
    row = _row(session, org) or OrgApiKey(organization_id=org, provider=PROVIDER)
    row.key, row.last4, row.created_by = key, key[-4:], user_id
    session.add(row)
    session.add(AuditLog(user_id=user_id, action="ai_key.set", entity_type="organization", entity_id=str(org),
                         detail={"provider": PROVIDER}))  # 키는 남기지 않음
    session.commit()
    return status(session, org)


def delete(session: Session, org: uuid.UUID, user_id) -> dict:
    if row := _row(session, org):
        session.delete(row)
        session.add(AuditLog(user_id=user_id, action="ai_key.delete", entity_type="organization", entity_id=str(org),
                             detail={"provider": PROVIDER}))
        session.commit()
    return status(session, org)
