"""System endpoints: health, and integrity verification of the signal log."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import signals_log
from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..services.ticker import MarketRuntime
from ..util import to_iso, now_utc
from .deps import get_runtime

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(runtime: MarketRuntime = Depends(get_runtime)) -> dict:
    with runtime.lock:
        engine_health = runtime.engine.health()
    return {"status": "ok", "server_time": to_iso(now_utc()), "engine": engine_health}


@router.get("/log/verify")
def verify_log(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Recompute the hash chain and report whether the activity log is intact.

    Authenticated: recomputing the whole chain is O(n), so we don't expose it to
    anonymous callers as a cheap DoS lever."""
    return signals_log.verify_chain(db)
