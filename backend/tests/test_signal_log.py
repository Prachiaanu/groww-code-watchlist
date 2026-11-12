"""Append-only, hash-chained activity log: integrity and queries."""

from __future__ import annotations

from datetime import timedelta

from app import signals_log
from app.models import SignalLog
from app.significance import Signal, SignalType
from tests.conftest import T0


def _sig(symbol_dir="up", score=30.0, reason="moved", stype=SignalType.INTRADAY_MOVE):
    return Signal(type=stype, direction=symbol_dir, score=score, reason=reason,
                  magnitude_pct=1.0, z=2.0, as_of=T0)


def test_append_builds_valid_chain(mem_session):
    for i in range(3):
        signals_log.append(mem_session, "CALM", _sig(reason=f"e{i}"), now=T0 + timedelta(seconds=i))
    result = signals_log.verify_chain(mem_session)
    assert result["ok"] is True and result["entries"] == 3


def test_seq_is_dense_and_monotonic(mem_session):
    for i in range(4):
        signals_log.append(mem_session, "CALM", _sig(reason=f"e{i}"), now=T0 + timedelta(seconds=i))
    seqs = [r.seq for r in mem_session.query(SignalLog).order_by(SignalLog.seq).all()]
    assert seqs == [1, 2, 3, 4]


def test_tamper_of_a_field_is_detected(mem_session):
    for i in range(3):
        signals_log.append(mem_session, "CALM", _sig(reason=f"e{i}"), now=T0 + timedelta(seconds=i))
    middle = mem_session.query(SignalLog).filter_by(seq=2).one()
    middle.reason = "totally different reason"
    mem_session.commit()
    result = signals_log.verify_chain(mem_session)
    assert result["ok"] is False and result["broken_at_seq"] == 2


def test_deletion_breaks_the_chain(mem_session):
    for i in range(3):
        signals_log.append(mem_session, "CALM", _sig(reason=f"e{i}"), now=T0 + timedelta(seconds=i))
    first = mem_session.query(SignalLog).filter_by(seq=1).one()
    mem_session.delete(first)
    mem_session.commit()
    result = signals_log.verify_chain(mem_session)
    # seq 2 now expects prev_hash == GENESIS, which it is not
    assert result["ok"] is False and result["broken_at_seq"] == 2


def test_query_since_filters_by_symbol_and_time(mem_session):
    signals_log.append(mem_session, "CALM", _sig(reason="old"), now=T0)
    cutoff = T0 + timedelta(seconds=10)
    signals_log.append(mem_session, "CALM", _sig(reason="new"), now=T0 + timedelta(seconds=20))
    signals_log.append(mem_session, "JUMPY", _sig(reason="other"), now=T0 + timedelta(seconds=30))

    rows = signals_log.query_since(mem_session, ["CALM"], since=cutoff, limit=50)
    reasons = [r.reason for r in rows]
    assert reasons == ["new"]  # only CALM, only after cutoff


def test_query_since_none_returns_recent(mem_session):
    for i in range(5):
        signals_log.append(mem_session, "CALM", _sig(reason=f"e{i}"), now=T0 + timedelta(seconds=i))
    rows = signals_log.query_since(mem_session, ["CALM"], since=None, limit=3)
    assert len(rows) == 3  # newest-first, limited
    assert rows[0].reason == "e4"
