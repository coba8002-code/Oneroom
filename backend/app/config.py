import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _env(*names: str, default: str = "") -> str:
    """앞의 이름부터 차례로 보고 처음 값이 있는 것. ROOMAX_* 를 먼저 보고, 없으면 Vercel 의 Supabase 연결
    (Storage → Connect Project)이 넣어 주는 이름을 쓴다 — 비밀값을 손으로 옮겨 적지 않아도 되게."""
    for name in names:
        if value := os.getenv(name, "").strip():
            return value
    return default


def _db_url(url: str) -> str:
    """Supabase 등이 주는 postgresql:// · postgres:// 주소를 이 앱의 드라이버(psycopg 3) 주소로 바꾼다.
    Vercel 연결이 붙이는 `supa=` 같은 libpq 가 모르는 옵션은 접속을 막으므로 뺀다."""
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            url = "postgresql+psycopg://" + url[len(scheme):]
            break
    parts = urlsplit(url)
    if parts.query:
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "supa"]
        url = urlunsplit(parts._replace(query=urlencode(query)))
    return url


@dataclass(frozen=True)
class Settings:
    # production 이면 시작할 때 위험한 설정을 검사하고, 문제가 있으면 서버를 띄우지 않는다
    env: str = os.getenv("ROOMAX_ENV", "development")
    # Vercel 의 Supabase 연결은 POSTGRES_URL(풀러 6543, 서버리스용)을 넣어 준다
    database_url: str = _db_url(_env(
        "ROOMAX_DATABASE_URL", "POSTGRES_URL", default="postgresql+psycopg://roomax:roomax@localhost:5432/roomax"
    ))
    # Fernet 키: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    field_key: str = os.getenv("ROOMAX_FIELD_KEY", "")
    # 계약서 파일 저장 위치 (암호화 저장). 운영에서는 백업 대상에 포함할 것
    upload_dir: str = os.getenv("ROOMAX_UPLOAD_DIR", "uploads")
    # 파일 보관소: local(디스크) | supabase(Storage — Vercel 등 서버리스). app/services/blobs.py
    storage: str = os.getenv("ROOMAX_STORAGE", "local")
    supabase_url: str = _env("ROOMAX_SUPABASE_URL", "SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
    supabase_service_key: str = _env("ROOMAX_SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY")
    supabase_bucket: str = os.getenv("ROOMAX_SUPABASE_BUCKET", "roomax")
    # 서버리스(Vercel 은 VERCEL=1 을 넣어 줌): DB 연결을 매 요청 새로(NullPool), 풀러 호환(prepared statement 끔)
    serverless: bool = os.getenv("ROOMAX_SERVERLESS", os.getenv("VERCEL", "")) in ("1", "true")
    # 매일 작업(정기 백업·DB 깨우기) 주소를 부를 때 쓰는 비밀값 — Vercel Cron 이 Authorization: Bearer 로 보냄
    cron_secret: str = os.getenv("ROOMAX_CRON_SECRET", os.getenv("CRON_SECRET", ""))
    # 복구 직전 자동 안전 백업을 두는 곳 (백업 파일과 같은 비밀번호로 암호화됨)
    backup_dir: str = os.getenv("ROOMAX_BACKUP_DIR", "backups")
    # NAVER CLOVA OCR (General). 둘 다 있어야 OCR 사용, 없으면 이미지만 저장하고 직접 입력
    clova_ocr_url: str = os.getenv("ROOMAX_CLOVA_OCR_URL", "")
    clova_ocr_secret: str = os.getenv("ROOMAX_CLOVA_OCR_SECRET", "")
    # 운영(HTTPS)에서는 반드시 true — 세션 쿠키를 HTTPS 로만 보냄
    # 가입: open(누구나 — 상용) | first_only(처음 한 명만 대표로 가입, 이후는 초대로만 — 개인 사용)
    signup_mode: str = os.getenv("ROOMAX_SIGNUP_MODE", "open")
    # first_only 에서 첫 대표가 될 이메일. 정해 두면 서버를 켠 뒤 남이 먼저 가입해 대표가 되는 일을 막는다
    owner_email: str = os.getenv("ROOMAX_OWNER_EMAIL", "").strip().lower()
    cookie_secure: bool = os.getenv("ROOMAX_COOKIE_SECURE", "false").lower() == "true"
    session_days: int = int(os.getenv("ROOMAX_SESSION_DAYS", "14"))
    # 메일 속 링크가 가리킬 화면 주소
    app_url: str = os.getenv("ROOMAX_APP_URL", "http://localhost:3000").rstrip("/")
    # 메일 발송: file(개발 — mail_outbox 폴더에 .eml 로 저장) | smtp(운영)
    mail_mode: str = os.getenv("ROOMAX_MAIL_MODE", "file")
    # 서버리스는 /tmp 만 쓸 수 있음 (그것도 잠깐) — 서버리스에서는 실제 메일(smtp)을 권장
    mail_outbox_dir: str = os.getenv("ROOMAX_MAIL_OUTBOX_DIR",
                                     "/tmp/mail_outbox" if os.getenv("VERCEL") == "1" else "mail_outbox")
    mail_from: str = os.getenv("ROOMAX_MAIL_FROM", "ROOMAX <no-reply@localhost>")
    smtp_host: str = os.getenv("ROOMAX_SMTP_HOST", "")
    smtp_port: int = int(os.getenv("ROOMAX_SMTP_PORT", "587"))
    smtp_user: str = os.getenv("ROOMAX_SMTP_USER", "")
    smtp_password: str = os.getenv("ROOMAX_SMTP_PASSWORD", "")
    smtp_starttls: bool = os.getenv("ROOMAX_SMTP_STARTTLS", "true").lower() == "true"
    # 카카오 알림톡 등 메시지 발송 업체 (향후 연결). 비어 있으면 '연결 전' — 문구를 복사해 직접 보냄
    alimtalk_provider: str = os.getenv("ROOMAX_ALIMTALK_PROVIDER", "")
    alimtalk_api_key: str = os.getenv("ROOMAX_ALIMTALK_API_KEY", "")
    alimtalk_sender_key: str = os.getenv("ROOMAX_ALIMTALK_SENDER_KEY", "")
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
    if s.signup_mode not in ("open", "first_only"):
        problems.append("ROOMAX_SIGNUP_MODE 는 open 또는 first_only 여야 합니다")
    # 누구나 가입하는 서버는 메일(주소 확인·비밀번호 재설정)이 꼭 필요. 개인 사용(first_only)은 서버에서
    # `python -m app.admin_cli reset-link <이메일>` 로 재설정 링크를 만들 수 있어 메일 없이도 운영 가능
    if s.signup_mode == "open" and (s.mail_mode != "smtp" or not s.smtp_host):
        problems.append("ROOMAX_MAIL_MODE=smtp 와 ROOMAX_SMTP_HOST 가 필요합니다 (file 모드는 메일을 실제로 보내지 않음)")
    if s.serverless and s.storage != "supabase":
        problems.append("서버리스(Vercel)에서는 서버 디스크에 파일을 둘 수 없습니다 — ROOMAX_STORAGE=supabase 로 설정하세요")
    if s.storage == "supabase" and not (s.supabase_url and s.supabase_service_key):
        problems.append("ROOMAX_STORAGE=supabase 인데 Supabase 주소·service 키가 없습니다 "
                        "(ROOMAX_SUPABASE_URL·ROOMAX_SUPABASE_SERVICE_KEY, 또는 Vercel Storage 에서 Connect Project)")
    if ":roomax@" in s.database_url:
        problems.append("ROOMAX_DATABASE_URL 에 개발용 비밀번호(roomax)가 들어 있습니다")
    return problems


settings = Settings()
