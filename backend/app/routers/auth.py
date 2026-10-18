"""회원가입 · 로그인 · 계정."""
import re

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import auth
from app.auth import Member, current_member
from app.config import settings
from app.db import get_session
from app.models import (
    AuditLog,
    BankAccount,
    EmailToken,
    Invitation,
    Lease,
    LeaseDocument,
    Organization,
    Property,
    Transaction,
    Unit,
    User,
)
from app.services import account_deletion, mailer

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


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class ResetRequestIn(BaseModel):
    email: str = Field(max_length=320)


class ResetConfirmIn(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=200)
    otp: str | None = Field(default=None, max_length=10)
    confirm_name: str | None = Field(default=None, max_length=200)  # 대표 탈퇴(사업장 해지) 때 사업장 이름


class InviteAcceptIn(BaseModel):
    token: str = Field(max_length=200)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(max_length=200)
    agree_terms: bool
    agree_privacy: bool
    agree_marketing: bool = False


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
                 "email_verified": user.email_verified_at is not None,
                 "marketing_agreed": user.marketing_agreed_at is not None},
        "organization": {"id": str(org.id), "name": org.name},
        # 화면 로고 옆에 보이는 건물 이름 (등록 순)
        "buildings": list(session.scalars(select(Property.name).where(Property.organization_id == org.id)
                                          .order_by(Property.created_at))),
        # 운영 서버인데 메일이 file 모드(개인 사용)면 확인 메일이 실제로 가지 않는다 → 화면은 확인 안내를 띄우지 않음
        "mail_enabled": not (settings.env == "production" and settings.mail_mode == "file"),
    }


VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)
BAD_LINK = "링크가 만료됐거나 이미 사용됐습니다. 새 메일을 요청하세요"
RESET_ACCEPTED = "가입된 주소라면 비밀번호 재설정 메일을 보냈습니다. 메일함(스팸함 포함)을 확인하세요"


def _issue(session: Session, user: User, purpose: str, ttl: timedelta) -> str:
    """새 토큰을 만들고, 같은 용도의 쓰지 않은 이전 토큰은 무효로 한다."""
    for old in session.scalars(select(EmailToken).where(
            EmailToken.user_id == user.id, EmailToken.purpose == purpose, EmailToken.used_at.is_(None))):
        old.used_at = auth.utcnow()
    token = auth.secrets.token_urlsafe(32)
    session.add(EmailToken(user_id=user.id, purpose=purpose, token_hash=auth._token_hash(token),
                           expires_at=auth.utcnow() + ttl))
    return token


def _consume(session: Session, token: str, purpose: str) -> EmailToken | None:
    row = session.scalar(select(EmailToken).where(
        EmailToken.token_hash == auth._token_hash(token), EmailToken.purpose == purpose))
    if row is None or row.used_at is not None or auth._aware(row.expires_at) <= auth.utcnow():
        return None
    row.used_at = auth.utcnow()
    return row


def _send_verify(session: Session, user: User, background: BackgroundTasks) -> None:
    token = _issue(session, user, "verify_email", VERIFY_TTL)
    link = f"{settings.app_url}/verify-email?token={token}"
    mailer.send_after_response(background, mailer.verify_mail(user.email, user.name, link))


def _log(session: Session, user: User, action: str, detail: dict | None = None) -> None:
    # 감사 기록 — 비밀번호·토큰·이메일 등 개인정보는 남기지 않는다
    session.add(AuditLog(user_id=user.id, action=action, entity_type="user", entity_id=str(user.id), detail=detail))


def signup_open(session: Session) -> bool:
    """개인 사용 모드(first_only)는 아직 아무 계정도 없을 때만 가입을 받는다."""
    return settings.signup_mode != "first_only" or session.scalar(select(User.id).limit(1)) is None


@router.get("/signup-status")
def signup_status(session: Session = Depends(get_session)) -> dict:
    return {"open": signup_open(session), "mode": settings.signup_mode}


@router.post("/signup", status_code=201)
def signup(body: SignupIn, request: Request, response: Response, background: BackgroundTasks,
           session: Session = Depends(get_session)) -> dict:
    if not signup_open(session):
        raise HTTPException(403, "이 서버는 개인 사용 모드라 새 가입을 받지 않습니다. 사업장 대표에게 초대를 요청하세요")
    email = body.email.strip().lower()
    if settings.signup_mode == "first_only" and settings.owner_email and email != settings.owner_email:
        raise HTTPException(403, "이 서버는 정해진 대표 이메일로만 처음 가입할 수 있습니다")
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
    _send_verify(session, user, background)  # 가입 직후 확인 메일 (안 해도 쓸 수 있음)
    token, expires = auth.start_session(session, user, request.headers.get("user-agent"))
    session.commit()
    auth.set_cookie(response, token, expires)
    return _me(session, user)


