"""메일 발송.

- smtp: 운영. 어느 메일 서비스든 SMTP 로 연결 (AWS SES · NAVER Works · Gmail 등).
  발송 업체를 정하면 개인정보 처리방침의 '처리 위탁'에 추가할 것.
- file: 개발. 실제로 보내지 않고 ROOMAX_MAIL_OUTBOX_DIR 에 .eml 파일로 저장.
- 테스트는 get_mailer 를 MemoryMailer 로 바꿔 끼운다.

로그에는 받는 주소를 남기지 않는다 (개인정보).
"""
from __future__ import annotations

import logging
import smtplib
import ssl
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from app.config import settings

log = logging.getLogger("roomax.mail")


@dataclass
class Mail:
    to: str
    subject: str
    text: str


class FileMailer:
    mode = "file"

    def send(self, mail: Mail) -> None:
        out = Path(settings.mail_outbox_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{uuid.uuid4().hex}.eml").write_bytes(bytes(_message(mail)))


class SmtpMailer:
    mode = "smtp"

    def send(self, mail: Mail) -> None:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(_message(mail))


@dataclass
class MemoryMailer:
    mode: str = "memory"
    sent: list[Mail] = field(default_factory=list)

    def send(self, mail: Mail) -> None:
        self.sent.append(mail)


def _message(mail: Mail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg.set_content(mail.text)
    return msg


def get_mailer():
    if settings.mail_mode == "smtp":
        if not settings.smtp_host:
            raise RuntimeError("ROOMAX_MAIL_MODE=smtp 인데 ROOMAX_SMTP_HOST 가 없습니다")
        return SmtpMailer()
    return FileMailer()


def deliver(mail: Mail) -> None:
    """백그라운드에서 호출. 실패해도 요청은 이미 끝났으므로 기록만 남긴다 (주소는 남기지 않음)."""
    try:
        get_mailer().send(mail)
    except Exception as e:  # noqa: BLE001 — 어떤 발송 오류든 기록만
        log.error("mail send failed: %s (%s)", type(e).__name__, mail.subject)


# ── 메일 내용 ────────────────────────────────────────────────

def verify_mail(to: str, name: str | None, link: str) -> Mail:
    return Mail(to, "[ROOMAX] 이메일 주소를 확인해 주세요", f"""{name or ''}님, ROOMAX 가입을 환영합니다.

아래 링크를 눌러 이메일 주소 확인을 마쳐 주세요. (24시간 동안 유효)
{link}

본인이 가입하지 않았다면 이 메일을 무시하세요. 확인하지 않으면 아무 일도 일어나지 않습니다.

— ROOMAX (이 메일은 발신 전용입니다)
""")


def reset_mail(to: str, name: str | None, link: str) -> Mail:
    return Mail(to, "[ROOMAX] 비밀번호 재설정 안내", f"""{name or ''}님, 비밀번호 재설정 요청을 받았습니다.

아래 링크에서 새 비밀번호를 정하세요. (1시간 동안 유효, 한 번만 사용 가능)
{link}

재설정하면 로그인돼 있던 모든 기기에서 로그아웃됩니다.
본인이 요청하지 않았다면 이 메일을 무시하세요. 비밀번호는 바뀌지 않습니다.

— ROOMAX (이 메일은 발신 전용입니다)
""")


def invite_mail(to: str, organization_name: str, inviter: str | None, role_label: str, link: str) -> Mail:
    return Mail(to, f"[ROOMAX] {organization_name} 사업장에 초대되었습니다", f"""{inviter or '사업장 대표'}님이 ROOMAX 의 '{organization_name}' 사업장에 {role_label} 권한으로 초대했습니다.

아래 링크에서 이름과 비밀번호를 정하면 바로 참여합니다. (7일 동안 유효, 한 번만 사용 가능)
{link}

초대받을 일이 없다면 이 메일을 무시하세요. 수락하지 않으면 계정은 만들어지지 않습니다.

— ROOMAX (이 메일은 발신 전용입니다)
""")
