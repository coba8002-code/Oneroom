# ROOMAX

다가구주택(임대 원룸 9호실 + 주인세대) 관리 웹앱. 요구사항: [docs/PRD.md](./docs/PRD.md)

## 구성

```
backend/    FastAPI + SQLAlchemy + Alembic (PostgreSQL)
frontend/   Next.js + TypeScript + Tailwind (온보딩 화면)
samples/    온보딩 CSV · 은행 거래 CSV 샘플 (가상 데이터)
docs/       PRD
```

## 실행

```bash
# 1) DB
docker compose up -d db

# 2) 백엔드
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # ROOMAX_FIELD_KEY 를 새로 생성해 넣으세요
alembic upgrade head
uvicorn app.main:app --reload   # http://localhost:8000/docs

# 3) 프런트
cd ../frontend
npm install
npm run dev                     # http://localhost:3000/onboarding
```

## 지금 되는 것 (MVP 1단계)

| 기능 | API / 화면 |
|---|---|
| 건물·호실·임차인·계약·보증금 한 번에 등록 | `POST /api/v1/onboarding` · `/onboarding` 화면 |
| 온보딩 CSV 업로드 → 화면에서 검수 후 등록 (업로드만으로는 저장 안 됨) | `POST /api/v1/onboarding/csv-preview` · 샘플 `samples/onboarding_units.csv` |
| 월 청구 생성 (호실별 납부일, 말일 보정, 재실행해도 중복 없음) | `POST /api/v1/charges/generate?organization_id=…&period=2026-11` |
| 월 청구 조회 | `GET /api/v1/charges?organization_id=…&period=2026-11` |
| 은행 거래 CSV/XLSX 가져오기 (재업로드 중복 없음) | `POST /api/v1/bank-accounts/{id}/import` · 샘플 `samples/bank_transactions_sample.csv` |
| 전체 데이터 모델 마이그레이션 (PRD §5, 19개 테이블) | `backend/alembic/versions/0001_initial_schema.py` |

## 다음 단계

입금 매칭(검토 대기 큐) → 운영비 분리 → 대시보드 → 계약서 OCR 검수 → 백업/복구.
