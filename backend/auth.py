import os
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "12"))
ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)

# simple in-memory brute force guard: 5 fails -> 60s lockout
_fails: dict = {"count": 0, "locked_until": 0.0}


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


def check_lockout():
    if time.time() < _fails["locked_until"]:
        wait = int(_fails["locked_until"] - time.time()) + 1
        raise HTTPException(status_code=429, detail=f"Bahut galat attempts. {wait}s baad try karo.")


def record_fail():
    _fails["count"] += 1
    if _fails["count"] >= 5:
        _fails["count"] = 0
        _fails["locked_until"] = time.time() + 60


def record_success():
    _fails["count"] = 0


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
    return "owner"
