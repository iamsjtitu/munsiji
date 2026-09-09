#!/usr/bin/env bash
# Generates data/Caddyfile from .env. TLS modes:
#   auto      (default) Let's Encrypt — needs DNS pointing DIRECTLY to the VPS (Cloudflare "DNS only" / grey cloud)
#   internal  Caddy self-signed cert — use behind Cloudflare proxy with SSL mode "Full"
#   origin    Cloudflare Origin Certificate at data/certs/origin.pem + origin.key — SSL mode "Full (strict)"
# Mode = TLS_MODE in .env; if origin cert files exist they are used automatically.
# Re-run after changes:  bash deploy/gen-caddyfile.sh && docker compose -f deploy/docker-compose.yml restart caddy
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
envval() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true; }
DOMAIN="$(envval DOMAIN)"
EMAIL="$(envval ACME_EMAIL)"
TLS_MODE="$(envval TLS_MODE)"
mkdir -p data data/certs
if [[ -f data/certs/origin.pem && -f data/certs/origin.key ]]; then TLS_MODE="origin"; fi
TLS_MODE="${TLS_MODE:-auto}"
OUT="data/Caddyfile"

{
  if [[ -n "$DOMAIN" ]]; then
    if [[ -n "$EMAIL" && "$TLS_MODE" == "auto" ]]; then printf '{\n  email %s\n}\n' "$EMAIL"; fi
    printf '%s {\n' "$DOMAIN"
    case "$TLS_MODE" in
      origin) printf '  tls /certs/origin.pem /certs/origin.key\n' ;;
      internal) printf '  tls internal\n' ;;
    esac
  else
    printf ':80 {\n'
  fi
  cat <<'EOF'
  encode gzip
  header {
    X-Content-Type-Options nosniff
    X-Frame-Options DENY
    Referrer-Policy strict-origin-when-cross-origin
    Permissions-Policy "camera=(), microphone=(), geolocation=()"
    -Server
  }
EOF
  if [[ -n "$DOMAIN" ]]; then
    printf '  header Strict-Transport-Security "max-age=31536000; includeSubDomains"\n'
  fi
  cat <<'EOF'
  handle /api/* {
    reverse_proxy backend:8001
  }
  handle {
    reverse_proxy web:80
  }
}
EOF
} > "$OUT"

echo "Caddyfile written: domain=${DOMAIN:-<none, plain http :80>} tls=$( [[ -n "$DOMAIN" ]] && echo "$TLS_MODE" || echo "off")"
