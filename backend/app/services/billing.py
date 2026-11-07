"""요금제·정기결제 — 토스페이먼츠 빌링(카드 자동결제).

요금 (2026-11-06 소유자 확정)
- 무료: 임대 호실 3개까지 (주인세대는 세지 않음)
- 유료(basic): 임대 호실 10개까지 월 9,900원, 11번째부터 호실당 월 800원. 연 결제는 10개월 값(2개월 할인)
- 체험: 사업장을 처음 볼 때부터 30일 — 한도 없음
- 셀프 신고 도우미: 연 50,000원 (결제일부터 365일). 체험·무상 제공(comp) 중에도 쓸 수 있음

규칙
- 결제 키(ROOMAX_TOSS_CLIENT_KEY·SECRET_KEY)가 없으면 결제가 꺼진 것 — 한도 없이 모두 쓸 수 있다.
- 한도는 '새 호실 등록'만 막는다. 이미 넣은 장부는 언제나 보고 고칠 수 있다 (데이터를 볼모로 잡지 않음).
- 결제 실패 뒤 7일은 그대로 쓰고(유예), 그 뒤에는 무료 한도로 돌아간다. 해지는 남은 기간 끝까지 쓴다.
- 카드 번호·결제 응답 원문은 저장하지 않는다. 빌링키는 암호화(EncryptedString), 화면엔 카드사·끝 4자리만.
"""
from __future__ import annotations

import base64
import calendar
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog, BillingPayment, Property, Subscription, Unit

FREE_UNITS = 3
BASE_UNITS = 10
BASE_PRICE = 9_900
EXTRA_UNIT_PRICE = 800
YEARLY_MONTHS = 10  # 연 결제 = 10개월 값
TRIAL_DAYS = 30
GRACE_DAYS = 7
TAX_HELPER_PRICE = 50_000
TAX_HELPER_DAYS = 365
NOTICE = ("카드를 등록하면 매달(연 결제는 매년) 같은 날 자동으로 결제됩니다. 해지하면 다음 결제부터 멈추고 "
          "남은 기간 끝까지 쓸 수 있습니다. 금액은 결제할 때의 임대 호실 수로 셉니다.")


class BillingError(ValueError):
    pass


class QuotaError(BillingError):
    pass


def enabled() -> bool:
    return bool(settings.toss_client_key and settings.toss_secret_key)


def _aware(dt: datetime | None) -> datetime | None:  # SQLite(테스트)는 시간대 없이 돌려준다
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    y, m = dt.year + m // 12, m % 12 + 1
    return dt.replace(year=y, month=m, day=min(dt.day, calendar.monthrange(y, m)[1]))


def monthly_price(units: int) -> int:
    return BASE_PRICE + max(0, units - BASE_UNITS) * EXTRA_UNIT_PRICE


def price(units: int, cycle: str) -> int:
    return monthly_price(units) * (YEARLY_MONTHS if cycle == "yearly" else 1)


def rental_units(session: Session, organization_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(Unit).join(Property, Unit.property_id == Property.id)
                          .where(Property.organization_id == organization_id, Unit.use_type == "rental")) or 0


def get(session: Session, organization_id: uuid.UUID, now: datetime) -> Subscription:
    """사업장 요금제. 처음 보는 사업장이면 오늘부터 30일 체험으로 만든다."""
    sub = session.scalar(select(Subscription).where(Subscription.organization_id == organization_id))
    if sub is None:
        sub = Subscription(organization_id=organization_id, plan="trial", trial_ends_at=now + timedelta(days=TRIAL_DAYS),
                           customer_key=f"rmx_{uuid.uuid4().hex}")
        session.add(sub)
        session.flush()
    return sub


def effective(sub: Subscription, now: datetime) -> str:
    """지금 적용되는 상태: comp | trial | basic | grace(결제 실패 유예) | free"""
    if sub.plan == "comp":
        return "comp"
    if sub.plan == "basic" and sub.current_period_end is not None:
        if _aware(sub.current_period_end) > now:
            return "basic"
        if sub.canceled_at is None and sub.past_due_since is not None \
                and now - _aware(sub.past_due_since) < timedelta(days=GRACE_DAYS):
            return "grace"
        if sub.canceled_at is None and sub.past_due_since is None:
            return "grace"  # 갱신 결제를 아직 시도하지 않음 (매일 작업 전)
    if sub.trial_ends_at is not None and _aware(sub.trial_ends_at) > now:
        return "trial"
    return "free"


def unlimited(sub: Subscription, now: datetime) -> bool:
    return not enabled() or effective(sub, now) in ("comp", "trial", "basic", "grace")


def tax_helper_active(sub: Subscription, now: datetime, today: date) -> bool:
    if not enabled():
        return True
    return effective(sub, now) in ("comp", "trial") or (sub.tax_helper_until is not None and sub.tax_helper_until >= today)


