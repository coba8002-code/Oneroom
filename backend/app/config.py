import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # production 이면 시작할 때 위험한 설정을 검사하고, 문제가 있으면 서버를 띄우지 않는다
    env: str = os.getenv("ROOMAX_ENV", "development")
    database_url: str = os.getenv(
        "ROOMAX_DATABASE_URL", "postgresql+psycopg://roomax:roomax@localhost:5432/roomax"
    )
    # Fernet 키: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    field_key: str = os.getenv("ROOMAX_FIELD_KEY", "")
    # 계약서 파일 저장 위치 (암호화 저장). 운영에서는 백업 대상에 포함할 것
    upload_dir: str = os.getenv("ROOMAX_UPLOAD_DIR", "uploads")
    # 복구 직전 자동 안전 백업을 두는 곳 (백업 파일과 같은 비밀번호로 암호화됨)
    backup_dir: str = os.getenv("ROOMAX_BACKUP_DIR", "backups")
    # NAVER CLOVA OCR (General). 둘 다 있어야 OCR 사용, 없으면 이미지만 저장하고 직접 입력
    clova_ocr_url: str = os.getenv("ROOMAX_CLOVA_OCR_URL", "")
    clova_ocr_secret: str = os.getenv("ROOMAX_CLOVA_OCR_SECRET", "")
    # 운영(HTTPS)에서는 반드시 true — 세션 쿠키를 HTTPS 로만 보냄
    cookie_secure: bool = os.getenv("ROOMAX_COOKIE_SECURE", "false").lower() == "true"
    session_days: int = int(os.getenv("ROOMAX_SESSION_DAYS", "14"))
    # 메일 속 링크가 가리킬 화면 주소
    app_url: str = os.getenv("ROOMAX_APP_URL", "http://localhost:3000").rstrip("/")
    # 메일 발송: file(개발 — mail_outbox 폴더에 .eml 로 저장) | smtp(운영)
    mail_mode: str = os.getenv("ROOMAX_MAIL_MODE", "file")
    mail_outbox_dir: str = os.getenv("ROOMAX_MAIL_OUTBOX_DIR", "mail_outbox")
    mail_from: str = os.getenv("ROOMAX_MAIL_FROM", "ROOMAX <no-reply@localhost>")
    smtp_host: str = os.getenv("ROOMAX_SMTP_HOST", "")
    smtp_port: int = int(os.getenv("ROOMAX_SMTP_PORT", "587"))
    smtp_user: str = os.getenv("ROOMAX_SMTP_USER", "")
    smtp_password: str = os.getenv("ROOMAX_SMTP_PASSWORD", "")
    smtp_starttls: bool = os.getenv("ROOMAX_SMTP_STARTTLS", "true").lower() == "true"
    cors_origins: tuple[str, ...] = tuple(
        o for o in os.getenv("ROOMAX_CORS_ORIGINS", "http://localhost:3000").split(",") if o
    )


def production_problems(s: Settings) -> list[str]:
    """운영에서 그대로 두면 안 되는 설정. 비어 있으면 통과."""
    from cryptography.fernet import Fernet

    problems = []
    try:
        Fernet(s.field_key.encode())
    except Exception:
        problems.append("ROOMAX_FIELD_KEY 가 없거나 올바른 Fernet 키가 아닙니다")
    if not s.cookie_secure:
        problems.append("ROOMAX_COOKIE_SECURE=true 여야 합니다 (세션 쿠키를 HTTPS 로만)")
    if not s.app_url.startswith("https://"):
        problems.append("ROOMAX_APP_URL 은 https:// 주소여야 합니다 (메일 속 링크)")
    if s.mail_mode != "smtp" or not s.smtp_host:
        problems.append("ROOMAX_MAIL_MODE=smtp 와 ROOMAX_SMTP_HOST 가 필요합니다 (file 모드는 메일을 실제로 보내지 않음)")
    if ":roomax@" in s.database_url:
        problems.append("ROOMAX_DATABASE_URL 에 개발용 비밀번호(roomax)가 들어 있습니다")
    return problems


settings = Settings()
