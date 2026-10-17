"""멤버 초대 · 권한 변경 · 내보내기."""
import re
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import auth
from app.main import app
from app.models import AuditLog, Invitation, User
from tests.conftest import PASSWORD

M = "/api/v1/members"
NEW_PW = "member-pass-2026"


def _token(mailbox) -> str:
    return re.search(r"token=([\w-]+)", mailbox.sent[-1].text).group(1)


def _invite(c, email="staff@example.com", role="manager"):
    return c.post(f"{M}/invitations", json={"email": email, "role": role})


def _accept(c, token, **kw):
    body = {"token": token, "name": "김직원", "password": NEW_PW, "agree_terms": True, "agree_privacy": True, **kw}
    return c.post("/api/v1/auth/invitation/accept", json=body)


def test_invite_accept_joins_org_with_role(client, anon_client, mailbox, session):
    owner = client.get("/api/v1/auth/me").json()
    res = _invite(client, " Staff@Example.com ", "manager")
    assert res.status_code == 201, res.text
    mail = mailbox.sent[-1]
    assert mail.to == "staff@example.com" and "테스트 임대" in mail.subject and "/invite?token=" in mail.text
    token = _token(mailbox)
    assert session.scalar(select(Invitation.token_hash)) == auth._token_hash(token)  # 원문은 DB 에 없음

    pv = anon_client.post("/api/v1/auth/invitation/preview", json={"token": token}).json()
    assert pv["organization_name"] == "테스트 임대" and pv["email"] == "staff@example.com" and pv["role"] == "manager"

    res = _accept(anon_client, token)
    assert res.status_code == 201, res.text
    me = res.json()
    assert me["organization"]["id"] == owner["organization"]["id"]
    assert me["user"]["role"] == "manager" and me["user"]["email_verified"] is True
    assert anon_client.get("/api/v1/auth/me").status_code == 200  # 바로 로그인됨

    # 링크는 한 번만, 수락하면 초대의 이메일은 지움
    assert _accept(TestClient(app), token).status_code == 410
    session.expire_all()
    inv = session.scalar(select(Invitation))
    assert inv.accepted_at and inv.email is None
    listed = client.get(M).json()
    assert [m["role"] for m in listed["members"]] == ["owner", "manager"] and listed["invitations"] == []


def test_only_owner_manages_members(client, anon_client, mailbox):
    _invite(client, "mgr@example.com", "manager")
    _accept(anon_client, _token(mailbox))
    assert anon_client.get(M).status_code == 403
    assert _invite(anon_client, "x@example.com").status_code == 403


def test_viewer_invite_is_read_only(client, anon_client, mailbox):
    _invite(client, "view@example.com", "viewer")
    _accept(anon_client, _token(mailbox))
    assert anon_client.get("/api/v1/organizations").status_code == 200
    assert anon_client.post("/api/v1/charges/generate", params={"period": "2026-11"}).status_code == 403


def test_invite_validation(client):
    assert _invite(client, "not-an-email").status_code == 422
    assert _invite(client, role="owner").status_code == 422  # 대표 권한은 줄 수 없음
    assert _invite(client, "owner@example.com").status_code == 409  # 이미 이 사업장 멤버


def test_reinvite_revokes_previous_link(client, anon_client, mailbox):
    _invite(client)
    first = _token(mailbox)
    _invite(client, role="viewer")
    second = _token(mailbox)
    assert _accept(anon_client, first).status_code == 410
    assert _accept(anon_client, second).json()["user"]["role"] == "viewer"


