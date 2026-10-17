"""이메일 인증 · 비밀번호 재설정."""
import re
from datetime import timedelta

from sqlalchemy import select

from app import auth
from app.models import AuditLog, AuthSession, EmailToken, User
from tests.conftest import PASSWORD

NEW_PW = "brand-new-pass-77"


def _token(mail) -> str:
    return re.search(r"token=([\w-]+)", mail.text).group(1)


def _signup(c, email="v@example.com"):
    return c.post("/api/v1/auth/signup", json={
        "email": email, "password": PASSWORD, "name": "김대표", "organization_name": "확인 임대",
        "agree_terms": True, "agree_privacy": True})


# ── 이메일 확인 ──

def test_signup_sends_verification_mail(anon_client, mailbox, session):
    me = _signup(anon_client).json()
    assert me["user"]["email_verified"] is False
    assert len(mailbox.sent) == 1
    mail = mailbox.sent[0]
    assert mail.to == "v@example.com" and "확인" in mail.subject
    assert "http://localhost:3000/verify-email?token=" in mail.text
    token = _token(mail)
    assert session.scalar(select(EmailToken.token_hash)) == auth._token_hash(token)  # 원문은 DB 에 없음
    assert token not in str(session.scalar(select(EmailToken)).__dict__)


def test_verify_once_without_login(anon_client, mailbox, make_client):
    c, _ = make_client(email="once@example.com")
    token = _token(mailbox.sent[-1])
    assert anon_client.post("/api/v1/auth/verify-email", json={"token": token}).json() == {"verified": True}
    assert c.get("/api/v1/auth/me").json()["user"]["email_verified"] is True
    again = anon_client.post("/api/v1/auth/verify-email", json={"token": token})
    assert again.status_code == 400 and "이미 사용" in again.json()["detail"]
    assert anon_client.post("/api/v1/auth/verify-email", json={"token": "made-up"}).status_code == 400


def test_verify_expired(anon_client, mailbox, session, make_client):
    make_client(email="exp@example.com")
    row = session.scalar(select(EmailToken))
    row.expires_at = auth.utcnow() - timedelta(seconds=1)
    session.commit()
    assert anon_client.post("/api/v1/auth/verify-email", json={"token": _token(mailbox.sent[-1])}).status_code == 400


def test_resend_invalidates_old_link_and_is_throttled(make_client, mailbox, anon_client):
    c, _ = make_client(email="re@example.com")
    first = _token(mailbox.sent[-1])
    assert c.post("/api/v1/auth/verify-email/send").status_code == 202
    second = _token(mailbox.sent[-1])
    assert c.post("/api/v1/auth/verify-email/send").status_code == 429  # 1분에 1번
    assert anon_client.post("/api/v1/auth/verify-email", json={"token": first}).status_code == 400  # 옛 링크 무효
    assert anon_client.post("/api/v1/auth/verify-email", json={"token": second}).status_code == 200
    assert c.post("/api/v1/auth/verify-email/send").status_code == 409  # 이미 확인됨


def test_resend_requires_login(anon_client):
    assert anon_client.post("/api/v1/auth/verify-email/send").status_code == 401


# ── 비밀번호 재설정 ──

def test_reset_same_answer_for_unknown_email(anon_client, mailbox, make_client):
    make_client(email="known@example.com")
    mailbox.sent.clear()
    a = anon_client.post("/api/v1/auth/password-reset/request", json={"email": "known@example.com"})
    b = anon_client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()  # 가입 여부 노출 안 함
    assert [m.to for m in mailbox.sent] == ["known@example.com"]
    assert "reset-password?token=" in mailbox.sent[0].text and "1시간" in mailbox.sent[0].text


def test_reset_full_flow(make_client, anon_client, mailbox, session):
    c, _ = make_client(email="r@example.com")
    assert c.get("/api/v1/auth/me").status_code == 200
    anon_client.post("/api/v1/auth/password-reset/request", json={"email": "R@example.com"})
    token = _token(mailbox.sent[-1])

    weak = anon_client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "short1"})
    assert weak.status_code == 422  # 약한 비밀번호 → 토큰은 아직 살아 있음
    ok = anon_client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PW})
    assert ok.json() == {"reset": True}

    assert c.get("/api/v1/auth/me").status_code == 401  # 모든 기기 로그아웃
    assert anon_client.post("/api/v1/auth/login", json={"email": "r@example.com", "password": PASSWORD}).status_code == 401
    me = anon_client.post("/api/v1/auth/login", json={"email": "r@example.com", "password": NEW_PW}).json()
    assert me["user"]["email_verified"] is True  # 메일을 받았으니 주소 확인도 됨
    again = anon_client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "another-pass-88"})
    assert again.status_code == 400  # 한 번만
    uid = session.scalar(select(User.id).where(User.email == "r@example.com"))
    live = session.scalars(select(AuthSession).where(AuthSession.user_id == uid, AuthSession.revoked_at.is_(None))).all()
    assert len(live) == 1  # 재설정 전 세션은 모두 폐기, 남은 건 방금 새 비밀번호로 로그인한 것


