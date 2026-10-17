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


def test_daily_cron_needs_secret_and_backs_up(anon_client, onboarded, monkeypatch, tmp_path):
    from app.routers import internal
    from app.services import blobs
    url = "/api/v1/internal/cron/daily"
    assert anon_client.get(url).status_code == 404  # 비밀값 미설정 → 없는 주소
    monkeypatch.setattr(internal, "settings", dataclasses.replace(internal.settings, cron_secret="s3cret-cron"))
    assert anon_client.get(url).status_code == 401
    assert anon_client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
    monkeypatch.setattr(blobs, "settings", dataclasses.replace(blobs.settings, backup_dir=str(tmp_path)))
    blobs.store.cache_clear()
    stale = tmp_path / f"upload-20200101000000-{'0' * 32}.roomaxbak"  # 복구하다 만 임시 파일
    stale.write_bytes(b"x")
    monkeypatch.delenv("ROOMAX_BACKUP_PASSPHRASE", raising=False)
    ok = anon_client.get(url, headers={"Authorization": "Bearer s3cret-cron"}).json()
    assert ok["db"] == "ok" and ok["backup"][0].startswith("건너뜀")
    assert not stale.exists()  # 백업 비밀번호가 없어도 임시 파일은 정리
    monkeypatch.setenv("ROOMAX_BACKUP_PASSPHRASE", "cron-backup-pass-1")
    res = anon_client.get(url, headers={"Authorization": "Bearer s3cret-cron"}).json()
    assert len(res["backup"]) == 1 and list(tmp_path.glob("roomax-*.roomaxbak"))


def test_serverless_must_use_supabase_storage():
    s = dataclasses.replace(GOOD, serverless=True)
    assert any("ROOMAX_STORAGE=supabase" in p for p in production_problems(s))
    assert any("SUPABASE_URL" in p for p in production_problems(dataclasses.replace(s, storage="supabase")))
    assert production_problems(dataclasses.replace(s, storage="supabase", supabase_url="https://x.supabase.co",
                                                   supabase_service_key="k")) == []


def test_supabase_store_requests():
    import json

    import httpx

    from app.services.blobs import SupabaseStore
    seen, objects = [], {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.headers.get("authorization")))
        path = req.url.path.removeprefix("/storage/v1")
        if req.method == "POST" and path.startswith("/object/list/"):
            body = json.loads(req.content)
            folder = body["prefix"]
            names = [k[len(folder) + 1:] for k in objects if k.startswith(folder + "/") and k[len(folder) + 1:].startswith(body["search"])]
            return httpx.Response(200, json=[{"name": n, "id": "x"} for n in names])
        if req.method == "POST" and path == "/object/move":
            body = json.loads(req.content)
            objects[body["destinationKey"]] = objects.pop(body["sourceKey"])
            return httpx.Response(200, json={})
        if req.method == "POST":
            objects[path.removeprefix("/object/roomax/")] = req.content
            assert req.headers["x-upsert"] == "true"
            return httpx.Response(200, json={})
        if req.method == "GET":
            key = path.removeprefix("/object/roomax/")
            return httpx.Response(200, content=objects[key]) if key in objects else httpx.Response(400, json={})
        if req.method == "DELETE":
            for k in json.loads(req.content)["prefixes"]:
                objects.pop(k, None)
            return httpx.Response(200, json=[])
        return httpx.Response(500)

    s = SupabaseStore("https://p.supabase.co", "service-key", "roomax", "backups", transport=httpx.MockTransport(handler))
    s.put("pre-restore-a-1.roomaxbak", b"one")
    s.put("roomax-a-2.roomaxbak", b"two")
    assert objects == {"backups/pre-restore-a-1.roomaxbak": b"one", "backups/roomax-a-2.roomaxbak": b"two"}
    assert s.get("roomax-a-2.roomaxbak") == b"two"
    assert s.list("pre-restore-") == ["pre-restore-a-1.roomaxbak"]
    s.move("roomax-a-2.roomaxbak", "roomax-a-3.roomaxbak")
    s.delete(["pre-restore-a-1.roomaxbak"])
    assert list(objects) == ["backups/roomax-a-3.roomaxbak"]
    assert all(auth == "Bearer service-key" for _, _, auth in seen)
    import pytest
    with pytest.raises(FileNotFoundError):
        s.get("nope.bin")
    with pytest.raises(ValueError):
        s.put("../escape", b"x")


def test_supabase_style_database_url_is_accepted():
    from app.config import _db_url
    assert _db_url("postgresql://u:p@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres") == \
        "postgresql+psycopg://u:p@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres"
    assert _db_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _db_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _db_url("sqlite://") == "sqlite://"
