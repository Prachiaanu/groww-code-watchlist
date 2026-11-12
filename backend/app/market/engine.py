"""The ingest engine: messy quotes in, one trustworthy view out.

Responsibilities (each is a data-quality hazard the brief calls out):
  * out-of-order / duplicate ticks  -> monotonic guard per (symbol, source)
  * delayed / stale data            -> freshness computed at read time from as_of
  * conflicting sources             -> deterministic winner + explicit CONFLICT flag
  * volatility for "meaningful"     -> rolling sigma of per-tick returns per symbol

State is in-memory and shared by all users: N users watching the same symbol cost
one price + one stats object, not N. That is the core of the scaling story.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..config import SignificanceConfig, settings
from ..util import ensure_utc, safe_pct_change
from .provider import Freshness, Instrument, Quote


@dataclass(slots=True)
class SourceView:
    """What one source currently says about a symbol (for transparency in the UI)."""

    source: str
    price: float
    as_of: datetime
    freshness: Freshness


@dataclass(slots=True)
class ConflictInfo:
    divergence_pct: float
    views: list[SourceView]


@dataclass(slots=True)
class ConsolidatedQuote:
    """The single trustworthy quote the rest of the system consumes."""

    symbol: str
    price: float
    prev_close: float
    as_of: datetime
    received_at: datetime
    source: str
    freshness: Freshness
    volume: int
    day_high: Optional[float]
    day_low: Optional[float]
    currency: str
    conflict: Optional[ConflictInfo] = None
    sources: list[SourceView] = field(default_factory=list)

    @property
    def day_change_pct(self) -> float:
        return safe_pct_change(self.price, self.prev_close)


class SymbolStats:
    """Rolling per-symbol statistics — the memory that makes moves interpretable."""

    def __init__(self, inst: Instrument, window: int):
        self.instrument = inst
        self.returns: deque[float] = deque(maxlen=window)  # per-tick % returns
        self.last_price: Optional[float] = None
        self.last_stat_as_of: Optional[datetime] = None
        self.session_open: Optional[float] = None
        self.ticks_since_open: int = 0
        self.day_high: float = inst.base_price
        self.day_low: float = inst.base_price
        self.week52_high: float = inst.week52_high
        self.week52_low: float = inst.week52_low
        self.prev_close: float = inst.prev_close
        self.last_volume: int = 0
        self.vol_deltas: deque[int] = deque(maxlen=window)  # per-tick volume increments
        self.last_vol_delta: int = 0

    @property
    def sigma_per_tick(self) -> float:
        """Std-dev of recent per-tick % returns. 0.0 until we have >= 2 samples."""
        if len(self.returns) < 2:
            return 0.0
        return statistics.pstdev(self.returns)

    @property
    def samples(self) -> int:
        return len(self.returns)


class MarketEngine:
    def __init__(
        self,
        instruments: list[Instrument],
        source_priority: list[str],
        cfg: SignificanceConfig | None = None,
        window: int | None = None,
    ):
        self.cfg = cfg or settings.significance
        self.instruments = {i.symbol: i for i in instruments}
        self.source_priority = source_priority  # index 0 = most trusted
        self._window = window or settings.returns_window
        # latest[symbol][source] = Quote (only what passed the monotonic guard)
        self._latest: dict[str, dict[str, Quote]] = {s: {} for s in self.instruments}
        self._stats: dict[str, SymbolStats] = {
            s: SymbolStats(i, self._window) for s, i in self.instruments.items()
        }
        # observability counters
        self.ticks_ingested = 0
        self.rejected_out_of_order = 0
        self.conflicts_detected = 0

    # ------------------------------------------------------------------ ingest
    def ingest(self, quotes: list[Quote], now: datetime) -> None:
        now = ensure_utc(now)
        self.ticks_ingested += 1
        affected: set[str] = set()
        for q in quotes:
            if q.symbol not in self._latest:
                continue  # unknown symbol — ignore rather than trust it
            prior = self._latest[q.symbol].get(q.source)
            # Monotonic guard: never let an older/duplicate tick from the SAME
            # source overwrite a newer one. This is how we survive out-of-order
            # delivery and redelivery without corrupting state.
            if prior is not None and ensure_utc(q.as_of) <= ensure_utc(prior.as_of):
                self.rejected_out_of_order += 1
                continue
            self._latest[q.symbol][q.source] = Quote(
                symbol=q.symbol, price=q.price, prev_close=q.prev_close, as_of=q.as_of,
                source=q.source, volume=q.volume, day_high=q.day_high, day_low=q.day_low,
                currency=q.currency, received_at=now,
            )
            affected.add(q.symbol)
        for sym in affected:
            self._update_stats(sym, now)

    def _update_stats(self, symbol: str, now: datetime) -> None:
        c = self.consolidate(symbol, now)
        if c is None:
            return
        st = self._stats[symbol]
        # Only fold each genuinely-new consolidated observation in once.
        if st.last_stat_as_of is not None and ensure_utc(c.as_of) <= ensure_utc(st.last_stat_as_of):
            return
        if c.conflict is not None:  # count once per genuinely-new tick, not per read
            self.conflicts_detected += 1
        if st.session_open is None:
            st.session_open = c.price
        if st.last_price is not None and st.last_price > 0:
            st.returns.append(safe_pct_change(c.price, st.last_price))
        st.last_price = c.price
        st.last_stat_as_of = c.as_of
        st.ticks_since_open += 1
        st.day_high = max(st.day_high, c.price)
        st.day_low = min(st.day_low, c.price)
        st.week52_high = max(st.week52_high, c.price)
        st.week52_low = min(st.week52_low, c.price)
        # Track the per-tick volume increment (for spike detection). Cumulative
        # volume is monotonic truth; a *lagged* winner can report a smaller number,
        # which is not a real increment — ignore it rather than recording a spurious
        # zero delta (which would dilute the spike baseline).
        prev_vol = st.last_volume
        if c.volume >= prev_vol:
            if prev_vol > 0:
                st.last_vol_delta = c.volume - prev_vol
                st.vol_deltas.append(st.last_vol_delta)
            st.last_volume = c.volume
        st.prev_close = c.prev_close

    # ------------------------------------------------------------- consolidate
    def consolidate(self, symbol: str, now: datetime) -> Optional[ConsolidatedQuote]:
        """Merge all sources for a symbol into one quote, deterministically.

        Winner = freshest first, then most-trusted source, then most-recent as_of.
        If two non-stale sources disagree beyond tolerance we still pick a winner
        (so the UI never blanks) but flag CONFLICT so the disagreement is visible.
        """
        now = ensure_utc(now)
        per_source = self._latest.get(symbol) or {}
        if not per_source:
            return None

        views: list[SourceView] = []
        for src, q in per_source.items():
            views.append(SourceView(src, q.price, ensure_utc(q.as_of), q.freshness(now, self.cfg)))

        def priority(src: str) -> int:
            try:
                return self.source_priority.index(src)
            except ValueError:
                return len(self.source_priority)

        fresh_rank = {Freshness.FRESH: 0, Freshness.DELAYED: 1, Freshness.STALE: 2}
        winner_src = min(
            per_source,
            key=lambda s: (
                fresh_rank[per_source[s].freshness(now, self.cfg)],
                priority(s),
                -ensure_utc(per_source[s].as_of).timestamp(),
            ),
        )
        w = per_source[winner_src]

        # Conflict is disagreement between sources we currently *trust as live*.
        # A delayed/stale source is expected to differ (it is simply behind), so it
        # is excluded — otherwise every lagging feed would look like a conflict.
        fresh = [v for v in views if v.freshness == Freshness.FRESH]
        conflict: Optional[ConflictInfo] = None
        if len(fresh) >= 2:
            hi = max(fresh, key=lambda v: v.price).price
            lo = min(fresh, key=lambda v: v.price).price
            divergence = safe_pct_change(hi, lo)
            if abs(divergence) > self.cfg.conflict_tolerance_pct:
                # NB: consolidate() is a pure read — the conflict *counter* is bumped
                # once per tick in _update_stats, not here (this runs on every read).
                conflict = ConflictInfo(divergence_pct=round(divergence, 3), views=fresh)

        return ConsolidatedQuote(
            symbol=symbol, price=w.price, prev_close=w.prev_close, as_of=ensure_utc(w.as_of),
            received_at=ensure_utc(w.received_at or now), source=w.source,
            freshness=w.freshness(now, self.cfg), volume=w.volume, day_high=w.day_high,
            day_low=w.day_low, currency=w.currency, conflict=conflict, sources=views,
        )

    # ---------------------------------------------------------------- accessors
    def stats(self, symbol: str) -> Optional[SymbolStats]:
        return self._stats.get(symbol)

    def snapshot(self, now: datetime, symbols: Optional[list[str]] = None) -> dict[str, ConsolidatedQuote]:
        syms = symbols or list(self.instruments)
        out: dict[str, ConsolidatedQuote] = {}
        for s in syms:
            c = self.consolidate(s, now)
            if c is not None:
                out[s] = c
        return out

    def reset_counters(self) -> None:
        """Zero observability counters (used after warmup so metrics reflect live run)."""
        self.ticks_ingested = 0
        self.rejected_out_of_order = 0
        self.conflicts_detected = 0

    def health(self) -> dict[str, int]:
        return {
            "ticks_ingested": self.ticks_ingested,
            "rejected_out_of_order": self.rejected_out_of_order,
            "conflicts_detected": self.conflicts_detected,
            "symbols": len(self.instruments),
        }
