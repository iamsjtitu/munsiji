#!/usr/bin/env bash
# ------------------------------------------------------------------------------------------
# Munsiji.app — one-command VPS installer (Ubuntu 22.04 / 24.04, Debian 12)
#
#   curl -fsSL https://raw.githubusercontent.com/iamsjtitu/munsiji/main/deploy/install.sh | sudo bash -s -- \
#       --repo https://github.com/iamsjtitu/munsiji.git \
#       --domain munsiji.app --email admin@munsiji.com \
#       --owner 917205930002 --pin 3366 --llm-key sk-emergent-xxxx --email-key ek_xxxx
#
# Flags: --repo (required) --branch main --domain (optional, HTTPS auto) --email (Let's Encrypt + default owner email)
#        --owner-email <alerts inbox> --owner <whatsapp number> --pin <4-6 digit>
#        --llm-key <Emergent LLM key> --email-key <Emergent email key> --dir /opt/munsiji
# Re-running is safe: it updates code, keeps .env and data.
# ------------------------------------------------------------------------------------------
set -euo pipefail

REPO_URL="" BRANCH="main" DOMAIN="" EMAIL="" PIN="3366" OWNER="" LLM_KEY="" EMAIL_KEY="" OWNER_EMAIL="" APP_DIR="/opt/munsiji"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO_URL="$2"; shift 2 ;;
    --branch) BRANCH="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --owner-email) OWNER_EMAIL="$2"; shift 2 ;;
    --pin) PIN="$2"; shift 2 ;;
    --owner) OWNER="$2"; shift 2 ;;
    --llm-key) LLM_KEY="$2"; shift 2 ;;
    --email-key) EMAIL_KEY="$2"; shift 2 ;;
    --dir) APP_DIR="$2"; shift 2 ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done
OWNER_EMAIL="${OWNER_EMAIL:-$EMAIL}"

log() { echo -e "\n\033[1;32m[munsiji]\033[0m $*"; }
die() { echo -e "\033[1;31m[munsiji] $*\033[0m"; exit 1; }

[[ $EUID -eq 0 ]] || die "Root chahiye: 'sudo bash install.sh ...' se chalao"
[[ -n "$REPO_URL" ]] || die "--repo <github url> zaroori hai"
command -v systemctl >/dev/null || die "systemd nahi mila (Ubuntu/Debian VPS use karo)"

if [[ -z "$OWNER" && ! -f "$APP_DIR/.env" ]]; then
  read -rp "Owner WhatsApp number (country code ke saath, e.g. 917205930002): " OWNER </dev/tty
fi
if [[ -z "$LLM_KEY" && ! -f "$APP_DIR/.env" ]]; then
  read -rp "Emergent LLM key (AI parsing ke liye, sk-emergent-...): " LLM_KEY </dev/tty
fi

log "1/7 System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq ca-certificates curl git gnupg openssl util-linux >/dev/null

log "2/7 Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y -qq docker-compose-plugin >/dev/null
fi
systemctl enable --now docker >/dev/null

log "3/7 Swap (Expo web build ke liye RAM)"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
SWAP_MB=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)
if [[ $MEM_MB -lt 3500 && $SWAP_MB -lt 1024 && ! -f /swapfile ]]; then
  fallocate -l 3G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  echo "3G swap add kiya"
fi

