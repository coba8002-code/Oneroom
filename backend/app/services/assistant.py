"""AI 비서 — 장부를 묻고 답하기 (Claude API, 읽기 전용 도구).

원칙 (CLAUDE.md 규칙 5·6·7)
- 숫자는 모델이 만들지 않는다. 모델은 아래 '조회 도구'를 불러 DB 에서 나온 값만 문장으로 옮긴다.
  도구 결과에 없는 숫자(합계·평균·추정)를 만들지 말라고 지시하고, 응답에 쓴 도구와 조회 시각을 함께 돌려준다.
- 장부를 바꾸지 않는다. 도구는 모두 읽기 전용 — 확정·발송·삭제는 화면에서 사람이 한다.
- 개인정보를 보내지 않는다. 도구 결과에는 호실 번호·금액·날짜만 — 임차인 이름·연락처·입금자명·메모(자유 입력)는 뺀다.
- 세금·법률 판단, 독촉 결정은 하지 않는다 (안내 화면으로 보냄).
- 사업장마다 하루 질문 수 상한 (비용 보호): ROOMAX_AI_DAILY_LIMIT.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Lease, Property, Unit
from app.services import dashboard, fixtures, receivables, reports, routines, tax_prep, vacancy

KST = ZoneInfo("Asia/Seoul")
MODEL = os.getenv("ROOMAX_AI_MODEL", "claude-opus-5-5")
DAILY_LIMIT = int(os.getenv("ROOMAX_AI_DAILY_LIMIT", "50"))
MAX_ROUNDS = 6
MAX_HISTORY = 10
MAX_QUESTION = 1000
# 안전 분류기가 거절하면 서버가 권장 모델로 다시 시도 (Opus·Fable·Sonnet 5.5 만 지원 — Haiku 는 보내면 안 됨)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = """당신은 원룸 임대 장부 앱 ROOMAX 의 비서입니다. 임대인이 자기 장부에 대해 묻습니다.

반드시 지킬 것
1. 숫자(금액·건수·날짜·일수)는 이번 대화에서 부른 도구 결과에 그대로 있는 값만 씁니다. 직접 더하거나 빼거나 평균을 내거나 추정하지 마세요. 필요한 값이 도구 결과에 없으면 "장부에서 확인할 수 없습니다"라고 말합니다.
2. 도구 결과의 null 은 '모름'입니다. 0 이나 다른 값으로 바꾸지 말고 "자료 없음"이라고 말합니다. 은행 내역 기간(bank_data_as_of, bank_covered)이 없거나 오래되었거나 입금 검토 대기가 있으면, 미납·수입이 실제와 다를 수 있다고 함께 알립니다.
3. 장부를 바꾸는 일(입금 확정, 메시지 발송, 삭제)은 할 수 없습니다. 어느 화면에서 하면 되는지만 알려 줍니다.
4. 세금 신고액·법적 판단·독촉 여부는 정하지 않습니다. 세금은 '세무 준비' 화면의 입력자료까지만, 법은 화면의 안내 문구 수준까지만 말하고 세무사·법률 상담을 권합니다.
5. 임차인은 호실 번호로만 부릅니다 (도구에도 이름이 없습니다).
6. 장부와 관계없는 질문에는 짧게 답할 수 없다고 말합니다.

