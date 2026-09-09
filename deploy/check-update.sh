#!/usr/bin/env bash
# Munsiji: refresh data/updater/version.json (installed vs latest GitHub commit). Runs on the host
# (systemd timer every 10 min, or immediately when the app writes CHECK_REQUESTED).
set -uo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"
umask 000  # files must stay writable by the (non-root) backend container user
UPD="$APP_DIR/data/updater"
mkdir -p "$UPD"
rm -f "$UPD/CHECK_REQUESTED"
BRANCH="$(grep -E '^GIT_BRANCH=' .env 2>/dev/null | cut -d= -f2- | tr -d '"')"
BRANCH="${BRANCH:-main}"

git fetch -q origin "$BRANCH" 2>>"$UPD/update.log" || true

export V_BRANCH="$BRANCH"
export V_CUR="$(git rev-parse --short HEAD 2>/dev/null)"
export V_CUR_MSG="$(git log -1 --format=%s 2>/dev/null)"
export V_CUR_DATE="$(git log -1 --format=%cI 2>/dev/null)"
export V_LAT="$(git rev-parse --short "origin/$BRANCH" 2>/dev/null)"
export V_LAT_MSG="$(git log -1 --format=%s "origin/$BRANCH" 2>/dev/null)"
export V_LAT_DATE="$(git log -1 --format=%cI "origin/$BRANCH" 2>/dev/null)"
export V_BEHIND="$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)"

python3 - "$UPD/version.json" <<'EOF'
import json, os, sys
from datetime import datetime, timezone
e = os.environ
data = {
    "branch": e["V_BRANCH"],
    "current": {"commit": e["V_CUR"], "message": e["V_CUR_MSG"], "date": e["V_CUR_DATE"]},
    "latest": {"commit": e["V_LAT"], "message": e["V_LAT_MSG"], "date": e["V_LAT_DATE"]},
    "behind": int(e["V_BEHIND"] or 0),
    "checked_at": datetime.now(timezone.utc).isoformat(),
}
tmp = sys.argv[1] + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f)
os.replace(tmp, sys.argv[1])
EOF
