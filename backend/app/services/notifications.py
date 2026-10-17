"""임차인 메시지 (월세 고지 · 미납 안내 · 계약 만료 안내).

규칙 (CLAUDE.md 절대 규칙 2 — 자동 독촉 금지):
- 시스템은 '초안'만 만든다. 관리자가 승인(approved_at)해야 보낼 수 있다.
- 미납 안내 초안은 세 가지가 모두 있을 때만: 관리자가 정한 유예기간이 지났고, 은행 내역이 유예기간 끝까지
  반영돼 있고, 입금 검토 대기가 없다. 하나라도 없으면 만들지 않고 이유를 돌려준다.
- 유예기간·문구는 관리자가 정한다. 기본값을 두지 않는다 (비어 있으면 그 종류의 초안을 만들지 않음).
- 계약 만료 안내는 갱신 통지 기간(만료 6개월~2개월 전, 주임법 §6) 안에서만 만든다. 갱신 거절·조건 변경 같은
  내용은 관리자가 정한 문구 그대로 — 시스템이 정하지 않는다.
- 발송 업체가 연결되기 전에는 승인 후 문구를 복사해 직접 보내고 '직접 보냄'으로 표시한다.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Charge, Lease, Notification, NotificationSetting, Property, Tenant, Unit
from app.services import lease_renewal, ledger, messaging, receivables
from app.services.expenses import kst_date

KINDS = ("rent_notice", "overdue_notice", "renewal_notice")
VARIABLES = {
    "임차인": "임차인 이름", "호실": "호실 번호", "청구월": "예: 2026-11", "금액": "그 달 월세 (원)",
    "납부일": "예: 11월 25일", "미납액": "아직 안 낸 금액 (원)", "경과일": "납부일에서 지난 날 수",
}
RENEWAL_VARIABLES = {
    "임차인": "임차인 이름", "호실": "호실 번호", "월세": "지금 월세 (원)", "보증금": "계약 보증금 (원)",
    "계약시작일": "예: 2025년 9월 1일", "만료일": "예: 2027년 8월 31일", "통지마감일": "만료 2개월 전 날",
}
VAR_RE = re.compile(r"\{([^{}]+)\}")
MAX_GRACE = 60


class NotifyError(Exception):
    pass


def unknown_variables(template: str, known: dict[str, str] = VARIABLES) -> list[str]:
    return sorted({v for v in VAR_RE.findall(template) if v not in known})


def get_settings(session: Session, organization_id: uuid.UUID) -> NotificationSetting:
    row = session.scalar(select(NotificationSetting).where(NotificationSetting.organization_id == organization_id))
    return row or NotificationSetting(organization_id=organization_id)


def save_settings(session: Session, organization_id: uuid.UUID, *, grace_days: int | None,
                  rent_template: str | None, overdue_template: str | None,
                  renewal_template: str | None = None) -> NotificationSetting:
    if grace_days is not None and not (0 <= grace_days <= MAX_GRACE):
        raise NotifyError(f"유예기간은 0~{MAX_GRACE}일로 정하세요")
    for label, t, known in (("월세 고지", rent_template, VARIABLES), ("미납 안내", overdue_template, VARIABLES),
                            ("계약 만료 안내", renewal_template, RENEWAL_VARIABLES)):
        if t and (bad := unknown_variables(t, known)):
            raise NotifyError(f"{label} 문구에 모르는 칸이 있습니다: " + ", ".join("{" + b + "}" for b in bad))
    row = session.scalar(select(NotificationSetting).where(NotificationSetting.organization_id == organization_id))
    if row is None:
        row = NotificationSetting(organization_id=organization_id)
        session.add(row)
    row.grace_days = grace_days
    row.rent_template = (rent_template or "").strip() or None
    row.overdue_template = (overdue_template or "").strip() or None
    row.renewal_template = (renewal_template or "").strip() or None
    row.updated_at = datetime.now(timezone.utc)
    session.add(AuditLog(action="notification.settings", entity_type="organization", entity_id=str(organization_id),
                         detail={"grace_days": grace_days, "rent_template": bool(row.rent_template),
                                 "overdue_template": bool(row.overdue_template),
                                 "renewal_template": bool(row.renewal_template)}))
    session.commit()
    return row


def render(template: str, ctx: dict[str, str]) -> str:
    return VAR_RE.sub(lambda m: ctx.get(m.group(1), m.group(0)), template)


def _charges(session: Session, organization_id: uuid.UUID):
    return (select(Charge, Lease, Unit.label, Tenant)
            .join(Lease, Charge.lease_id == Lease.id).join(Unit, Lease.unit_id == Unit.id)
            .join(Property, Unit.property_id == Property.id).join(Tenant, Lease.tenant_id == Tenant.id)
            .where(Property.organization_id == organization_id))


def _ctx(session: Session, charge: Charge, unit_no: str, tenant: Tenant, as_of: date | None = None) -> dict[str, str]:
    outstanding = charge.amount - ledger.paid_amount(session, charge.id)
    return {"임차인": tenant.name, "호실": unit_no, "청구월": charge.period, "금액": f"{charge.amount:,}",
            "납부일": f"{charge.due_date.month}월 {charge.due_date.day}일", "미납액": f"{outstanding:,}",
            "경과일": str(max(0, ((as_of or charge.due_date) - charge.due_date).days))}


def _exists(session: Session, charge_id: uuid.UUID, kind: str) -> bool:
    return session.scalar(select(Notification.id).where(
        Notification.charge_id == charge_id, Notification.template == kind,
        Notification.status.in_(("draft", "approved", "sent")))) is not None


def _new(session: Session, organization_id, kind, charge, lease, tenant, body) -> Notification:
    n = Notification(organization_id=organization_id, tenant_id=tenant.id, lease_id=lease.id, charge_id=charge.id,
                     channel="alimtalk", template=kind, body=body, status="draft")
    session.add(n)
    return n


def make_rent_notices(session: Session, organization_id: uuid.UUID, period: str) -> dict:
    """그 달 청구마다 월세 고지 초안. 이미 낸 청구·이미 만든 초안은 건너뛴다."""
    cfg = get_settings(session, organization_id)
    if not cfg.rent_template:
        raise NotifyError("월세 고지 문구를 먼저 정하세요 (알림 설정)")
    rows = session.execute(_charges(session, organization_id).where(Charge.period == period)).all()
    if not rows:
        raise NotifyError(f"{period} 청구가 없습니다. 청구를 먼저 만드세요")
    created, skipped = 0, []
    for charge, lease, unit_no, tenant in rows:
        if charge.status in ("paid", "waived"):
            skipped.append(f"{unit_no} 이미 납부")
        elif _exists(session, charge.id, "rent_notice"):
            skipped.append(f"{unit_no} 이미 만든 고지 있음")
        else:
            _new(session, organization_id, "rent_notice", charge, lease, tenant,
                 render(cfg.rent_template, _ctx(session, charge, unit_no, tenant)))
            created += 1
    session.commit()
    return {"created": created, "skipped": skipped}


def make_overdue_notices(session: Session, organization_id: uuid.UUID, as_of: date) -> dict:
    """미납 안내 초안 — 유예기간 경과 + 은행 내역이 유예기간 끝까지 + 입금 검토 대기 없음, 셋 다일 때만."""
    cfg = get_settings(session, organization_id)
    if cfg.grace_days is None or not cfg.overdue_template:
        raise NotifyError("유예기간과 미납 안내 문구를 먼저 정하세요 (알림 설정)")
    pending = receivables.unconfirmed_count(session, organization_id, "in")
    if pending:
        raise NotifyError(f"입금 검토 대기 {pending}건을 먼저 확정하세요 — 실제로는 낸 돈일 수 있습니다")
    latest = receivables.latest_transaction_at(session, organization_id)
    if latest is None:
        raise NotifyError("은행 거래내역이 없습니다. 최신 내역을 가져온 뒤 만드세요")
    bank_until = kst_date(latest)
    rows = session.execute(_charges(session, organization_id).where(
        Charge.status.in_(("open", "partial")), Charge.due_date < as_of)).all()
    created, skipped = 0, []
    for charge, lease, unit_no, tenant in rows:
        if charge.amount - ledger.paid_amount(session, charge.id) <= 0:
            continue
        grace_end = charge.due_date + timedelta(days=cfg.grace_days)
        if as_of <= grace_end:
            skipped.append(f"{unit_no} {charge.period} 유예기간 중 ({grace_end.isoformat()}까지)")
        elif bank_until < grace_end:
            skipped.append(f"{unit_no} {charge.period} 은행 내역이 {bank_until.isoformat()}까지라 유예기간 끝까지 확인 안 됨")
        elif _exists(session, charge.id, "overdue_notice"):
            skipped.append(f"{unit_no} {charge.period} 이미 만든 안내 있음")
        else:
            _new(session, organization_id, "overdue_notice", charge, lease, tenant,
                 render(cfg.overdue_template, _ctx(session, charge, unit_no, tenant, as_of)))
            created += 1
    session.commit()
    return {"created": created, "skipped": skipped}


def _korean(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


def make_renewal_notices(session: Session, organization_id: uuid.UUID, as_of: date) -> dict:
    """계약 만료 안내 초안 — as_of 가 그 계약의 갱신 통지 기간(만료 6개월~2개월 전) 안일 때만."""
    cfg = get_settings(session, organization_id)
    if not cfg.renewal_template:
        raise NotifyError("계약 만료 안내 문구를 먼저 정하세요 (알림 설정)")
    rows = session.execute(
        select(Lease, Unit.label, Tenant).join(Unit, Lease.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id).join(Tenant, Lease.tenant_id == Tenant.id)
        .where(Property.organization_id == organization_id, Lease.status == "active")
        .order_by(Unit.label)).all()
    created, skipped = 0, []
    for lease, unit_no, tenant in rows:
        if lease.end_date is None:
            skipped.append(f"{unit_no} 만료일 없음")
            continue
        w = lease_renewal.window(lease.end_date)
        stage = w.stage(as_of)
        if stage == "early":
            continue  # 아직 먼 계약은 목록을 어지럽히지 않게 조용히 건너뛴다
        if stage != "open":
            skipped.append(f"{unit_no} 통지 기간({w.notice_until.isoformat()}까지)이 지남 — 만료 {lease.end_date.isoformat()}")
            continue
        if session.scalar(select(Notification.id).where(
                Notification.lease_id == lease.id, Notification.template == "renewal_notice",
                Notification.term_end == lease.end_date,
                Notification.status.in_(("draft", "approved", "sent", "failed")))) is not None:
            skipped.append(f"{unit_no} 이번 만료({lease.end_date.isoformat()}) 안내를 이미 만듦")
            continue
        ctx = {"임차인": tenant.name, "호실": unit_no, "월세": f"{lease.rent:,}", "보증금": f"{lease.deposit:,}",
               "계약시작일": _korean(lease.start_date), "만료일": _korean(lease.end_date),
               "통지마감일": _korean(w.notice_until)}
        session.add(Notification(organization_id=organization_id, tenant_id=tenant.id, lease_id=lease.id,
                                 term_end=lease.end_date, channel="alimtalk", template="renewal_notice",
                                 body=render(cfg.renewal_template, ctx), status="draft"))
        created += 1
    session.commit()
    return {"created": created, "skipped": skipped}


def get(session: Session, organization_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
    n = session.get(Notification, notification_id)
    if n is None or n.organization_id != organization_id:
        raise LookupError("메시지를 찾을 수 없습니다")
    return n


def edit(session: Session, n: Notification, body: str) -> Notification:
    if n.status != "draft":
        raise NotifyError("초안만 고칠 수 있습니다")
    if not body.strip():
        raise NotifyError("내용이 비었습니다")
    n.body = body.strip()
    session.commit()
    return n


def approve(session: Session, n: Notification, user_id: uuid.UUID) -> Notification:
    """승인. 업체가 연결돼 있으면 바로 보내고, 아니면 '승인됨(직접 보내기 대기)'으로 둔다."""
    if n.status != "draft":
        raise NotifyError("초안만 승인할 수 있습니다")
    n.status, n.approved_at = "approved", datetime.now(timezone.utc)
    session.add(AuditLog(user_id=user_id, action="notification.approve", entity_type="notification",
                         entity_id=str(n.id), detail={"template": n.template}))
    provider = messaging.get_provider()
    if provider is not None:
        tenant = session.get(Tenant, n.tenant_id)
        try:
            if not tenant or not tenant.phone:
                raise messaging.SendError("임차인 연락처가 없습니다")
            provider.send(messaging.OutgoingMessage(phone=tenant.phone, body=n.body, template=n.template))
            n.status, n.sent_at, n.sent_via, n.error = "sent", datetime.now(timezone.utc), provider.name, None
        except messaging.SendError as e:
            n.status, n.error = "failed", str(e)[:500]
    session.commit()
    return n


def mark_sent(session: Session, n: Notification, user_id: uuid.UUID) -> Notification:
    """연결 전: 관리자가 문구를 복사해 직접 보낸 뒤 표시한다. 승인 없이는 안 됨."""
    if n.approved_at is None or n.status not in ("approved", "failed"):
        raise NotifyError("승인한 메시지만 '보냄'으로 표시할 수 있습니다")
    n.status, n.sent_at, n.sent_via = "sent", datetime.now(timezone.utc), "manual"
    session.add(AuditLog(user_id=user_id, action="notification.mark_sent", entity_type="notification",
                         entity_id=str(n.id), detail={"via": "manual"}))
    session.commit()
    return n


def discard(session: Session, n: Notification, user_id: uuid.UUID) -> Notification:
    if n.status not in ("draft", "approved", "failed"):
        raise NotifyError("이미 보낸 메시지는 버릴 수 없습니다")
    n.status = "discarded"
    session.add(AuditLog(user_id=user_id, action="notification.discard", entity_type="notification",
                         entity_id=str(n.id), detail={"template": n.template}))
    session.commit()
    return n


def listing(session: Session, organization_id: uuid.UUID) -> list[dict]:
    rows = session.execute(
        select(Notification, Tenant.name, Tenant.phone, Unit.label, Charge.period)
        .outerjoin(Tenant, Notification.tenant_id == Tenant.id)
        .outerjoin(Lease, Notification.lease_id == Lease.id).outerjoin(Unit, Lease.unit_id == Unit.id)
        .outerjoin(Charge, Notification.charge_id == Charge.id)
        .where(Notification.organization_id == organization_id, Notification.status != "discarded")
        .order_by(Notification.created_at.desc())).all()
    return [{"id": str(n.id), "kind": n.template, "status": n.status, "body": n.body, "tenant_name": name,
             "phone": phone, "unit_no": unit_no, "period": period, "created_at": n.created_at,
             "lease_end": n.term_end, "approved_at": n.approved_at, "sent_at": n.sent_at,
             "sent_via": n.sent_via, "error": n.error}
            for n, name, phone, unit_no, period in rows]
