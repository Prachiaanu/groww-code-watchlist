"""The market runtime: owns the simulator, providers and engine, advances time,
and records material events to the append-only log.

Key scaling property lives here: per tick we do work proportional to the number of
*symbols*, not the number of *users*. Event detection and logging are symbol-level;
anything user-specific (since-you-last-looked, price alerts) is computed cheaply at
read time in ``watchlist.py``.

Event logging is deduplicated so the log captures transitions, not every tick:
  * discrete conditions (52-week high, gap, volume spike) are edge-triggered — logged
    when they first become active and not again while they stay active;
  * moves use a monotonic ratchet per (symbol, direction) — logged when the move
    reaches a new whole-percent high-water mark, so an oscillating price doesn't
    re-log the same magnitude over and over.
Dedup state is seeded after warmup so a process restart doesn't re-log standing
conditions.
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .. import signals_log
from ..config import SignificanceConfig, settings
from ..market.engine import MarketEngine
from ..market.provider import Instrument, Quote
from ..market.simulated import build_default_providers
from ..significance import Signal, SignalType, evaluate_symbol_events
from ..util import now_utc


class MarketRuntime:
    def __init__(self, cfg: Optional[SignificanceConfig] = None, seed: Optional[int] = None):
        self.cfg = cfg or settings.significance
        self.sim, self.providers = build_default_providers(seed=seed)
        self.engine = MarketEngine(
            instruments=list(self.sim.instruments.values()),
            source_priority=[p.source_id for p in self.providers],
            cfg=self.cfg,
        )
        # dedup memory: active discrete keys (edge-trigger) + move high-water marks (ratchet)
        self._active: dict[str, set[str]] = {s: set() for s in self.sim.instruments}
        self._peak: dict[str, dict[str, int]] = {s: {} for s in self.sim.instruments}
        # Guards the shared engine: the background loop writes while request threads
        # (FastAPI runs sync endpoints in a threadpool) read. Reentrant so a locked
        # tick can call locked helpers.
        self.lock = threading.RLock()

    def universe(self) -> list[Instrument]:
        return list(self.sim.instruments.values())

    def _advance(self, now) -> None:
        """One simulation step, ingested from ALL providers in a single batch so the
        engine sees the complete same-tick source set exactly once (correct conflict
        detection and per-tick counters)."""
        self.sim.step(now)
        quotes: list[Quote] = []
        for p in self.providers:
            quotes.extend(p.poll(now))
        self.engine.ingest(quotes, now)

    def warmup(self, ticks: int = 60) -> None:
        """Pre-run history so volatility estimates (and thus z-scores) are meaningful
        from the first request. Compresses ``ticks`` steps into the recent past.
        Kept modest so first-load day-moves stay realistic while sigma is well-estimated."""
        interval = settings.tick_interval_seconds
        end = now_utc()
        start = end - timedelta(seconds=interval * (ticks - 1))
        with self.lock:
            for i in range(ticks):
                self._advance(start + timedelta(seconds=interval * i))
            self.engine.reset_counters()   # metrics should reflect the live run, not warmup
            self._seed_dedup(end)          # mark standing conditions as already-known

    def _dedup_new_events(self, symbol: str, events: list[Signal]) -> list[Signal]:
        """Return only the events that represent a genuine transition worth logging,
        updating dedup state. Discrete signals edge-trigger; moves ratchet upward."""
        new: list[Signal] = []
        discrete: dict[str, Signal] = {}
        peaks = self._peak[symbol]
        for s in events:
            if s.type in (SignalType.INTRADAY_MOVE, SignalType.MOVE_SINCE_SEEN):
                base = f"{s.type.value}:{s.direction}"
                bucket = round(abs(s.magnitude_pct))
                if bucket > peaks.get(base, 0):
                    peaks[base] = bucket
                    new.append(s)
            else:
                discrete[s.dedup_key] = s
        active = self._active[symbol]
        for key, s in discrete.items():
            if key not in active:
                new.append(s)
        self._active[symbol] = set(discrete)
        return new

    def _seed_dedup(self, now) -> None:
        """Populate dedup state from the current market so standing conditions are not
        re-logged after a restart. Runs under the caller's lock; logs nothing."""
        for symbol in self.sim.instruments:
            c = self.engine.consolidate(symbol, now)
            stats = self.engine.stats(symbol)
            if c is None or stats is None:
                continue
            self._dedup_new_events(symbol, evaluate_symbol_events(c, stats, self.cfg))

    def tick(self, session: Optional[Session] = None, now=None, *, log: bool = True) -> int:
        """Advance one tick; log genuinely-new material events. Returns #events logged."""
        now = now or now_utc()
        with self.lock:
            self._advance(now)
            if not log or session is None:
                return 0

            logged = 0
            for symbol in self.sim.instruments:
                c = self.engine.consolidate(symbol, now)
                stats = self.engine.stats(symbol)
                if c is None or stats is None:
                    continue
                events = evaluate_symbol_events(c, stats, self.cfg)
                for s in self._dedup_new_events(symbol, events):
                    signals_log.append(session, symbol, s, now=now, commit=False)
                    logged += 1
            if logged:
                session.commit()
            return logged