log "4/7 Code ($REPO_URL @ $BRANCH) -> $APP_DIR"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" remote set-url origin "$REPO_URL"
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
git config --global --add safe.directory "$APP_DIR" || true
mkdir -p data/updater
chmod +x deploy/*.sh

log "5/7 Config (.env)"
if [[ -n "$DOMAIN" ]]; then PUBLIC_URL="https://$DOMAIN"; else
  IP=$(curl -fsS4 --max-time 8 https://ifconfig.me || hostname -I | awk '{print $1}')
  PUBLIC_URL="http://$IP"
fi
if [[ ! -f .env ]]; then
  cat > .env <<EOF
DB_NAME=munsiji
MONGO_URL=mongodb://mongo:27017
JWT_SECRET=$(openssl rand -hex 32)
JWT_EXPIRE_HOURS=72
OWNER_PIN=$PIN
OWNER_WHATSAPP=$OWNER
EMERGENT_LLM_KEY=$LLM_KEY
EMERGENT_EMAIL_KEY=$EMAIL_KEY
EMAIL_FROM_NAME=Munsiji
OWNER_EMAIL=$OWNER_EMAIL
PUBLIC_BASE_URL=$PUBLIC_URL
DOMAIN=$DOMAIN
ACME_EMAIL=$EMAIL
GIT_BRANCH=$BRANCH
EOF
  chmod 600 .env
  echo ".env ban gaya"
else
  echo ".env already hai — same rakha (edit: $APP_DIR/.env)"
  grep -q '^EMAIL_FROM_NAME=' .env || echo "EMAIL_FROM_NAME=Munsiji" >> .env
  grep -q '^EMERGENT_EMAIL_KEY=' .env || echo "EMERGENT_EMAIL_KEY=$EMAIL_KEY" >> .env
  grep -q '^OWNER_EMAIL=' .env || echo "OWNER_EMAIL=$OWNER_EMAIL" >> .env
  # allow changing domain / branch on re-run
  [[ -n "$DOMAIN" ]] && sed -i "s#^DOMAIN=.*#DOMAIN=$DOMAIN#; s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=$PUBLIC_URL#" .env
  [[ -n "$EMAIL" ]] && sed -i "s#^ACME_EMAIL=.*#ACME_EMAIL=$EMAIL#" .env
  sed -i "s#^GIT_BRANCH=.*#GIT_BRANCH=$BRANCH#" .env
fi
DOMAIN="$(grep -E '^DOMAIN=' .env | cut -d= -f2-)"
EMAIL="$(grep -E '^ACME_EMAIL=' .env | cut -d= -f2-)"
PUBLIC_URL="$(grep -E '^PUBLIC_BASE_URL=' .env | cut -d= -f2-)"

# Caddy reverse proxy (auto HTTPS when a domain is given)
if [[ -n "$DOMAIN" ]]; then
  {
    [[ -n "$EMAIL" ]] && printf '{\n  email %s\n}\n' "$EMAIL"
    printf '%s {\n' "$DOMAIN"
  } > data/Caddyfile
else
  printf ':80 {\n' > data/Caddyfile
fi
cat >> data/Caddyfile <<'EOF'
  encode gzip
  handle /api/* {
    reverse_proxy backend:8001
  }
  handle {
    reverse_proxy web:80
  }
}
EOF

if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
fi

log "6/7 Auto-updater (systemd)"
for unit in deploy/systemd/*; do
  name=$(basename "$unit")
  sed "s#/opt/munsiji#$APP_DIR#g" "$unit" > "/etc/systemd/system/$name"
done
systemctl daemon-reload
systemctl enable --now munsiji-updater.path munsiji-autoupdate.timer >/dev/null

log "7/7 Build & start (pehli baar 5-10 min lag sakte hain)"
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml up -d --remove-orphans

echo -n "Backend ready ho raha hai"
for _ in $(seq 1 40); do
  if docker compose -f deploy/docker-compose.yml exec -T backend curl -fsS http://localhost:8001/api/health >/dev/null 2>&1; then echo " ✔"; break; fi
  echo -n "."; sleep 3
done
printf '{"state":"done","message":"Install complete","commit":"%s","updated_at":"%s"}\n' \
  "$(git rev-parse --short HEAD)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > data/updater/status.json

cat <<EOF

==========================================================
  Munsiji install ho gaya!

  App (web):        $PUBLIC_URL
  PIN:              $(grep -E '^OWNER_PIN=' .env | cut -d= -f2-)
  WhatsApp webhook: $PUBLIC_URL/api/whatsapp/webhook
                    (wa.9x dashboard mein ye URL daalo; API key app Settings mein)

  Update:   Emergent mein "Save to GitHub" -> app Settings > "Update now"
            (ya home screen ka update bar). Auto-update switch bhi Settings mein hai.
  Logs:     cd $APP_DIR && docker compose -f deploy/docker-compose.yml logs -f backend
  Config:   $APP_DIR/.env   (badalne ke baad: docker compose -f deploy/docker-compose.yml up -d)
==========================================================
EOF
