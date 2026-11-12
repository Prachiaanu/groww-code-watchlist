"""Watchlist endpoints: CRUD, the composed view, the "mark reviewed" action,
recent activity, and a Server-Sent Events live stream.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import signals_log
from ..auth import decode_token, get_current_user
from ..config import settings
from ..db import SessionLocal, get_db
from ..models import User
from ..schemas import AddItemRequest, InstrumentOut, MarkSeenRequest, UpdateItemRequest
from ..services import watchlist as wl_service
from ..services.ticker import MarketRuntime
from .deps import get_runtime

router = APIRouter(prefix="/api", tags=["watchlist"])


@router.get("/instruments", response_model=list[InstrumentOut])
def instruments(runtime: MarketRuntime = Depends(get_runtime)) -> list[InstrumentOut]:
    """The tradable universe — used by the add-symbol search box."""
    return [
        InstrumentOut(symbol=i.symbol, name=i.name, sector=i.sector, currency=i.currency)
        for i in runtime.universe()
    ]


@router.get("/watchlist")
def get_watchlist(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime: MarketRuntime = Depends(get_runtime),
) -> dict:
    return wl_service.build_view(db, user, runtime)


@router.post("/watchlist/items", status_code=status.HTTP_201_CREATED)
def add_item(
    body: AddItemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime: MarketRuntime = Depends(get_runtime),
) -> dict:
    wl_service.add_item(db, user, runtime, body.symbol, body.alert_above, body.alert_below)
    return wl_service.build_view(db, user, runtime)


@router.patch("/watchlist/items/{symbol}")
def update_item(
    symbol: str,
    body: UpdateItemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime: MarketRuntime = Depends(get_runtime),
) -> dict:
    wl_service.update_item(db, user, runtime, symbol, body.alert_above, body.alert_below, body.clear_alerts)
    return wl_service.build_view(db, user, runtime)


@router.delete("/watchlist/items/{symbol}")
def remove_item(
    symbol: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime: MarketRuntime = Depends(get_runtime),
) -> dict:
    wl_service.remove_item(db, user, runtime, symbol)
    return wl_service.build_view(db, user, runtime)


@router.post("/watchlist/seen")
def mark_seen(
    body: MarkSeenRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime: MarketRuntime = Depends(get_runtime),
) -> dict:
    """Mark symbols as reviewed: resets the "since you last checked" baseline."""
    updated = wl_service.mark_seen(db, user, runtime, body.symbols)
    view = wl_service.build_view(db, user, runtime)
    view["marked_seen"] = updated
    return view


@router.get("/activity")
def activity(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    runtime: MarketRuntime = Depends(get_runtime),
) -> dict:
    """All recent material events for the user's symbols (not just since last review)."""
    wl = wl_service.default_watchlist(db, user)
    symbols = [i.symbol for i in wl.items]
    rows = signals_log.query_since(db, symbols, since=None, limit=limit)
    return {"events": [signals_log.row_to_dict(r) for r in rows]}


def _snapshot_json(runtime: MarketRuntime, user_id: int) -> str | None:
    """Build one view snapshot in a worker thread (own DB session)."""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            return None
        return json.dumps(wl_service.build_view(db, user, runtime), default=str)
    finally:
        db.close()


@router.get("/stream")
async def stream(
    request: Request,
    token: str = Query(..., description="short-lived STREAM-scoped token (EventSource cannot set headers)"),
    runtime: MarketRuntime = Depends(get_runtime),
) -> StreamingResponse:
    """Server-Sent Events: pushes a fresh watchlist view on every tick.

    SSE over WebSockets on purpose: updates are one-way (server->client), it rides
    plain HTTP (no upgrade/proxy headaches), and EventSource auto-reconnects. The
    token is passed as a query param because EventSource cannot set headers — so it
    must be a STREAM-scoped token (read-only, short-lived), never the session token.
    """
    payload = decode_token(token, expected_scope="stream")  # rejects session tokens in the URL
    user_id = int(payload["sub"])

    async def event_gen():
        # small heartbeat so proxies keep the connection open between ticks
        while True:
            if await request.is_disconnected():
                break
            snapshot = await asyncio.to_thread(_snapshot_json, runtime, user_id)
            if snapshot is None:
                break
            yield f"event: snapshot\ndata: {snapshot}\n\n"
            await asyncio.sleep(settings.tick_interval_seconds)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
