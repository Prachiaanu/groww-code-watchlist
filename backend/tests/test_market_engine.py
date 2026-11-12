"""Data-quality behaviour of the ingest engine: ordering, freshness, conflict,
winner selection, and rolling statistics."""

from __future__ import annotations

from datetime import timedelta

from app.market.provider import Freshness
from tests.conftest import T0


def test_out_of_order_tick_is_rejected(engine, mkq):
    engine.ingest([mkq("CALM", 1000, T0 + timedelta(seconds=4))], T0 + timedelta(seconds=4))
    # a later-arriving but older tick from the same source must not overwrite
    engine.ingest([mkq("CALM", 999, T0 + timedelta(seconds=2))], T0 + timedelta(seconds=5))
    c = engine.consolidate("CALM", T0 + timedelta(seconds=5))
    assert c.price == 1000
    assert engine.rejected_out_of_order == 1


def test_duplicate_as_of_is_rejected(engine, mkq):
    engine.ingest([mkq("CALM", 1000, T0)], T0)
    engine.ingest([mkq("CALM", 1234, T0)], T0)  # same as_of => duplicate
    c = engine.consolidate("CALM", T0)
    assert c.price == 1000
    assert engine.rejected_out_of_order == 1


def test_freshness_classification(engine, mkq):
    engine.ingest([mkq("CALM", 1000, T0)], T0)
    assert engine.consolidate("CALM", T0 + timedelta(seconds=1)).freshness == Freshness.FRESH
    assert engine.consolidate("CALM", T0 + timedelta(seconds=8)).freshness == Freshness.DELAYED
    assert engine.consolidate("CALM", T0 + timedelta(seconds=30)).freshness == Freshness.STALE


def test_conflict_only_between_fresh_sources(engine, mkq):
    now = T0 + timedelta(seconds=1)
    engine.ingest([mkq("CALM", 1000, T0, source="A")], T0)
    engine.ingest([mkq("CALM", 1010, T0, source="B")], T0)  # +1% > 0.75% tolerance
    c = engine.consolidate("CALM", now)
    assert c.conflict is not None
    assert c.conflict.divergence_pct > 0.75


def test_delayed_source_is_not_a_conflict(engine, mkq):
    # B disagrees but is stale -> it is behind, not conflicting
    engine.ingest([mkq("CALM", 1000, T0 + timedelta(seconds=40), source="A")], T0 + timedelta(seconds=40))
    engine.ingest([mkq("CALM", 1050, T0, source="B")], T0)  # 40s old => stale
    c = engine.consolidate("CALM", T0 + timedelta(seconds=41))
    assert c.conflict is None


def test_winner_prefers_fresh_over_priority(engine, mkq):
    now = T0 + timedelta(seconds=41)
    engine.ingest([mkq("CALM", 1000, T0, source="A")], T0)                       # A: stale
    engine.ingest([mkq("CALM", 1010, now, source="B")], now)                     # B: fresh
    c = engine.consolidate("CALM", now)
    assert c.source == "B" and c.price == 1010


def test_winner_prefers_priority_when_equally_fresh(engine, mkq):
    now = T0 + timedelta(seconds=1)
    engine.ingest([mkq("CALM", 1000, T0, source="A")], T0)
    engine.ingest([mkq("CALM", 1004, T0, source="B")], T0)  # 0.4% < tolerance, no conflict
    c = engine.consolidate("CALM", now)
    assert c.source == "A" and c.price == 1000  # A is higher priority


def test_unknown_symbol_is_ignored(engine, mkq):
    engine.ingest([mkq("NOPE", 1000, T0)], T0)
    assert engine.consolidate("NOPE", T0) is None


def test_rolling_volatility_reflects_input(engine, feed):
    feed("CALM", n=30, d=0.001)   # ~0.1% per-tick moves
    feed("JUMPY", n=30, d=0.02)   # ~2% per-tick moves
    calm, jumpy = engine.stats("CALM"), engine.stats("JUMPY")
    assert calm.samples >= 10 and jumpy.samples >= 10
    assert jumpy.sigma_per_tick > 5 * calm.sigma_per_tick


def test_session_open_and_tick_count(engine, mkq):
    for i, price in enumerate([1000, 1002, 1001, 1005]):
        t = T0 + timedelta(seconds=2 * i)
        engine.ingest([mkq("CALM", price, t)], t)
    st = engine.stats("CALM")
    assert st.session_open == 1000
    assert st.ticks_since_open == 4
    assert st.day_high == 1005 and st.day_low == 1000


def test_volume_delta_tracking(engine, mkq):
    vols = [1000, 2000, 3000, 9000]  # last jump is a spike
    for i, v in enumerate(vols):
        t = T0 + timedelta(seconds=2 * i)
        engine.ingest([mkq("CALM", 1000 + i, t, volume=v)], t)
    st = engine.stats("CALM")
    assert list(st.vol_deltas) == [1000, 1000, 6000]
    assert st.last_vol_delta == 6000
