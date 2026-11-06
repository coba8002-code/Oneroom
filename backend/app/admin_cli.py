"""서버 관리 명령 — 서버에 접속할 수 있는 운영자만 실행.

  python -m app.admin_cli reset-link <이메일>
  python -m app.admin_cli comp <이메일> [--off]   — 그 사람이 대표인 사업장을 무상 제공(요금 한도 없음)으로

메일 업체 없이 혼자 쓰는 서버에서 비밀번호를 잊었을 때: 재설정 링크(1시간, 한 번만)를 화면에 출력한다.
링크를 브라우저에 붙여 넣어 새 비밀번호를 정하면 된다. 링크 자체가 비밀번호와 같으니 남에게 보이지 말 것.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import AuditLog, User
from app.routers.auth import RESET_TTL, _issue
from app.services import billing


def reset_link(email: str) -> int:
    with SessionLocal() as session:
        user = session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
        if user is None:
            print("그 이메일의 계정이 없습니다", file=sys.stderr)
            return 1
        token = _issue(session, user, "reset_password", RESET_TTL)
        session.add(AuditLog(user_id=user.id, action="auth.reset_link_cli", entity_type="user", entity_id=str(user.id)))
        session.commit()
    print(f"{settings.app_url}/reset-password?token={token}")
    print("(1시간 동안 한 번만 쓸 수 있습니다)", file=sys.stderr)
    return 0


def comp(email: str, off: bool) -> int:
    with SessionLocal() as session:
        user = session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
        if user is None or user.role != "owner":
            print("그 이메일의 대표 계정이 없습니다", file=sys.stderr)
            return 1
        sub = billing.get(session, user.organization_id, datetime.now(timezone.utc))
        sub.plan = "free" if off else "comp"
        session.add(AuditLog(action="billing.comp_cli", entity_type="organization", entity_id=str(user.organization_id),
                             detail={"plan": sub.plan}))
        session.commit()
    print(f"요금제: {'무료 한도' if off else '무상 제공'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ROOMAX 관리 명령")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rl = sub.add_parser("reset-link", help="비밀번호 재설정 링크 출력 (메일 없이)")
    rl.add_argument("email")
    cp = sub.add_parser("comp", help="사업장을 무상 제공(요금 한도 없음)으로")
    cp.add_argument("email")
    cp.add_argument("--off", action="store_true", help="무상 제공을 끄고 무료 한도로")
    args = ap.parse_args(argv)
    if args.cmd == "reset-link":
        return reset_link(args.email)
    if args.cmd == "comp":
        return comp(args.email, args.off)
    return 2


if __name__ == "__main__":
    sys.exit(main())
