"""개인 사용 모드 — 처음 한 명만 가입, 메일 없이 재설정 링크."""
import dataclasses

from cryptography.fernet import Fernet

from app import admin_cli
from app.config import Settings, production_problems, settings
from tests.conftest import PASSWORD


def _signup(c, email):
    return c.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD, "name": "대표",
                                               "organization_name": "내 건물", "agree_terms": True, "agree_privacy": True})


def test_first_only_allows_just_the_first_owner(anon_client, monkeypatch):
    monkeypatch.setattr("app.routers.auth.settings", dataclasses.replace(settings, signup_mode="first_only"))
    assert anon_client.get("/api/v1/auth/signup-status").json() == {"open": True, "mode": "first_only"}
    assert _signup(anon_client, "me@example.com").status_code == 201
    assert anon_client.get("/api/v1/auth/signup-status").json()["open"] is False
    res = _signup(anon_client, "stranger@example.com")
    assert res.status_code == 403 and "개인 사용 모드" in res.json()["detail"]


def test_open_mode_keeps_signup_open(anon_client):
    assert _signup(anon_client, "a@example.com").status_code == 201
    assert anon_client.get("/api/v1/auth/signup-status").json()["open"] is True


def test_personal_server_may_run_without_smtp():
    base = Settings(env="production", database_url="postgresql+psycopg://roomax:s3cret@db/roomax",
                    field_key=Fernet.generate_key().decode(), cookie_secure=True, app_url="https://x.duckdns.org",
                    mail_mode="file", smtp_host="")
    assert production_problems(dataclasses.replace(base, signup_mode="first_only")) == []
    assert any("SMTP" in p for p in production_problems(dataclasses.replace(base, signup_mode="open")))
    assert production_problems(dataclasses.replace(base, signup_mode="whatever"))


def test_reset_link_cli(client, session_factory, monkeypatch, capsys, anon_client):
    monkeypatch.setattr(admin_cli, "SessionLocal", session_factory)
    assert admin_cli.main(["reset-link", "nobody@example.com"]) == 1
    assert admin_cli.main(["reset-link", "Owner@Example.com"]) == 0
    link = capsys.readouterr().out.strip()
    token = link.split("token=")[1]
    res = anon_client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "brand-new-pass-7"})
    assert res.status_code == 200, res.text
    assert anon_client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "brand-new-pass-7"}).status_code == 200


def test_owner_email_pins_the_first_signup(anon_client, monkeypatch):
    monkeypatch.setattr("app.routers.auth.settings",
                        dataclasses.replace(settings, signup_mode="first_only", owner_email="boss@example.com"))
    res = _signup(anon_client, "early-bird@example.com")
    assert res.status_code == 403 and "대표 이메일" in res.json()["detail"]
    assert _signup(anon_client, "Boss@Example.com").status_code == 201


def test_me_reports_mail_disabled_only_on_personal_production(client, monkeypatch):
    assert client.get("/api/v1/auth/me").json()["mail_enabled"] is True  # 개발: file 모드라도 outbox 로 확인 가능
    monkeypatch.setattr("app.routers.auth.settings", dataclasses.replace(settings, env="production", mail_mode="file"))
    assert client.get("/api/v1/auth/me").json()["mail_enabled"] is False
