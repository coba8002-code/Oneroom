import os
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["ROOMAX_DATABASE_URL"] = "sqlite://"
os.environ["ROOMAX_FIELD_KEY"] = Fernet.generate_key().decode()

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


@pytest.fixture
def client(session_factory):
    def _override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


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
