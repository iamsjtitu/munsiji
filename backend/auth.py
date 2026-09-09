import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from db import db

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "12"))
ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)

# Persistent brute-force guard (survives restarts / multiple workers). Backoff by total fails.
LOCK_STEPS = [(15, 1800), (10, 300), (5, 60)]  # fails >= n -> lock seconds


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_pin(pin: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pin.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def make_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": "owner", "iat": now, "exp": now + timedelta(hours=JWT_EXPIRE_HOURS)}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def _utc(d: Optional[datetime]) -> Optional[datetime]:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


async def check_lockout(ip: str) -> None:
    now = datetime.now(timezone.utc)
    for key in ("global", f"ip:{ip}"):
        doc = await db.login_guard.find_one({"key": key})
        locked_until = _utc(doc.get("locked_until")) if doc else None
        if locked_until and locked_until > now:
            wait = int((locked_until - now).total_seconds()) + 1
            raise HTTPException(status_code=429, detail=f"Bahut galat attempts. {wait}s baad try karo.")


async def record_fail(ip: str) -> bool:
    """Increment counters; returns True when this failure started a new lockout."""
    now = datetime.now(timezone.utc)
    locked = False
    for key in ("global", f"ip:{ip}"):
        doc = await db.login_guard.find_one_and_update(
            {"key": key}, {"$inc": {"fails": 1}, "$set": {"last_fail_at": now}}, upsert=True, return_document=True
        )
        fails = doc.get("fails", 1)
        for threshold, seconds in LOCK_STEPS:
            if fails >= threshold and fails % 5 == 0:
                await db.login_guard.update_one({"key": key}, {"$set": {"locked_until": now + timedelta(seconds=seconds)}})
                locked = True
                break
    return locked


async def record_success(ip: str) -> None:
    await db.login_guard.delete_many({"key": {"$in": ["global", f"ip:{ip}"]}})


async def current_owner(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> str:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError:
        raise unauthorized
    if payload.get("sub") != "owner":
        raise unauthorized
    # tokens issued before the last PIN change are revoked
    s = await db.settings.find_one({"key": "main"}, {"pin_changed_at": 1})
    changed = _utc(s.get("pin_changed_at")) if s else None
    if changed and datetime.fromtimestamp(payload["iat"], tz=timezone.utc) < changed - timedelta(seconds=1):
        raise unauthorized
    return "owner"
