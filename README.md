# ROOMAX

다가구주택(임대 원룸 9호실 + 주인세대) 관리 웹앱. 요구사항: [docs/PRD.md](./docs/PRD.md)

## 구성

```
backend/    FastAPI + SQLAlchemy + Alembic (PostgreSQL)
frontend/   Next.js + TypeScript + Tailwind
deploy/     운영 배포 (docker compose + Caddy HTTPS) — deploy/README.md
            · GitHub → Vercel + Supabase (서버 관리 없음) — deploy/vercel-supabase-guide.md
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
- **모르는 값은 '—'**: 그 달 청구를 만들기 전이면 청구액, 은행 내역 기간이 그 달과 겹치지 않으면 입금·운영비·순운영수익을
  0원이 아니라 `null`(화면 '—')로 두고 이유를 함께 표시 (월 결산 `GET /api/v1/reports/monthly` 도 같은 규칙, `charges_ready`·`bank_covered`)
- **세금 일정**: 일반 법정 일정만(사업장현황신고·종소세·재산세·중간예납·종부세). 해당 여부는 판정하지 않음

| 계약서 등록 (촬영·파일) → 클라우드 OCR → 관리자 검수 → 원장 반영 | `/contracts` 화면 · `POST /api/v1/leases/{id}/documents` · `POST /api/v1/documents/{id}/verify` |

### 계약서 OCR (NAVER CLOVA OCR)

1. NAVER Cloud 콘솔 → CLOVA OCR → **General** 도메인 생성 → API Gateway 연동 → Invoke URL · Secret Key 발급
2. `backend/.env` 에 `ROOMAX_CLOVA_OCR_URL` · `ROOMAX_CLOVA_OCR_SECRET` 입력 후 서버 재시작
3. 설정 전에도 계약서 업로드·검수는 됩니다 (값을 직접 입력)

- 계약서 원본은 서버에 **암호화 저장** (`ROOMAX_UPLOAD_DIR`, 키는 `ROOMAX_FIELD_KEY`) — 백업 대상에 포함하세요
- OCR 은 보증금 · 월세 · 납부일 · 계약 시작/종료만 **후보**로 뽑습니다 (근거 문장 표시, 이름·연락처는 뽑지 않음, 못 찾으면 빈칸)
- **검수 완료를 눌러야만** 계약(원장)에 반영되고 전후 값이 `audit_logs` 에 남습니다
- 월세·납부일 변경은 다음에 만드는 청구부터 적용
- **보증금 증액**: 검수 화면에서 보증금을 올리면 이미 받은 금액은 그대로 두고 **차액만 '받을 보증금'**으로 등록
  (보증금은 받은 묶음별로 기록 — 최초분·증액분). 증액분 입금은 매칭이 '보증금 수령'으로 제안하고, 확정하면 부채로 기록
  (월세 입금·NOI 에 안 들어감). 이미 받은 금액보다 낮추는 것은 거부 — 일부 반환은 반환 출금으로 처리.
  만기 반환은 받은 묶음 합계(최초분+증액분)와 같은 출금을 '보증금 반환'으로 제안

## 회원가입 · 로그인 · 권한

- **회원가입 = 사업장 생성**: 가입한 사람이 그 사업장의 대표(owner). 이용약관·개인정보 동의(필수), 광고성 정보 수신(선택,
  기본 꺼짐, 설정에서 철회) 일시를 기록. 약관·처리방침은 `/terms` `/privacy` (**초안 — 법률 검토 필요**)
- **로그인 세션**: HttpOnly 쿠키, DB 에는 토큰 해시만. 로그아웃·비밀번호 변경 시 서버에서 폐기. 5회 실패 시 15분 잠금
- **모든 업무 API 는 로그인 필요**, 남의 사업장 데이터는 404 (테스트가 모든 경로를 훑어 검사)
- **역할**: owner(전체) · manager(입력·수정) · viewer(조회만). 백업·복구는 owner 만
- **멤버 초대** (설정 → 멤버, 대표만): 이메일 + 권한(관리자·조회)으로 초대 → 메일 링크(7일, 1회용, DB 에는 해시만)에서 이름·비밀번호를
  정하면 그 사업장 계정이 만들어지고 로그인. 메일 링크로 왔으므로 이메일 확인 완료로 처리. 같은 주소로 다시 초대하면 이전 링크 무효,
  사업장당 하루 20통. 권한 변경은 다음 요청부터 바로 적용, 내보내면 그 계정 삭제·즉시 로그아웃(입력한 기록은 남음).
  한 계정은 한 사업장에만 속하므로 다른 사업장에 이미 가입한 이메일은 수락 단계에서 안내 (초대할 때는 가입 여부를 알려주지 않음).
  초대 이메일은 수락·취소하면 즉시, 만료되면 30일 뒤 삭제. `GET/POST /api/v1/members…` · `POST /api/v1/auth/invitation/{preview,accept}`
- **2단계 인증(MFA)**: 인증 앱 TOTP, 설정에서 켜기
- **이메일 확인 · 비밀번호 재설정**: 가입 직후 확인 메일(24시간), `/forgot-password` 에서 재설정 메일(1시간). 링크는 한 번만,
  DB 에는 토큰 해시만. 재설정 요청은 가입 여부와 관계없이 같은 응답, 주소당 시간당 3통. 재설정하면 모든 기기 로그아웃
  (2단계 인증은 유지). 미확인 계정도 이용 가능, 화면 위에 안내 배너
- **메일 발송 설정**: 개발은 `ROOMAX_MAIL_MODE=file` (보내지 않고 `mail_outbox/` 에 .eml 저장), 운영은 `smtp` +
  `ROOMAX_SMTP_HOST/PORT/USER/PASSWORD`, `ROOMAX_MAIL_FROM`, 링크 주소 `ROOMAX_APP_URL`. 업체를 정하면 처리방침 '처리 위탁'에 기재
- 운영(HTTPS)에서는 `ROOMAX_COOKIE_SECURE=true`, 화면과 API 를 같은 도메인(리버스 프록시)으로 두는 것을 권장

## 회원 탈퇴 · 사업장 해지 (`/settings` 맨 아래)

| 누가 | 지워지는 것 | 남는 것 |
|---|---|---|
| 대표(owner) = **사업장 해지** | 그 사업장의 모든 업무 데이터(임차인·계약·거래·운영비·변경 기록) + 계약서 파일 + 복구 직전 안전 백업 + 그 사업장의 **모든 계정**(세션·메일 토큰) | 개인정보 없는 파기 기록 1줄 (일시·테이블별 건수) |
| 관리자 · 조회 | 그 계정과 세션·메일 토큰, 계정 자체의 기록 | 사업장 데이터·변경 기록 (작성자 연결만 끊음) |

- 지우기 전에 무엇이 몇 건 지워지는지 미리 보여주고(`GET /api/v1/auth/account/deletion-preview`), 백업 내려받기를 권함
- 실행(`POST /api/v1/auth/account/delete`)은 **비밀번호 재확인 + 2단계 코드(켜져 있으면) + 대표는 사업장 이름 입력**
- DB 는 한 트랜잭션(실패하면 아무것도 안 지워짐), 파일은 커밋 뒤에 삭제. 다른 사업장은 건드리지 않음 (테스트·PostgreSQL 외래키로 확인)
- 서버 정기 백업(`backup_cli --keep`)에 남은 사본은 보관 개수만큼 지나면 순환 삭제 — 처리방침에 기재

## 백업 · 복구 (`/settings`)

- **백업 파일 하나** (`.roomaxbak`): 사업장의 모든 데이터 + 계약서 원본. 사용자가 정한 비밀번호로 파일 전체를
  암호화 (scrypt → AES-256-GCM). 서버 키와 무관해서 **다른 서버·새 키로도 복구**됩니다. 비밀번호를 잃으면 복구 불가
- **복구 전 확인**: 사업장 이름·백업 시각·건수·버전 호환 여부를 먼저 보여줌
- **복구 대상은 로그인한 사업장**: 다른 서버·다른 사업장에서 만든 백업도 이 사업장으로 옮겨 넣음. 계정 정보(비밀번호·세션)는
  백업에 넣지 않음
- **덮어쓰기**: 이 사업장에 이미 데이터가 있으면 사업장 이름을 입력해야 진행. 직전 상태를 `ROOMAX_BACKUP_DIR` 에 같은
  비밀번호로 자동 백업. DB 는 한 트랜잭션이라 실패하면 아무것도 바뀌지 않음. 감사 기록은 되감지 않고 보존
- **서버 정기 백업**: `ROOMAX_BACKUP_PASSPHRASE='…' python -m app.backup_cli --out /srv/roomax-backups --keep 30`
  (cron 예시는 설정 화면에). 백업 폴더는 다른 디스크·외부 저장소로 한 번 더 복사 권장
- 대시보드는 백업한 적이 없거나 30일이 지나면 알려줌

## 알림·메시지 (`/notifications`) — 알림톡은 향후 연결

- **월세 고지**(그 달 청구마다, 이미 낸 호실 제외)와 **미납 안내** 초안을 만들고, 관리자가 내용을 확인·수정해 **승인**해야 보낼 수 있음
- **미납 안내 초안은 세 조건이 모두 있을 때만**: 관리자가 정한 유예기간 경과 + 은행 내역이 유예기간 끝까지 반영 + 입금 검토 대기 없음
  (PRD §4 자동 독촉 금지). 조건이 안 되면 만들지 않고 호실별 이유를 보여줌
- **유예기간·문구는 관리자가 화면에서 정함** — 기본값 없음. 문구에 `{임차인}` `{호실}` `{청구월}` `{금액}` `{납부일}` `{미납액}` `{경과일}` 칸
- **알림톡 연결 전**: 승인한 문구를 복사해 문자·카톡으로 직접 보내고 '보냄으로 표시' (기록: 승인 시각·보낸 시각·방법)
- **연결할 때**: `backend/app/services/messaging.py` 에 업체 구현을 등록하고 `ROOMAX_ALIMTALK_PROVIDER`·`_API_KEY`·`_SENDER_KEY` 설정 →
  승인과 동시에 발송, 실패하면 이유를 남기고 직접 보냄으로 처리 가능

## 개인 사용 모드

- `ROOMAX_SIGNUP_MODE=first_only`(배포 기본값): 처음 가입한 한 명만 대표, 이후 가입 화면은 닫히고 멤버는 초대로만.
  `ROOMAX_OWNER_EMAIL` 로 첫 대표 이메일을 고정할 수 있음
- 메일 업체 없이 운영 가능 — 비밀번호를 잊으면 서버에서 `python -m app.admin_cli reset-link <이메일>` 로 재설정 링크 생성
- 무료로 올리는 두 가지
  - **GitHub → Vercel + Supabase** (서버 관리 없음, main 에 합치면 자동 배포): [deploy/vercel-supabase-guide.md](./deploy/vercel-supabase-guide.md)
  - Oracle Cloud Always Free 서울 + DuckDNS (서버 1대, docker): [deploy/README.md](./deploy/README.md) 0장

## 운영 배포 (`deploy/`)

서버 1대에 `docker compose up -d --build` — Caddy(HTTPS 자동 발급·갱신) · 화면 · API · PostgreSQL · 정기 백업.
절차와 확인 목록은 [deploy/README.md](./deploy/README.md).

- 화면과 API 를 **같은 도메인**에 (`/api/*` 만 API 로). 세션 쿠키는 `Secure` · `HttpOnly` · `SameSite=Lax`
- `ROOMAX_ENV=production` 이면 시작할 때 설정을 검사해 **위험하면 띄우지 않음**: 암호화 키 없음, 쿠키 Secure 꺼짐,
  메일 링크가 http, 메일이 file 모드(실제로 안 보냄), DB 개발용 비밀번호. 운영에서는 `/docs` 닫힘
- `GET /api/v1/health` 는 DB 까지 확인 (끊기면 503) — 컨테이너 상태 검사·외부 가동 감시에 사용
- 정기 백업 파일은 소유자만 읽기(600), 이름은 한국 시각. 해지된 사업장의 백업은 30일 뒤 자동 삭제

## Vercel + Supabase 로 돌릴 때 (`ROOMAX_SERVERLESS`·`VERCEL=1`)

- 파일(계약서 원본·정기 백업·복구 직전 안전 백업)은 **Supabase Storage 비공개 버킷**에 (`ROOMAX_STORAGE=supabase`, 서버 키는 API 에만).
  서버리스인데 `supabase` 가 아니면 시작하지 않음
- DB 는 Supabase **Transaction pooler(6543)** — 연결 풀 없이(NullPool) prepared statement 끔. 마이그레이션은 GitHub Actions
  (`.github/workflows/db-migrate.yml`, Session pooler 5432 를 시크릿으로)
- Vercel 요청 한도 4.5MB: 계약서 사진은 화면에서 줄여 올리고(`frontend/lib/image.ts`), **백업 파일은 브라우저 ↔ Storage 서명 URL 로
  직접** 주고받음 (API 를 거치지 않음). 다 쓴 임시 파일은 정기 작업이 하루 뒤 정리
- 정기 작업: Vercel Cron → `GET /api/v1/internal/cron/daily` (`Authorization: Bearer $CRON_SECRET`, 비밀값이 없으면 404) —
  DB 조회(일시정지 방지) + `ROOMAX_BACKUP_PASSPHRASE` 가 있으면 사업장별 암호화 백업. Hobby 는 정한 시각의 1시간 안에 실행
- 메일은 응답 전에 바로 보냄 (서버리스에서는 응답 뒤 작업이 끊길 수 있음)

## 화면 디자인

- 데스크톱: 남색 사이드바 + 카드형 대시보드 / 모바일: 상단 바 + 하단 탭(홈·임대료·운영비·계약·더보기)
- 글꼴 Pretendard(로컬 번들), 아이콘 lucide-react, 공통 스타일은 `frontend/app/globals.css` 의 `.card` `.btn-primary` `.field` 등
- 아직 없는 메뉴(세무, 전월세 시뮬레이션, 보고서)는 **'준비 중'** 으로만 표시

## 다음 단계

MVP 완료. 결제·요금제는 **향후로 연기** (베타 기간 무료). (2차) 문자·알림톡, 계약만료/미납 알림, 증빙·세무 준비, 전월세 시뮬레이션, AI 비서.
