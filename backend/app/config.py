import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "ROOMAX_DATABASE_URL", "postgresql+psycopg://roomax:roomax@localhost:5432/roomax"
    )
    # Fernet 키: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    field_key: str = os.getenv("ROOMAX_FIELD_KEY", "")
    cors_origins: tuple[str, ...] = tuple(
        o for o in os.getenv("ROOMAX_CORS_ORIGINS", "http://localhost:3000").split(",") if o
    )


settings = Settings()
