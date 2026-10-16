import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["ROOMAX_DATABASE_URL"] = "sqlite://"
os.environ["ROOMAX_FIELD_KEY"] = Fernet.generate_key().decode()
os.environ["ROOMAX_UPLOAD_DIR"] = tempfile.mkdtemp(prefix="roomax-test-uploads-")
os.environ.pop("ROOMAX_CLOVA_OCR_URL", None)  # 테스트는 실제 OCR 서버를 부르지 않는다
os.environ.pop("ROOMAX_CLOVA_OCR_SECRET", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


ORG_NAME = "테스트 임대"
PASSWORD = "test-password-123"


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    from app import auth
    auth._fails.clear()
    yield
    auth._fails.clear()


@pytest.fixture
def _override(session_factory):
    def _get():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _get
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client(_override):
    """로그인하지 않은 클라이언트."""
    return TestClient(app)


@pytest.fixture
def make_client(_override):
    """가입(=사업장 생성)까지 마친 새 클라이언트를 만든다. 반환: (client, me)"""
    n = iter(range(1, 1000))

    def _make(org_name: str = ORG_NAME, email: str | None = None):
        c = TestClient(app)
        res = c.post("/api/v1/auth/signup", json={
            "email": email or f"owner{next(n)}@example.com", "password": PASSWORD, "name": "대표",
            "organization_name": org_name, "agree_terms": True, "agree_privacy": True})
        assert res.status_code == 201, res.text
        return c, res.json()
    return _make


@pytest.fixture
def client(make_client):
    """가입·로그인된 사업장 대표(owner)."""
    c, _ = make_client(email="owner@example.com")
    return c


@pytest.fixture
def onboarded(client):
    """샘플 CSV(9 임대 + 주인세대 1, 공실 1) 를 미리보기 → 등록까지."""
    raw = (SAMPLES / "onboarding_units.csv").read_bytes()
    preview = client.post("/api/v1/onboarding/csv-preview", files={"file": ("u.csv", raw, "text/csv")}).json()
    assert preview["errors"] == []
    res = client.post("/api/v1/onboarding", json={
        "property": {"name": "테스트 다가구", "address": "어딘가"},
        "units": preview["units"],
    })
    assert res.status_code == 201, res.text
    return res.json()
