"""메시지 발송 업체 연결 자리 (카카오 알림톡 등).

지금은 연결된 업체가 없다 → get_provider() 는 None. 이 상태에서는 승인된 메시지를 화면에서 복사해
직접 보내고 '직접 보냄'으로 표시한다. 업체를 정하면 MessageProvider 를 구현해 PROVIDERS 에 등록하고
ROOMAX_ALIMTALK_PROVIDER · ROOMAX_ALIMTALK_API_KEY · ROOMAX_ALIMTALK_SENDER_KEY 를 설정한다.
알림톡은 사전 심사된 템플릿만 보낼 수 있으므로, 연결할 때 업체에 등록한 템플릿 코드를 함께 넘긴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import settings


class SendError(Exception):
    pass


@dataclass(frozen=True)
class OutgoingMessage:
    phone: str  # 받는 사람 (복호화된 번호 — 로그에 남기지 말 것)
    body: str
    template: str  # rent_notice | overdue_notice (업체 템플릿 코드와 연결)


class MessageProvider(Protocol):
    name: str

    def send(self, message: OutgoingMessage) -> None:
        """실패하면 SendError. 성공하면 아무것도 돌려주지 않는다."""


PROVIDERS: dict[str, type] = {}  # 예: {"업체이름": 업체Provider} — 업체를 정하면 추가


def get_provider() -> MessageProvider | None:
    name = settings.alimtalk_provider
    if not name:
        return None
    if name not in PROVIDERS:
        raise RuntimeError(f"ROOMAX_ALIMTALK_PROVIDER={name} 를 지원하지 않습니다 (app/services/messaging.py)")
    return PROVIDERS[name]()
