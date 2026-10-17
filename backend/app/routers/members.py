"""멤버 관리 — 대표(owner)만. 초대 · 권한 변경 · 내보내기."""
import uuid
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import auth
from app.auth import Member, require_owner
from app.config import settings
from app.db import get_session
from app.models import AuditLog, Invitation, Organization, User
from app.routers.auth import EMAIL_RE
from app.services import account_deletion, mailer

router = APIRouter(prefix="/api/v1/members", tags=["members"])

INVITE_TTL = timedelta(days=7)
PURGE_AFTER = timedelta(days=30)  # 만료된 초대(이메일 포함)는 만료 30일 뒤 지운다
INVITE_ROLES = ("manager", "viewer")
ROLE_LABEL = {"owner": "대표", "manager": "관리자(입력·수정)", "viewer": "조회"}
DAILY_INVITES = 20


class InviteIn(BaseModel):
    email: str = Field(max_length=320)
    role: str


class RoleIn(BaseModel):
    role: str


def _role(role: str) -> str:
    if role not in INVITE_ROLES:
        raise HTTPException(422, "권한은 관리자(manager) 또는 조회(viewer)만 줄 수 있습니다")
    return role


def _log(session: Session, member: Member, action: str, entity_id: uuid.UUID, detail: dict) -> None:
    # 이메일·이름은 남기지 않는다
    session.add(AuditLog(user_id=member.user_id, action=action, entity_type="member", entity_id=str(entity_id),
                         detail=detail))


def _purge_expired(session: Session, org_id: uuid.UUID) -> None:
    session.execute(delete(Invitation).where(Invitation.organization_id == org_id,
                                             Invitation.expires_at < auth.utcnow() - PURGE_AFTER))


def _invitation_out(inv: Invitation) -> dict:
    return {"id": str(inv.id), "email": inv.email, "role": inv.role, "created_at": inv.created_at.isoformat(),
            "expires_at": inv.expires_at.isoformat(), "expired": auth._aware(inv.expires_at) <= auth.utcnow()}


def _member_in_org(session: Session, member: Member, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None or user.organization_id != member.organization_id:
        raise HTTPException(404, "찾을 수 없습니다")
    if user.role == "owner":
        raise HTTPException(409, "대표 계정은 바꾸거나 내보낼 수 없습니다")
    return user


@router.get("")
def list_members(member: Member = Depends(require_owner), session: Session = Depends(get_session)) -> dict:
    _purge_expired(session, member.organization_id)
    session.commit()
    users = session.scalars(select(User).where(User.organization_id == member.organization_id)
                            .order_by(User.created_at)).all()
    pending = session.scalars(select(Invitation).where(
        Invitation.organization_id == member.organization_id,
        Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None)).order_by(Invitation.created_at)).all()
    return {
        "members": [{"id": str(u.id), "name": u.name, "email": u.email, "role": u.role, "me": u.id == member.user_id,
                     "mfa_enabled": u.mfa_enabled_at is not None, "last_login_at": u.last_login_at and u.last_login_at.isoformat(),
                     "created_at": u.created_at.isoformat()} for u in users],
        "invitations": [_invitation_out(i) for i in pending],
    }


@router.post("/invitations", status_code=201)
def invite(body: InviteIn, background: BackgroundTasks, member: Member = Depends(require_owner),
           session: Session = Depends(get_session)) -> dict:
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "이메일 형식이 올바르지 않습니다")
    role = _role(body.role)
    # 이 사업장 안에서만 확인한다 (다른 사업장 가입 여부는 알려주지 않음 — 수락할 때 안내)
    if session.scalar(select(User.id).where(User.organization_id == member.organization_id,
                                            func.lower(User.email) == email)):
        raise HTTPException(409, "이미 이 사업장의 멤버입니다")
    if not auth.allow_send(f"invite:{member.organization_id}", DAILY_INVITES, 86400):
        raise HTTPException(429, f"초대는 하루 {DAILY_INVITES}통까지 보낼 수 있습니다. 내일 다시 시도하세요")

    now = auth.utcnow()
    # 같은 주소로 다시 초대하면 이전 링크는 무효
    for old in session.scalars(select(Invitation).where(
            Invitation.organization_id == member.organization_id, Invitation.email == email,
            Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))):
        old.revoked_at, old.email = now, None
    token = auth.secrets.token_urlsafe(32)
    inv = Invitation(organization_id=member.organization_id, email=email, role=role,
                     token_hash=auth._token_hash(token), invited_by=member.user_id, expires_at=now + INVITE_TTL)
    session.add(inv)
    session.flush()
    _log(session, member, "member.invited", inv.id, {"role": role})
    org = session.get(Organization, member.organization_id)
    inviter = session.get(User, member.user_id)
    session.commit()
    link = f"{settings.app_url}/invite?token={token}"
    mailer.send_after_response(background, mailer.invite_mail(email, org.name, inviter.name, ROLE_LABEL[role], link))
    return _invitation_out(inv)


@router.post("/invitations/{invitation_id}/revoke")
def revoke(invitation_id: uuid.UUID, member: Member = Depends(require_owner),
           session: Session = Depends(get_session)) -> dict:
    inv = session.get(Invitation, invitation_id)
    if inv is None or inv.organization_id != member.organization_id:
        raise HTTPException(404, "찾을 수 없습니다")
    if inv.accepted_at is not None:
        raise HTTPException(409, "이미 수락된 초대입니다")
    if inv.revoked_at is None:
        inv.revoked_at, inv.email = auth.utcnow(), None
        _log(session, member, "member.invite_revoked", inv.id, {"role": inv.role})
        session.commit()
    return {"revoked": True}


@router.patch("/{user_id}")
def change_role(user_id: uuid.UUID, body: RoleIn, member: Member = Depends(require_owner),
                session: Session = Depends(get_session)) -> dict:
    user = _member_in_org(session, member, user_id)
    role = _role(body.role)
    if user.role != role:
        _log(session, member, "member.role_changed", user.id, {"from": user.role, "to": role})
        user.role = role  # 다음 요청부터 바로 적용 (권한은 요청마다 DB 에서 읽음)
        session.commit()
    return {"id": str(user.id), "role": user.role}


@router.delete("/{user_id}")
def remove(user_id: uuid.UUID, member: Member = Depends(require_owner),
           session: Session = Depends(get_session)) -> dict:
    """내보내기 = 그 계정 삭제 (본인 탈퇴와 같은 처리). 사업장 기록은 남고 작성자 연결만 끊긴다."""
    user = _member_in_org(session, member, user_id)
    _log(session, member, "member.removed", user.id, {"role": user.role})
    account_deletion.delete_member(session, user)
    return {"removed": True}