답변 형식: 한국어, 짧게. 핵심 숫자를 먼저, 그다음 주의할 점 한두 줄. 표가 필요하면 짧은 목록으로."""


def _date_prop(desc: str) -> dict:
    return {"type": "string", "description": desc + " (YYYY-MM-DD, 비우면 오늘)"}


def _tool(name: str, description: str, props: dict | None = None) -> dict:
    props = props or {}
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": props, "required": list(props),
                             "additionalProperties": False}}


TOOLS = [
    _tool("get_overview", "홈 요약: 호실 수·공실, 이번 달 청구·입금·미납·운영비·순운영수익, 은행 내역 기준 시각, "
          "확인이 필요한 항목, 오늘 납부일, 7일 안 납부 예정.", {"as_of": _date_prop("기준일")}),
    _tool("list_unpaid", "납부일이 지난 미수(호실·청구 월·납부일·청구액·입금액·남은 금액·지난 일수), 선납 잔액, 입금 검토 대기 건수.",
          {"as_of": _date_prop("기준일")}),
    _tool("get_month_report", "한 달 결산: 청구액, 확인된 월세 입금, 운영비 항목별, 순운영수익, 생활비·주인세대(제외 항목), 확정 여부.",
          {"period": {"type": "string", "description": "청구 월 YYYY-MM"}}),
    _tool("list_leases", "진행 중인 계약: 호실, 보증금, 월세, 납부일, 시작·만료일."),
    _tool("list_lease_endings", "만료가 다가오는 계약과 갱신 통지 기간(만료 6~2개월 전), 통지 기록, 돌려줄 보증금.",
          {"as_of": _date_prop("기준일")}),
    _tool("list_vacancies", "공실: 호실, 공실 시작일, 공실 일수, 직전 월세, 직전 월세 기준 손실액.", {"as_of": _date_prop("기준일")}),
    _tool("list_maintenance", "정기 점검(예정일·상태)과 진행 중인 수리(위치·품목·접수일)."),
    _tool("get_tax_prep", "귀속연도 세무 준비 자료 요약: 자료 있는 달만 더한 청구·입금·운영비, 은행 내역 없는 달, 미확정 거래, "
          "증빙 없는 운영비, 연말 보증금 합계. 세액은 없음.", {"year": {"type": "integer", "description": "귀속연도"}}),
]


class AssistantError(Exception):
    pass


class NotConfigured(AssistantError):
    pass


def configured() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _client():
    import anthropic  # 키가 없으면 불러오지도 않는다

    return anthropic.Anthropic(timeout=50.0, max_retries=1)  # Vercel 함수 60초 안에서 끝나게


# ── 도구 (읽기 전용, 이름·연락처 없음) ──────────────────────────────

def _day(value: str | None, today: date) -> date:
    if not value:
        return today
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise ValueError("날짜는 YYYY-MM-DD") from e


def _overview(session: Session, org: uuid.UUID, a: dict, today: date) -> dict:
    d = dashboard.build(session, org, _day(a.get("as_of"), today))
    return {
        "as_of": d["as_of"], "period": d["period"], "bank_data_as_of": d["bank_data_as_of"], "counts": d["counts"],
        "money": d["money"],
        "attention": [{"level": x["level"], "message": x["message"]} for x in d["attention"]],
        "due_today": [{k: x[k] for k in ("unit_no", "period", "amount", "paid", "status", "paid_at", "via")}
                      for x in d["due_today"]],
        "due_soon": d["due_soon"],
    }


def _unpaid(session: Session, org: uuid.UUID, a: dict, today: date) -> dict:
    r = receivables.compute(session, org, _day(a.get("as_of"), today))
    return {"as_of": r.as_of, "bank_data_as_of": r.bank_data_as_of, "pending_review": r.pending_review,
            "items": [{"unit_no": i.unit_no, "period": i.period, "due_date": i.due_date, "amount": i.amount,
                       "paid": i.paid, "outstanding": i.outstanding, "days_past_due": i.days_past_due} for i in r.items],
            "credits": [{"unit_no": c.unit_no, "credit": c.credit} for c in r.credits],
            "note": "입금 검토 대기가 있거나 은행 내역이 오래되면 실제로는 낸 돈일 수 있음"}


def _month(session: Session, org: uuid.UUID, a: dict, today: date) -> dict:
    return reports.monthly(session, org, a.get("period") or today.strftime("%Y-%m"))


def _leases(session: Session, org: uuid.UUID, a: dict, today: date) -> list[dict]:
    rows = session.execute(select(Lease, Unit.label).join(Unit, Lease.unit_id == Unit.id)
                           .join(Property, Unit.property_id == Property.id)
                           .where(Property.organization_id == org, Lease.status == "active")
                           .order_by(Unit.label)).all()
    return [{"unit_no": u, "deposit": le.deposit, "rent": le.rent, "due_day": le.due_day,
             "start_date": le.start_date, "end_date": le.end_date} for le, u in rows]


def _endings(session: Session, org: uuid.UUID, a: dict, today: date) -> list[dict]:
    d = dashboard.build(session, org, _day(a.get("as_of"), today))
    return [{k: v for k, v in x.items() if k != "tenant_name"} for x in d["lease_endings"]]


def _vacancies(session: Session, org: uuid.UUID, a: dict, today: date) -> dict:
    return vacancy.summary(session, org, _day(a.get("as_of"), today))


def _maintenance(session: Session, org: uuid.UUID, a: dict, today: date) -> dict:
    return {
        "routine_tasks": [{k: r[k] for k in ("title", "unit_no", "state", "next_due_on", "days_left", "last_done_on",
                                             "interval_months")} for r in routines.list_tasks(session, org, today)],
        # 수리 내용·메모는 자유 입력이라 보내지 않는다 (이름이 들어 있을 수 있음)
        "open_repairs": [{k: r[k] for k in ("unit_no", "fixture_name", "reported_on")}
                         for r in fixtures.list_repairs(session, org, status="open")],
    }


def _tax(session: Session, org: uuid.UUID, a: dict, today: date) -> dict:
    t = tax_prep.annual(session, org, int(a.get("year") or today.year), today)
    return {"year": t["year"], "notice": t["notice"], "status": t["status"],
            "totals_known_months": t["totals_known_months"], "deposits_at": t["deposits_at"],
            "deposits_total": t["deposits_total"]}


HANDLERS = {"get_overview": _overview, "list_unpaid": _unpaid, "get_month_report": _month, "list_leases": _leases,
            "list_lease_endings": _endings, "list_vacancies": _vacancies, "list_maintenance": _maintenance,
            "get_tax_prep": _tax}


def run_tool(session: Session, org: uuid.UUID, name: str, args: dict, today: date) -> tuple[str, bool]:
    """(JSON 문자열, 오류 여부)."""
    handler = HANDLERS.get(name)
    if handler is None:
        return f"알 수 없는 도구: {name}", True
    try:
        return json.dumps(handler(session, org, args or {}, today), ensure_ascii=False, default=str), False
    except (ValueError, LookupError) as e:
        return f"조회 실패: {e}", True


# ── 하루 상한 ─────────────────────────────────────────────────

def used_today(session: Session, org: uuid.UUID, today: date) -> int:
    start = datetime.combine(today, time(), KST).astimezone(timezone.utc)
    return session.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "assistant.ask", AuditLog.entity_id == str(org), AuditLog.created_at >= start)) or 0


# ── 묻기 ─────────────────────────────────────────────────────

def _history(history: list[dict]) -> list[dict]:
    """화면이 보낸 지난 대화 (글자만). 사용자 → 비서 순서가 맞는 것만 최근 것부터."""
    out: list[dict] = []
    for h in history[-MAX_HISTORY:]:
        role, text = h.get("role"), (h.get("text") or "").strip()[:4000]
        if role in ("user", "assistant") and text and (not out or out[-1]["role"] != role):
            out.append({"role": role, "content": text})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if out and out[-1]["role"] == "user":
        out.pop()
    return out


def _request_extras(model: str) -> dict:
    if model.startswith("claude-haiku"):
        return {}
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"}


def ask(session: Session, org: uuid.UUID, user_id, question: str, history: list[dict], today: date,
        client=None) -> dict:
    question = (question or "").strip()
    if not question:
        raise AssistantError("질문을 적어 주세요")
    if len(question) > MAX_QUESTION:
        raise AssistantError(f"질문은 {MAX_QUESTION}자 이하로 적어 주세요")
    if client is None:
        if not configured():
            raise NotConfigured("AI 비서가 아직 연결되지 않았습니다. 서버 환경변수 ANTHROPIC_API_KEY 를 넣어 주세요 (설정 → AI 비서 안내)")
        client = _client()
    if used_today(session, org, today) >= DAILY_LIMIT:
        raise AssistantError(f"오늘 질문 한도({DAILY_LIMIT}회)를 다 썼습니다. 내일 다시 이용해 주세요")

    messages = _history(history) + [{"role": "user", "content": f"(오늘: {today.isoformat()} KST)\n{question}"}]
    sources: list[dict] = []
    kind, answer = "unknown", ""
    for _ in range(MAX_ROUNDS):
        response = client.beta.messages.create(
            model=MODEL, max_tokens=4096, system=SYSTEM, tools=TOOLS, messages=messages,
            output_config={"effort": "low"}, cache_control={"type": "ephemeral"}, **_request_extras(MODEL))
        if response.stop_reason == "refusal":
            kind, answer = "denied", "이 질문에는 답할 수 없습니다. 장부에 관한 질문으로 다시 물어봐 주세요."
            break
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                body, is_error = run_tool(session, org, block.name, block.input, today)
                sources.append({"tool": block.name, "input": block.input, "error": is_error})
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": body, "is_error": is_error})
            messages.append({"role": "user", "content": results})
            continue
        answer = text or "답을 만들지 못했습니다. 다시 물어봐 주세요."
        if response.stop_reason == "max_tokens":
            answer += "\n\n(답이 길어 중간에 끊겼습니다.)"
        kind = "fact" if any(not s["error"] for s in sources) else "unknown"
        break
    else:
        answer = "조회를 여러 번 했지만 답을 정리하지 못했습니다. 질문을 좁혀 다시 물어봐 주세요."

    session.add(AuditLog(user_id=user_id, action="assistant.ask", entity_type="organization", entity_id=str(org),
                         detail={"kind": kind, "tools": [s["tool"] for s in sources], "model": MODEL}))  # 질문 원문은 남기지 않음
    session.commit()
    return {"answer": answer, "kind": kind, "sources": sources, "queried_at": datetime.now(timezone.utc),
            "model": MODEL, "remaining_today": max(0, DAILY_LIMIT - used_today(session, org, today))}
