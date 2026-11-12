"""The significance ("attention") engine — the heart of the product.

A watchlist's real job is not to show numbers; it is to decide **what deserves
attention right now** and **what meaningfully changed since you last looked**. That
is a policy problem, so this module is a deterministic, explainable rules engine:
pure functions in, scored + human-readable ``Signal`` objects out. No I/O, no clock
of its own — everything is passed in — which is exactly what makes it exhaustively
unit-testable.

Definition of "meaningful": a move must clear BOTH an absolute floor AND a
volatility-normalised bar (a z-score against the stock's own recent realised vol,
scaled to the horizon of the move). A 1.5% move is major for a calm large-cap and
noise for a jumpy small-cap — flat % thresholds cannot tell those apart; this can.
Every threshold lives in ``SignificanceConfig`` and every signal carries a ``reason``
string, so the user is never asked to trust a black box.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from .config import SignificanceConfig
from .market.engine import ConsolidatedQuote, SymbolStats
from .util import clamp, expected_sigma, safe_pct_change, to_iso


class SignalType(str, Enum):
    MOVE_SINCE_SEEN = "MOVE_SINCE_SEEN"   # per-user: change since you last looked
    INTRADAY_MOVE = "INTRADAY_MOVE"       # symbol-level: unusual move today
    ALERT_CROSSED = "ALERT_CROSSED"       # your own price alert was crossed
    WEEK52_HIGH = "WEEK52_HIGH"
    WEEK52_LOW = "WEEK52_LOW"
    GAP = "GAP"                           # overnight gap vs previous close
    VOLUME_SPIKE = "VOLUME_SPIKE"


# Signals that are *always* worth surfacing, regardless of numeric score.
HARD_SIGNALS = {SignalType.ALERT_CROSSED, SignalType.WEEK52_HIGH, SignalType.WEEK52_LOW}


@dataclass(slots=True)
class Signal:
    type: SignalType
    direction: str            # "up" | "down" | "neutral"
    score: float              # contribution to the attention score (0..100)
    reason: str               # human-readable, shown directly in the UI
    magnitude_pct: float = 0.0
    z: Optional[float] = None
    as_of: Optional[datetime] = None

    @property
    def dedup_key(self) -> str:
        """Identity for the append-only log so a *standing* condition is logged
        once, while a *worsening* move (each additional whole %) logs again."""
        if self.type in (SignalType.MOVE_SINCE_SEEN, SignalType.INTRADAY_MOVE):
            return f"{self.type.value}:{self.direction}:{round(self.magnitude_pct)}"
        return f"{self.type.value}:{self.direction}"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        d["as_of"] = to_iso(self.as_of) if self.as_of else None
        return d


@dataclass(slots=True)
class Baseline:
    """What the user last saw for a symbol (the "since you last checked" anchor)."""

    price: float
    seen_at: datetime


@dataclass(slots=True)
class AttentionResult:
    symbol: str
    attention_score: float
    severity: str                       # "high" | "medium" | "low" | "none"
    is_meaningful: bool
    signals: list[Signal] = field(default_factory=list)
    since_seen: Optional[dict] = None   # populated when a baseline exists
    primary_reason: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "attention_score": round(self.attention_score, 1),
            "severity": self.severity,
            "is_meaningful": self.is_meaningful,
            "primary_reason": self.primary_reason,
            "since_seen": self.since_seen,
            "signals": [s.as_dict() for s in self.signals],
        }


# --------------------------------------------------------------------- helpers
def _move_signal(
    change_pct: float,
    n_ticks: float,
    stats: SymbolStats,
    cfg: SignificanceConfig,
    sig_type: SignalType,
    horizon_label: str,
    as_of: datetime,
) -> Optional[Signal]:
    """Score a price move, normalised by the stock's own volatility over the
    move's horizon. Returns None if the move is below the floor or, when we have
    enough history, below the z-score bar."""
    if abs(change_pct) < cfg.min_abs_move_pct:
        return None
    direction = "up" if change_pct > 0 else "down"
    sign = "+" if change_pct >= 0 else ""

    if stats.samples >= cfg.min_samples_for_z and stats.sigma_per_tick > 0:
        # Never extrapolate volatility beyond the window that produced sigma, else a
        # long horizon (e.g. hours into the session) silently inflates the expected
        # move and blinds us to real ones.
        exp = expected_sigma(stats.sigma_per_tick, min(n_ticks, cfg.max_horizon_ticks))
        z = change_pct / exp if exp > 0 else 0.0
        if abs(z) < cfg.sigma_notable:
            return None  # a move within its own normal range is not news
        score = clamp(abs(z) / cfg.sigma_major, 0.0, 1.0) * cfg.move_score_at_major
        reason = f"{sign}{change_pct:.2f}% {horizon_label} — {abs(z):.1f}σ vs its usual move"
        return Signal(sig_type, direction, round(score, 1), reason, round(change_pct, 3), round(z, 2), as_of)

    # Fallback before we have enough history to trust sigma: absolute move only.
    score = clamp(abs(change_pct) / 3.0, 0.0, 1.0) * cfg.move_score_at_major
    reason = f"{sign}{change_pct:.2f}% {horizon_label} (limited history)"
    return Signal(sig_type, direction, round(score, 1), reason, round(change_pct, 3), None, as_of)


def _week52_signals(c: ConsolidatedQuote, stats: SymbolStats, cfg: SignificanceConfig) -> list[Signal]:
    out: list[Signal] = []
    # stats.week52_* already includes the current price, so ">=" means "at its high/low now".
    if c.price >= stats.week52_high * (1 - 1e-9):
        out.append(Signal(SignalType.WEEK52_HIGH, "up", cfg.week52_break_score,
                          f"At a 52-week high (₹{c.price:,.2f})", c.day_change_pct, None, c.as_of))
    if c.price <= stats.week52_low * (1 + 1e-9):
        out.append(Signal(SignalType.WEEK52_LOW, "down", cfg.week52_break_score,
                          f"At a 52-week low (₹{c.price:,.2f})", c.day_change_pct, None, c.as_of))
    return out


def _gap_signal(stats: SymbolStats, cfg: SignificanceConfig, as_of: datetime) -> Optional[Signal]:
    if stats.session_open is None:
        return None
    gap = safe_pct_change(stats.session_open, stats.prev_close)
    if abs(gap) < cfg.gap_min_pct:
        return None
    direction = "up" if gap > 0 else "down"
    return Signal(SignalType.GAP, direction, cfg.gap_score,
                  f"Gapped {'+' if gap >= 0 else ''}{gap:.2f}% at open", round(gap, 3), None, as_of)


def _volume_signal(stats: SymbolStats, cfg: SignificanceConfig, as_of: datetime) -> Optional[Signal]:
    deltas = list(stats.vol_deltas)
    if len(deltas) < cfg.min_samples_for_z:
        return None
    avg = statistics.fmean(deltas)
    if avg <= 0 or stats.last_vol_delta < cfg.volume_spike_mult * avg:
        return None
    ratio = stats.last_vol_delta / avg
    return Signal(SignalType.VOLUME_SPIKE, "neutral", cfg.volume_spike_score,
                  f"Volume {ratio:.1f}× its recent pace", round(ratio, 2), None, as_of)


def _alert_signals(
    c: ConsolidatedQuote, baseline: Optional[Baseline],
    alert_above: Optional[float], alert_below: Optional[float], cfg: SignificanceConfig,
) -> list[Signal]:
    out: list[Signal] = []
    if alert_above is not None:
        crossed = baseline is not None and baseline.price < alert_above <= c.price
        standing = baseline is None and c.price >= alert_above
        if crossed or standing:
            verb = "Crossed" if crossed else "Above"
            out.append(Signal(SignalType.ALERT_CROSSED, "up", cfg.alert_cross_score,
                              f"{verb} your ₹{alert_above:,.2f} alert (now ₹{c.price:,.2f})",
                              safe_pct_change(c.price, alert_above), None, c.as_of))
    if alert_below is not None:
        crossed = baseline is not None and baseline.price > alert_below >= c.price
        standing = baseline is None and c.price <= alert_below
        if crossed or standing:
            verb = "Fell below" if crossed else "Below"
            out.append(Signal(SignalType.ALERT_CROSSED, "down", cfg.alert_cross_score,
                              f"{verb} your ₹{alert_below:,.2f} alert (now ₹{c.price:,.2f})",
                              safe_pct_change(c.price, alert_below), None, c.as_of))
    return out


def _aggregate(symbol: str, signals: list[Signal], since_seen: Optional[dict], cfg: SignificanceConfig) -> AttentionResult:
    signals = sorted(signals, key=lambda s: s.score, reverse=True)
    score = clamp(sum(s.score for s in signals), 0.0, 100.0)
    has_hard = any(s.type in HARD_SIGNALS for s in signals)
    is_meaningful = score >= cfg.meaningful_threshold or has_hard
    if score >= cfg.high_threshold or has_hard:
        severity = "high"
    elif score >= cfg.meaningful_threshold:
        severity = "medium"
    elif score > 0:
        severity = "low"
    else:
        severity = "none"
    return AttentionResult(
        symbol=symbol, attention_score=score, severity=severity, is_meaningful=is_meaningful,
        signals=signals, since_seen=since_seen,
        primary_reason=signals[0].reason if signals else None,
    )


# ----------------------------------------------------------------- public API
def evaluate_symbol_events(
    c: ConsolidatedQuote, stats: SymbolStats, cfg: SignificanceConfig,
) -> list[Signal]:
    """Symbol-level, user-independent signals for the append-only activity log.

    Computed once per tick per symbol in the hot loop (not once per user) — this
    is what keeps the fan-out O(symbols), not O(users × symbols)."""
    signals: list[Signal] = []
    # Anchor the intraday move to the SESSION OPEN (not prev close), so its horizon
    # matches the volatility estimate and the overnight gap isn't double-counted here
    # (the gap gets its own signal via _gap_signal).
    intraday_pct = safe_pct_change(c.price, stats.session_open) if stats.session_open else c.day_change_pct
    mv = _move_signal(intraday_pct, stats.ticks_since_open, stats, cfg,
                      SignalType.INTRADAY_MOVE, "intraday", c.as_of)
    if mv:
        signals.append(mv)
    signals.extend(_week52_signals(c, stats, cfg))
    gap = _gap_signal(stats, cfg, c.as_of)
    if gap:
        signals.append(gap)
    vol = _volume_signal(stats, cfg, c.as_of)
    if vol:
        signals.append(vol)
    return signals


def evaluate_attention(
    c: ConsolidatedQuote,
    stats: SymbolStats,
    baseline: Optional[Baseline],
    cfg: SignificanceConfig,
    *,
    tick_interval_seconds: float,
    now: datetime,
    alert_above: Optional[float] = None,
    alert_below: Optional[float] = None,
) -> AttentionResult:
    """Per-user attention for the watchlist view: everything in the symbol-level
    events PLUS the "since you last checked" move and the user's own price alerts."""
    signals: list[Signal] = []
    since_seen: Optional[dict] = None

    if baseline is not None:
        change_pct = safe_pct_change(c.price, baseline.price)
        seconds_away = max((now - baseline.seen_at).total_seconds(), 0.0)
        n_ticks = seconds_away / max(tick_interval_seconds, 0.001)
        since_seen = {
            "baseline_price": round(baseline.price, 2),
            "current_price": round(c.price, 2),
            "change_pct": round(change_pct, 3),
            "change_abs": round(c.price - baseline.price, 2),
            "seconds_away": round(seconds_away, 1),
            "last_seen_at": to_iso(baseline.seen_at),
        }
        mv = _move_signal(change_pct, n_ticks, stats, cfg,
                          SignalType.MOVE_SINCE_SEEN, "since you last looked", c.as_of)
        if mv:
            signals.append(mv)
    else:
        # Never seen before: anchor to today's intraday move (from session open, to
        # match the volatility horizon) so a brand-new item still explains itself.
        intraday_pct = safe_pct_change(c.price, stats.session_open) if stats.session_open else c.day_change_pct
        mv = _move_signal(intraday_pct, stats.ticks_since_open, stats, cfg,
                          SignalType.MOVE_SINCE_SEEN, "intraday", c.as_of)
        if mv:
            signals.append(mv)

    signals.extend(_alert_signals(c, baseline, alert_above, alert_below, cfg))
    signals.extend(_week52_signals(c, stats, cfg))
    gap = _gap_signal(stats, cfg, c.as_of)
    if gap:
        signals.append(gap)
    vol = _volume_signal(stats, cfg, c.as_of)
    if vol:
        signals.append(vol)

    return _aggregate(c.symbol, signals, since_seen, cfg)
