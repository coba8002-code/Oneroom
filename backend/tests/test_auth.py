"""회원가입 · 로그인 · 권한 · 사업장 격리."""
import re
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app import auth
from app.main import app
from app.models import AuditLog, AuthSession, User
from tests.conftest import PASSWORD

# 로그인 없이 쓰는 경로 (메일 링크는 다른 기기에서 열 수 있고, 비밀번호를 잊은 사람은 로그인할 수 없으므로)
PUBLIC = {"/api/v1/health", "/api/v1/internal/cron/daily", "/api/v1/auth/signup", "/api/v1/auth/login", "/api/v1/auth/logout",
          "/api/v1/auth/verify-email", "/api/v1/auth/password-reset/request", "/api/v1/auth/password-reset/confirm",
          "/api/v1/auth/invitation/preview", "/api/v1/auth/invitation/accept", "/api/v1/auth/signup-status"}


def _signup(c, **kw):
    body = {"email": "new@example.com", "password": PASSWORD, "name": "김대표", "organization_name": "새 임대",
            "agree_terms": True, "agree_privacy": True, **kw}
    return c.post("/api/v1/auth/signup", json=body)


def _routes():
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path not in PUBLIC:
            yield sorted(r.methods)[0], r.path, r


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


# ── 가입 ──

def test_signup_creates_owner_org_and_logs_in(anon_client, session):
    res = _signup(anon_client, email=" New@Example.com ", agree_marketing=True)
    assert res.status_code == 201, res.text
    me = res.json()
    assert me["user"]["role"] == "owner" and me["user"]["email"] == "new@example.com"
    assert me["organization"]["name"] == "새 임대" and me["user"]["marketing_agreed"] is True
    assert anon_client.get("/api/v1/auth/me").json()["organization"]["id"] == me["organization"]["id"]
    user = session.scalar(select(User).where(User.email == "new@example.com"))
    assert user.password_hash.startswith("scrypt$") and PASSWORD not in user.password_hash
    assert user.terms_agreed_at and user.privacy_agreed_at and user.marketing_agreed_at
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    token = anon_client.cookies.get(auth.COOKIE)
    assert session.scalar(select(AuthSession.token_hash)) == auth._token_hash(token)  # 토큰 원문은 DB 에 없음


@pytest.mark.parametrize("kw,status,msg", [
    ({"agree_terms": False}, 422, "동의"),
    ({"agree_privacy": False}, 422, "동의"),
    ({"email": "not-an-email"}, 422, "이메일"),
    ({"password": "short1"}, 422, "10자"),
    ({"password": "onlyletters"}, 422, "문자와 숫자"),
    ({"email": "kimboss@example.com", "password": "kimboss-2026"}, 422, "이메일 아이디"),
])
def test_signup_validation(anon_client, kw, status, msg):
    res = _signup(anon_client, **kw)
    assert res.status_code == status and msg in res.json()["detail"]


def test_short_email_id_does_not_block_passwords():
    assert auth.password_problem("apple-pie-2026", "a@example.com") is None


def test_marketing_is_optional_and_default_off(anon_client):
    assert _signup(anon_client).json()["user"]["marketing_agreed"] is False


def test_duplicate_email(anon_client, make_client):
    make_client(email="dup@example.com")
    assert _signup(anon_client, email="DUP@example.com").status_code == 409


# ── 로그인 · 로그아웃 ──

def test_login_logout(anon_client, make_client):
    make_client(email="a@example.com")
    bad = anon_client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "wrong-pass-1"})
    nobody = anon_client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass-1"})
    assert bad.status_code == nobody.status_code == 401
    assert bad.json()["detail"] == nobody.json()["detail"]  # 계정 존재 여부를 알려주지 않음
    ok = anon_client.post("/api/v1/auth/login", json={"email": "A@example.com", "password": PASSWORD})
    assert ok.status_code == 200 and anon_client.get("/api/v1/auth/me").status_code == 200
    token = anon_client.cookies.get(auth.COOKIE)
    assert anon_client.post("/api/v1/auth/logout").status_code == 204
    anon_client.cookies.set(auth.COOKIE, token)  # 훔친 쿠키를 다시 넣어도
    assert anon_client.get("/api/v1/auth/me").status_code == 401  # 서버에서 폐기됨


