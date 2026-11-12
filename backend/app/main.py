"""FastAPI application: wiring, the background price loop, and lifecycle.

The price loop advances the market once per ``TICK_INTERVAL_SECONDS`` and records
material events. It runs the (synchronous) tick in a worker thread so the event loop
stays free to serve requests and SSE streams; the runtime's lock keeps that tick and
the request threads from stepping on shared engine state.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import auth, system, watchlist
from .config import settings
from .db import SessionLocal, init_db
from .services.ticker import MarketRuntime
from .util import now_utc, to_iso

log = logging.getLogger("watchlist")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _run_tick(runtime: MarketRuntime) -> int:
    """Own its DB session; runs inside a worker thread."""
    db = SessionLocal()
    try:
        return runtime.tick(db, None)
    finally:
        db.close()


async def _price_loop(runtime: MarketRuntime, stop: asyncio.Event) -> None:
    interval = settings.tick_interval_seconds
    log.info("price loop started (interval=%.2fs)", interval)
    while not stop.is_set():
        try:
            await asyncio.sleep(interval)
            await asyncio.to_thread(_run_tick, runtime)
        except asyncio.CancelledError:
            break
        except Exception:  # never let one bad tick kill the loop
            log.exception("tick failed")
    log.info("price loop stopped")


def _check_secret() -> None:
    """Fail fast in production if the insecure default JWT secret is in use — with it,
    anyone could forge a token for any user (the default is public in source)."""
    if settings.using_insecure_default_secret:
        if settings.app_env.lower() in ("prod", "production"):
            raise RuntimeError("JWT_SECRET must be set to a strong value when APP_ENV=prod")
        log.warning("Using the INSECURE default JWT secret — set JWT_SECRET before any real deployment.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_secret()
    init_db()
    runtime = MarketRuntime()
    runtime.warmup()  # build volatility history so z-scores are meaningful immediately
    app.state.runtime = runtime
    stop = asyncio.Event()
    task = asyncio.create_task(_price_loop(runtime, stop)) if settings.enable_price_loop else None
    try:
        yield
    finally:
        if task is not None:
            stop.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Smart Market Watchlist", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(watchlist.router)
app.include_router(system.router)


@app.get("/", tags=["system"])
def root() -> dict:
    return {
        "name": "Smart Market Watchlist API",
        "version": __version__,
        "server_time": to_iso(now_utc()),
        "docs": "/docs",
        "endpoints": [
            "POST /api/auth/login",
            "GET  /api/instruments",
            "GET  /api/watchlist",
            "POST /api/watchlist/items",
            "PATCH /api/watchlist/items/{symbol}",
            "DELETE /api/watchlist/items/{symbol}",
            "POST /api/watchlist/seen",
            "GET  /api/activity",
            "GET  /api/stream?token=...",
            "GET  /api/health",
            "GET  /api/log/verify",
        ],
    }
