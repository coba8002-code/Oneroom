"""계약서 파일 저장소 — 개인정보가 담겨 있으므로 암호화해서 저장한다 (ROOMAX_FIELD_KEY).

파일 이름은 서버가 만든 무작위 이름만 쓴다 (사용자 파일명은 DB 에만, 경로 조작 불가).
운영에서 객체 스토리지로 바꿀 때는 save / load 두 함수만 바꾸면 된다.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.config import settings
from app.crypto import _fernet


def _root() -> Path:
    root = Path(settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def save(raw: bytes) -> str:
    name = f"{uuid.uuid4().hex}.bin"
    (_root() / name).write_bytes(_fernet().encrypt(raw))
    return name


def load(name: str) -> bytes:
    path = (_root() / name).resolve()
    if path.parent != _root():
        raise ValueError("잘못된 파일 경로")
    return _fernet().decrypt(path.read_bytes())