def test_login_throttle(anon_client, make_client):
    make_client(email="t@example.com")
    for _ in range(auth.MAX_FAILS):
        anon_client.post("/api/v1/auth/login", json={"email": "t@example.com", "password": "wrong-pass-1"})
    res = anon_client.post("/api/v1/auth/login", json={"email": "t@example.com", "password": PASSWORD})
    assert res.status_code == 429  # 맞는 비밀번호도 잠금 동안은 거부


def test_expired_session(client, session):
    s = session.scalar(select(AuthSession))
    s.expires_at = auth.utcnow() - timedelta(seconds=1)
    session.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_change_logs_out_other_devices(make_client, anon_client):
    c1, _ = make_client(email="p@example.com")
    anon_client.post("/api/v1/auth/login", json={"email": "p@example.com", "password": PASSWORD})
    assert c1.post("/api/v1/auth/password", json={"current_password": "x", "new_password": "new-pass-9999"}).status_code == 401
    assert c1.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "new-pass-9999"}).status_code == 204
    assert c1.get("/api/v1/auth/me").status_code == 200  # 바꾼 기기는 유지
    assert anon_client.get("/api/v1/auth/me").status_code == 401  # 다른 기기는 로그아웃
    assert anon_client.post("/api/v1/auth/login", json={"email": "p@example.com", "password": "new-pass-9999"}).status_code == 200


def test_no_secrets_in_audit_logs(client, session):
    for log in session.scalars(select(AuditLog).where(AuditLog.action.like("auth.%"))):
        text = str(log.detail)
        assert PASSWORD not in text and "@" not in text


# ── MFA ──

def test_totp_rfc6238_vector():
    # RFC 6238 부록 B (SHA1, 비밀키 "12345678901234567890", T=59 → 94287082 의 끝 6자리)
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert auth.totp_now(secret, at=59) == "287082"
    assert auth.verify_totp(secret, "287082", at=59) and not auth.verify_totp(secret, "000000", at=59)


def test_mfa_flow(make_client, anon_client):
    c, _ = make_client(email="m@example.com")
    setup = c.post("/api/v1/auth/mfa/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/ROOMAX:")
    assert c.post("/api/v1/auth/mfa/enable", json={"code": "000000"}).status_code == 422
    assert c.post("/api/v1/auth/mfa/enable", json={"code": auth.totp_now(setup["secret"])}).status_code == 204
    assert c.get("/api/v1/auth/me").json()["user"]["mfa_enabled"] is True

    step1 = anon_client.post("/api/v1/auth/login", json={"email": "m@example.com", "password": PASSWORD})
    assert step1.json() == {"mfa_required": True} and anon_client.cookies.get(auth.COOKIE) is None
    wrong = anon_client.post("/api/v1/auth/login", json={"email": "m@example.com", "password": PASSWORD, "otp": "000000"})
    assert wrong.status_code == 401
    ok = anon_client.post("/api/v1/auth/login", json={"email": "m@example.com", "password": PASSWORD,
                                                      "otp": auth.totp_now(setup["secret"])})
    assert ok.status_code == 200 and anon_client.get("/api/v1/auth/me").status_code == 200

    assert c.post("/api/v1/auth/mfa/disable", json={"password": PASSWORD, "code": "000000"}).status_code == 401
    assert c.post("/api/v1/auth/mfa/disable", json={"password": PASSWORD,
                                                    "code": auth.totp_now(setup["secret"])}).status_code == 204


def test_mfa_secret_encrypted_at_rest(make_client, session):
    from sqlalchemy import text
    c, me = make_client(email="enc@example.com")
    secret = c.post("/api/v1/auth/mfa/setup").json()["secret"]
    raw = session.execute(text("select mfa_secret from users where email='enc@example.com'")).scalar_one()
    assert raw and secret not in raw


# ── 모든 업무 API: 로그인 필요 · 사업장 격리 ──

