"""Self-host system info: version/update state read from files written by host scripts (deploy/*.sh).

The backend never runs git or docker itself: it only writes request flags into UPDATER_DIR and reads
version.json / status.json that the host-side systemd units maintain.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

UPDATER_DIR = os.environ.get("UPDATER_DIR")
BUSY_STATES = {"requested", "updating", "building", "restarting"}


def supported() -> bool:
    return bool(UPDATER_DIR and Path(UPDATER_DIR).is_dir())


def _read_json(name: str, default: dict) -> dict:
    try:
        return json.loads(Path(UPDATER_DIR, name).read_text())
    except (OSError, ValueError):
        return default


def read_status() -> dict:
    return _read_json("status.json", {"state": "idle"})


def _log_tail(lines: int = 40) -> list:
    try:
        return Path(UPDATER_DIR, "update.log").read_text(errors="ignore").splitlines()[-lines:]
    except OSError:
        return []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def version_info(force: bool = False) -> dict:
    if not supported():
        return {"supported": False}
    version = _read_json("version.json", {})
    if force:
        before = version.get("checked_at")
        Path(UPDATER_DIR, "CHECK_REQUESTED").write_text(_now())
        for _ in range(16):  # wait up to ~8s for the host check script
            await asyncio.sleep(0.5)
            version = _read_json("version.json", {})
            if version.get("checked_at") and version.get("checked_at") != before:
                break
    empty = {"commit": "", "message": "", "date": ""}
    behind = int(version.get("behind") or 0)
    return {
        "supported": True,
        "branch": version.get("branch", ""),
        "current": version.get("current") or empty,
        "latest": version.get("latest") or empty,
        "behind": behind,
        "update_available": behind > 0,
        "checked_at": version.get("checked_at"),
        "status": read_status(),
        "auto_update": Path(UPDATER_DIR, "AUTO_UPDATE").exists(),
        "log": _log_tail(),
    }


def request_update() -> dict:
    status = {"state": "requested", "message": "Update request bhej diya — server 1 minute mein shuru karega", "updated_at": _now()}
    Path(UPDATER_DIR, "status.json").write_text(json.dumps(status))
    Path(UPDATER_DIR, "UPDATE_REQUESTED").write_text(status["updated_at"])
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
