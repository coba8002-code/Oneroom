# GitHub → Vercel + Supabase 로 ROOMAX 올리기 (무료 · 서버 관리 없음)

혼자 쓰고 테스트하는 단계용입니다. 서버에 접속할 일이 없고, **main 에 합치면 자동으로 배포**됩니다. 처음이면 40분쯤 걸립니다.
화면의 메뉴 이름은 업체가 바꿀 수 있습니다 — 비슷한 이름을 찾으면 됩니다. 막히면 그 화면을 캡처해 물어보세요.

```
휴대폰·PC ──▶ Vercel ①화면 (Next.js)  ──/api/*──▶  Vercel ②API (FastAPI, 서울 icn1)
                                                   ├──▶ Supabase PostgreSQL (서울)
                                                   └──▶ Supabase Storage (계약서 원본·정기 백업, 비공개)
GitHub Actions ── 마이그레이션(DB 표 만들기·바꾸기) ──▶ Supabase PostgreSQL
Vercel Cron   ── 매일 03시대 KST ──▶ ②API: DB 깨우기 + 암호화 정기 백업
```

준비물: GitHub 계정(이 저장소), 이메일. 신용카드는 필요 없습니다.

## 먼저 알아 둘 제약 (조사일 2026-10-17)

| 항목 | 내용 | 대비 |
|---|---|---|
| Vercel Hobby(무료) | **개인·비상업 용도만** 허용 | 상용화하면 Pro 또는 Oracle/유료 서버로 ([README.md](./README.md)) |
| 요청 크기 4.5MB | 한 번에 올리는 파일 한도 | 계약서 **사진은 화면에서 자동으로 줄여** 올림. PDF 는 4MB 이하로. 백업 파일은 Storage 와 직접 주고받아 크기 제한 없음 |
| 정기 작업 | 하루 1번, 정한 시각의 **1시간 안 아무 때나** | 정기 백업이 03:00~03:59 KST 사이에 돔 |
| Supabase Free | DB 500MB · 파일 1GB · **7일 동안 아무 요청이 없으면 일시정지** | 매일 정기 작업이 DB 를 조회해 깨워 둠. 정지되면 Supabase 화면에서 Restore 한 번 |
| Supabase Free 백업 | 자동 백업 **없음** | 앱이 매일 Storage 에 암호화 백업(30개). 같은 업체 안이므로 **월 1회 설정 → 백업 파일 내려받기** 로 PC 에도 보관 |
| 저장소가 공개(public) | GitHub Actions 로그가 누구에게나 보임 | 비밀값은 **Secrets 에만** 넣고, 로그에 비밀값·링크를 출력하는 작업을 만들지 않음 |

---

## 0단계. 코드를 main 에 합치기 (1분)