def test_revoke_and_expiry(client, anon_client, mailbox, session):
    inv = _invite(client).json()
    token = _token(mailbox)
    assert client.post(f"{M}/invitations/{inv['id']}/revoke").json() == {"revoked": True}
    assert anon_client.post("/api/v1/auth/invitation/preview", json={"token": token}).status_code == 410
    assert client.get(M).json()["invitations"] == []

    _invite(client, "late@example.com")
    late = _token(mailbox)
    row = session.scalar(select(Invitation).where(Invitation.email == "late@example.com"))
    row.expires_at = auth.utcnow() - timedelta(minutes=1)
    session.commit()
    assert _accept(anon_client, late).status_code == 410
    assert client.get(M).json()["invitations"][0]["expired"] is True  # 대표 화면엔 '만료'로 남아 다시 보낼 수 있음

    row.expires_at = auth.utcnow() - timedelta(days=31)
    session.commit()
    assert client.get(M).json()["invitations"] == []  # 만료 30일 뒤 이메일째 삭제
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Invitation).where(Invitation.email == "late@example.com")) == 0


def test_accept_requires_consent_and_password_rules(client, anon_client, mailbox):
    _invite(client)
    token = _token(mailbox)
    assert _accept(anon_client, token, agree_privacy=False).status_code == 422
    assert _accept(anon_client, token, password="short1").status_code == 422
    assert _accept(anon_client, token).status_code == 201  # 실패해도 링크는 소모되지 않음


def test_existing_account_elsewhere_cannot_accept(make_client, client, anon_client, mailbox):
    make_client(email="taken@example.com", org_name="다른 사업장")
    res = _invite(client, "taken@example.com")
    assert res.status_code == 201  # 초대할 때는 다른 사업장 가입 여부를 알려주지 않음
    res = _accept(anon_client, _token(mailbox))
    assert res.status_code == 409 and "이미 ROOMAX 계정" in res.json()["detail"]


def test_change_role_and_remove(client, anon_client, mailbox, session):
    _invite(client)
    staff = _accept(anon_client, _token(mailbox)).json()["user"]
    owner_id = client.get("/api/v1/auth/me").json()["user"]["id"]

    assert client.patch(f"{M}/{staff['id']}", json={"role": "viewer"}).json()["role"] == "viewer"
    assert anon_client.post("/api/v1/charges/generate", params={"period": "2026-11"}).status_code == 403  # 즉시 적용
    assert client.patch(f"{M}/{staff['id']}", json={"role": "owner"}).status_code == 422
    assert client.patch(f"{M}/{owner_id}", json={"role": "viewer"}).status_code == 409
    assert client.delete(f"{M}/{owner_id}").status_code == 409

    assert client.delete(f"{M}/{staff['id']}").json() == {"removed": True}
    assert anon_client.get("/api/v1/auth/me").status_code == 401  # 내보낸 계정은 바로 로그아웃
    session.expire_all()
    assert session.scalar(select(User).where(User.email == "staff@example.com")) is None
    logs = session.scalars(select(AuditLog).where(AuditLog.action.like("member.%"))).all()
    assert {log.action for log in logs} >= {"member.invited", "member.role_changed", "member.removed"}
    assert "staff@example.com" not in str([log.detail for log in logs])  # 감사 기록에 이메일 없음


def test_other_orgs_member_is_not_found(make_client, client, anon_client, mailbox):
    other, _ = make_client(email="boss2@example.com", org_name="남의 사업장")
    _invite(other, "theirs@example.com")
    theirs = _accept(anon_client, _token(mailbox)).json()["user"]["id"]
    inv = _invite(other, "pending@example.com").json()
    assert client.patch(f"{M}/{theirs}", json={"role": "viewer"}).status_code == 404
    assert client.delete(f"{M}/{theirs}").status_code == 404
    assert client.post(f"{M}/invitations/{inv['id']}/revoke").status_code == 404


def test_invite_rate_limit(client):
    for i in range(20):
        assert _invite(client, f"p{i}@example.com").status_code == 201
    assert _invite(client, "p20@example.com").status_code == 429


def test_org_deletion_removes_invitations(client, session):
    _invite(client)
    from tests.conftest import ORG_NAME
    assert client.post("/api/v1/auth/account/delete",
                       json={"password": PASSWORD, "confirm_name": ORG_NAME}).status_code == 200
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(Invitation)) == 0
