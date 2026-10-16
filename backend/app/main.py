from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import org_guard
from app.config import settings
from app.routers import auth, backups, bank, charges, contracts, dashboard, expenses, onboarding, payments

app = FastAPI(title="ROOMAX API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,  # 세션 쿠키
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],  # 백업 파일 이름을 브라우저가 읽도록
)

app.include_router(auth.router)  # 가입·로그인은 로그인 없이

# 업무 API 는 전부 로그인 필요 + organization_id 가 오면 내 사업장인지 검사 (app/auth.py)
PROTECTED = [Depends(org_guard)]
for r in (onboarding, charges, bank, payments, expenses, dashboard, contracts, backups):
    app.include_router(r.router, dependencies=PROTECTED)


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok"}