def test_every_api_requires_login(anon_client):
    checked = 0
    for method, path, _ in _routes():
        if path.startswith("/api/v1/auth/"):
            res = anon_client.request(method, _fill(path))
        else:
            res = anon_client.request(method, _fill(path), params={"organization_id": str(uuid.uuid4())})
        assert res.status_code == 401, f"{method} {path} → {res.status_code}"
        checked += 1
    assert checked >= 40


def test_other_org_is_not_found_on_every_org_route(make_client):
    c, _ = make_client(email="me@example.com")
    _, other = make_client(email="other@example.com", org_name="남의 사업장")
    other_org = other["organization"]["id"]
    checked = 0
    for method, path, route in _routes():
        if "organization_id" not in [p.name for p in route.dependant.query_params]:
            continue
        res = c.request(method, _fill(path), params={"organization_id": other_org})
        assert res.status_code == 404, f"{method} {path} → {res.status_code}"
        checked += 1
    assert checked >= 30


def test_cannot_touch_other_orgs_resources_by_id(make_client):
    from tests.conftest import SAMPLES
    a, me_a = make_client(email="a1@example.com")
    b, me_b = make_client(email="b1@example.com", org_name="B 사업장")
    onboard = b.post("/api/v1/onboarding", json={"property": {"name": "B 건물"}, "units": [{"unit_no": "101"}]}).json()
    raw = (SAMPLES / "bank_transactions_sample.csv").read_bytes()
    # A 가 자기 organization_id 를 붙여도 B 의 계좌에는 못 올림
    res = a.post(f"/api/v1/bank-accounts/{onboard['bank_account_id']}/import",
                 params={"organization_id": me_a["organization"]["id"]}, files={"file": ("s.csv", raw)})
    assert res.status_code == 404
    assert [o["id"] for o in a.get("/api/v1/organizations").json()] == [me_a["organization"]["id"]]


def test_onboarding_goes_into_my_org(client):
    me = client.get("/api/v1/auth/me").json()
    res = client.post("/api/v1/onboarding", json={"property": {"name": "x"}, "units": [{"unit_no": "101"}]}).json()
    assert res["organization_id"] == me["organization"]["id"]


# ── 역할 ──

def _member(session, org_id, role, email):
    u = User(organization_id=uuid.UUID(org_id), email=email, name=role, role=role,
             password_hash=auth.hash_password(PASSWORD))
    session.add(u)
    session.commit()


def test_viewer_is_read_only_and_manager_cannot_backup(client, onboarded, session, anon_client):
    org = onboarded["organization_id"]
    _member(session, org, "viewer", "viewer@example.com")
    _member(session, org, "manager", "manager@example.com")
    anon_client.post("/api/v1/auth/login", json={"email": "viewer@example.com", "password": PASSWORD})
    assert anon_client.get("/api/v1/dashboard", params={"organization_id": org}).status_code == 200
    res = anon_client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"})
    assert res.status_code == 403 and "조회" in res.json()["detail"]

    anon_client.post("/api/v1/auth/logout")
    anon_client.post("/api/v1/auth/login", json={"email": "manager@example.com", "password": PASSWORD})
    assert anon_client.post("/api/v1/charges/generate", params={"organization_id": org, "period": "2026-11"}).status_code == 200
    exp = anon_client.post("/api/v1/backups/export", params={"organization_id": org}, json={"passphrase": "x" * 12})
    assert exp.status_code == 403  # 백업(전체 개인정보)은 대표만
    assert client.post("/api/v1/backups/export", params={"organization_id": org}, json={"passphrase": "x" * 12}).status_code == 200


def test_deactivated_user_is_logged_out(client, session):
    u = session.scalar(select(User).where(User.email == "owner@example.com"))
    u.is_active = False
    session.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_hash_timing_safe_dummy():
    # 없는 계정도 실제 해시 검증을 수행 (응답 시간으로 계정 존재 여부 추측 방지)
    t = time.perf_counter()
    assert not auth.verify_password("x", auth._DUMMY_HASH)
    assert time.perf_counter() - t > 0.005


def test_marketing_consent_can_be_withdrawn(client):
    assert client.post("/api/v1/auth/marketing", json={"agree": True}).json()["user"]["marketing_agreed"] is True
    assert client.post("/api/v1/auth/marketing", json={"agree": False}).json()["user"]["marketing_agreed"] is False
