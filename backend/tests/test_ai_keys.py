"""설정 화면의 Claude API 키 — 대표만, 암호화 저장, 끝 4자리만 보임, 키가 있으면 판독·비서가 켜짐, 백업 제외."""
import re

import pytest
from sqlalchemy import select, text

from app.models import AuditLog, OrgApiKey
from app.services import ai_keys, assistant

KEY = "sk-ant-api03-" + "x" * 40 + "AB12"


@pytest.fixture(autouse=True)
def _no_env_and_no_network(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    checked = []
    monkeypatch.setattr(ai_keys, "verify", lambda k: checked.append(k))
    return checked


def test_owner_sets_key_and_features_turn_on(client, onboarded, session, _no_env_and_no_network):
    assert client.get("/api/v1/settings/ai-key").json()["configured"] is False
    assert client.get("/api/v1/vision/status").json()["configured"] is False
    assert client.put("/api/v1/settings/ai-key", json={"key": "abc"}).status_code == 422
    res = client.put("/api/v1/settings/ai-key", json={"key": f"  {KEY} "})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {**body, "configured": True, "source": "organization", "last4": "AB12"}
    assert KEY not in res.text and _no_env_and_no_network == [KEY]  # 응답에 키 전체 없음, 넣기 전에 확인
    assert client.get("/api/v1/vision/status").json()["configured"] is True
    assert client.get("/api/v1/assistant/status").json()["configured"] is True
    # DB 에는 암호화되어 들어감, 감사 기록엔 키 없음
    raw = session.execute(text("SELECT key FROM org_api_keys")).scalar_one()
    assert KEY not in raw and session.scalar(select(OrgApiKey.key)) == KEY
    assert all(KEY not in str(a.detail) for a in session.scalars(select(AuditLog)))
    assert assistant.api_key(session, session.scalar(select(OrgApiKey.organization_id))) == KEY

    assert client.delete("/api/v1/settings/ai-key").json()["configured"] is False
    assert client.get("/api/v1/vision/status").json()["configured"] is False


def test_server_env_wins(client, onboarded, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server")
    assert client.get("/api/v1/settings/ai-key").json()["source"] == "server"


def test_rejected_key_is_not_saved(client, onboarded, session, monkeypatch):
    def bad(_):
        raise ai_keys.AiKeyError("Anthropic 이 이 키를 받아들이지 않습니다")
    monkeypatch.setattr(ai_keys, "verify", bad)
    res = client.put("/api/v1/settings/ai-key", json={"key": KEY})
    assert res.status_code == 422 and "받아들이지" in res.json()["detail"]
    assert session.scalar(select(OrgApiKey)) is None


def test_only_owner(client, anon_client, mailbox, onboarded):
    client.post("/api/v1/members/invitations", json={"email": "staff@example.com", "role": "manager"})
    token = re.search(r"token=([\w-]+)", mailbox.sent[-1].text).group(1)
    res = anon_client.post("/api/v1/auth/invitation/accept", json={
        "token": token, "name": "김직원", "password": "member-pass-2026", "agree_terms": True, "agree_privacy": True})
    assert res.status_code == 201, res.text
    assert anon_client.put("/api/v1/settings/ai-key", json={"key": KEY}).status_code == 403
    assert anon_client.delete("/api/v1/settings/ai-key").status_code == 403
    assert anon_client.get("/api/v1/settings/ai-key").json()["configured"] is False  # 상태는 볼 수 있음