def test_new_reset_request_invalidates_previous(make_client, anon_client, mailbox):
    make_client(email="two@example.com")
    anon_client.post("/api/v1/auth/password-reset/request", json={"email": "two@example.com"})
    old = _token(mailbox.sent[-1])
    anon_client.post("/api/v1/auth/password-reset/request", json={"email": "two@example.com"})
    new = _token(mailbox.sent[-1])
    assert anon_client.post("/api/v1/auth/password-reset/confirm", json={"token": old, "new_password": NEW_PW}).status_code == 400
    assert anon_client.post("/api/v1/auth/password-reset/confirm", json={"token": new, "new_password": NEW_PW}).status_code == 200


def test_reset_expired_and_throttled(make_client, anon_client, mailbox, session):
    make_client(email="t3@example.com")
    for _ in range(5):
        anon_client.post("/api/v1/auth/password-reset/request", json={"email": "t3@example.com"})
    assert sum(m.to == "t3@example.com" and "재설정" in m.subject for m in mailbox.sent) == 3  # 시간당 3통
    row = session.scalars(select(EmailToken).where(EmailToken.purpose == "reset_password",
                                                   EmailToken.used_at.is_(None))).one()
    row.expires_at = auth.utcnow() - timedelta(seconds=1)
    session.commit()
    res = anon_client.post("/api/v1/auth/password-reset/confirm",
                           json={"token": _token(mailbox.sent[-1]), "new_password": NEW_PW})
    assert res.status_code == 400


def test_reset_clears_login_lock_and_keeps_mfa(make_client, anon_client, mailbox, session):
    c, _ = make_client(email="lock@example.com")
    secret = c.post("/api/v1/auth/mfa/setup").json()["secret"]
    c.post("/api/v1/auth/mfa/enable", json={"code": auth.totp_now(secret)})
    for _ in range(auth.MAX_FAILS):
        anon_client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": "wrong-pass-1"})
    anon_client.post("/api/v1/auth/password-reset/request", json={"email": "lock@example.com"})
    anon_client.post("/api/v1/auth/password-reset/confirm", json={"token": _token(mailbox.sent[-1]), "new_password": NEW_PW})
    res = anon_client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": NEW_PW})
    assert res.json() == {"mfa_required": True}  # 잠금 풀림, 2단계 인증은 그대로


def test_inactive_user_gets_no_reset_mail(make_client, anon_client, mailbox, session):
    make_client(email="off@example.com")
    u = session.scalar(select(User).where(User.email == "off@example.com"))
    u.is_active = False
    session.commit()
    mailbox.sent.clear()
    assert anon_client.post("/api/v1/auth/password-reset/request", json={"email": "off@example.com"}).status_code == 202
    assert mailbox.sent == []


def test_no_email_or_token_in_audit_logs(make_client, anon_client, mailbox, session):
    make_client(email="audit@example.com")
    anon_client.post("/api/v1/auth/password-reset/request", json={"email": "audit@example.com"})
    token = _token(mailbox.sent[-1])
    for log in session.scalars(select(AuditLog)):
        assert "audit@example.com" not in str(log.detail) and token not in str(log.detail)


def test_file_mailer_writes_eml(tmp_path, monkeypatch):
    import dataclasses
    from app.config import settings
    from app.services import mailer
    monkeypatch.setattr(mailer, "settings", dataclasses.replace(settings, mail_outbox_dir=str(tmp_path)))
    mailer.FileMailer().send(mailer.verify_mail("a@example.com", "가", "http://x/verify-email?token=abc"))
    eml = next(tmp_path.glob("*.eml")).read_bytes()
    assert b"Subject:" in eml and b"To: a@example.com" in eml


def test_mail_failure_does_not_break_signup(anon_client, monkeypatch):
    from app.services import mailer

    class Broken:
        def send(self, mail):
            raise OSError("smtp down")
    monkeypatch.setattr(mailer, "get_mailer", lambda: Broken())
    assert _signup(anon_client, "down@example.com").status_code == 201
