"""회원가입 · 로그인 · 계정."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import auth
from app.auth import Member, current_member
from app.db import get_session
from app.models import AuditLog, Organization, User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)
    name: str = Field(min_length=1, max_length=100)
    organization_name: str = Field(min_length=1, max_length=200)  # 사업장 이름 (예: 행복빌라 임대)
    agree_terms: bool
    agree_privacy: bool
    agree_marketing: bool = False


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)
    otp: str | None = Field(default=None, max_length=10)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class CodeIn(BaseModel):
    code: str = Field(max_length=10)


class MarketingIn(BaseModel):
    agree: bool


class DisableMfaIn(BaseModel):
    password: str = Field(max_length=200)
    code: str = Field(max_length=10)


def _me(session: Session, user: User) -> dict:
    org = session.get(Organization, user.organization_id)
    return {
        "user": {"id": str(user.id), "email": user.email, "name": user.name, "role": user.role,
                 "mfa_enabled": user.mfa_enabled_at is not None,
                 "marketing_agreed": user.marketing_agreed_at is not None},
        "organization": {"id": str(org.id), "name": org.name},
    }


def _log(session: Session, user: User, action: str, detail: dict | None = None) -> None:
    # 감사 기록 — 비밀번호·토큰·이메일 등 개인정보는 남기지 않는다
    session.add(AuditLog(user_id=user.id, action=action, entity_type="user", entity_id=str(user.id), detail=detail))


@router.post("/signup", status_code=201)
def signup(body: SignupIn, request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "이메일 형식이 올바르지 않습니다")
    if not (body.agree_terms and body.agree_privacy):
        raise HTTPException(422, "이용약관과 개인정보 수집·이용에 동의해야 가입할 수 있습니다")
    if (problem := auth.password_problem(body.password, email)):
        raise HTTPException(422, problem)
    if session.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(409, "이미 가입된 이메일입니다. 로그인하세요")

    now = auth.utcnow()
    org = Organization(name=body.organization_name.strip())
    session.add(org)
    session.flush()
    user = User(organization_id=org.id, email=email, name=body.name.strip(), role="owner",
                password_hash=auth.hash_password(body.password), terms_agreed_at=now, privacy_agreed_at=now,
                marketing_agreed_at=now if body.agree_marketing else None)
    session.add(user)
    session.flush()
    _log(session, user, "auth.signup", {"marketing": body.agree_marketing})
    token, expires = auth.start_session(session, user, request.headers.get("user-agent"))
    session.commit()
    auth.set_cookie(response, token, expires)
    return _me(session, user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    key = auth.throttle_key(body.email)
    if (wait := auth.is_locked(key)):
        raise HTTPException(429, f"로그인 시도가 너무 많습니다. {wait // 60 + 1}분 뒤에 다시 시도하세요")
    user = session.scalar(select(User).where(func.lower(User.email) == key))
    ok = auth.verify_password(body.password, user.password_hash if user else auth._DUMMY_HASH)
    if not (user and ok and user.is_active):
        auth.record_fail(key)
        raise HTTPException(401, "이메일 또는 비밀번호가 맞지 않습니다")
    if user.mfa_enabled_at is not None:
        if not body.otp:
            return {"mfa_required": True}  # 비밀번호는 맞음 → 인증 코드 입력 단계
        if not auth.verify_totp(user.mfa_secret, body.otp):
            auth.record_fail(key)
            raise HTTPException(401, "인증 코드가 맞지 않습니다")
    auth.clear_fails(key)
    token, expires = auth.start_session(session, user, request.headers.get("user-agent"))
    _log(session, user, "auth.login", {"mfa": user.mfa_enabled_at is not None})
    session.commit()
    auth.set_cookie(response, token, expires)
    return _me(session, user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: Session = Depends(get_session)) -> None:
    token = request.cookies.get(auth.COOKIE)
    if token:
        row = session.scalar(select(auth.AuthSession).where(auth.AuthSession.token_hash == auth._token_hash(token)))
        if row and row.revoked_at is None:
            row.revoked_at = auth.utcnow()
            session.commit()
    auth.clear_cookie(response)


@router.get("/me")
def me(member: Member = Depends(current_member), session: Session = Depends(get_session)) -> dict:
    return _me(session, session.get(User, member.user_id))


@router.post("/password", status_code=204)
def change_password(body: PasswordIn, member: Member = Depends(current_member),
                    session: Session = Depends(get_session)) -> None:
    user = session.get(User, member.user_id)
    if not auth.verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "현재 비밀번호가 맞지 않습니다")
    if (problem := auth.password_problem(body.new_password, user.email or "")):
        raise HTTPException(422, problem)
    user.password_hash = auth.hash_password(body.new_password)
    n = auth.revoke_all(session, user.id, except_hash=member.session_hash)  # 다른 기기는 로그아웃
    _log(session, user, "auth.password_change", {"other_sessions_revoked": n})
    session.commit()


@router.post("/sessions/revoke-others")
def revoke_others(member: Member = Depends(current_member), session: Session = Depends(get_session)) -> dict:
    user = session.get(User, member.user_id)
    n = auth.revoke_all(session, user.id, except_hash=member.session_hash)
    _log(session, user, "auth.revoke_others", {"count": n})
    session.commit()
    return {"revoked": n}


@router.post("/mfa/setup")
def mfa_setup(member: Member = Depends(current_member), session: Session = Depends(get_session)) -> dict:
    """새 비밀키를 만들어 둔다 (아직 꺼진 상태). 인증 앱에 등록 후 /mfa/enable 로 켠다."""
    user = session.get(User, member.user_id)
    if user.mfa_enabled_at is not None:
        raise HTTPException(409, "이미 2단계 인증을 쓰고 있습니다")
    user.mfa_secret = auth.new_totp_secret()
    session.commit()
    return {"secret": user.mfa_secret, "otpauth_uri": auth.otpauth_uri(user.mfa_secret, user.email or "")}


@router.post("/mfa/enable", status_code=204)
def mfa_enable(body: CodeIn, member: Member = Depends(current_member), session: Session = Depends(get_session)) -> None:
    user = session.get(User, member.user_id)
    if not user.mfa_secret or user.mfa_enabled_at is not None:
        raise HTTPException(409, "먼저 2단계 인증 설정을 시작하세요")
    if not auth.verify_totp(user.mfa_secret, body.code):
        raise HTTPException(422, "인증 코드가 맞지 않습니다. 앱의 현재 6자리 코드를 넣으세요")
    user.mfa_enabled_at = auth.utcnow()
    _log(session, user, "auth.mfa_enable")
    session.commit()


@router.post("/mfa/disable", status_code=204)
def mfa_disable(body: DisableMfaIn, member: Member = Depends(current_member),
                session: Session = Depends(get_session)) -> None:
    user = session.get(User, member.user_id)
    if user.mfa_enabled_at is None:
        raise HTTPException(409, "2단계 인증을 쓰고 있지 않습니다")
    if not (auth.verify_password(body.password, user.password_hash) and auth.verify_totp(user.mfa_secret, body.code)):
        raise HTTPException(401, "비밀번호 또는 인증 코드가 맞지 않습니다")
    user.mfa_secret, user.mfa_enabled_at = None, None
    _log(session, user, "auth.mfa_disable")
    session.commit()


@router.post("/marketing")
def marketing(body: MarketingIn, member: Member = Depends(current_member), session: Session = Depends(get_session)) -> dict:
    """광고성 정보 수신 동의·철회 (정보통신망법 제50조 — 언제든 철회 가능해야 함)."""
    user = session.get(User, member.user_id)
    user.marketing_agreed_at = auth.utcnow() if body.agree else None
    _log(session, user, "auth.marketing", {"agree": body.agree})
    session.commit()
    return _me(session, user)
