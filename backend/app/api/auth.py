"""Auth endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import create_stream_token, create_token, get_current_user
from ..db import get_db
from ..models import User
from ..schemas import LoginRequest, LoginResponse
from ..services.accounts import get_or_create_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Passwordless login/registration by email. Returns a bearer token.

    First login also provisions a default watchlist so the user has somewhere to land.
    """
    user = get_or_create_user(db, body.email, body.display_name)
    return LoginResponse(
        token=create_token(user), user_id=user.id, email=user.email, display_name=user.display_name
    )


@router.post("/stream-token")
def stream_token(user: User = Depends(get_current_user)) -> dict:
    """Exchange the (header-based) session token for a short-lived, SSE-only token.

    The frontend passes THIS in the stream URL instead of the session token, so a
    leaked stream URL exposes only a narrow, quickly-expiring, read-only credential.
    """
    return {"stream_token": create_stream_token(user)}
