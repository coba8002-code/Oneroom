"""사진 판독 — 표만 돌려주고 저장하지 않음, 형식 틀린 칸은 비움, 확인한 통장 줄은 파일과 같은 규칙으로.

실제 API 는 부르지 않는다: 가짜 클라이언트가 정해진 JSON 을 돌려주고 보낸 요청을 기록한다.
"""
import json
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, Transaction
from app.services import assistant, vision

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 100


class FakeClient:
    def __init__(self, payload, stop="end_turn"):
        self.payload, self.stop, self.requests = payload, stop, []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        return NS(stop_reason=self.stop, content=[NS(type="text", text=json.dumps(self.payload, ensure_ascii=False))])


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(payload, stop="end_turn"):
        holder["c"] = FakeClient(payload, stop)
        monkeypatch.setattr(assistant, "_client", lambda: holder["c"])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        return holder["c"]
    return install


def _post(client, kind, files=None):
    files = files or [("files", ("a.png", PNG, "image/png"))]
    return client.post(f"/api/v1/vision/{kind}", files=files)


def _unit(**kw):
    base = {k: None for k in vision.UNIT_FIELDS}
    return {**base, "evidence": "사진 1", **kw}


def _bank(**kw):
    return {**{k: None for k in vision.BANK_FIELDS}, **kw}


def test_not_configured(client, onboarded, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/v1/vision/status").json()["configured"] is False
    res = _post(client, "units")
    assert res.status_code == 503 and "ANTHROPIC_API_KEY" in res.json()["detail"]


def test_units_rows_cleaned_and_not_saved(client, onboarded, fake, session):
    c = fake({"rows": [
        _unit(unit_no="203", tenant_name="홍길동", deposit=5_000_000, rent=450_000, due_day=5,
              start_date="2026-11-01", end_date="2028-10-31"),
        _unit(unit_no="204", deposit=-1, due_day=40, start_date="2026/11/01", end_date="2026-02-30"),
        _unit(),  # 전부 비면 버림
    ], "notes": ["2번째 사진 흐림"]})
    before = session.scalar(select(func.count()).select_from(Transaction))
    res = _post(client, "units")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [r["unit_no"] for r in body["rows"]] == ["203", "204"]
    ok, bad = body["rows"]
    assert (ok["deposit"], ok["rent"], ok["due_day"], ok["start_date"]) == (5_000_000, 450_000, 5, "2026-11-01")
    assert (bad["deposit"], bad["due_day"], bad["start_date"], bad["end_date"]) == (None, None, None, None)  # 모르면 비움
    assert body["notes"][0] == "2번째 사진 흐림" and any("2번째 줄" in n and "due_day" in n for n in body["notes"])
    # 요청: 사진 + 구조화 출력, 장부에는 아무것도 안 들어감
    req = c.requests[0]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert any(b["type"] == "image" for b in req["messages"][0]["content"])
    assert session.scalar(select(func.count()).select_from(Transaction)) == before
    log = session.scalar(select(AuditLog).where(AuditLog.action == "vision.read"))
    assert log.detail == {"kind": "units", "files": 1, "rows": 2, "model": assistant.MODEL}  # 이름 없음


def test_file_checks(client, onboarded, fake):
    fake({"rows": [], "notes": []})
    assert _post(client, "units", [("files", ("a.txt", b"hi", "text/plain"))]).status_code == 422
    many = [("files", (f"{i}.png", PNG, "image/png")) for i in range(vision.MAX_FILES + 1)]
    assert "장까지" in _post(client, "units", many).json()["detail"]
    pdf = _post(client, "units", [("files", ("c.pdf", b"%PDF-1.4", "application/pdf"))])
    assert pdf.status_code == 200


def test_refusal_and_daily_limit(client, onboarded, fake, monkeypatch):
    fake({"rows": [], "notes": []}, stop="refusal")
    assert _post(client, "bank").status_code == 422
    fake({"rows": [], "notes": []})
    monkeypatch.setattr(vision, "DAILY_LIMIT", 1)
    assert _post(client, "bank").status_code == 200
    assert "한도" in _post(client, "bank").json()["detail"]


def test_bank_photo_rows_then_confirmed_import(client, onboarded, fake, session):
    fake({"rows": [
        _bank(date="2026-11-01", time="9:05", direction="in", amount=450_000, counterparty="임차인A",
              description="인터넷", balance_after=1_450_000),
        _bank(date="2026-11-02", direction="sideways", amount=30_000),
    ], "notes": []})
    body = _post(client, "bank").json()
    first, second = body["rows"]
    assert first["time"] == "09:05" and second["direction"] is None
    assert any("2번째 줄" in n and "direction" in n for n in body["notes"])

    acct = onboarded["bank_account_id"]
    rows = [first, {**second, "direction": "out"}]  # 관리자가 고친 뒤 넣기
    res = client.post(f"/api/v1/bank-accounts/{acct}/import-rows", json={"rows": rows})
    assert res.status_code == 200, res.text
    assert (res.json()["inserted"], res.json()["duplicates"]) == (2, 0)
    t = session.scalar(select(Transaction).where(Transaction.amount == 450_000))
    assert (t.direction, t.counterparty, t.source, t.balance_after) == ("in", "임차인A", "statement", 1_450_000)
    # 같은 줄을 다시 넣으면 중복
    assert client.post(f"/api/v1/bank-accounts/{acct}/import-rows", json={"rows": rows}).json()["duplicates"] == 2
    # 다른 계좌·잘못된 줄
    assert client.post(f"/api/v1/bank-accounts/{acct}/import-rows",
                       json={"rows": [{**first, "amount": 0}]}).status_code == 422


def test_file_after_photo_dedupes_by_balance(client, onboarded, session):
    """사진은 적요를 다르게 읽어도, 나중에 올린 파일과 (날짜·시각·금액·잔액)이 같으면 같은 거래로 본다."""
    acct = onboarded["bank_account_id"]
    client.post(f"/api/v1/bank-accounts/{acct}/import-rows", json={"rows": [
        {"date": "2026-11-03", "time": "14:20", "direction": "in", "amount": 420_000, "counterparty": "임차인 C",
         "description": None, "balance_after": 2_000_000}]})
    csv = ("거래일시,적요,기재내용,출금금액,입금금액,잔액\n"
           "2026.11.03 14:20:41,인터넷,임차인C,0원,\"420,000원\",\"2,000,000원\"\n"
           "2026.11.03 15:00:00,인터넷,임차인D,0원,\"420,000원\",\"2,420,000원\"\n").encode()
    res = client.post(f"/api/v1/bank-accounts/{acct}/import", files={"file": ("w.csv", csv, "text/csv")}).json()
    assert (res["inserted"], res["duplicates"]) == (1, 1)
    assert session.scalar(select(func.count()).select_from(Transaction).where(Transaction.amount == 420_000)) == 2
