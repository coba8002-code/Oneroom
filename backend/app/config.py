import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
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
    cors_origins: tuple[str, ...] = tuple(
        o for o in os.getenv("ROOMAX_CORS_ORIGINS", "http://localhost:3000").split(",") if o
    )


settings = Settings()