BAD_INVITE = "초대 링크가 만료됐거나 취소됐습니다. 사업장 대표에게 다시 초대를 요청하세요"


def _open_invitation(session: Session, token: str) -> Invitation:
    inv = session.scalar(select(Invitation).where(Invitation.token_hash == auth._token_hash(token)))
    if (inv is None or inv.accepted_at is not None or inv.revoked_at is not None
            or auth._aware(inv.expires_at) <= auth.utcnow()):
        raise HTTPException(410, BAD_INVITE)
    return inv


@router.post("/invitation/preview")
def invitation_preview(body: TokenIn, session: Session = Depends(get_session)) -> dict:
    """초대 링크를 연 사람에게 어느 사업장·어떤 권한인지 보여준다 (로그인 없이)."""
    inv = _open_invitation(session, body.token)
    org = session.get(Organization, inv.organization_id)
    return {"organization_name": org.name, "email": inv.email, "role": inv.role,
            "expires_at": inv.expires_at.isoformat()}


@router.post("/invitation/accept", status_code=201)
def invitation_accept(body: InviteAcceptIn, request: Request, response: Response,
                      session: Session = Depends(get_session)) -> dict:
    """초대 수락 = 그 사업장의 계정 만들기 + 로그인. 메일 링크로 왔으므로 이메일은 확인된 것으로 본다."""
    inv = _open_invitation(session, body.token)
    if not (body.agree_terms and body.agree_privacy):
        raise HTTPException(422, "이용약관과 개인정보 수집·이용에 동의해야 참여할 수 있습니다")
    if (problem := auth.password_problem(body.password, inv.email)):
        raise HTTPException(422, problem)
    if session.scalar(select(User.id).where(func.lower(User.email) == inv.email)):
        raise HTTPException(409, "이 이메일로 이미 ROOMAX 계정이 있습니다. 한 계정은 한 사업장에만 속할 수 있어, "
                                 "대표에게 다른 이메일로 초대를 요청하세요")
    now = auth.utcnow()
    user = User(organization_id=inv.organization_id, email=inv.email, name=body.name.strip(), role=inv.role,
                password_hash=auth.hash_password(body.password), terms_agreed_at=now, privacy_agreed_at=now,
                marketing_agreed_at=now if body.agree_marketing else None, email_verified_at=now)
    session.add(user)
    session.flush()
    inv.accepted_at, inv.email = now, None
    _log(session, user, "auth.invitation_accepted", {"role": inv.role, "marketing": body.agree_marketing})
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


# ── 이메일 확인 ─────────────────────────────────────────────

@router.post("/verify-email/send", status_code=202)
def verify_send(background: BackgroundTasks, member: Member = Depends(current_member),
                session: Session = Depends(get_session)) -> dict:
    user = session.get(User, member.user_id)
    if user.email_verified_at is not None:
        raise HTTPException(409, "이미 확인된 이메일입니다")
    if not (auth.allow_send(f"verify-min:{user.id}", 1, 60) and auth.allow_send(f"verify-day:{user.id}", 5, 86400)):
        raise HTTPException(429, "확인 메일을 너무 자주 요청했습니다. 잠시 뒤에 다시 시도하세요")
    _send_verify(session, user, background)
    _log(session, user, "auth.verify_email_send")
    session.commit()
    return {"sent": True}


@router.post("/verify-email")
def verify_email(body: TokenIn, session: Session = Depends(get_session)) -> dict:
    """메일 링크로 들어온 확인. 로그인하지 않아도 된다 (다른 기기에서 메일을 열 수 있으므로)."""
    row = _consume(session, body.token, "verify_email")
    if row is None:
        raise HTTPException(400, BAD_LINK)
    user = session.get(User, row.user_id)
    user.email_verified_at = user.email_verified_at or auth.utcnow()
    _log(session, user, "auth.verify_email")
    session.commit()
    return {"verified": True}


# ── 비밀번호 재설정 ─────────────────────────────────────────

