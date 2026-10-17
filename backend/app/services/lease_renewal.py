"""계약 갱신 통지 기간 (주택임대차보호법 제6조·제6조의3).

- 임대인이 만료 6개월 전부터 2개월 전까지 갱신거절·조건변경 통지를 하지 않으면, 만료 때 같은 조건으로 다시
  계약한 것으로 본다 (제6조 제1항, 묵시적 갱신). 이때 존속기간은 2년 (제6조 제2항).
- 임차인의 계약갱신요구도 같은 기간에 한다 (제6조의3 제1항).

날짜는 달력 기준으로 거꾸로 센 참고값이다 (그 달에 같은 날이 없으면 말일). 통지는 상대방에게 도달해야 하므로
화면에서는 여유를 두고 보내라고 안내한다. 통지했는지는 이 앱의 '계약 만료 안내' 발송 기록(같은 만료일)으로만 판단한다.
"""
from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notification
from app.services.expenses import kst_date

NOTICE_FROM_MONTHS = 6
NOTICE_UNTIL_MONTHS = 2
LAW = "주택임대차보호법 제6조"


def months_before(d: date, months: int) -> date:
    """달력으로 months 개월 전 같은 날. 그 달에 같은 날이 없으면 그 달 말일."""
    y, m = divmod(d.year * 12 + (d.month - 1) - months, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


@dataclass(frozen=True)
class Window:
    end_date: date
    notice_from: date
    notice_until: date

    def stage(self, as_of: date) -> str:
        """early: 통지 기간 전 · open: 통지 기간 · closed: 통지 기간 지남(만료 전) · ended: 만료 지남"""
        if as_of < self.notice_from:
            return "early"
        if as_of <= self.notice_until:
            return "open"
        if as_of <= self.end_date:
            return "closed"
        return "ended"


def window(end_date: date) -> Window:
    return Window(end_date, months_before(end_date, NOTICE_FROM_MONTHS), months_before(end_date, NOTICE_UNTIL_MONTHS))


def notice_sent_on(session: Session, lease_id: uuid.UUID, end_date: date) -> date | None:
    """이 만료일을 가리키는 '계약 만료 안내'를 처음 보낸 날 (KST). 없으면 None.
    갱신으로 만료일이 바뀌면 예전 안내는 세지 않는다."""
    sent: datetime | None = session.scalar(
        select(func.min(Notification.sent_at)).where(
            Notification.lease_id == lease_id, Notification.template == "renewal_notice",
            Notification.term_end == end_date, Notification.status == "sent"))
    return kst_date(sent) if sent else None
