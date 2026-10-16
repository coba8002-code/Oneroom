"""운영 설정 검사 · 상태 검사."""
import dataclasses

from cryptography.fernet import Fernet

from app.config import Settings, production_problems

GOOD = Settings(
    env="production",
    database_url="postgresql+psycopg://roomax:s3cret-long@db:5432/roomax",
    field_key=Fernet.generate_key().decode(),
    cookie_secure=True,
    app_url="https://roomax.example.kr",
    mail_mode="smtp",
    smtp_host="smtp.example.kr",
)


def test_good_production_settings_pass():
    assert production_problems(GOOD) == []


def test_each_unsafe_setting_is_reported():
    cases = {
        "field_key": "",
        "cookie_secure": False,
        "app_url": "http://roomax.example.kr",
        "mail_mode": "file",
        "smtp_host": "",
        "database_url": "postgresql+psycopg://roomax:roomax@db:5432/roomax",
    }
    for field, bad in cases.items():
        problems = production_problems(dataclasses.replace(GOOD, **{field: bad}))
        assert len(problems) == 1, (field, problems)
    assert len(production_problems(dataclasses.replace(GOOD, field_key="not-a-key"))) == 1


def test_health_checks_database(anon_client):
    assert anon_client.get("/api/v1/health").json() == {"status": "ok"}
