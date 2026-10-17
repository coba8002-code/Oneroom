from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

if settings.serverless:
    # 서버리스(Vercel): 요청마다 짧게 살다 사라지므로 연결을 들고 있지 않는다(NullPool).
    # Supabase 풀러(트랜잭션 모드 6543)는 prepared statement 를 못 쓰므로 psycopg 의 자동 준비를 끈다.
    engine = create_engine(settings.database_url, poolclass=NullPool, connect_args={"prepare_threshold": None})
else:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
