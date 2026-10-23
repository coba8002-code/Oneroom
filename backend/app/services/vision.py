"""사진·스캔 판독 — 계약서·호실 목록·통장 내역 사진을 표로 읽는다 (Claude API, 비전).

원칙 (CLAUDE.md 규칙 1·5·7)
- 읽기만 한다. 결과는 저장하지 않고 화면에 표로 돌려준다 — 관리자가 고치고 '넣기'를 눌러야 장부에 들어간다.
- 보이는 글자만 옮긴다. 흐리거나 잘린 칸은 null — 추측·계산·다른 줄에서 베껴 채우기 금지.
  서버도 형식(날짜·금액·납부일)을 다시 검사해 맞지 않으면 null 로 바꾸고 그 칸을 알린다.
- 사진은 서버에 저장하지 않는다 (판독에만 쓰고 버림). 감사 기록에는 종류·장수·줄 수만 남긴다.
  사진에 담긴 이름·연락처는 Anthropic(미국)으로 전송된다 — 처리방침 1.2 국외 이전 고지.
- 주민등록번호·계좌번호 전체는 읽지 않게 지시한다.
- 사업장마다 하루 판독 횟수 상한: ROOMAX_VISION_DAILY_LIMIT.
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from datetime import date, datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.services import assistant
from app.services.assistant import KST

DAILY_LIMIT = int(os.getenv("ROOMAX_VISION_DAILY_LIMIT", "30"))
MAX_FILES = 5
MAX_TOTAL_BYTES = 4_000_000  # Vercel 요청 한도 4.5MB 안
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PDF = "application/pdf"


class VisionError(Exception):
    pass


class NotConfigured(VisionError):
    pass


def configured(session: Session | None = None, org: uuid.UUID | None = None) -> bool:
    return assistant.configured(session, org)


def _nullable(kind: str, desc: str) -> dict:
    return {"type": [kind, "null"], "description": desc}


UNIT_FIELDS = {
    "unit_no": _nullable("string", "호실 번호 (예: 101, B01). 보이지 않으면 null"),
    "tenant_name": _nullable("string", "임차인 이름"),
    "tenant_phone": _nullable("string", "임차인 휴대폰 번호"),
    "deposit": _nullable("integer", "보증금 (원, 숫자만)"),
    "rent": _nullable("integer", "월세·차임 (원, 숫자만). 관리비가 따로 적혀 있으면 빼지 말고 적힌 월세만"),
    "mgmt_fee": _nullable("integer", "정액 관리비 (원). 따로 적혀 있지 않으면 null"),
    "due_day": _nullable("integer", "월세 납부일 (매월 며칠, 1~31)"),
    "start_date": _nullable("string", "계약 시작일 YYYY-MM-DD"),
    "end_date": _nullable("string", "계약 종료일 YYYY-MM-DD"),
    "signed_on": _nullable("string", "계약서 작성일 YYYY-MM-DD"),
    "deposit_received_on": _nullable("string", "보증금(잔금) 받은 날 YYYY-MM-DD — 적혀 있을 때만"),
    "evidence": {"type": "string", "description": "이 줄의 값을 읽은 근거 (사진 몇 번째·어느 부분, 20자 안팎)"},
}
BANK_FIELDS = {
    "date": _nullable("string", "거래일 YYYY-MM-DD"),
    "time": _nullable("string", "거래 시각 HH:MM 또는 HH:MM:SS — 보이지 않으면 null"),
    "direction": _nullable("string", "in(입금) 또는 out(출금·지급)"),
    "amount": _nullable("integer", "거래 금액 (원, 숫자만)"),
    "counterparty": _nullable("string", "보낸 사람·받는 사람·기재내용"),
    "description": _nullable("string", "적요·거래 구분 (예: 인터넷, 타행CD)"),
    "balance_after": _nullable("integer", "거래 후 잔액 (원)"),
}


def _schema(row_fields: dict) -> dict:
    row = {"type": "object", "properties": row_fields, "required": list(row_fields), "additionalProperties": False}
    return {"type": "object", "additionalProperties": False, "required": ["rows", "notes"],
            "properties": {"rows": {"type": "array", "items": row},
                           "notes": {"type": "array", "items": {"type": "string"},
                                     "description": "읽지 못한 부분·의심스러운 칸 안내 (짧게)"}}}


COMMON = """당신은 임대 장부 앱에 넣을 자료를 사진에서 옮겨 적는 판독기입니다.
반드시 지킬 것
1. 사진에 보이는 글자만 옮깁니다. 흐리거나 잘리거나 가려진 칸은 null 로 둡니다. 추측·계산·평균·다른 줄에서 베껴 채우기 금지.
2. 금액은 원 단위 정수로 (예: '오백만원', '5,000,000' → 5000000, '45만' → 450000). 날짜는 YYYY-MM-DD.
   연도가 두 자리면 20xx 로. 연도가 아예 없으면 그 칸은 null.
