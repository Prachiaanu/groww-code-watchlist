"""Shared test fixtures.

Environment is configured BEFORE importing the app so config picks it up: a throwaway
SQLite file, the background price loop disabled (determinism), and a fixed seed.
"""

from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="wl_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{os.path.join(_TMP, 'test.db')}")
os.environ["ENABLE_PRICE_LOOP"] = "0"
os.environ.setdefault("SIM_SEED", "42")

from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db import Base  # noqa: E402
from app.market.engine import MarketEngine  # noqa: E402
from app.market.provider import Instrument, Quote  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 1, 2, 9, 15, 0, tzinfo=UTC)  # a fixed "market open"


@pytest.fixture
def mem_session():
    """A fresh in-memory database session, isolated per test."""
    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        eng.dispose()


def make_instrument(symbol: str, sector: str = "FMCG", base: float = 1000.0) -> Instrument:
    return Instrument(symbol, f"{symbol} Ltd", sector, base_price=base, prev_close=base,
                      week52_high=base * 1.2, week52_low=base * 0.8, avg_daily_volume=1_000_000)


@pytest.fixture
def instruments():
    # identical starting price so moves are directly comparable; only volatility differs
    return [make_instrument("CALM", "FMCG"), make_instrument("JUMPY", "Tech")]


@pytest.fixture
def engine(instruments):
    return MarketEngine(instruments, source_priority=["A", "B"])


@pytest.fixture
def mkq():
    def _q(symbol, price, as_of, *, source="A", prev_close=1000.0, volume=0):
        return Quote(symbol=symbol, price=price, prev_close=prev_close, as_of=as_of,
                     source=source, volume=volume)
    return _q


@pytest.fixture
def feed(engine, mkq):
    """Ingest ``n`` ticks that oscillate by ±``d`` (fraction), so the resulting
    per-tick volatility ≈ d. Returns (last_as_of, last_price)."""
    def _feed(symbol, n=30, d=0.001, base=1000.0, start=T0, interval=2, source="A", prev_close=1000.0):
        as_of = start
        last_price = base
        for i in range(n):
            last_price = round(base * (1 + d) if i % 2 == 0 else base, 4)
            engine.ingest([mkq(symbol, last_price, as_of, source=source, prev_close=prev_close)], as_of)
            as_of = as_of + timedelta(seconds=interval)
        return as_of, last_price
    return _feed


@pytest.fixture
def client():
    """FastAPI TestClient with lifespan (warmup runs, loop disabled)."""
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c
