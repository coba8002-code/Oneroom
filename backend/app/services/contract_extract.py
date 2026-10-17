"""OCR 글자에서 계약 값 **후보**를 뽑는다. 확정은 관리자가 한다 (PRD §6).

뽑는 것: 보증금 · 월세(차임) · 납부일 · 계약 시작 · 계약 종료
뽑지 않는 것: 이름 · 연락처 · 주민번호 등 개인정보
찾지 못하면 value=None — 추측하지 않는다. 각 값에는 근거 문장(evidence)을 붙인다.
"""
from __future__ import annotations

import re
from datetime import date

KOR_DIGIT = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
KOR_SMALL = {"십": 10, "백": 100, "천": 1000}
KOR_BIG = {"만": 10_000, "억": 100_000_000}
KOR_CHARS = "".join(KOR_DIGIT) + "".join(KOR_SMALL) + "".join(KOR_BIG)

NUM_WON = re.compile(r"[₩￦\\]\s*([\d,]{4,})|(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
KOR_WON = re.compile(rf"금\s*([{KOR_CHARS}\d,\s]+?)\s*원")
DATE = re.compile(r"(\d{2}\s?\d{2})\s*[년.]\s*(\d{1,2})\s*[월.]\s*(\d{1,2})\s*일?")
DUE_DAY = re.compile(r"매\s*월\s*(\d{1,2})\s*일")

DEPOSIT_KEYS = ("보증금",)
RENT_KEYS = ("차임", "월세", "월차임")
PERIOD_KEYS = ("임대차기간", "임대차 기간", "존속기간", "임대기간", "계약기간")
# 금액 문장의 경계. '보증금 및 차임을 아래와 같이…' 처럼 키워드가 이어 나오면 다음 키워드에서 끊는다
MONEY_KEYS = DEPOSIT_KEYS + RENT_KEYS + ("계약금", "중도금", "잔금")
NEXT_MONEY_KEY = re.compile("|".join(re.escape(k) for k in MONEY_KEYS))


def _segment(text: str, start: int, window: int) -> str:
    """start 부터 window 글자, 단 다음 금액 키워드 앞에서 끊는다."""
    seg = text[start:start + window]
    nxt = NEXT_MONEY_KEY.search(seg)
    return seg[:nxt.start()] if nxt else seg


def korean_number(s: str) -> int | None:
    """'오천만' → 50000000, '사십오만' → 450000, '5천만' → 50000000."""
    s = s.replace(",", "").replace(" ", "")
    if not s:
        return None
    total = section = num = 0
    digits = ""
    for ch in s:
        if ch.isdigit():
            digits += ch
            continue
        if digits:
            num, digits = int(digits), ""
        if ch in KOR_DIGIT:
            num = KOR_DIGIT[ch]
        elif ch in KOR_SMALL:
            section += (num or 1) * KOR_SMALL[ch]
            num = 0
        elif ch in KOR_BIG:
            section += num
            total += (section or 1) * KOR_BIG[ch]
            section = num = 0
        else:
            return None
    if digits:
        num = int(digits)
    return total + section + num


def _snippet(text: str, start: int, end: int) -> str:
    return re.sub(r"\s+", " ", text[max(0, start):min(len(text), end)]).strip()


def _money_after(text: str, keys: tuple[str, ...], window: int = 80) -> tuple[int, str] | None:
    """키워드 뒤 window 글자 안의 첫 금액. 숫자(₩·원) 우선, 없으면 한글 금액."""
    for key in keys:
        for m in re.finditer(re.escape(key), text):
            seg = _segment(text, m.end(), window)
            n = NUM_WON.search(seg)
            if n:
                value = int((n.group(1) or n.group(2)).replace(",", ""))
                if value > 0:
                    return value, _snippet(text, m.start(), m.end() + n.end())
            k = KOR_WON.search(seg)
            if k:
                value = korean_number(k.group(1))
                if value:
                    return value, _snippet(text, m.start(), m.end() + k.end())
    return None


def _date(m: re.Match) -> date | None:
    try:
        return date(int(m.group(1).replace(" ", "")), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _field(value=None, evidence: str | None = None) -> dict:
    return {"value": value, "evidence": evidence}


def extract(text: str) -> dict[str, dict]:
    fields = {k: _field() for k in ("deposit", "rent", "due_day", "start_date", "end_date")}

    if (d := _money_after(text, DEPOSIT_KEYS)):
        fields["deposit"] = _field(*d)
    if (r := _money_after(text, RENT_KEYS)):
        fields["rent"] = _field(*r)

    # 납부일: 차임 문장 근처의 '매월 n일' 우선
    for key in RENT_KEYS:
        found = None
        for m in re.finditer(re.escape(key), text):
            seg = _segment(text, m.end(), 120)
            if (dd := DUE_DAY.search(seg)) and 1 <= int(dd.group(1)) <= 31:
                found = (int(dd.group(1)), _snippet(text, m.start(), m.end() + dd.end()))
                break
        if found:
            fields["due_day"] = _field(*found)
            break
    else:
        if (dd := DUE_DAY.search(text)) and 1 <= int(dd.group(1)) <= 31:
            fields["due_day"] = _field(int(dd.group(1)), _snippet(text, dd.start() - 20, dd.end()))

    # 기간: '임대차기간' 뒤 날짜 2개 = 시작·종료, 1개면 종료만
    for key in PERIOD_KEYS:
        if (k := text.find(key)) < 0:
            continue
        window_end = k + len(key) + 200
        dates = [(m, d) for m in DATE.finditer(text, k, window_end) if (d := _date(m))]
        if len(dates) >= 2 and dates[0][1] < dates[1][1]:
            fields["start_date"] = _field(dates[0][1].isoformat(), _snippet(text, k, dates[1][0].end()))
            fields["end_date"] = _field(dates[1][1].isoformat(), _snippet(text, k, dates[1][0].end()))
        elif len(dates) == 1:
            fields["end_date"] = _field(dates[0][1].isoformat(), _snippet(text, k, dates[0][0].end()))
        break
    if fields["end_date"]["value"] is None:
        # 'YYYY년 M월 D일부터 YYYY년 M월 D일까지'
        pat = re.compile(DATE.pattern + r"\s*부터\s*" + DATE.pattern + r"\s*까지")
        for m in pat.finditer(text):
            try:
                a = date(int(m.group(1).replace(" ", "")), int(m.group(2)), int(m.group(3)))
                b = date(int(m.group(4).replace(" ", "")), int(m.group(5)), int(m.group(6)))
            except ValueError:
                continue
            if a < b:
                ev = _snippet(text, m.start(), m.end())
                fields["start_date"] = _field(a.isoformat(), ev)
                fields["end_date"] = _field(b.isoformat(), ev)
                break
    return fields