3. 주민등록번호, 계좌번호 전체, 카드번호는 어디에도 적지 않습니다.
4. 읽기 어려웠던 부분은 notes 에 짧게 적습니다."""

UNITS_PROMPT = COMMON + """
할 일: 임대차 계약서, 호실·임차인 목록, 임대관리 앱 화면 캡처에서 '호실별 계약' 한 줄씩 뽑습니다.
- 한 호실은 한 줄. 같은 호실이 여러 사진에 나오면 한 줄로 합칩니다 (값이 서로 다르면 notes 에 적고 null).
- 계약서 한 장이면 보통 한 줄입니다. 공인중개사·임대인 정보는 뽑지 않습니다.
- 공실로 표시된 호실은 unit_no 만 적고 나머지는 null."""

BANK_PROMPT = COMMON + """
할 일: 은행 앱·인터넷뱅킹 거래내역 캡처나 통장 사진에서 거래를 한 줄씩 옮깁니다.
- 화면에 보이는 순서대로. 입금/출금 구분은 '입금·받은금액'이면 in, '출금·지급·보낸금액'이면 out.
- 합계·소계·잔액만 있는 줄, 광고·안내 문구는 빼세요."""


def _content(files: list[tuple[bytes, str]], prompt: str) -> list[dict]:
    blocks: list[dict] = []
    for i, (raw, media_type) in enumerate(files, 1):
        data = base64.standard_b64encode(raw).decode()
        kind = "document" if media_type == PDF else "image"
        blocks.append({"type": "text", "text": f"사진 {i}"})
        blocks.append({"type": kind, "source": {"type": "base64", "media_type": media_type, "data": data}})
    blocks.append({"type": "text", "text": prompt})
    return blocks


def check_files(files: list[tuple[bytes, str]]) -> None:
    if not files:
        raise VisionError("사진이나 PDF 를 하나 이상 올려 주세요")
    if len(files) > MAX_FILES:
        raise VisionError(f"한 번에 {MAX_FILES}장까지 올릴 수 있습니다")
    if sum(len(r) for r, _ in files) > MAX_TOTAL_BYTES:
        raise VisionError("파일이 너무 큽니다 (모두 합쳐 4MB 이하). 사진 수를 줄여 나눠 올려 주세요")
    for _, t in files:
        if t not in IMAGE_TYPES and t != PDF:
            raise VisionError("JPG·PNG·WEBP 사진이나 PDF 만 읽을 수 있습니다")


def used_today(session: Session, org: uuid.UUID, today: date) -> int:
    start = datetime.combine(today, time(), KST).astimezone(timezone.utc)
    return session.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "vision.read", AuditLog.entity_id == str(org), AuditLog.created_at >= start)) or 0


def _call(client, prompt: str, files, schema: dict) -> dict:
    response = client.beta.messages.create(
        model=assistant.MODEL, max_tokens=16000, system=prompt,
        messages=[{"role": "user", "content": _content(files, "위 자료를 규칙대로 옮겨 주세요.")}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        **assistant._request_extras(assistant.MODEL))
    if response.stop_reason == "refusal":
        raise VisionError("이 자료는 읽을 수 없습니다. 계약서·목록·거래내역 사진인지 확인해 주세요")
    if response.stop_reason == "max_tokens":
        raise VisionError("내용이 너무 많아 다 읽지 못했습니다. 사진을 나눠 올려 주세요")
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise VisionError("판독 결과를 해석하지 못했습니다. 다시 시도해 주세요") from e


# ── 서버 쪽 검사: 형식이 틀린 값은 null 로 바꾸고 알린다 (규칙 7) ──

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def _date(v) -> str | None:
    if not isinstance(v, str) or not DATE_RE.match(v.strip()):
        return None
    try:
        return date.fromisoformat(v.strip()).isoformat()
    except ValueError:
        return None


def _money(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100_000_000_000 else None


def _text(v, limit: int) -> str | None:
    return (v.strip()[:limit] or None) if isinstance(v, str) else None


def _clock(v) -> str | None:
    """'9:05' → '09:05'. 형식이 아니면 None."""
    if not isinstance(v, str) or not TIME_RE.match(v.strip()):
        return None
    h, rest = v.strip().split(":", 1)
    return f"{int(h):02d}:{rest}" if int(h) < 24 else None


def clean_units(rows: list[dict]) -> tuple[list[dict], list[str]]:
    out, notes = [], []
    for i, r in enumerate(rows, 1):
        row = {
            "unit_no": _text(r.get("unit_no"), 20), "tenant_name": _text(r.get("tenant_name"), 100),
            "tenant_phone": _text(r.get("tenant_phone"), 30),
            "deposit": _money(r.get("deposit")), "rent": _money(r.get("rent")), "mgmt_fee": _money(r.get("mgmt_fee")),
            "due_day": r.get("due_day") if isinstance(r.get("due_day"), int) and 1 <= r["due_day"] <= 31 else None,
            "start_date": _date(r.get("start_date")), "end_date": _date(r.get("end_date")),
            "signed_on": _date(r.get("signed_on")), "deposit_received_on": _date(r.get("deposit_received_on")),
            "evidence": _text(r.get("evidence"), 100),
        }
        dropped = [k for k in UNIT_FIELDS if k != "evidence" and r.get(k) not in (None, "") and row[k] is None]
        if dropped:
            notes.append(f"{i}번째 줄: 형식이 맞지 않아 비운 칸 — {', '.join(dropped)}")
        if any(v is not None for k, v in row.items() if k != "evidence"):
            out.append(row)
    return out, notes


def clean_bank(rows: list[dict]) -> tuple[list[dict], list[str]]:
    out, notes = [], []
    for i, r in enumerate(rows, 1):
        t = r.get("time")
        row = {"date": _date(r.get("date")),
               "time": _clock(t),
               "direction": r.get("direction") if r.get("direction") in ("in", "out") else None,
               "amount": _money(r.get("amount")) or None,
               "counterparty": _text(r.get("counterparty"), 200), "description": _text(r.get("description"), 500),
               "balance_after": _money(r.get("balance_after"))}
        missing = [k for k in ("date", "direction", "amount") if row[k] is None]
        if missing:
            notes.append(f"{i}번째 줄: 확인 필요 — {', '.join(missing)}")
        out.append(row)
    return out, notes


def read(session: Session, org: uuid.UUID, user_id, kind: str, files: list[tuple[bytes, str]], today: date,
         client=None) -> dict:
    """kind: 'units' | 'bank'. 저장하지 않고 표만 돌려준다."""
    if kind not in ("units", "bank"):
        raise VisionError("알 수 없는 판독 종류입니다")
    check_files(files)
    if client is None:
        if not (key := assistant.api_key(session, org)):
            raise NotConfigured("사진 판독이 아직 연결되지 않았습니다. 설정 → 'AI 연결'에서 Claude API 키를 넣어 주세요")
        client = assistant._client(key)
    if used_today(session, org, today) >= DAILY_LIMIT:
        raise VisionError(f"오늘 사진 판독 한도({DAILY_LIMIT}회)를 다 썼습니다. 내일 다시 이용해 주세요")
    prompt, fields, clean = (UNITS_PROMPT, UNIT_FIELDS, clean_units) if kind == "units" \
        else (BANK_PROMPT, BANK_FIELDS, clean_bank)
    result = _call(client, prompt, files, _schema(fields))
    rows, notes = clean([r for r in result.get("rows", []) if isinstance(r, dict)])
    notes = [n for n in result.get("notes", []) if isinstance(n, str)][:20] + notes
    session.add(AuditLog(user_id=user_id, action="vision.read", entity_type="organization", entity_id=str(org),
                         detail={"kind": kind, "files": len(files), "rows": len(rows), "model": assistant.MODEL}))
    session.commit()
    return {"kind": kind, "rows": rows, "notes": notes, "model": assistant.MODEL,
            "read_at": datetime.now(timezone.utc), "remaining_today": max(0, DAILY_LIMIT - used_today(session, org, today))}
