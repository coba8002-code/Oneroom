from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import bank, charges, contracts, dashboard, expenses, onboarding, payments

app = FastAPI(title="ROOMAX API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(onboarding.router)
app.include_router(charges.router)
app.include_router(bank.router)
app.include_router(payments.router)
app.include_router(expenses.router)
app.include_router(dashboard.router)
app.include_router(contracts.router)


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok"}