Vercel·GitHub Actions 는 **main** 브랜치를 배포합니다.
열려 있는 [PR](https://github.com/coba8002-code/Oneroom/pulls)이 있으면 → **Ready for review** → **Merge pull request** → **Confirm merge** (없으면 건너뜀)

## 1단계. 비밀값 4개 만들기 (3분)

PC 브라우저에서 아무 페이지나 열고 **F12 → Console** 탭에 아래를 붙여 넣고 Enter. 4줄이 나옵니다.

```js
const r = n => crypto.getRandomValues(new Uint8Array(n)), hex = n => [...r(n)].map(b => b.toString(16).padStart(2, "0")).join("");
console.log("ROOMAX_FIELD_KEY=" + btoa(String.fromCharCode(...r(32))).replace(/\+/g, "-").replace(/\//g, "_"));
console.log("ROOMAX_BACKUP_PASSPHRASE=" + hex(16)); console.log("CRON_SECRET=" + hex(24)); console.log("DB 비밀번호=" + hex(16));
```

(Console 에 붙여넣기가 막혀 있으면 먼저 `allow pasting` 을 입력하고 Enter)

**비밀번호 관리자나 종이에 적어 두세요.** 특히 `ROOMAX_FIELD_KEY`·`ROOMAX_BACKUP_PASSPHRASE` 를 잃으면
임차인 연락처·계약서·정기 백업을 다시 열 수 없습니다.

## 2단계. Supabase — DB 와 파일 보관소 (10분)

1. https://supabase.com → **Start your project** → GitHub 로 로그인
2. **New project**
   - Name: `roomax`
   - Database Password: 1단계의 **DB 비밀번호**
   - Region: **Northeast Asia (Seoul)** ← 나중에 못 바꿉니다
   - → **Create new project** (1~2분 대기)
3. **파일 보관소**: 왼쪽 **Storage → New bucket**
   - Name: `roomax`
   - **Public bucket: 끔** ← 반드시 꺼 두세요 (계약서·백업이 들어갑니다)
   - → Create
4. **서버용 키**: 왼쪽 아래 **Project Settings → API Keys**
   - **Secret key**(`sb_secret_…`)를 하나 만들어 복사 — 화면에 없으면 Legacy 탭의 `service_role` 키
   - 이 키는 **Vercel ②API 에만** 넣습니다. 화면(①) 설정·GitHub·채팅·캡처에 절대 넣지 마세요
   - 같은 화면(또는 **Data API**)의 **Project URL** (`https://xxxx.supabase.co`) 도 복사
5. **DB 주소 두 개**: 위쪽 **Connect** 버튼 → **Connection String** 탭
   - **Transaction pooler** (포트 **6543**) → 앱이 씀 → `[YOUR-PASSWORD]` 를 DB 비밀번호로 바꿔 적어 둠
   - **Session pooler** (포트 **5432**) → 마이그레이션이 씀 → 같은 방법으로 적어 둠
   - 둘 다 끝에 `?sslmode=require` 를 붙입니다
   - 예: `postgresql://postgres.abcd:비밀번호@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres?sslmode=require`

## 3단계. DB 표 만들기 — GitHub Actions (3분)

1. GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `ROOMAX_DATABASE_URL`
   - Secret: 2-5 의 **Session pooler(5432)** 주소
2. **Actions** 탭 → 왼쪽 **DB migrate (Supabase)** → **Run workflow** → Run
3. 1분 뒤 초록 체크 ✅ — 로그 끝에 가장 최근 버전(지금은 `0019 (head)`)이 보이면 끝

이후에는 마이그레이션이 main 에 들어올 때마다 자동으로 돕니다. (로그에는 버전 이름만 나오고 주소·비밀번호는 나오지 않습니다)

4. **Data API 잠그기 (한 번만)** — Supabase 는 `public` 표를 웹 API(anon 키)로도 열어 둡니다. 이 앱은 그 API 를 쓰지 않으므로 닫습니다.
   Supabase → **SQL Editor** → 아래를 붙여 넣고 **Run**

   ```sql
   REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
   REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
   ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
   DO $$ DECLARE t text; BEGIN
     FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
       EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
     END LOOP;
   END $$;
   ```

   앱은 표 소유자(`postgres`)로 접속하므로 영향이 없습니다. 끝나면 **Advisors → Security** 에 'RLS disabled' 경고가 없어야 합니다.

## 4단계. Vercel ② API (10분)

1. https://vercel.com → **Sign Up → Hobby** → GitHub 로 계속
2. **Add New… → Project** → `Oneroom` 저장소 **Import**
3. 설정
   - Project Name: `roomax-api-내이름` 처럼 **겹치지 않는 이름** (주소가 `https://그이름.vercel.app` 이 됩니다)
     - `roomax-api` 처럼 남이 이미 쓰는 이름이면 Vercel 이 뒤에 글자를 붙인 다른 주소를 줍니다. 배포 뒤 프로젝트의 **Domains** 에 적힌 주소가 진짜 내 주소입니다
     - `○○○.vercel.app/api/v1/health` 가 `ok` 여도 남의 앱일 수 있습니다 — 반드시 Domains 의 주소로 확인
   - **Root Directory: `backend`** (Edit 눌러 선택)
   - Framework Preset: **Other**
4. **Environment Variables** 에 아래를 하나씩 (값은 따옴표 없이)

| 이름 | 값 |
|---|---|
| `ROOMAX_ENV` | `production` |
| `ROOMAX_DATABASE_URL` | 2-5 의 **Transaction pooler(6543)** 주소 |
| `ROOMAX_STORAGE` | `supabase` |
| `ROOMAX_SUPABASE_URL` | 2-4 의 Project URL |
| `ROOMAX_SUPABASE_SERVICE_KEY` | 2-4 의 Secret key |
| `ROOMAX_SUPABASE_BUCKET` | `roomax` |
| `ROOMAX_FIELD_KEY` | 1단계 |
| `ROOMAX_BACKUP_PASSPHRASE` | 1단계 |
| `CRON_SECRET` | 1단계 |
| `ROOMAX_COOKIE_SECURE` | `true` |
| `ROOMAX_SIGNUP_MODE` | `first_only` |
| `ROOMAX_OWNER_EMAIL` | 내 이메일 — 이 이메일로만 첫 가입 |
| `ROOMAX_APP_URL` | 일단 `https://roomax.vercel.app` — 5단계 뒤 실제 화면 주소로 고침 |
| 메일 (권장, 아래 표) | |

5. **Deploy** → 끝나면 `https://roomax-api.vercel.app/api/v1/health` 를 열어 `{"status":"ok"…}` 확인

**메일 (권장)** — Vercel 에서는 서버 명령(`admin_cli reset-link`)을 쓸 수 없어서, 비밀번호를 잊으면 메일로 재설정합니다.
Gmail → Google 계정 → 보안 → **2단계 인증** 켜기 → **앱 비밀번호** 만들기 → 아래를 추가:

| 이름 | 값 |
|---|---|
| `ROOMAX_MAIL_MODE` | `smtp` |
| `ROOMAX_SMTP_HOST` / `ROOMAX_SMTP_PORT` | `smtp.gmail.com` / `587` |
| `ROOMAX_SMTP_USER` / `ROOMAX_SMTP_PASSWORD` | 내 Gmail / 앱 비밀번호(16자리) |
| `ROOMAX_MAIL_FROM` | `ROOMAX <내 Gmail>` |

**AI 비서 (선택)** — https://console.anthropic.com → 결제 수단 등록·충전 → **API Keys → Create Key** → 아래를 추가하고 Redeploy.
키는 이 칸에만 넣고 채팅·메일·화면에 붙여 넣지 마세요. 키가 없으면 AI 비서 화면에 '연결 안 됨'만 보이고 다른 기능은 그대로입니다.

| 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | 만든 키 (`sk-ant-…`) |
| `ROOMAX_AI_MODEL` | 비우면 `claude-opus-5-5`. 비용을 줄이려면 `claude-sonnet-5-5` 나 `claude-haiku-5-5` |
| `ROOMAX_AI_DAILY_LIMIT` | 사업장당 하루 질문 수 (비우면 50) — 비용 보호 |

콘솔 **Settings → Limits** 에서 월 사용 한도(예: 1만 원 남짓)를 걸어 두면 예상 밖 비용이 생기지 않습니다.

메일 없이 쓰다가 비밀번호를 잊으면: PC 에 Python 을 설치하고 이 저장소의 `backend` 에서
`ROOMAX_DATABASE_URL=…(5432 주소) ROOMAX_APP_URL=…(화면 주소) python -m app.admin_cli reset-link 내이메일` → 나온 링크를 브라우저에.

## 5단계. Vercel ① 화면 (5분)

1. Vercel → **Add New… → Project** → 같은 `Oneroom` 저장소를 다시 **Import**
2. 설정
   - Project Name: `roomax` (→ `https://roomax.vercel.app`, 이미 있으면 다른 이름)
   - **Root Directory: `frontend`**, Framework: **Next.js** (자동)
   - Environment Variables: `ROOMAX_API_ORIGIN` = 4단계의 API 주소 (`https://roomax-api.vercel.app`, 끝에 `/` 없이)
3. **Deploy**
4. 화면 주소가 4-4 에 적은 `ROOMAX_APP_URL` 과 다르면: **② API 프로젝트 → Settings → Environment Variables** 에서 고치고
   **Deployments → 맨 위 … → Redeploy** (메일 속 링크가 이 주소로 만들어집니다)

화면과 API 는 브라우저에서 보면 **같은 주소**(`roomax.vercel.app/api/…`)라 로그인 쿠키가 그대로 동작합니다.

## 6단계. 가입하고 확인

1. `https://roomax.vercel.app/signup` → 4단계의 `ROOMAX_OWNER_EMAIL` 로 가입 → 이후 가입 화면은 자동으로 닫힘
2. 휴대폰 브라우저 메뉴 → **홈 화면에 추가**
3. 확인 목록
   - [ ] 계약서 사진 등록 → 미리보기가 열림 (Supabase Storage → `roomax` → `uploads/` 에 파일이 생김)
   - [ ] 설정 → **백업 파일 내려받기** 성공
   - [ ] 다음 날 Supabase Storage → `roomax/backups/` 에 `roomax-…roomaxbak` 이 생김 (정기 백업)
   - [ ] Vercel ② API → **Settings → Cron Jobs** 에 `/api/v1/internal/cron/daily` 가 보임
   - [ ] (AI 비서를 켰다면) AI 비서 → "이번 달 미납 알려줘" → 답 아래 '근거: 미수 현황'이 보임
   - [ ] 설정 → 입금 알림 자동 연결 → 연결 주소 만들기 → 휴대폰 연결 (docs/bank-alerts-guide.md)

## 평소 관리

| 할 일 | 방법 |
|---|---|
| 업데이트 | PR 을 main 에 합치면 Vercel 이 두 프로젝트를 다시 배포, 마이그레이션은 Actions 가 적용 |
| 백업을 PC 에 (월 1회) | 설정 → **백업 파일 내려받기** |
| 비밀번호를 잊었을 때 | 로그인 화면 → 비밀번호 찾기 (메일 설정 시) |
| Supabase 가 일시정지됨 | Supabase 화면 → 프로젝트 → **Restore** |
| 사용량 확인 | Supabase → **Project Settings → Usage** (DB 500MB · Storage 1GB) |

## 막힐 때

| 증상 | 확인할 것 |
|---|---|
| ② API 배포 후 health 가 500 | Vercel ② → **Logs**. `운영 설정을 고친 뒤 다시 시작하세요` 아래 줄들이 무엇을 고칠지 알려 줍니다 |
| health 가 503 | DB 주소(6543, 비밀번호, `?sslmode=require`), Supabase 가 일시정지됐는지 |
| 화면은 열리는데 로그인·조회가 안 됨 | ① 의 `ROOMAX_API_ORIGIN` 이 ② 주소와 같은지 → 고친 뒤 ① **Redeploy** (빌드할 때 읽습니다) |
| 계약서 등록 시 "파일이 너무 큽니다" | PDF 를 4MB 이하로 (사진은 자동으로 줄어듦) |
| 계약서·백업에서 Storage 오류 | `ROOMAX_SUPABASE_*` 세 값, 버킷 이름 `roomax`, Secret key 를 넣었는지 (publishable 키가 아님) |
| Actions 마이그레이션 실패 | Secret 이 **Session pooler(5432)** 주소인지, 비밀번호 특수문자 |
