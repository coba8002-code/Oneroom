"""계약서 파일 저장소 — 개인정보가 담겨 있으므로 암호화해서 저장한다 (ROOMAX_FIELD_KEY).

파일 이름은 서버가 만든 무작위 이름만 쓴다 (사용자 파일명은 DB 에만, 경로 조작 불가).
실제 보관 위치(디스크 또는 Supabase Storage)는 app/services/blobs.py 가 정한다.
"""
from __future__ import annotations

import re
import uuid

from app.crypto import _fernet
from app.services import blobs

NAME_RE = re.compile(r"^[0-9a-f]{32}\.bin$")


def _store():
    return blobs.store("uploads")


def _name(name: str) -> str:
    if not NAME_RE.match(name):
        raise ValueError("잘못된 파일 이름")
    return name


def save(raw: bytes) -> str:
    name = f"{uuid.uuid4().hex}.bin"
    _store().put(name, _fernet().encrypt(raw))
    return name


# 복구: 문서 파일을 먼저 임시 이름으로 써 두고(stage), DB 커밋이 끝난 뒤 제자리로 옮긴다(promote).
# DB 가 실패하면 임시 파일만 지운다(discard) — 기존 파일은 끝까지 건드리지 않는다.
def _staging(name: str) -> str:
    return f"restore-{_name(name)}"


def stage(name: str, raw: bytes) -> None:
    """이 서버의 키로 다시 암호화해 임시 저장."""
    _store().put(_staging(name), _fernet().encrypt(raw))


def promote(name: str) -> None:
    _store().move(_staging(name), name)


def discard(name: str) -> None:
    _store().delete([_staging(name)])


def delete(name: str) -> None:
    if NAME_RE.match(name):
        _store().delete([name])


def load(name: str) -> bytes:
    return _fernet().decrypt(_store().get(_name(name)))
