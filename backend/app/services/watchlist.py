"""Watchlist operations and the composed watchlist *view*.

``build_view`` is where the whole system pays off: for each symbol it takes the
consolidated quote (market engine), the user's baseline (seen-state) and the user's
alerts, runs the significance engine, and returns a ranked, explained view plus a
"while you were away" feed drawn from the tamper-evident log.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import signals_log
from ..config import SignificanceConfig, settings
from ..market.engine import ConsolidatedQuote, SourceView
from ..models import SeenState, User, Watchlist, WatchlistItem
from ..significance import Baseline, evaluate_attention
from ..util import ensure_utc, now_utc, safe_pct_change, to_iso
from .accounts import default_watchlist
from .ticker import MarketRuntime


# ------------------------------------------------------------------ mutations
def _known_symbol(runtime: MarketRuntime, symbol: str) -> str:
    symbol = symbol.strip().upper()
    if symbol not in runtime.engine.instruments:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown symbol '{symbol}'")
    return symbol


def add_item(db: Session, user: User, runtime: MarketRuntime, symbol: str,
             alert_above: Optional[float], alert_below: Optional[float]) -> WatchlistItem:
    symbol = _known_symbol(runtime, symbol)
    wl = default_watchlist(db, user)
    existing = db.execute(
        select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id, WatchlistItem.symbol == symbol)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{symbol}' is already on the watchlist")
    max_order = db.execute(
        select(WatchlistItem.sort_order).where(WatchlistItem.watchlist_id == wl.id)
        .order_by(WatchlistItem.sort_order.desc()).limit(1)
    ).scalar_one_or_none()
    item = WatchlistItem(
        watchlist_id=wl.id, symbol=symbol, alert_above=alert_above, alert_below=alert_below,
        sort_order=(max_order or 0) + 1,
    )
    db.add(item)
    db.commit()
    return item


def update_item(db: Session, user: User, runtime: MarketRuntime, symbol: str,
                alert_above: Optional[float], alert_below: Optional[float], clear: bool) -> WatchlistItem:
    symbol = _known_symbol(runtime, symbol)
    item = _get_item(db, user, symbol)
    if clear:
        item.alert_above = None
        item.alert_below = None
    else:
        item.alert_above = alert_above
        item.alert_below = alert_below
    db.commit()
    return item


def remove_item(db: Session, user: User, runtime: MarketRuntime, symbol: str) -> None:
    symbol = _known_symbol(runtime, symbol)
    item = _get_item(db, user, symbol)
    db.delete(item)
    db.commit()


def _get_item(db: Session, user: User, symbol: str) -> WatchlistItem:
    wl = default_watchlist(db, user)
    item = db.execute(
        select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id, WatchlistItem.symbol == symbol)
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"'{symbol}' is not on the watchlist")
    return item


def mark_seen(db: Session, user: User, runtime: MarketRuntime,
              symbols: Optional[list[str]], now: Optional[datetime] = None) -> int:
    """Snapshot current prices as the new "since you last checked" baselines.

    This is the "I've reviewed this" action: it resets the diff and the checkpoint
    for the while-you-were-away feed."""
    now = now or now_utc()
    wl = default_watchlist(db, user)
    all_symbols = [i.symbol for i in wl.items]
    target = [s.strip().upper() for s in symbols] if symbols else all_symbols
    existing = {
        s.symbol: s for s in db.execute(
            select(SeenState).where(SeenState.user_id == user.id, SeenState.symbol.in_(target))
        ).scalars().all()
    }
    with runtime.lock:
        price_map = {
            symbol: c.price
            for symbol in target
            if (c := runtime.engine.consolidate(symbol, now)) is not None
        }
    updated = 0
    for symbol, price in price_map.items():
        row = existing.get(symbol)
        if row is None:
            db.add(SeenState(user_id=user.id, symbol=symbol, baseline_price=price,
                             seen_at=ensure_utc(now).replace(microsecond=0, tzinfo=None)))
        else:
            row.baseline_price = price
            row.seen_at = ensure_utc(now).replace(microsecond=0, tzinfo=None)
        updated += 1
    db.commit()
    return updated


# ------------------------------------------------------------------ view
def _view_dict(v: SourceView) -> dict:
    return {"source": v.source, "price": v.price, "as_of": to_iso(v.as_of), "freshness": v.freshness.value}


def _item_view(c: ConsolidatedQuote, item: WatchlistItem, runtime: MarketRuntime,
               baseline: Optional[Baseline], now: datetime, cfg: SignificanceConfig) -> dict:
    inst = runtime.engine.instruments[c.symbol]
    stats = runtime.engine.stats(c.symbol)
    attn = evaluate_attention(
        c, stats, baseline, cfg,
        tick_interval_seconds=settings.tick_interval_seconds, now=now,
        alert_above=item.alert_above, alert_below=item.alert_below,
    )
    return {
        "symbol": c.symbol, "name": inst.name, "sector": inst.sector, "currency": c.currency,
        "price": c.price, "prev_close": c.prev_close,
        "day_change_pct": round(c.day_change_pct, 3),
        "day_change_abs": round(c.price - c.prev_close, 2),
        "as_of": to_iso(c.as_of), "received_at": to_iso(c.received_at),
        "freshness": c.freshness.value, "source": c.source,
        "age_seconds": round((ensure_utc(now) - c.as_of).total_seconds(), 1),
        "conflict": (
            {"divergence_pct": c.conflict.divergence_pct, "views": [_view_dict(v) for v in c.conflict.views]}
            if c.conflict else None
        ),
        "sources": [_view_dict(v) for v in c.sources],
        "day_high": stats.day_high if stats else None,
        "day_low": stats.day_low if stats else None,
        "week52_high": stats.week52_high if stats else None,
        "week52_low": stats.week52_low if stats else None,
        "volume": c.volume,
        "alert_above": item.alert_above, "alert_below": item.alert_below,
        "seen": (
            {"baseline_price": baseline.price, "seen_at": to_iso(baseline.seen_at)} if baseline else None
        ),
        "attention": attn.as_dict(),
    }


def build_view(db: Session, user: User, runtime: MarketRuntime,
               now: Optional[datetime] = None, cfg: Optional[SignificanceConfig] = None,
               while_away_limit: int = 40) -> dict:
    now = ensure_utc(now or now_utc())
    cfg = cfg or settings.significance
    wl = default_watchlist(db, user)
    items = list(wl.items)
    symbols = [i.symbol for i in items]

    seen_rows = {
        s.symbol: s for s in db.execute(
            select(SeenState).where(SeenState.user_id == user.id, SeenState.symbol.in_(symbols or [""]))
        ).scalars().all()
    }

    item_views: list[dict] = []
    counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
    data_issues = {"stale": 0, "delayed": 0, "conflict": 0}
    meaningful = 0
    last_reviewed: Optional[datetime] = None

    # Hold the engine lock for the whole read span so a concurrent tick cannot
    # mutate stats/quotes mid-computation. Pure CPU + in-memory reads, no I/O here.
    with runtime.lock:
        for item in items:
            c = runtime.engine.consolidate(item.symbol, now)
            if c is None:
                continue
            seen = seen_rows.get(item.symbol)
            baseline = Baseline(seen.baseline_price, ensure_utc(seen.seen_at)) if seen else None
            if seen is not None:
                sa = ensure_utc(seen.seen_at)
                last_reviewed = sa if last_reviewed is None else max(last_reviewed, sa)
            iv = _item_view(c, item, runtime, baseline, now, cfg)
            item_views.append(iv)
            counts[iv["attention"]["severity"]] += 1
            if iv["attention"]["is_meaningful"]:
                meaningful += 1
            if c.freshness.value == "STALE":
                data_issues["stale"] += 1
            elif c.freshness.value == "DELAYED":
                data_issues["delayed"] += 1
            if c.conflict is not None:
                data_issues["conflict"] += 1

    attention_order = [
        iv["symbol"] for iv in sorted(
            item_views,
            key=lambda x: (x["attention"]["attention_score"], abs(x["day_change_pct"])),
            reverse=True,
        )
    ]

    # "While you were away" is filtered per-symbol against each symbol's own review
    # time; symbols never reviewed contribute nothing (you were never away for them),
    # so a first-ever visit shows an empty feed instead of dumping history.
    cutoffs = {sym: ensure_utc(seen.seen_at) for sym, seen in seen_rows.items() if sym in symbols}
    while_away_rows = signals_log.query_since_per_symbol(db, cutoffs, limit=while_away_limit)

    return {
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "watchlist": {"id": wl.id, "name": wl.name},
        "server_time": to_iso(now),
        "summary": {
            "total": len(item_views),
            "meaningful": meaningful,
            "by_severity": counts,
            "data_issues": data_issues,
            "last_reviewed_at": to_iso(last_reviewed) if last_reviewed else None,
        },
        "attention_order": attention_order,
        "items": item_views,
        "while_away": [signals_log.row_to_dict(r) for r in while_away_rows],
    }
