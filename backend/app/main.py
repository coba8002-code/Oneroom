from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.auth import org_guard
from app.config import production_problems, settings
from app.db import engine
from app.routers import (assets, assistant, auth, backups, bank, bank_alerts, charges, contracts, dashboard, expenses,
                         internal, leases, members, move_out, notifications, onboarding, payments, rent_sim, routines,
                         tax_prep, vacancy)

PRODUCTION = settings.env == "production"
if PRODUCTION and (problems := production_problems(settings)):
    raise RuntimeError("운영 설정을 고친 뒤 다시 시작하세요:\n- " + "\n- ".join(problems))

# 운영에서는 API 문서(/docs)를 열어 두지 않는다
app = FastAPI(title="ROOMAX API", version="0.2.0",
              **({"docs_url": None, "redoc_url": None, "openapi_url": None} if PRODUCTION else {}))
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,  # 세션 쿠키
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],  # 백업 파일 이름을 브라우저가 읽도록
)

app.include_router(auth.router)  # 가입·로그인은 로그인 없이
app.include_router(internal.router)  # 매일 작업 — 자체 비밀값으로 보호
app.include_router(bank_alerts.public)  # 휴대폰 입금 알림 — 계좌별 비밀 토큰으로 보호

# 업무 API 는 전부 로그인 필요 + organization_id 가 오면 내 사업장인지 검사 (app/auth.py)
PROTECTED = [Depends(org_guard)]
for r in (onboarding, charges, bank, payments, expenses, dashboard, contracts, backups, members, notifications,
          assets, move_out, leases, tax_prep, rent_sim, bank_alerts, routines, vacancy, assistant):
    app.include_router(r.router, dependencies=PROTECTED)


@app.get("/api/v1/health")
def health():
    """컨테이너 상태 검사용. DB 에 연결되지 않으면 503."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "db_unavailable"}, status_code=503)
    return {"status": "ok"}
