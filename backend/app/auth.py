"""Authentication: short, JWT-scoped, passwordless.

Identity is by email; a signed JWT carries the user id on every request. This is
intentionally lightweight for the challenge — no password storage (and none of its
risks). A production deployment swaps ``login`` for an OTP/OAuth step and keeps the
rest of the token machinery unchanged. Per-user scoping is what makes state follow a
user across sessions and devices.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

_ALGO = "HS256"
log = logging.getLogger("watchlist.auth")


def create_token(user: User) -> str:
    """A full-privilege session token (sent in the Authorization header)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "scope": "session",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.token_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def create_stream_token(user: User) -> str:
    """A short-lived, SSE-only token. It rides in the stream URL (EventSource can't
    set headers), so it is deliberately narrow: it cannot mutate anything and it
    expires quickly, limiting the blast radius if a URL leaks via logs/history."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "scope": "stream",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.stream_token_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def decode_token(token: str, *, expected_scope: Optional[str] = None) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGO])
    except jwt.PyJWTError as exc:  # expired, bad signature, malformed
        log.warning("token decode failed: %s", exc)  # detail stays server-side
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if expected_scope is not None and payload.get("scope") not in (expected_scope, None):
        # a stream-scoped token must never be accepted where a session token is required
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token scope")
    return payload


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    # a stream-scoped token must not authenticate a normal (mutating) request
    payload = decode_token(authorization.split(" ", 1)[1].strip(), expected_scope="session")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user