@router.post("/password-reset/request", status_code=202)
def reset_request(body: ResetRequestIn, background: BackgroundTasks, session: Session = Depends(get_session)) -> dict:
    """가입 여부와 관계없이 같은 응답 (가입된 주소인지 알아낼 수 없게)."""
    email = body.email.strip().lower()
    user = session.scalar(select(User).where(func.lower(User.email) == email))
    if user and user.is_active and auth.allow_send(f"reset:{email}", 3, 3600):
        token = _issue(session, user, "reset_password", RESET_TTL)
        mailer.send_after_response(background, mailer.reset_mail(user.email, user.name,
                                                              f"{settings.app_url}/reset-password?token={token}"))
        _log(session, user, "auth.password_reset_request")
        session.commit()
    return {"message": RESET_ACCEPTED}


@router.post("/password-reset/confirm")
def reset_confirm(body: ResetConfirmIn, session: Session = Depends(get_session)) -> dict:
    row = session.scalar(select(EmailToken).where(
        EmailToken.token_hash == auth._token_hash(body.token), EmailToken.purpose == "reset_password"))
    if row is None or row.used_at is not None or auth._aware(row.expires_at) <= auth.utcnow():
        raise HTTPException(400, BAD_LINK)
    user = session.get(User, row.user_id)
    if not user.is_active:
        raise HTTPException(400, BAD_LINK)
    if (problem := auth.password_problem(body.new_password, user.email or "")):
        raise HTTPException(422, problem)  # 토큰은 아직 쓰지 않음 → 다시 입력 가능
    row.used_at = auth.utcnow()
    user.password_hash = auth.hash_password(body.new_password)
    user.email_verified_at = user.email_verified_at or auth.utcnow()  # 메일을 받았으니 주소 확인도 된 셈
    n = auth.revoke_all(session, user.id)  # 모든 기기 로그아웃 (2단계 인증은 그대로)
    auth.clear_fails(auth.throttle_key(user.email or ""))
    _log(session, user, "auth.password_reset", {"sessions_revoked": n})
    session.commit()
    return {"reset": True}


# ── 탈퇴 · 사업장 해지 ──────────────────────────────────────

@router.get("/account/deletion-preview")
def deletion_preview(member: Member = Depends(current_member), session: Session = Depends(get_session)) -> dict:
    """탈퇴하면 무엇이 지워지는지 미리 보여준다."""
    user = session.get(User, member.user_id)
    org = session.get(Organization, user.organization_id)
    if user.role != "owner":
        return {"scope": "member", "organization_name": org.name}
    props = select(Property.id).where(Property.organization_id == org.id)
    units = select(Unit.id).where(Unit.property_id.in_(props))
    count = lambda q: session.scalar(select(func.count()).select_from(q.subquery()))  # noqa: E731
    return {
        "scope": "organization",
        "organization_name": org.name,
        "other_accounts": count(select(User.id).where(User.organization_id == org.id, User.id != user.id)),
        "counts": {
            "units": count(units),
            "leases": count(select(Lease.id).where(Lease.unit_id.in_(units))),
            "transactions": count(select(Transaction.id).join(BankAccount).where(BankAccount.organization_id == org.id)),
            "documents": count(select(LeaseDocument.id).join(Lease).where(Lease.unit_id.in_(units))),
        },
    }


@router.post("/account/delete")
def delete_account(body: DeleteAccountIn, response: Response, member: Member = Depends(current_member),
                   session: Session = Depends(get_session)) -> dict:
    """영구 삭제. 비밀번호(+2단계 코드)를 다시 확인하고, 대표는 사업장 이름까지 입력해야 한다."""
    user = session.get(User, member.user_id)
    if not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "비밀번호가 맞지 않습니다")
    if user.mfa_enabled_at is not None and not auth.verify_totp(user.mfa_secret, body.otp or ""):
        raise HTTPException(401, "2단계 인증 코드가 맞지 않습니다")
    if user.role == "owner":
        org = session.get(Organization, user.organization_id)
        if (body.confirm_name or "").strip() != org.name:
            raise HTTPException(422, f"사업장을 해지하려면 사업장 이름 '{org.name}' 을 그대로 입력하세요")
        result = account_deletion.delete_organization(session, org.id)
        scope = "organization"
    else:
        account_deletion.delete_member(session, user)
        result, scope = {}, "member"
    auth.clear_cookie(response)
    return {"deleted": True, "scope": scope, **result}
