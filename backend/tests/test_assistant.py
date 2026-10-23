"""AI 비서 — 도구로 조회한 값만, 이름·연락처는 보내지 않음, 키 없으면 안내, 하루 상한, 거절 처리.

실제 API 는 부르지 않는다: 가짜 클라이언트가 정해진 순서로 응답하고, 보낸 요청을 기록한다.
"""
import json
import re
import uuid
from datetime import date
from types import SimpleNamespace as NS

import pytest

from app.services import assistant as svc


def _text(t):
    return NS(type="text", text=t)


def _use(name, args, id_="tu_1"):
    return NS(type="tool_use", name=name, input=args, id=id_)


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        return self.responses.pop(0)


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(*responses):
        holder["c"] = FakeClient(*responses)
        monkeypatch.setattr(svc, "_client", lambda *_: holder["c"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        return holder["c"]
    return install


def _ask(client, q="이번 달 미납 알려줘", history=None):
    return client.post("/api/v1/assistant/ask", json={"question": q, "history": history or []})


def test_not_configured(client, onboarded, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    st = client.get("/api/v1/assistant/status").json()
    assert st["configured"] is False and st["model"] == svc.MODEL
    res = _ask(client)
    assert res.status_code == 503 and "AI 연결" in res.json()["detail"]


def test_tool_loop_returns_answer_with_sources(client, onboarded, fake):
    client.post("/api/v1/charges/generate", params={"organization_id": onboarded["organization_id"], "period": "2026-11"})
    c = fake(NS(stop_reason="tool_use", content=[_use("list_unpaid", {"as_of": "2026-11-30"})]),
             NS(stop_reason="end_turn", content=[_text("101호 450,000원 미납입니다.")]))
    res = _ask(client)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer"] == "101호 450,000원 미납입니다." and body["kind"] == "fact"
    assert body["sources"] == [{"tool": "list_unpaid", "input": {"as_of": "2026-11-30"}, "error": False}]
    assert body["queried_at"] and body["remaining_today"] == svc.DAILY_LIMIT - 1

    first, second = c.requests
    assert first["model"] == svc.MODEL and first["output_config"] == {"effort": "low"}
    assert first["fallbacks"] == "default" and first["betas"] == [svc.FALLBACK_BETA]
    assert all(t["strict"] and t["input_schema"]["additionalProperties"] is False for t in first["tools"])
    tool_result = second["messages"][-1]["content"][0]
    data = json.loads(tool_result["content"])
    assert {i["unit_no"] for i in data["items"]} >= {"101"} and tool_result["is_error"] is False


def test_tool_results_never_carry_names_or_phones(client, onboarded, session):
    """모든 도구 결과에 임차인 이름(샘플: 임차인A~H)·전화번호가 없어야 한다."""
    client.post("/api/v1/charges/generate", params={"organization_id": onboarded["organization_id"], "period": "2026-11"})
    org = uuid.UUID(onboarded["organization_id"])
    args = {"as_of": "2026-11-30", "period": "2026-11", "year": 2026}
    for name in svc.HANDLERS:
        body, is_error = svc.run_tool(session, org, name, args, date(2026, 11, 30))
        assert not is_error, (name, body)
        assert not re.search(r"임차인[A-H]", body) and "010-" not in body, name  # 샘플 임차인 이름·연락처


def test_bad_tool_input_is_error_result(client, onboarded, session):
    body, is_error = svc.run_tool(session, uuid.UUID(onboarded["organization_id"]), "get_overview",
                                  {"as_of": "어제"}, date(2026, 11, 30))
    assert is_error and "YYYY-MM-DD" in body
    assert svc.run_tool(session, uuid.uuid4(), "drop_table", {}, date(2026, 11, 30))[1] is True


def test_refusal_and_no_tool_answer(client, onboarded, fake):
    fake(NS(stop_reason="refusal", content=[]))
    body = _ask(client).json()
    assert body["kind"] == "denied" and "답할 수 없습니다" in body["answer"]
    fake(NS(stop_reason="end_turn", content=[_text("장부와 관계없는 질문입니다.")]))
    assert _ask(client, "날씨 어때?").json()["kind"] == "unknown"  # 도구를 안 쓰면 사실 답이 아님


def test_history_is_cleaned_and_question_has_date(client, onboarded, fake):
    c = fake(NS(stop_reason="end_turn", content=[_text("네")]))
    history = [{"role": "assistant", "text": "먼저 온 비서 말"}, {"role": "user", "text": "앞 질문"},
               {"role": "assistant", "text": "앞 답"}, {"role": "user", "text": "답 없는 질문"}]
    _ask(client, "이번 질문", history)
    msgs = c.requests[0]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "앞 질문" and msgs[-1]["content"].endswith("이번 질문") and "KST" in msgs[-1]["content"]


def test_daily_limit_and_validation(client, onboarded, fake, monkeypatch):
    monkeypatch.setattr(svc, "DAILY_LIMIT", 1)
    fake(NS(stop_reason="end_turn", content=[_text("네")]))
    assert _ask(client).status_code == 200
    res = _ask(client)
    assert res.status_code == 409 and "한도" in res.json()["detail"]
    assert _ask(client, " ").status_code == 409


def test_round_limit(client, onboarded, fake, monkeypatch):
    monkeypatch.setattr(svc, "MAX_ROUNDS", 2)
    fake(*[NS(stop_reason="tool_use", content=[_use("list_leases", {})])] * 2)
    body = _ask(client).json()
    assert "정리하지 못했습니다" in body["answer"]


def test_haiku_gets_no_fallbacks(monkeypatch):
    assert svc._request_extras("claude-haiku-5-5") == {}
    assert svc._request_extras("claude-opus-5-5")["fallbacks"] == "default"


def test_audit_log_has_no_question_text(client, onboarded, fake, session):
    from app.models import AuditLog

    fake(NS(stop_reason="end_turn", content=[_text("네")]))
    _ask(client, "101호 임차인 홍길동 010-1234-5678 미납?")
    row = session.query(AuditLog).filter_by(action="assistant.ask").one()
    assert "홍길동" not in json.dumps(row.detail, ensure_ascii=False)
