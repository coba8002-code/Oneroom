"""계약서 파일 저장소 — 개인정보가 담겨 있으므로 암호화해서 저장한다 (ROOMAX_FIELD_KEY).

파일 이름은 서버가 만든 무작위 이름만 쓴다 (사용자 파일명은 DB 에만, 경로 조작 불가).
운영에서 객체 스토리지로 바꿀 때는 save / load 두 함수만 바꾸면 된다.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.config import settings
from app.crypto import _fernet


def _root() -> Path:
    root = Path(settings.upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


NAME_RE = re.compile(r"^[0-9a-f]{32}\.bin$")


def save(raw: bytes) -> str:
    name = f"{uuid.uuid4().hex}.bin"
    (_root() / name).write_bytes(_fernet().encrypt(raw))
    return name


# 복구: 문서 파일을 먼저 임시 이름으로 써 두고(stage), DB 커밋이 끝난 뒤 제자리로 옮긴다(promote).
# DB 가 실패하면 임시 파일만 지운다(discard) — 기존 파일은 끝까지 건드리지 않는다.
def _staging(name: str) -> Path:
    if not NAME_RE.match(name):
        raise ValueError("잘못된 파일 이름")
    return _root() / f".{name}.restore"


def stage(name: str, raw: bytes) -> None:
    """이 서버의 키로 다시 암호화해 임시 저장."""
    _staging(name).write_bytes(_fernet().encrypt(raw))


def promote(name: str) -> None:
    _staging(name).replace(_root() / name)


def discard(name: str) -> None:
    _staging(name).unlink(missing_ok=True)


def delete(name: str) -> None:
    if NAME_RE.match(name):
        (_root() / name).unlink(missing_ok=True)


def load(name: str) -> bytes:
    path = (_root() / name).resolve()
    if path.parent != _root():
        raise ValueError("잘못된 파일 경로")
    return _fernet().decrypt(path.read_bytes())