def check_quota(session: Session, organization_id: uuid.UUID, adding: int, now: datetime) -> None:
    """임대 호실을 adding 개 더 넣어도 되는지. 무료 한도를 넘으면 QuotaError."""
    if adding <= 0 or not enabled():
        return
    sub = get(session, organization_id, now)
    if unlimited(sub, now):
        return
    have = rental_units(session, organization_id)
    if have + adding > FREE_UNITS:
        raise QuotaError(f"무료로는 임대 호실 {FREE_UNITS}개까지 넣을 수 있습니다 (지금 {have}개). "
                         f"설정 → 요금제에서 유료(월 {BASE_PRICE:,}원부터)로 바꾸면 계속 넣을 수 있습니다")


def state(session: Session, organization_id: uuid.UUID, now: datetime, today: date) -> dict:
    sub = get(session, organization_id, now)
    units = rental_units(session, organization_id)
    eff = effective(sub, now)
    payments = session.scalars(select(BillingPayment).where(BillingPayment.organization_id == organization_id)
                               .order_by(BillingPayment.created_at.desc()).limit(12)).all()
    return {
        "enabled": enabled(), "client_key": settings.toss_client_key or None, "customer_key": sub.customer_key,
        "plan": sub.plan, "effective": eff, "unlimited": unlimited(sub, now),
        "units": units, "free_units": FREE_UNITS, "over_free": max(0, units - FREE_UNITS),
        "prices": {"monthly": price(units, "monthly"), "yearly": price(units, "yearly"),
                   "base": BASE_PRICE, "base_units": BASE_UNITS, "extra_unit": EXTRA_UNIT_PRICE,
                   "tax_helper": TAX_HELPER_PRICE},
        "billing_cycle": sub.billing_cycle, "trial_ends_at": sub.trial_ends_at,
        "current_period_end": sub.current_period_end, "canceled": sub.canceled_at is not None,
        "past_due_since": sub.past_due_since, "card": sub.card_label,
        "tax_helper_until": sub.tax_helper_until, "tax_helper_active": tax_helper_active(sub, now, today),
        "notice": NOTICE,
        "payments": [{"created_at": p.created_at, "item": p.item, "amount": p.amount, "units": p.units,
                      "status": p.status, "failure": p.failure} for p in payments],
    }


# ── 토스페이먼츠 ─────────────────────────────────────────────

class TossClient:
    def __init__(self, secret_key: str, base_url: str, transport: httpx.BaseTransport | None = None):
        token = base64.b64encode(f"{secret_key}:".encode()).decode()
        self._client = httpx.Client(base_url=base_url, transport=transport, timeout=30.0,
                                    headers={"Authorization": f"Basic {token}"})

    def _post(self, path: str, body: dict, idempotency_key: str | None = None) -> dict:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        try:
            res = self._client.post(path, json=body, headers=headers)
        except httpx.HTTPError:
            raise BillingError("결제사에 연결하지 못했습니다. 잠시 뒤 다시 하세요")
        data = res.json() if res.content else {}
        if res.status_code >= 400:
            raise BillingError(str(data.get("message") or "결제사가 요청을 거절했습니다"))
        return data

    def issue_billing_key(self, auth_key: str, customer_key: str) -> dict:
        return self._post("/v1/billing/authorizations/issue", {"authKey": auth_key, "customerKey": customer_key})

    def charge(self, billing_key: str, customer_key: str, amount: int, order_id: str, order_name: str) -> dict:
        return self._post(f"/v1/billing/{billing_key}", {"customerKey": customer_key, "amount": amount,
                                                          "orderId": order_id, "orderName": order_name},
                          idempotency_key=order_id)


def client() -> TossClient:
    if not enabled():
        raise BillingError("결제가 아직 준비되지 않았습니다")
    return TossClient(settings.toss_secret_key, settings.toss_api_url)


def _card_label(data: dict) -> str | None:
    card = data.get("card") or {}
    number = str(data.get("cardNumber") or card.get("number") or "")
    company = str(data.get("cardCompany") or card.get("issuerCode") or "카드")
    last4 = "".join(ch for ch in number if ch.isdigit())[-4:]
    return f"{company} ****{last4}"[:50] if last4 else company[:50]


def register_card(session: Session, organization_id: uuid.UUID, user_id, auth_key: str, customer_key: str,
                  now: datetime, toss: TossClient | None = None) -> None:
    sub = get(session, organization_id, now)
    if not secrets.compare_digest(customer_key, sub.customer_key):
        raise BillingError("카드 등록 정보가 이 사업장과 맞지 않습니다. 처음부터 다시 하세요")
    data = (toss or client()).issue_billing_key(auth_key, customer_key)
    if not data.get("billingKey"):
        raise BillingError("카드를 등록하지 못했습니다")
    sub.billing_key, sub.card_label = data["billingKey"], _card_label(data)
    session.add(AuditLog(user_id=user_id, action="billing.card", entity_type="organization",
                         entity_id=str(organization_id), detail={"card": sub.card_label}))
    session.commit()


