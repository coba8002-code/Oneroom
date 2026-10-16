"""인증 · 권한.

- 비밀번호: scrypt 해시 (표준 라이브러리), 평문 저장·로그 금지
- 세션: 쿠키(roomax_session, HttpOnly, SameSite=Lax)에 무작위 토큰, DB 에는 SHA-256 해시만
- 권한: owner(전체) · manager(입력·수정) · viewer(조회만). 백업·복구는 owner 만
- 사업장 격리: 요청의 organization_id 가 로그인한 사용자의 사업장과 다르면 404
  (다른 사업장이 있는지조차 알 수 없게)
- MFA: TOTP (RFC 6238, 30초, 6자리) — 인증 앱(Google Authenticator 등)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import AuthSession, User

COOKIE = "roomax_session"
ROLES = ("owner", "manager", "viewer")
WRITE_ROLES = ("owner", "manager")
READ_METHODS = ("GET", "HEAD", "OPTIONS")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── 비밀번호 ────────────────────────────────────────────────

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(bytes.fromhex(dk)))
        return hmac.compare_digest(got.hex(), dk)
    except ValueError:
        return False


# 존재하지 않는 계정도 같은 시간이 걸리게 (계정 존재 여부 노출 방지)
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problem(password: str, email: str) -> str | None:
    if len(password) < 10:
        return "비밀번호는 10자 이상이어야 합니다"
    if password.isdigit() or password.isalpha():
        return "비밀번호에 문자와 숫자를 함께 쓰세요"
    local = email.split("@")[0].lower() if email else ""
    if len(local) >= 4 and local in password.lower():  # 짧은 아이디(a@…)까지 막으면 거의 모든 비밀번호가 걸림
        return "비밀번호에 이메일 아이디를 넣지 마세요"
    return None


# ── 세션 ────────────────────────────────────────────────────

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User, user_agent: str | None) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(days=settings.session_days)
    session.add(AuthSession(user_id=user.id, token_hash=_token_hash(token), expires_at=expires,
                            last_seen_at=utcnow(), user_agent=(user_agent or "")[:200]))
    user.last_login_at = utcnow()
    return token, expires


def set_cookie(response, token: str, expires: datetime) -> None:
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=int((expires - utcnow()).total_seconds()), path="/")


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE, path="/", samesite="lax", secure=settings.cookie_secure, httponly=True)


def revoke_all(session: Session, user_id: uuid.UUID, except_hash: str | None = None) -> int:
    rows = session.scalars(select(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))).all()
    n = 0
    for s in rows:
        if s.token_hash != except_hash:
            s.revoked_at = utcnow()
            n += 1
    return n


# ── 로그인 시도 제한 (프로세스 메모리 — 서버 여러 대면 Redis 등으로 옮길 것) ──

MAX_FAILS, FAIL_WINDOW = 5, 15 * 60
_fails: dict[str, deque] = defaultdict(deque)


def throttle_key(email: str) -> str:
    return email.strip().lower()


def is_locked(key: str) -> int:
    """잠겨 있으면 남은 초, 아니면 0."""
    q = _fails[key]
    now = time.monotonic()
    while q and now - q[0] > FAIL_WINDOW:
        q.popleft()
    return int(FAIL_WINDOW - (now - q[0])) + 1 if len(q) >= MAX_FAILS else 0


def record_fail(key: str) -> None:
    _fails[key].append(time.monotonic())


def clear_fails(key: str) -> None:
    _fails.pop(key, None)


# ── TOTP ────────────────────────────────────────────────────

def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _totp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_now(secret: str, at: float | None = None) -> str:
    return _totp(secret, int((at or time.time()) // 30))


def verify_totp(secret: str, code: str, at: float | None = None) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return False
    step = int((at or time.time()) // 30)
    return any(hmac.compare_digest(_totp(secret, step + d), code) for d in (-1, 0, 1))


def otpauth_uri(secret: str, email: str) -> str:
    return f"otpauth://totp/ROOMAX:{quote(email)}?secret={secret}&issuer=ROOMAX&digits=6&period=30"


# ── 요청 의존성 ─────────────────────────────────────────────

@dataclass(frozen=True)
class Member:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    email: str
    session_hash: str


def current_member(request: Request, session: Session = Depends(get_session)) -> Member:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "로그인이 필요합니다")
    th = _token_hash(token)
    row = session.execute(
        select(AuthSession, User).join(User, AuthSession.user_id == User.id).where(AuthSession.token_hash == th)
    ).first()
    if row is None:
        raise HTTPException(401, "로그인이 필요합니다")
    auth, user = row
    if auth.revoked_at is not None or _aware(auth.expires_at) <= utcnow() or not user.is_active:
        raise HTTPException(401, "로그인이 만료되었습니다. 다시 로그인하세요")
    if request.method not in READ_METHODS and user.role not in WRITE_ROLES:
        raise HTTPException(403, "조회 권한만 있는 계정입니다")
    now = utcnow()
    if auth.last_seen_at is None or now - _aware(auth.last_seen_at) > timedelta(minutes=5):
        auth.last_seen_at = now
        session.commit()
    return Member(user.id, user.organization_id, user.role, user.email or "", th)


def org_guard(organization_id: uuid.UUID | None = Query(None), member: Member = Depends(current_member)) -> Member:
    """organization_id 를 받는 모든 API 에 붙는다. 남의 사업장이면 404 (존재 여부도 숨김)."""
    if organization_id is not None and organization_id != member.organization_id:
        raise HTTPException(404, "찾을 수 없습니다")
    return member


def require_owner(member: Member = Depends(org_guard)) -> Member:
    if member.role != "owner":
        raise HTTPException(403, "사업장 대표(owner)만 할 수 있습니다")
    return member
