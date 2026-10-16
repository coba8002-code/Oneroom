# ROOMAX 운영 배포 (서버 1대 · HTTPS)

서버 한 대에 `docker compose` 로 다섯 개를 띄웁니다.

```
인터넷 ──443──▶ caddy ──/api/*──▶ api (FastAPI) ──▶ db (PostgreSQL 16)
                  │                  ▲
                  └──── 그 외 ────▶ web (Next.js)
                                   backup ── 매일 03:10 KST 모든 사업장 암호화 백업
```

| 구성 | 하는 일 |
|---|---|
| `caddy` | HTTPS 인증서 자동 발급·갱신(Let's Encrypt), HTTP→HTTPS 전환, 보안 헤더(HSTS 등) |
| `web` | 화면. API 와 **같은 도메인**이라 쿠키가 같은 사이트로 동작하고 CORS 가 필요 없음 |
| `api` | 시작할 때 마이그레이션 적용. `ROOMAX_ENV=production` 이라 위험한 설정이면 **시작하지 않음** |
| `db` | 밖으로 포트를 열지 않음 |
| `backup` | `backup_cli` 를 매일 실행. 사업장마다 최근 30개, 해지된 사업장 백업은 30일 뒤 삭제 |

## 1. 준비

1. **서버**: Linux(Ubuntu 22.04/24.04 등) 1대, 메모리 2GB 이상, Docker Engine + Compose 플러그인 설치
   - 임차인 개인정보가 저장되므로 **국내 리전**을 권장합니다 (국외 리전이면 처리방침에 국외 이전 고지가 필요)
   - 방화벽에서 **80, 443(TCP·UDP)** 만 엽니다. SSH 는 관리자 IP 로 제한
2. **도메인**: DNS A 레코드(필요하면 AAAA)를 서버 IP 로. 인증서 발급 전에 반영돼 있어야 합니다
3. **메일 발송 계정 (SMTP)**: 이메일 확인·비밀번호 재설정에 필수. 업체를 정하면
   - 처리방침 '처리 위탁'에 업체명을 적고 (`frontend/app/privacy/page.tsx`)
   - 보내는 도메인에 SPF·DKIM 을 설정해야 스팸함으로 덜 갑니다

## 2. 설정

```bash
git clone <저장소> roomax && cd roomax/deploy
cp .env.example .env
chmod 600 .env
```

`.env` 에 채울 값 (설명은 파일 안 주석):

| 값 | 만드는 법 | 잃어버리면 |
|---|---|---|
| `SITE_ADDRESS` | 도메인 (`https://` 없이) | — |
| `POSTGRES_PASSWORD` | `openssl rand -hex 24` | DB 볼륨이 있으면 같은 값을 계속 써야 함 |
| `ROOMAX_FIELD_KEY` | `.env.example` 의 명령 | **저장된 연락처·계약서를 열 수 없음** — 서버 밖에 따로 보관 |
| `ROOMAX_BACKUP_PASSPHRASE` | 길고 무작위로 | **정기 백업을 열 수 없음** — 서버 밖에 따로 보관 |
| `ROOMAX_SMTP_*`, `ROOMAX_MAIL_FROM` | 메일 업체 | — |

`ROOMAX_ENV`, `ROOMAX_COOKIE_SECURE`, `ROOMAX_APP_URL`, DB 주소는 `docker-compose.yml` 이 정합니다.

## 3. 첫 실행과 확인

```bash
docker compose up -d --build
docker compose ps                       # api 가 healthy 인지
docker compose logs api | tail          # 설정 문제가 있으면 무엇을 고칠지 출력하고 멈춤
curl -I https://<도메인>/api/v1/health  # 200 + strict-transport-security 헤더
```

브라우저에서 확인할 것:

- [ ] `http://<도메인>` 이 `https://` 로 넘어감
- [ ] 회원가입 → 확인 메일이 실제로 도착하고 링크가 `https://<도메인>/verify-email?...`
- [ ] 비밀번호 찾기 메일 도착
- [ ] 설정 → 백업 내려받기 성공
- [ ] `https://<도메인>/docs` 는 404 (운영에서는 API 문서를 열지 않음)

## 4. 백업

- **정기 백업**은 `backup_files` 볼륨에 쌓입니다. 서버가 통째로 사라질 때를 대비해 **다른 곳으로 매일 복사**하세요.
  ```bash
  # 예: 매일 04:00 에 서버 밖으로 복사 (호스트 crontab)
  0 4 * * * cd /srv/roomax/deploy && mkdir -p /srv/offsite-staging && docker compose cp backup:/backups/. /srv/offsite-staging && rsync -a /srv/offsite-staging/ <원격 저장소>
  ```
- 지금 바로 한 번 백업: `docker compose exec backup python -m app.backup_cli --out /backups`
- 백업 파일은 `ROOMAX_BACKUP_PASSPHRASE` 로 암호화되어 있고 서버 키와 무관합니다. 새 서버에서 가입한 뒤
  설정 → 백업에서 복구 로 사업장 단위 복구가 됩니다.
- 계약서 원본·복구 직전 안전 백업은 `app_data` 볼륨, DB 는 `pg_data` 볼륨. **`docker compose down -v` 는 이 볼륨을 지웁니다** — 쓰지 마세요.

## 5. 업데이트

```bash
cd /srv/roomax && git pull
cd deploy && docker compose up -d --build   # api 가 시작하며 새 마이그레이션 적용
docker compose ps
```

마이그레이션이 들어간 업데이트 전에는 `docker compose exec backup python -m app.backup_cli --out /backups` 로 먼저 백업하세요.

## 6. 알아 둘 제약

- **API 워커는 1개**입니다. 로그인 실패 잠금·메일 발송 제한이 프로세스 메모리에 있어서, 워커나 서버를 늘리려면
  먼저 이 저장소를 Redis 등으로 옮겨야 합니다 (상용화 계획 Ⅵ-2-6).
- **오류 모니터링은 아직 없습니다.** 당장은 외부 가동 감시 서비스로 `https://<도메인>/api/v1/health` 를 1분마다
  확인하세요 (DB 가 끊기면 503). Sentry 같은 오류 수집 서비스를 붙이면 처리방침 위탁·국외 이전 항목을 함께 고쳐야 합니다.
- 컨테이너 로그는 `docker compose logs`. 로그에 이메일 주소·이름·전화번호는 남기지 않습니다.