ITEM_NAME = {"basic_monthly": "ROOMAX 월 이용료", "basic_yearly": "ROOMAX 연 이용료", "tax_helper": "ROOMAX 셀프 신고 도우미 (1년)"}


def _charge(session: Session, sub: Subscription, item: str, amount: int, units: int | None,
            toss: TossClient) -> BillingPayment:
    if not sub.billing_key:
        raise BillingError("먼저 결제할 카드를 등록하세요")
    order_id = f"rmx-{uuid.uuid4().hex[:24]}"
    pay = BillingPayment(organization_id=sub.organization_id, order_id=order_id, item=item, amount=amount, units=units,
                         status="failed")
    try:
        data = toss.charge(sub.billing_key, sub.customer_key, amount, order_id, ITEM_NAME[item])
        if data.get("status") != "DONE":
            raise BillingError("결제가 완료되지 않았습니다")
        pay.status, pay.payment_key = "done", str(data.get("paymentKey") or "")[:200] or None
    except BillingError as e:
        pay.failure = str(e)[:300]
    session.add(pay)
    session.flush()
    return pay


def subscribe(session: Session, organization_id: uuid.UUID, user_id, cycle: str, now: datetime,
              toss: TossClient | None = None) -> dict:
    if cycle not in ("monthly", "yearly"):
        raise BillingError("결제 주기는 monthly 또는 yearly 입니다")
    sub = get(session, organization_id, now)
    if sub.plan == "comp":
        raise BillingError("무상 제공 중인 사업장입니다")
    if effective(sub, now) == "basic":
        raise BillingError("이미 유료로 쓰고 있습니다. 해지 예약을 풀려면 '해지 취소'를 누르세요")
    units = rental_units(session, organization_id)
    amount = price(units, cycle)
    pay = _charge(session, sub, f"basic_{cycle}", amount, units, toss or client())
    if pay.status != "done":
        session.commit()
        raise BillingError(f"결제하지 못했습니다: {pay.failure}")
    sub.plan, sub.billing_cycle, sub.canceled_at, sub.past_due_since = "basic", cycle, None, None
    sub.current_period_end = add_months(now, 12 if cycle == "yearly" else 1)
    session.add(AuditLog(user_id=user_id, action="billing.subscribe", entity_type="organization",
                         entity_id=str(organization_id), detail={"cycle": cycle, "amount": amount, "units": units}))
    session.commit()
    return {"amount": amount, "units": units, "current_period_end": sub.current_period_end}


def set_canceled(session: Session, organization_id: uuid.UUID, user_id, cancel: bool, now: datetime) -> None:
    sub = get(session, organization_id, now)
    if sub.plan != "basic":
        raise BillingError("유료로 쓰고 있지 않습니다")
    sub.canceled_at = now if cancel else None
    session.add(AuditLog(user_id=user_id, action="billing.cancel" if cancel else "billing.resume",
                         entity_type="organization", entity_id=str(organization_id), detail={}))
    session.commit()


def buy_tax_helper(session: Session, organization_id: uuid.UUID, user_id, now: datetime, today: date,
                   toss: TossClient | None = None) -> date:
    sub = get(session, organization_id, now)
    pay = _charge(session, sub, "tax_helper", TAX_HELPER_PRICE, None, toss or client())
    if pay.status != "done":
        session.commit()
        raise BillingError(f"결제하지 못했습니다: {pay.failure}")
    start = max(today, sub.tax_helper_until or today)
    sub.tax_helper_until = start + timedelta(days=TAX_HELPER_DAYS)
    session.add(AuditLog(user_id=user_id, action="billing.tax_helper", entity_type="organization",
                         entity_id=str(organization_id), detail={"amount": TAX_HELPER_PRICE}))
    session.commit()
    return sub.tax_helper_until


def renew_due(session: Session, now: datetime, toss: TossClient | None = None) -> dict:
    """매일 작업: 기간이 끝난 유료 구독을 다시 결제한다. 해지 예약이면 결제하지 않는다."""
    if not enabled():
        return {"skipped": "결제 꺼짐"}
    toss = toss or client()
    done = failed = 0
    subs = session.scalars(select(Subscription).where(Subscription.plan == "basic", Subscription.canceled_at.is_(None),
                                                      Subscription.current_period_end <= now)).all()
    for sub in subs:
        if sub.past_due_since is not None and now - _aware(sub.past_due_since) >= timedelta(days=GRACE_DAYS):
            continue  # 유예가 끝남 — 무료 한도로 (카드를 바꾸고 다시 '유료로'를 누르면 됨)
        cycle = sub.billing_cycle or "monthly"
        units = rental_units(session, sub.organization_id)
        pay = _charge(session, sub, f"basic_{cycle}", price(units, cycle), units, toss)
        if pay.status == "done":
            sub.current_period_end = add_months(_aware(sub.current_period_end), 12 if cycle == "yearly" else 1)
            sub.past_due_since = None
            done += 1
        else:
            sub.past_due_since = sub.past_due_since or now
            failed += 1
        session.commit()
    return {"renewed": done, "failed": failed}
