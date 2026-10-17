"""휴대폰 입금 알림 → 거래 (실시간 입금 확인).

은행 앱 알림·문자를 폰 자동화 앱(MacroDroid·단축어)이 사업장 전용 비밀 주소로 보내면
문장에서 방향·금액·입금자·시각을 읽어 거래(source='alert')로 넣고, 기존 매칭 규칙을 그대로 돌린다
(이름·별칭이 계약 1건에만 맞고 금액이 가장 오래된 미납 잔액과 같을 때만 자동 확정, 나머지는 검토 대기).

원칙
- 알림은 '들어왔다'의 증거일 뿐이다. 알림이 없다고 미납으로 보지 않는다 — 은행 내역이 어디까지 있는지는
  통장 내역 파일(source='statement')만 센다 (receivables.latest_transaction_at, reports.monthly).
- 읽기는 보수적으로. 입금/출금이 애매하거나 금액 후보가 여럿이면 거래를 만들지 않고 'unparsed' 로 남긴다.
  입금자 후보가 여럿이면 입금자를 비워 둔다 → 금액만으로는 자동 확정되지 않는다.
- 나중에 통장 내역 파일을 올리면 같은 거래(같은 계좌·방향·금액, 30분 안)는 새로 넣지 않고 합친다 (bank_import).
- 은행별 문장 형식은 실물 샘플을 받아 보강한다.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, BankAccount, BankAlert, Transaction
from app.services import matching

KST = ZoneInfo("Asia/Seoul")
MAX_TEXT = 2000
RATE_WINDOW = timedelta(minutes=10)
RATE_LIMIT = int(os.getenv("ROOMAX_ALERT_RATE_LIMIT", "30"))  # 계좌당 10분에 받는 알림 수 (주소 노출 시 대량 투입 방지)
DUPLICATE_WINDOW = timedelta(minutes=2)  # 같은 알림이 두 번 오는 경우 (문자 + 앱 푸시, 자동화 재시도)

IN_WORDS = ("입금",)
OUT_WORDS = ("출금", "지급", "결제", "인출", "자동이체")
# 입금자 후보에서 뺄 낱말 — 은행 이름·알림 상투어
NOISE = {
    "kb", "국민", "국민은행", "kb국민", "신한", "신한은행", "우리", "우리은행", "하나", "하나은행", "농협", "nh", "nh농협",
    "농협은행", "기업", "기업은행", "ibk", "카카오뱅크", "카카오", "토스", "토스뱅크", "케이뱅크", "새마을", "새마을금고",
    "우체국", "sc", "sc제일", "제일", "씨티", "수협", "부산", "부산은행", "대구", "대구은행", "im뱅크", "경남", "경남은행",
    "광주", "광주은행", "전북", "전북은행", "제주", "제주은행", "신협", "은행", "뱅크", "web발신", "web", "발신",
    "입금", "출금", "잔액", "원", "알림", "통장", "계좌", "이체", "타행", "전자금융", "모바일", "인터넷", "스마트",
    "체크", "카드", "입금했어요", "입금됐어요", "입금되었습니다", "들어왔어요", "님", "내", "받은", "돈", "보낸분",
    "입금자", "거래", "안내", "누적", "fbs", "cms", "atm", "펌뱅킹",
}


class AlertError(ValueError):
    pass


class RateLimited(AlertError):
    pass


# ── 연결 주소(토큰) ─────────────────────────────────────────
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(session: Session, account: BankAccount) -> str:
    """새 비밀 토큰을 만들고(이전 주소는 바로 무효) 원문을 한 번만 돌려준다. DB 에는 해시만."""
    token = secrets.token_urlsafe(24)
    account.alert_token_hash = _hash(token)
    account.alert_token_created_at = datetime.now(timezone.utc)
    session.add(AuditLog(action="bank_alert.token", entity_type="bank_account", entity_id=str(account.id),
                         detail={"op": "create"}))
    session.commit()
    return token


def revoke_token(session: Session, account: BankAccount) -> None:
    account.alert_token_hash = None
    account.alert_token_created_at = None
    session.add(AuditLog(action="bank_alert.token", entity_type="bank_account", entity_id=str(account.id),
                         detail={"op": "revoke"}))
    session.commit()


def account_for_token(session: Session, token: str) -> BankAccount | None:
    if not token or len(token) > 100:
        return None
    return session.scalar(select(BankAccount).where(BankAccount.alert_token_hash == _hash(token)))


# ── 문장 읽기 ──────────────────────────────────────────────
@dataclass
class Parsed:
    direction: str | None  # in | out | None(모름)
    amount: int | None
    counterparty: str | None
    balance_after: int | None
    occurred_at: datetime | None  # UTC. 문장에 시각이 없으면 받은 시각
    time_from_text: bool
    problem: str | None  # 거래를 만들지 못한 이유

    def as_dict(self) -> dict:
        d = asdict(self)
        d["occurred_at"] = self.occurred_at.isoformat() if self.occurred_at else None
        return d


_NUM = r"\d{1,3}(?:,\d{3})+|\d+"
_BALANCE = re.compile(rf"(?:잔액|잔고|누적)\s*:?\s*({_NUM})\s*원?")
_FULL_DATE = re.compile(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})")
_SHORT_DATE = re.compile(r"(?<![\d,])(\d{1,2})[/.-](\d{1,2})(?![\d,])")
_TIME = re.compile(r"(?<![\d,])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d,])")
_ACCOUNT = re.compile(r"[\d*]*\*[\d*]*|\d+(?:-[\d*]+)+")
_BRACKET = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def _int(s: str) -> int:
    return int(s.replace(",", ""))


def _direction(text: str) -> str | None:
    has_in = any(w in text for w in IN_WORDS)
    has_out = any(w in text for w in OUT_WORDS)
    if has_in == has_out:
        return None
    return "in" if has_in else "out"


def _occurred(text: str, received_at: datetime) -> tuple[datetime | None, str]:
    """문장 속 시각(KST). 연도가 없으면 받은 날짜보다 미래가 되지 않는 해로."""
    recv = received_at.astimezone(KST)
    rest = text
    y = mo = d = None
    if m := _FULL_DATE.search(rest):
        y, mo, d = (int(x) for x in m.groups())
        rest = rest[:m.start()] + " " + rest[m.end():]
    elif m := _SHORT_DATE.search(rest):
        mo, d = int(m.group(1)), int(m.group(2))
        rest = rest[:m.start()] + " " + rest[m.end():]
    t = _TIME.search(rest)
    if t:
        rest = rest[:t.start()] + " " + rest[t.end():]
    if mo is None and t is None:
        return None, rest
    try:
        hh, mm, ss = (int(t.group(1)), int(t.group(2)), int(t.group(3) or 0)) if t else (recv.hour, recv.minute, 0)
        if mo is None:
            local = recv.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        else:
            local = datetime(y or recv.year, mo, d, hh, mm, ss, tzinfo=KST)
            if y is None and local > recv + timedelta(days=1):  # 12/31 알림을 1/1 에 받은 경우
                local = local.replace(year=recv.year - 1)
        if local > recv + timedelta(minutes=10):  # 시계 차이 조금은 허용, 그 이상 미래면 날짜를 잘못 읽은 것
            return None, rest
    except ValueError:
        return None, rest
    return local.astimezone(timezone.utc), rest


def parse(text: str, received_at: datetime | None = None) -> Parsed:
    received_at = received_at or datetime.now(timezone.utc)
    flat = re.sub(r"\s+", " ", text or "").strip()
    direction = _direction(flat)

    balance = None
    rest = flat
    if m := _BALANCE.search(rest):
        balance = _int(m.group(1))
        rest = rest[:m.start()] + " " + rest[m.end():]

    occurred, rest = _occurred(rest, received_at)
    rest = _BRACKET.sub(" ", rest)
    rest = _ACCOUNT.sub(" ", rest)

    def done(amount=None, counterparty=None, problem=None) -> Parsed:
        return Parsed(direction, amount, counterparty, balance, occurred or received_at, occurred is not None, problem)

    if direction is None:
        return done(problem="입금·출금을 알 수 없음")

    # 금액: 방향 낱말 바로 앞뒤의 숫자를 먼저, 없으면 '원'·쉼표 붙은 숫자가 하나뿐일 때만
    words = "|".join(IN_WORDS if direction == "in" else OUT_WORDS)
    near = re.findall(rf"(?:{words})\s*:?\s*({_NUM})\s*원?|({_NUM})\s*원\s*(?:이|을|가)?\s*(?:{words})", rest)
    near_amounts = {_int(a or b) for a, b in near}
    if len(near_amounts) == 1:
        amount = near_amounts.pop()
    elif near_amounts:
        return done(problem="금액 후보가 여럿")
    else:
        cands = {_int(x) for x in re.findall(rf"({_NUM})\s*원", rest)} | \
                {_int(x) for x in re.findall(r"\d{1,3}(?:,\d{3})+", rest)}
        if len(cands) != 1:
            return done(problem="금액을 찾지 못함" if not cands else "금액 후보가 여럿")
        amount = cands.pop()
    if amount <= 0:
        return done(problem="금액을 찾지 못함")

    # 입금자: 숫자·은행 이름·상투어를 뺀 나머지 낱말이 정확히 하나일 때만
    names = []
    for tok in re.split(r"[\s,:;|/→>·]+", re.sub(rf"(?<![A-Za-z가-힣\d])(?:{_NUM})\s*원?", " ", rest)):
        tok = re.sub(r"(님이|님께서|님에게서|님|이가|께서)$", "", tok.strip(".!~'\"`"))
        tok = re.sub(r"(으로부터|로부터|에서|으로|로)$", "", tok)
        if not tok or tok.lower() in NOISE or any(w in tok for w in IN_WORDS + OUT_WORDS + ("잔액",)):
            continue
        if not re.fullmatch(r"[가-힣A-Za-z][가-힣A-Za-z0-9()&.\-]{1,19}", tok):  # 한 글자(조사 '을' 등)는 이름으로 보지 않음
            continue
        names.append(tok)
    counterparty = names[0] if len(set(names)) == 1 else None
    return done(amount, counterparty)


# ── 받기 ──────────────────────────────────────────────────
def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def find_same(session: Session, account_id: uuid.UUID, direction: str, amount: int, when: datetime,
              window: timedelta, *, source: str | None = None, exclude: set | None = None) -> list[Transaction]:
    q = select(Transaction).where(
        Transaction.bank_account_id == account_id, Transaction.direction == direction,
        Transaction.amount == amount,
        Transaction.occurred_at >= when - window, Transaction.occurred_at <= when + window)
    if source:
        q = q.where(Transaction.source == source)
    rows = [t for t in session.scalars(q) if not exclude or t.id not in exclude]
    return sorted(rows, key=lambda t: abs(_as_utc(t.occurred_at) - when))


def receive(session: Session, account: BankAccount, text: str, received_at: datetime | None = None) -> BankAlert:
    text = (text or "").strip()
    if not text:
        raise AlertError("알림 문장이 비어 있습니다")
    if len(text) > MAX_TEXT:
        raise AlertError(f"알림 문장이 너무 깁니다 ({MAX_TEXT}자 이하)")
    received_at = received_at or datetime.now(timezone.utc)
    recent_count = session.scalar(select(func.count()).select_from(BankAlert).where(
        BankAlert.bank_account_id == account.id, BankAlert.created_at >= received_at - RATE_WINDOW))
    if recent_count >= RATE_LIMIT:
        raise RateLimited("잠시 뒤 다시 보내 주세요 (짧은 시간에 알림이 너무 많습니다)")
    p = parse(text, received_at)
    alert = BankAlert(bank_account_id=account.id, text=text, parsed=p.as_dict(), status="unparsed")
    session.add(alert)

    if p.problem or p.amount is None:
        session.commit()
        return alert
    if p.direction == "out":  # 지출은 통장 내역 파일로 (분류할 정보가 알림에는 거의 없음)
        alert.status = "outgoing"
        session.commit()
        return alert

    when = p.occurred_at
    near = DUPLICATE_WINDOW if p.time_from_text else DUPLICATE_WINDOW + timedelta(minutes=3)  # 시각 없는 알림은 받은 시각
    for t in find_same(session, account.id, "in", p.amount, when, timedelta(minutes=30), source="alert"):
        same_name = matching.normalize_name(t.counterparty) == matching.normalize_name(p.counterparty)
        # 잔액이 같으면 같은 거래 (같은 금액이 또 들어오면 잔액이 달라진다). 잔액을 모르면 같은 이름 + 몇 분 안
        same_balance = t.balance_after is not None and t.balance_after == p.balance_after
        unknown_balance = p.balance_after is None or t.balance_after is None
        if same_balance or (same_name and unknown_balance and abs(_as_utc(t.occurred_at) - when) <= near):
            alert.status = "duplicate"
            alert.transaction_id = t.id
            session.commit()
            return alert
    # 통장 내역 파일이 먼저 들어와 있으면 (알림이 늦게 온 경우) 새로 만들지 않는다
    if earlier := find_same(session, account.id, "in", p.amount, when, timedelta(minutes=30), source="statement"):
        alert.status = "duplicate"
        alert.transaction_id = earlier[0].id
        session.commit()
        return alert

    txn = Transaction(
        bank_account_id=account.id, occurred_at=when, amount=p.amount, direction="in",
        description="입금 알림", counterparty=p.counterparty, balance_after=p.balance_after,
        fingerprint=hashlib.sha256(f"alert|{uuid.uuid4().hex}".encode()).hexdigest(), source="alert",
    )
    session.add(txn)
    session.flush()
    alert.status = "created"
    alert.transaction_id = txn.id
    session.add(AuditLog(action="bank_alert.receive", entity_type="transaction", entity_id=str(txn.id),
                         detail={"amount": p.amount, "has_counterparty": p.counterparty is not None}))
    session.flush()
    matching.run_matching(session, account.organization_id)  # commit 포함
    return alert


def recent(session: Session, organization_id: uuid.UUID, limit: int = 20) -> list[dict]:
    rows = session.execute(
        select(BankAlert, BankAccount.alias)
        .join(BankAccount, BankAlert.bank_account_id == BankAccount.id)
        .where(BankAccount.organization_id == organization_id)
        .order_by(BankAlert.created_at.desc()).limit(limit)).all()
    return [{"id": a.id, "account": alias, "text": a.text, "status": a.status, "parsed": a.parsed,
             "transaction_id": a.transaction_id, "created_at": a.created_at} for a, alias in rows]
