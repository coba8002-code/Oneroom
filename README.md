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
| 전체 데이터 모델 마이그레이션 (PRD §5, 19개 테이블 + 입금자 별칭) | `backend/alembic/versions/` |
| 입금 매칭 실행 (확실한 것만 자동 확정, 나머지 검토 대기) | `POST /api/v1/matching/run` · `/payments` 화면 |
| 검토 대기열 · 관리자 확정 · 별칭 학습 · 확정 취소 | `GET /api/v1/matching/queue` · `POST /api/v1/transactions/{id}/decision` · `POST /api/v1/allocations/{id}/cancel` |
| 미수 현황 (은행 내역 최신 시각·검토 대기 건수 함께, 자동 독촉 없음) | `GET /api/v1/receivables` |

### 입금 매칭 규칙

| 상황 | 처리 |
|---|---|
| 입금자명(이름·별칭)이 계약 1건에만 일치 + 금액 = 가장 오래된 미납 청구 잔액 | **자동 확정** (신뢰도 95%) |
| 이름 일치, 금액이 적음 / 많음 / 미납 없음 | 검토 대기 — 부분납부 / 선납 제안 |
| 이름 일치, 금액 = 미수령 보증금 | 검토 대기 — 보증금 수령 제안 (부채, 매출 아님) |
| 입금자 미등록, 같은 금액 청구가 1건 | 검토 대기 — 금액만 일치 (50%) |
| 입금자 미등록, 같은 금액 청구가 여러 건 | 검토 대기 — 호실을 추측하지 않음 |

- 배분은 가장 오래된 미납 청구부터. 남는 돈은 선납 잔액 → 다음 달 청구 생성 시 자동 차감
- 승인할 때 "입금자명 기억"을 고르면 다음 달부터 그 이름으로 자동 확정
- 자동 확정도 취소 가능 → 청구는 미납으로, 거래는 검토 대기로 돌아감 (모든 결정은 `audit_logs`)

| 출금 자동 분류 (기억한 거래처 규칙만 자동 확정, 나머지 제안) | `POST /api/v1/expenses/classify` · `/expenses` 화면 |
| 출금 검토 대기 · 나눠서 확정(혼합 거래) · 규칙 기억 · 확정 취소 | `GET /api/v1/expenses/queue` · `POST /api/v1/transactions/{id}/expense-decision` · `…/expense-cancel` |
| 현금 지출 기록 · 월별 지출 내역 | `POST /api/v1/expenses` · `GET /api/v1/expenses?period=` |
| 기억한 거래처 규칙 조회·삭제 | `GET/DELETE /api/v1/expense-rules` |
| 월 결산 — 순운영수익(NOI) | `GET /api/v1/reports/monthly?period=` |

### 운영비 분류

| 구분 | 분류 | 순운영수익(NOI) |
|---|---|---|
| 운영비 | 공용전기 · 수도 · 청소 · 수리(호실 지정 가능) · 공용 기타 | **차감** |
| 운영비 아님 | 주인세대 · 개인 생활비 | **제외** (따로 표시) |
| 부채 | 보증금 수령 · 보증금 반환 | **제외** (따로 표시) |

- NOI = 그 달 확정된 월세 입금 − 그 달 운영비. 그 달 미확정 거래가 있으면 "확정 전 수치"로 표시
- 자동 확정은 관리자가 확정하며 **기억**한 거래처와 정확히 같을 때만. 키워드(한국전력·수도·청소·마트 등)는 제안까지만
- 혼합 거래(예: 마트 = 생활비 + 주인세대)는 금액을 나눠 확정, 합계가 거래금액과 다르면 거부. 기억하면 같은 비율로 자동 배분
- 받는 분이 임차인이고 금액이 받은 보증금과 같으면 보증금 반환 제안 → 확정 시 `deposits.returned_at` 기록

| 홈 대시보드 (호실 현황·이번 달 수지·납부 예정·계약 만료·세금 일정·확인 필요) | `GET /api/v1/dashboard?as_of=` · `/` 화면 |
| 은행 거래 가져오기 (수납 화면에서 언제든) | `GET /api/v1/bank-accounts` · `/payments` 화면 |

### 홈 대시보드

- **확인 필요**: 은행 내역 없음/7일 이상 끊김, 이번 달 청구 미생성(바로 생성 버튼), 입금·출금 검토 대기,
  납부일 지난 미수, 보증금 수령 기록 없음, 60일 안 계약 만료(반환할 보증금), 공실
- **미수 표시**: 은행 내역이 없거나 오래됐거나 입금 검토가 남아 있으면 납부일이 지나도 "미수"가 아니라
  **"확인 필요"**로 표시 (PRD §4 — 납부일 경과만으로 미납 단정 금지)
- **세금 일정**: 일반 법정 일정만(사업장현황신고·종소세·재산세·중간예납·종부세). 해당 여부는 판정하지 않음

## 다음 단계

계약서 OCR 검수 → 백업/복구.
