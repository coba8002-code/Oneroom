# Oracle Cloud 무료 서버에 ROOMAX 올리기 (단계별)

혼자 쓰는 ROOMAX 를 **Oracle Cloud Always Free (서울)** 에 올리는 순서입니다. 처음이면 30~40분 걸립니다.
화면의 메뉴 이름은 Oracle 이 바꿀 수 있습니다 — 비슷한 이름을 찾으면 됩니다. 막히면 그 화면을 캡처해 물어보세요.

준비물: 이메일, 휴대폰, 신용카드(본인 확인용 — 무료 한도 안에서는 청구되지 않음), PC(Windows 또는 Mac)

---

## 0단계. 코드를 main 에 합치기 (1분)

서버는 GitHub 의 **main** 브랜치에서 코드를 받습니다.
[PR #1](https://github.com/coba8002-code/Oneroom/pull/1) → **Ready for review** → **Merge pull request** → **Confirm merge**

## 1단계. Oracle Cloud 가입 (10분)

1. https://www.oracle.com/cloud/free/ → **Start for free**
2. 국가: **South Korea**, 이메일 인증
3. **Home Region: `South Korea Central (Seoul)`** ← 가입 후 바꿀 수 없습니다
4. 주소·휴대폰 인증 → 카드 등록(소액 임시 승인 후 취소될 수 있음) → 가입 완료

## 2단계. 회수 방지 + 요금 안전장치 (5분)

혼자 가끔 쓰는 서버는 Oracle 이 '유휴'로 보고 회수할 수 있습니다. 아래 두 가지로 막습니다.

1. 콘솔 왼쪽 위 메뉴 → **Billing & Cost Management** → **Upgrade and Manage Payment** → **Pay As You Go** 로 전환
   (무료 한도 안에서 쓰면 요금 0원. 이 안내대로 만들면 한도 안입니다)
2. **Billing & Cost Management → Budgets → Create Budget**: 금액 `1` (USD), 알림 이메일 = 내 이메일
   → 혹시 요금이 1달러라도 생기면 메일이 옵니다

## 3단계. 서버 만들기 (5분)

1. 메뉴 → **Compute → Instances → Create instance**
2. **Image**: Change image → **Ubuntu** → `Canonical Ubuntu 24.04`
3. **Shape**: Change shape → **Ampere** → `VM.Standard.A1.Flex` → OCPU **2**, Memory **12 GB**
   (2026년 무료 한도. 이보다 크게 만들면 요금이 나옵니다)
4. **Networking**: 새 VCN·공용 서브넷 만들기(기본값), **Assign a public IPv4 address** 켜기
5. **SSH keys**: **Generate a key pair for me** → **Save private key** ← 이 파일로만 서버에 들어갑니다. 잘 보관하세요
6. **Create** → 상태가 `RUNNING` 이 되면 **Public IP address** 를 적어 둡니다 (예: `152.67.x.x`)

> "Out of capacity" 가 나오면 서울에 남은 자리가 없는 것입니다. 몇 시간 뒤 다시 시도하세요.

## 4단계. 웹 포트 열기 (3분)

1. 만든 인스턴스 화면 → **Subnet** 링크 → **Security Lists** → `Default Security List…`
2. **Add Ingress Rules** 를 두 번:
   - Source CIDR `0.0.0.0/0`, IP Protocol **TCP**, Destination Port **80**
   - Source CIDR `0.0.0.0/0`, IP Protocol **TCP**, Destination Port **443**

(서버 안쪽 방화벽은 설치 스크립트가 엽니다)

## 5단계. 무료 주소 만들기 — DuckDNS (3분)

1. https://www.duckdns.org → Google 등으로 로그인
2. 원하는 이름 입력 (예: `myroom`) → **add domain**
3. 그 줄의 **current ip** 에 3단계의 Public IP 를 넣고 **update ip**
   → 이제 `myroom.duckdns.org` 가 내 서버를 가리킵니다

## 6단계. 서버에 접속 (5분)

**Windows** (PowerShell):
```powershell
cd $HOME\Downloads                                  # 받은 키 파일이 있는 곳
icacls .\ssh-key-*.key /inheritance:r /grant:r "$($env:USERNAME):R"   # 키 파일 권한 정리 (한 번만)
ssh -i .\ssh-key-*.key ubuntu@152.67.x.x            # 3단계의 Public IP
```
**Mac** (터미널):
```bash
cd ~/Downloads && chmod 400 ssh-key-*.key
ssh -i ssh-key-*.key ubuntu@152.67.x.x
```
처음 접속할 때 `Are you sure…?` 가 나오면 `yes`.

## 7단계. 설치 스크립트 실행 (10분)

서버에 접속한 창에서:
```bash
curl -fsSL https://raw.githubusercontent.com/coba8002-code/Oneroom/main/deploy/install.sh -o install.sh
bash install.sh
```
물어보는 두 가지:
- **서비스 주소**: `myroom.duckdns.org`
- **대표(내) 이메일**: 내가 가입할 이메일 — 이 이메일로만 첫 가입이 됩니다

설치 중 화면에 **ROOMAX_FIELD_KEY** 와 **ROOMAX_BACKUP_PASSPHRASE** 가 나옵니다.
**서버 밖(비밀번호 관리자·종이)에 꼭 적어 두세요.** 잃어버리면 임차인 연락처·계약서·정기 백업을 다시 열 수 없습니다.

`✅ 설치 완료` 가 나오면 끝입니다.

## 8단계. 가입하고 쓰기

1. 휴대폰·PC 브라우저에서 `https://myroom.duckdns.org/signup` → 7단계에서 넣은 이메일로 가입
   (인증서 발급에 1~2분 — 처음에 보안 경고가 나오면 잠시 뒤 새로고침)
2. 휴대폰: 브라우저 메뉴 → **홈 화면에 추가** 하면 앱처럼 열립니다
3. 가입 후 가입 화면은 자동으로 닫힙니다. 다른 사람은 **설정 → 멤버 → 초대** 로만 들어옵니다

## 평소 관리

| 할 일 | 방법 |
|---|---|
| 백업 받아 두기 (월 1회 권장) | 설정 → **백업 파일 내려받기** → PC·클라우드 드라이브에 보관 (무료 서버는 사라질 수 있다고 보고 대비) |
| 비밀번호를 잊었을 때 | 서버 접속 후 `cd ~/roomax/deploy && sudo docker compose exec api python -m app.admin_cli reset-link 내이메일` → 나온 링크를 브라우저에 |
| 새 버전으로 업데이트 | 서버 접속 후 `bash ~/roomax/deploy/install.sh` (설정·데이터는 그대로) |
| 서버 상태 보기 | `cd ~/roomax/deploy && sudo docker compose ps` |

## 막힐 때

| 증상 | 확인할 것 |
|---|---|
| 주소로 안 열림 / 인증서 오류가 계속됨 | 4단계 보안 목록(80·443), DuckDNS 의 IP 가 서버 IP 와 같은지 — `sudo docker compose logs caddy` |
| `ssh` 가 안 됨 | 키 파일 경로·권한, `ubuntu@IP` 의 IP, 4단계와 별개로 22번 포트는 기본 열림 |
| 설치가 `API 가 준비되지 않았습니다` 로 끝남 | 화면에 나온 로그를 그대로 캡처해 보여 주세요 |
| "Out of capacity" | 몇 시간 뒤 다시 만들기 |
