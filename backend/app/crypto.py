"""개인정보 필드 암호화 (임차인 연락처 등)."""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.config import settings


@lru_cache
def _fernet() -> Fernet:
    if not settings.field_key:
        raise RuntimeError("ROOMAX_FIELD_KEY 가 설정되지 않았습니다 (.env.example 참고)")
    return Fernet(settings.field_key.encode())


class EncryptedString(TypeDecorator):
    """저장 시 Fernet 암호화, 조회 시 복호화. None 은 그대로 None."""

    impl = String(500)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return _fernet().decrypt(value.encode()).decode()
