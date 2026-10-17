"""세금 일정 — 개인 주택임대 관련 **일반** 법정 일정.

해당 여부(사업자등록, 주택 수, 공시가격, 성실신고 대상 등)는 판정하지 않는다 (PRD §2 "검증 필요").
마감일이 주말·공휴일이면 다음 영업일로 미뤄지며, 여기서는 계산하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

NTS = "https://www.nts.go.kr"  # 국세청 (국세: 종합소득세·종합부동산세·사업장현황신고)
WETAX = "https://www.wetax.go.kr"  # 위택스 (지방세: 재산세)


@dataclass(frozen=True)
class TaxEvent:
    name: str
    start: tuple[int, int]  # (월, 일)
    end: tuple[int, int]
    note: str
    url: str


EVENTS: tuple[TaxEvent, ...] = (
    TaxEvent("사업장현황신고 (면세 개인사업자)", (1, 1), (2, 10),
             "주택임대업은 부가세 면세 — 사업자등록이 있으면 직전 연도 수입금액 신고", NTS),
    TaxEvent("종합소득세 확정신고·납부", (5, 1), (5, 31),
             "직전 연도 임대소득 포함. 성실신고확인 대상은 6월 30일까지", NTS),
    TaxEvent("재산세 1기 (건축물·주택 1/2)", (7, 16), (7, 31), "지자체 고지서 기준", WETAX),
    TaxEvent("재산세 2기 (토지·주택 1/2)", (9, 16), (9, 30), "지자체 고지서 기준", WETAX),
    TaxEvent("종합소득세 중간예납 (고지분)", (11, 1), (11, 30), "고지된 경우에만", NTS),
    TaxEvent("종합부동산세", (12, 1), (12, 15), "공시가격 합계 기준 대상자에게 고지", NTS),
)


def upcoming(as_of: date, days: int = 120) -> list[dict]:
    """진행 중이거나 days 안에 시작하는 일정."""
    out = []
    for year in (as_of.year, as_of.year + 1):
        for e in EVENTS:
            start, end = date(year, *e.start), date(year, *e.end)
            if end < as_of or (start - as_of).days > days:
                continue
            out.append({
                "name": e.name, "start": start, "end": end, "note": e.note, "url": e.url,
                "in_progress": start <= as_of <= end, "days_until_end": (end - as_of).days,
            })
    return sorted(out, key=lambda x: x["end"])
