#!/usr/bin/env bash
# Munsiji updater — runs on the VPS host (systemd). Pulls latest GitHub code, rebuilds & restarts.
# Usage: update.sh            -> force update now (triggered from app Settings / banner)
#        update.sh --if-changed -> only when AUTO_UPDATE flag exists and remote has new commits (timer)
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
UPD="$APP_DIR/data/updater"
mkdir -p "$UPD"
STATUS="$UPD/status.json"
LOG="$UPD/update.log"
FLAG="$UPD/UPDATE_REQUESTED"
LOCK="$UPD/.lock"
COMPOSE="docker compose -f $APP_DIR/deploy/docker-compose.yml"
BRANCH="$(grep -E '^GIT_BRANCH=' .env 2>/dev/null | cut -d= -f2- | tr -d '"')"
BRANCH="${BRANCH:-main}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
status() {
  printf '{"state":"%s","message":"%s","commit":"%s","updated_at":"%s"}\n' \
    "$1" "$2" "$(git rev-parse --short HEAD 2>/dev/null)" "$(ts)" > "$STATUS"
  echo "[$(ts)] $1: $2" >> "$LOG"
}

# keep log small
if [[ -f "$LOG" && $(stat -c%s "$LOG") -gt 1000000 ]]; then tail -n 300 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"; fi

exec 9>"$LOCK"
if ! flock -n 9; then echo "update already running"; exit 0; fi
rm -f "$FLAG"

if [[ "${1:-}" == "--if-changed" ]]; then
  [[ -f "$UPD/AUTO_UPDATE" ]] || exit 0
  git fetch -q origin "$BRANCH" || exit 0
  [[ "$(git rev-parse HEAD)" != "$(git rev-parse "origin/$BRANCH")" ]] || exit 0
  echo "[$(ts)] auto-update: new commits found" >> "$LOG"
fi

trap 'status failed "Update fail hua — Settings > Update log dekho"' ERR
set -e

status updating "GitHub se naya code download ho raha hai"
git fetch origin "$BRANCH" >> "$LOG" 2>&1
git reset --hard "origin/$BRANCH" >> "$LOG" 2>&1
chmod +x "$APP_DIR/deploy/"*.sh || true

status building "Docker images ban rahi hain (2-6 min lag sakte hain)"
$COMPOSE build >> "$LOG" 2>&1

status restarting "Services restart ho rahi hain"
$COMPOSE up -d --remove-orphans >> "$LOG" 2>&1
docker image prune -f >> "$LOG" 2>&1 || true

status done "Update ho gaya — naya version live hai"
