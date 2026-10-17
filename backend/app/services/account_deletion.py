"""회원 탈퇴 · 사업장 해지 · 데이터 파기.

- 대표(owner) 탈퇴 = 사업장 해지: 그 사업장의 업무 데이터 전부 + 계약서 파일 + 서버 안전 백업 +
  그 사업장의 모든 계정(세션·메일 토큰 포함)을 지운다. 다른 사업장은 건드리지 않는다.
- 관리자·조회 계정 탈퇴: 그 계정만 지운다. 사업장 데이터와 변경 기록은 남기되, 기록에서 그 사람과의
  연결(user_id)만 끊는다.
- 남기는 것: 개인정보 없는 '파기 기록' 한 줄 (언제·무엇을 몇 건 지웠는지) — 파기 사실의 증빙.
- DB 는 한 트랜잭션. 파일은 커밋이 끝난 뒤에 지운다 (DB 가 실패하면 파일은 그대로).
- 서버 정기 백업(backup_cli)에 들어 있던 사본은 보관 개수(--keep)에 따라 순환 삭제된다.
"""
from __future__ import annotations

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import AuditLog, AuthSession, Base, EmailToken, Invitation, LeaseDocument, Organization, User
from app.services import backup, blobs, storage


def _detach_user(session: Session, user_ids: list[uuid.UUID]) -> None:
    """계정 자체의 기록(가입·로그인 등)은 지우고, 사업장 기록에서는 그 계정과의 연결만 끊는다."""
    session.execute(delete(AuditLog).where(AuditLog.entity_type == "user",
                                           AuditLog.entity_id.in_([str(u) for u in user_ids])))
    session.execute(update(AuditLog).where(AuditLog.user_id.in_(user_ids)).values(user_id=None))
    session.execute(update(LeaseDocument).where(LeaseDocument.verified_by.in_(user_ids)).values(verified_by=None))
    session.execute(update(Invitation).where(Invitation.invited_by.in_(user_ids)).values(invited_by=None))
    session.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
    session.execute(delete(EmailToken).where(EmailToken.user_id.in_(user_ids)))


def delete_member(session: Session, user: User) -> None:
    """대표가 아닌 계정 하나만 지운다."""
    org_id = user.organization_id
    _detach_user(session, [user.id])
    session.delete(user)
    session.add(AuditLog(action="account.deleted", entity_type="organization", entity_id=str(org_id),
                         detail={"scope": "member"}))
    session.commit()


def delete_organization(session: Session, organization_id: uuid.UUID) -> dict:
    """사업장 해지: 업무 데이터·계정·파일을 모두 지운다. 지운 건수를 돌려준다."""
    rows = backup.collect(session, organization_id)
    files = [d["file_path"] for d in rows["lease_documents"]]
    user_ids = list(session.scalars(select(User.id).where(User.organization_id == organization_id)))

    counts: dict[str, int] = {}
    _detach_user(session, user_ids)
    # 외래키 역순으로: 자식 → 부모. 사업장 행과 계정은 맨 마지막
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in ("organizations", "users") or table.name in backup.EXCLUDED:
            continue
        ids = [r["id"] for r in rows.get(table.name, [])]
        if ids:
            session.execute(delete(table).where(table.c.id.in_(ids)))
            counts[table.name] = len(ids)
    session.execute(delete(User).where(User.id.in_(user_ids)))
    counts["users"] = len(user_ids)
    session.execute(delete(Invitation).where(Invitation.organization_id == organization_id))
    session.execute(delete(Organization).where(Organization.id == organization_id))

    # 파기 기록 — 개인정보 없이 건수만 (사업장 id 는 무작위 값이라 이제 아무것도 가리키지 않음)
    session.add(AuditLog(action="organization.deleted", entity_type="organization",
                         entity_id=str(organization_id), detail={"deleted": counts, "files": len(files)}))
    session.commit()

    # 커밋 뒤 파일 정리: 계약서 원본, 복구 직전 안전 백업
    for name in files:
        storage.delete(name)
    safety = backup.safety_backups(organization_id)
    blobs.store("backups").delete(safety)
    removed_safety = len(safety)
    return {"deleted": counts, "files": len(files), "safety_backups": removed_safety}
