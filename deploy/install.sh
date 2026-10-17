#!/usr/bin/env bash
# ROOMAX 무료 서버 설치 (Oracle Cloud Ubuntu 22.04/24.04 · ARM/x86)
#
#   curl -fsSL https://raw.githubusercontent.com/coba8002-code/Oneroom/main/deploy/install.sh -o install.sh
#   bash install.sh
#
# 하는 일: Docker 설치 → 서버 방화벽 80/443 열기 → 코드 내려받기 → 비밀값 자동 생성(.env) → 실행
# 다시 실행해도 됩니다 (이미 있는 .env 는 덮어쓰지 않고, 코드만 최신으로 받아 다시 띄움).
set -euo pipefail

REPO="${ROOMAX_REPO:-https://github.com/coba8002-code/Oneroom.git}"
BRANCH="${ROOMAX_BRANCH:-main}"
DIR="${ROOMAX_DIR:-$HOME/roomax}"
SKIP_SYSTEM="${ROOMAX_INSTALL_SKIP_SYSTEM:-}"  # 시험용: 1 이면 Docker 설치·방화벽 단계를 건너뜀

say() { printf '\n\033[1;34m▶ %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }
rand_hex() { openssl rand -hex "$1"; }
fernet_key() { python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())'; }

# ── 1. Docker · 방화벽 ─────────────────────────────────────────
if [ -z "$SKIP_SYSTEM" ]; then
  say "1/5 Docker 설치"
  if ! command -v docker >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2 git openssl python3 iptables-persistent
    sudo systemctl enable --now docker
  fi
  sudo usermod -aG docker "$USER" || true

  say "2/5 서버 방화벽에서 80·443 열기 (Oracle Ubuntu 이미지는 기본으로 막혀 있음)"
  open_port() {  # Oracle 이미지는 마지막 쪽에 REJECT 규칙이 있어 그 앞(6번째)에 넣는다. 규칙이 적으면 맨 앞에
    sudo iptables -C INPUT -p "$1" --dport "$2" -j ACCEPT 2>/dev/null && return
    sudo iptables -I INPUT 6 -p "$1" --dport "$2" -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 1 -p "$1" --dport "$2" -j ACCEPT
  }
  open_port tcp 80; open_port tcp 443; open_port udp 443
  sudo netfilter-persistent save >/dev/null 2>&1 || true
  echo "   ※ Oracle 웹 콘솔의 '보안 목록(Security List)'에서도 TCP 80·443 수신을 열어야 합니다 (안내서 3단계)"
fi
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"

# ── 2. 코드 ───────────────────────────────────────────────────
say "3/5 코드 내려받기 ($BRANCH)"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q "$BRANCH" && git -C "$DIR" pull -q --ff-only origin "$BRANCH"
else
  git clone -q -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR/deploy"

# ── 3. 설정 (.env) ────────────────────────────────────────────
say "4/5 설정"
if [ -f .env ]; then
  echo "   이미 있는 .env 를 그대로 씁니다 (바꾸려면 nano $DIR/deploy/.env)"
else
  SITE="${ROOMAX_SITE_ADDRESS:-}"; OWNER="${ROOMAX_OWNER_EMAIL:-}"
  [ -n "$SITE" ] || read -rp "   서비스 주소 (예: myroom.duckdns.org, https:// 없이): " SITE
  [ -n "$OWNER" ] || read -rp "   대표(내) 이메일 — 이 이메일로만 첫 가입 가능: " OWNER
  SITE="${SITE#https://}"; SITE="${SITE#http://}"; SITE="${SITE%/}"
  [[ "$SITE" == *.* || "$SITE" == "localhost" ]] || die "주소가 올바르지 않습니다: $SITE"
  [[ "$OWNER" == *@*.* ]] || die "이메일이 올바르지 않습니다: $OWNER"

  FIELD_KEY="$(fernet_key)"; BACKUP_PASS="$(rand_hex 16)"
  sed -e "s|^SITE_ADDRESS=.*|SITE_ADDRESS=$SITE|" \
      -e "s|^ACME_EMAIL=.*|ACME_EMAIL=$OWNER|" \
      -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand_hex 24)|" \
      -e "s|^ROOMAX_FIELD_KEY=.*|ROOMAX_FIELD_KEY=$FIELD_KEY|" \
      -e "s|^ROOMAX_OWNER_EMAIL=.*|ROOMAX_OWNER_EMAIL=$OWNER|" \
      -e "s|^ROOMAX_BACKUP_PASSPHRASE=.*|ROOMAX_BACKUP_PASSPHRASE=$BACKUP_PASS|" \
      .env.example > .env
  chmod 600 .env
  cat <<EOF

   ┌────────────────────────────────────────────────────────────────────────┐
   │ 아래 두 값을 서버 밖(비밀번호 관리자·종이 등)에 꼭 따로 적어 두세요.        │
   │ 잃어버리면 임차인 연락처·계약서·정기 백업을 다시 열 수 없습니다.            │
   └────────────────────────────────────────────────────────────────────────┘
   ROOMAX_FIELD_KEY        = $FIELD_KEY
   ROOMAX_BACKUP_PASSPHRASE = $BACKUP_PASS
   (같은 값이 $DIR/deploy/.env 에도 있습니다)
EOF
fi

# ── 4. 실행 ───────────────────────────────────────────────────
say "5/5 실행 (처음에는 이미지를 만드느라 5~10분 걸립니다)"
BUILD="--build"; [ -n "${ROOMAX_INSTALL_NO_BUILD:-}" ] && BUILD=""  # 시험용: 이미 만든 이미지로
$DOCKER compose up -d $BUILD
printf '   서버가 준비되기를 기다리는 중'
for _ in $(seq 90); do
  [ "$($DOCKER compose ps --format '{{.Health}}' api 2>/dev/null)" = healthy ] && break
  printf '.'; sleep 4
done
echo
if [ "$($DOCKER compose ps --format '{{.Health}}' api 2>/dev/null)" != healthy ]; then
  $DOCKER compose logs --tail 30 api
  die "API 가 준비되지 않았습니다. 위 로그를 확인하세요"
fi
SITE_NOW="$(grep -E '^SITE_ADDRESS=' .env | cut -d= -f2)"
cat <<EOF

✅ 설치 완료
   1) 브라우저에서 https://$SITE_NOW/signup 을 열어 대표 이메일로 바로 가입하세요.
      (인증서 발급에 1~2분 걸릴 수 있습니다. 보안 경고가 나오면 잠시 뒤 새로고침)
   2) 비밀번호를 잊으면:  cd $DIR/deploy && $DOCKER compose exec api python -m app.admin_cli reset-link 내이메일
   3) 업데이트:  bash $DIR/deploy/install.sh   (설정은 그대로, 코드만 최신으로)
EOF
