"""Service-level: the "since you last checked" baseline and the while-you-were-away
feed, driven through the real runtime + persistence (deterministic ticks)."""

from __future__ import annotations

from datetime import timedelta

from app.config import settings
from app.services import watchlist as wl
from app.services.accounts import get_or_create_user
from app.services.ticker import MarketRuntime
from app.util import now_utc

INTERVAL = settings.tick_interval_seconds


def _runtime():
    rt = MarketRuntime()
    rt.warmup(120)
    return rt


def test_first_visit_shows_no_while_away(mem_session):
    """A never-reviewed watchlist must not dump historical events as 'while you were
    away' — the user was never away."""
    rt = _runtime()
    u = get_or_create_user(mem_session, "firstvisit@example.com", "Reshu")
    wl.add_item(mem_session, u, rt, "ZOMATO", None, None)
    now = now_utc()
    for _ in range(60):  # generate events *before* any review
        now = now + timedelta(seconds=INTERVAL)
        rt.tick(mem_session, now)
    view = wl.build_view(mem_session, u, rt, now)
    assert view["summary"]["last_reviewed_at"] is None
    assert view["while_away"] == []


def test_since_seen_and_while_away(mem_session):
    rt = _runtime()
    u = get_or_create_user(mem_session, "since@example.com", "Reshu")
    wl.add_item(mem_session, u, rt, "ZOMATO", None, None)  # volatile: likely to move
    now = now_utc()
    wl.mark_seen(mem_session, u, rt, None, now)

    for _ in range(60):
        now = now + timedelta(seconds=INTERVAL)
        rt.tick(mem_session, now)

    view = wl.build_view(mem_session, u, rt, now)
    item = view["items"][0]
    assert item["symbol"] == "ZOMATO"
    assert item["seen"] is not None
    assert item["attention"]["since_seen"] is not None
    assert view["summary"]["last_reviewed_at"] is not None
    # anything in the feed must belong to the user's symbol
    for e in view["while_away"]:
        assert e["symbol"] == "ZOMATO"


def test_mark_seen_resets_baseline_to_current(mem_session):
    rt = _runtime()
    u = get_or_create_user(mem_session, "reset@example.com", "Reshu")
    wl.add_item(mem_session, u, rt, "RELIANCE", None, None)
    now = now_utc()
    wl.mark_seen(mem_session, u, rt, None, now)

    for _ in range(30):
        now = now + timedelta(seconds=INTERVAL)
        rt.tick(mem_session, now)

    # re-review: baseline should snap to the current price, so the diff resets to ~0
    wl.mark_seen(mem_session, u, rt, None, now)
    view = wl.build_view(mem_session, u, rt, now)
    item = view["items"][0]
    current = item["price"]
    assert abs(item["seen"]["baseline_price"] - current) < 0.01
    assert abs(item["attention"]["since_seen"]["change_pct"]) < 0.01
