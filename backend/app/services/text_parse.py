"""무료 판독 — 휴대폰·PC 브라우저가 사진에서 읽은 글자(Tesseract)를 규칙으로 표로 나눈다. AI 를 쓰지 않는다.

- 사진은 기기 밖으로 나가지 않는다. 서버에는 인식된 글자만 오고, 저장하지 않는다.
- 규칙에 맞는 것만 채우고 나머지는 비운다 (CLAUDE.md 규칙 7). AI 판독보다 정확도가 낮아 표 확인이 꼭 필요하다.
- 통장: 연도까지 있는 날짜(2026.10.16 · 2026-10-16 · 2026년 10월 16일)로 거래를 나눈다. 연도 없는 날짜는 쓰지 않는다.
  입금/출금은 글자('입금'·'출금'·'지급')나 '출금 입금 잔액' 열 순서(0원이 있는 쪽)로만 정한다.
- 계약서: contract_extract 규칙(보증금·월세·관리비·납부일·기간)을 그대로 쓴다. 이름·연락처는 뽑지 않는다.
"""
from __future__ import annotations

import re
from datetime import date

from app.services import contract_extract

# 글자 인식이 연도 뒤 점을 잃는 경우(202610.16)도 받는다 — 월·일 사이 구분자는 꼭 있어야 함
DATE_TIME = re.compile(r"(?<!\d)(20\d{2})\s*[.\-/년]?\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?"
                       r"(?:\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
# 글자 인식이 쉼표를 잃거나(1945,000원) 원을 빠뜨리는(2,000,000) 경우까지. 숫자 중간에서 시작하지 않게
AMOUNT = re.compile(r"(?<![\d:.,])(\d{1,4}(?:,\d{3})+|\d+)\s*원|(?<![\d:.,])(\d{1,4}(?:,\d{3})+)(?![\d:,])")
IN_WORDS = ("입금", "받은", "받음")
OUT_WORDS = ("출금", "지급", "보낸", "이체출금", "결제")
KIND_WORDS = ("인터넷", "모바일", "스마트", "타행", "CD", "ATM", "자동이체", "체크", "펌뱅킹", "오픈뱅킹", "창구", "텔레뱅킹")
NOISE = set(IN_WORDS + OUT_WORDS + ("잔액", "거래", "금액", "원", "내역", "적요", "기재내용", "취급점", "거래후"))
WORD = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z()·.\-]{0,19}")
UNIT_NO = re.compile(r"(?<!\d)(\d{1,4})\s*호(?!\s*증)")


def _date(m: re.Match) -> str | None:
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def _amounts(block: str) -> list[tuple[int, int, int]]:
    out = []
    for m in AMOUNT.finditer(block):
        raw = m.group(1) or m.group(2)
        out.append((int(raw.replace(",", "")), m.start(), m.end()))
    return out


def parse_bank(text: str) -> tuple[list[dict], list[str]]:
    rows, notes = [], []
    marks = list(DATE_TIME.finditer(text))
    for i, m in enumerate(marks):
        block = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        amounts = _amounts(block)
        row = {"date": _date(m), "time": None, "direction": None, "amount": None, "counterparty": None,
               "description": None, "balance_after": None}
        if m.group(4) and int(m.group(4)) < 24:
            row["time"] = f"{int(m.group(4)):02d}:{m.group(5)}" + (f":{m.group(6)}" if m.group(6) else "")
        has_in, has_out = any(w in block for w in IN_WORDS), any(w in block for w in OUT_WORDS)
        values = [a for a, _, _ in amounts]
        if len(values) >= 3 and (values[0] == 0) != (values[1] == 0):  # 표: 출금 · 입금 · 잔액
            row["direction"] = "in" if values[0] == 0 else "out"
            row["amount"] = values[1] if values[0] == 0 else values[0]
            row["balance_after"] = values[2]
        else:
            if has_in != has_out:
                row["direction"] = "in" if has_in else "out"
            nonzero = [(a, s, e) for a, s, e in amounts if a > 0]
            if bal := re.search(r"잔액", block):
                after = [a for a, s, _ in nonzero if s > bal.end()]
                row["balance_after"] = after[0] if after else None
                nonzero = [x for x in nonzero if x[0] != row["balance_after"] or x[1] < bal.end()]
            if nonzero:
                row["amount"] = nonzero[0][0]
        cut = block
        for _, s, e in sorted(amounts, key=lambda x: -x[1]):
            cut = cut[:s] + " " + cut[e:]
        kinds = [w for w in KIND_WORDS if w in cut]
        words = [w for w in WORD.findall(cut) if w not in NOISE and w not in KIND_WORDS and len(w) >= 2]
        row["description"] = kinds[0] if kinds else None
        row["counterparty"] = " ".join(words[:2]) or None
        if not row["amount"] and not row["direction"]:
            continue  # 날짜만 있는 머리글·조회 기간
        missing = [k for k in ("date", "direction", "amount") if row[k] is None]
        if missing:
            notes.append(f"{len(rows) + 1}번째 줄: 확인 필요 — {', '.join(missing)}")
        rows.append(row)
    if not rows:
        notes.append("연도가 있는 거래 날짜를 찾지 못했습니다. 날짜가 보이게 캡처하거나, 은행에서 CSV·엑셀을 받아 올려 주세요")
    return rows, notes


def parse_units(text: str) -> tuple[list[dict], list[str]]:
    fields = contract_extract.extract(text)
    row = {k: None for k in ("unit_no", "tenant_name", "tenant_phone", "deposit", "rent", "mgmt_fee", "due_day",
                             "start_date", "end_date", "signed_on", "deposit_received_on")}
    for k, f in fields.items():
        row[k] = f["value"]
    if u := UNIT_NO.search(text):
        row["unit_no"] = u.group(1)
    found = [k for k, f in fields.items() if f["value"] is not None]
    row["evidence"] = " / ".join(fields[k]["evidence"] for k in found[:2] if fields[k]["evidence"])[:100] or None
    notes = ["무료 판독은 계약서 한 장씩 읽습니다. 임차인 이름·연락처는 직접 적어 주세요"]
    if not found and row["unit_no"] is None:
        return [], notes + ["보증금·월세·기간 문구를 찾지 못했습니다. 계약서 첫 장을 밝게 찍어 다시 올려 주세요"]
    return [row], notes
