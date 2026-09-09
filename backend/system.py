"""Self-host system info: git version, update-available check, update trigger (VPS only)."""
import asyncio
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_DIR = os.environ.get("REPO_DIR")
UPDATER_DIR = os.environ.get("UPDATER_DIR")
BRANCH = os.environ.get("GIT_BRANCH", "main")
CACHE_TTL = 120

_cache: dict = {"at": 0.0, "data": None}
BUSY_STATES = {"requested", "updating", "building", "restarting"}


def supported() -> bool:
    return bool(REPO_DIR and Path(REPO_DIR, ".git").exists() and UPDATER_DIR)


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True, timeout=45)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        return ""


def _status_path() -> Path:
    return Path(UPDATER_DIR, "status.json")


def read_status() -> dict:
    try:
        return json.loads(_status_path().read_text())
    except (OSError, ValueError):
        return {"state": "idle"}


def _log_tail(lines: int = 40) -> list:
    try:
        content = Path(UPDATER_DIR, "update.log").read_text(errors="ignore").splitlines()
        return content[-lines:]
    except OSError:
        return []


def _commit(ref: str) -> dict:
    return {
        "commit": _git("rev-parse", "--short", ref),
        "message": _git("log", "-1", "--format=%s", ref),
        "date": _git("log", "-1", "--format=%cI", ref),
    }


def _collect() -> dict:
    _git("fetch", "-q", "origin", BRANCH)
    remote = f"origin/{BRANCH}"
    behind_raw = _git("rev-list", "--count", f"HEAD..{remote}")
    behind = int(behind_raw) if behind_raw.isdigit() else 0
    return {
        "supported": True,
        "branch": BRANCH,
        "current": _commit("HEAD"),
        "latest": _commit(remote),
        "behind": behind,
        "update_available": behind > 0,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def version_info(force: bool = False) -> dict:
    if not supported():
        return {"supported": False}
    now = time.time()
    if force or not _cache["data"] or now - _cache["at"] > CACHE_TTL:
        _cache["data"] = await asyncio.to_thread(_collect)
        _cache["at"] = now
    data = dict(_cache["data"])
    data["status"] = read_status()
    data["auto_update"] = Path(UPDATER_DIR, "AUTO_UPDATE").exists()
    data["log"] = _log_tail()
    return data


def request_update() -> dict:
    Path(UPDATER_DIR).mkdir(parents=True, exist_ok=True)
    status = {
        "state": "requested",
        "message": "Update request bhej diya — server 1 minute mein shuru karega",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _status_path().write_text(json.dumps(status))
    Path(UPDATER_DIR, "UPDATE_REQUESTED").write_text(status["updated_at"])
    _cache["at"] = 0.0
    return status


def set_auto_update(enabled: bool) -> bool:
    flag = Path(UPDATER_DIR, "AUTO_UPDATE")
    if enabled:
        flag.write_text("1")
    elif flag.exists():
        flag.unlink()
    return enabled


def is_busy(status: Optional[dict] = None) -> bool:
    return (status or read_status()).get("state") in BUSY_STATES
