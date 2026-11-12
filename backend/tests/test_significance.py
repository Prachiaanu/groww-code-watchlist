"""The significance engine: the definition of "meaningful", its floors and gates,
and the discrete event signals."""

from __future__ import annotations

from datetime import timedelta

from app.config import settings
from app.market.provider import Quote
from app.significance import (
    Baseline, SignalType, evaluate_attention, evaluate_symbol_events,
)
from tests.conftest import T0, make_instrument
from app.market.engine import MarketEngine

CFG = settings.significance


def _apply_move(engine, mkq, symbol, base_price, move_pct, move_time):
    price = round(base_price * (1 + move_pct), 4)
    engine.ingest([mkq(symbol, price, move_time, prev_close=1000)], move_time)
    return engine.consolidate(symbol, move_time)


def test_same_move_meaningful_for_calm_not_jumpy(engine, feed, mkq):
    """The thesis: an identical +1% move is major for a calm stock and noise for a
    volatile one, because 'meaningful' is normalised by each stock's own volatility."""
    last_as_of, _ = feed("CALM", n=30, d=0.001)   # ~0.1%/tick
    feed("JUMPY", n=30, d=0.02)                    # ~2%/tick
    out = {}
    for sym in ("CALM", "JUMPY"):
        base = engine.stats(sym).last_price
        c = _apply_move(engine, mkq, sym, base, 0.01, last_as_of)
        baseline = Baseline(base, last_as_of - timedelta(seconds=2))
        out[sym] = evaluate_attention(c, engine.stats(sym), baseline, CFG,
                                      tick_interval_seconds=2.0, now=last_as_of)
    assert out["CALM"].attention_score > out["JUMPY"].attention_score
    assert out["CALM"].is_meaningful
    assert not out["JUMPY"].is_meaningful


def test_absolute_floor_suppresses_micro_moves(engine, feed, mkq):
    last_as_of, _ = feed("CALM", n=30, d=0.001)
    base = engine.stats("CALM").last_price
    c = _apply_move(engine, mkq, "CALM", base, 0.002, last_as_of)  # 0.2% < 0.5% floor
    res = evaluate_attention(c, engine.stats("CALM"), Baseline(base, last_as_of - timedelta(seconds=2)),
                             CFG, tick_interval_seconds=2.0, now=last_as_of)
    assert not any(s.type == SignalType.MOVE_SINCE_SEEN for s in res.signals)


def test_alert_crossed_is_always_meaningful(engine, feed, mkq):
    last_as_of, _ = feed("CALM", n=30, d=0.001)
    base = engine.stats("CALM").last_price  # ~1000
    c = _apply_move(engine, mkq, "CALM", base, 0.02, last_as_of)  # -> ~1020
    res = evaluate_attention(c, engine.stats("CALM"), Baseline(base, last_as_of - timedelta(seconds=2)),
                             CFG, tick_interval_seconds=2.0, now=last_as_of, alert_above=1010)
    alerts = [s for s in res.signals if s.type == SignalType.ALERT_CROSSED]
    assert alerts and alerts[0].direction == "up"
    assert res.is_meaningful and res.severity == "high"


def test_week52_high_signal(engine, mkq):
    engine.ingest([mkq("CALM", 1250, T0)], T0)  # above the 1200 seeded 52w high
    c = engine.consolidate("CALM", T0)
    events = evaluate_symbol_events(c, engine.stats("CALM"), CFG)
    assert any(s.type == SignalType.WEEK52_HIGH for s in events)


def test_gap_signal(engine, mkq):
    engine.ingest([mkq("CALM", 1030, T0, prev_close=1000)], T0)  # +3% gap vs prev close
    c = engine.consolidate("CALM", T0)
    events = evaluate_symbol_events(c, engine.stats("CALM"), CFG)
    gaps = [s for s in events if s.type == SignalType.GAP]
    assert gaps and gaps[0].direction == "up"


def test_volume_spike_signal(engine, mkq):
    cum = 0
    t = T0
    for i in range(12):
        cum += 1000
        engine.ingest([mkq("CALM", 1000 + i, t, volume=cum)], t)
        t = t + timedelta(seconds=2)
    cum += 6000  # spike
    engine.ingest([mkq("CALM", 1012, t, volume=cum)], t)
    c = engine.consolidate("CALM", t)
    events = evaluate_symbol_events(c, engine.stats("CALM"), CFG)
    assert any(s.type == SignalType.VOLUME_SPIKE for s in events)


def test_attention_score_is_capped_at_100(engine, mkq):
    # New 52-week high + alert crossed + a large move should saturate, not overflow.
    inst = make_instrument("CALM")
    eng = MarketEngine([inst], source_priority=["A"])
    # build a little history around 1000, then leap to a new high
    t = T0
    for i in range(15):
        eng.ingest([mkq("CALM", 1000 + (i % 2), t)], t)
        t = t + timedelta(seconds=2)
    base = eng.stats("CALM").last_price
    eng.ingest([mkq("CALM", 1260, t, prev_close=1000)], t)  # new 52w high, big jump
    c = eng.consolidate("CALM", t)
    res = evaluate_attention(c, eng.stats("CALM"), Baseline(base, t - timedelta(seconds=2)),
                             CFG, tick_interval_seconds=2.0, now=t, alert_above=1100)
    assert res.attention_score == 100.0
    assert res.severity == "high"


def test_since_seen_fields(engine, feed, mkq):
    last_as_of, _ = feed("CALM", n=10, d=0.001)
    base = engine.stats("CALM").last_price
    c = _apply_move(engine, mkq, "CALM", base, 0.01, last_as_of)
    res = evaluate_attention(c, engine.stats("CALM"), Baseline(base, last_as_of - timedelta(seconds=2)),
                             CFG, tick_interval_seconds=2.0, now=last_as_of)
    ss = res.since_seen
    assert ss is not None
    assert ss["baseline_price"] == round(base, 2)
    assert abs(ss["change_pct"] - 1.0) < 0.05
    assert ss["change_abs"] > 0


def test_first_look_has_no_since_seen(engine, feed):
    last_as_of, _ = feed("CALM", n=10, d=0.001)
    c = engine.consolidate("CALM", last_as_of)
    res = evaluate_attention(c, engine.stats("CALM"), None, CFG,
                             tick_interval_seconds=2.0, now=last_as_of)
    assert res.since_seen is None
