"""Append-only, hash-chained activity log.

Each entry's ``hash = sha256(prev_hash | canonical(payload))``, so every row commits
to the entire history before it. Editing or deleting any past event breaks the chain
from that point on, which ``verify_chain`` detects. That is what lets a user who
returns after a week *trust* the "here's what happened while you were away" feed —
it cannot have been quietly rewritten.

Timestamps are stored at second resolution in UTC so the chain is reproducible
across the SQLite round-trip.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import SignalLog
from .significance import Signal
from .util import canonical_json, ensure_utc, now_utc, sha256_hex, to_iso

GENESIS = "GENESIS"


def _payload(seq: int, symbol: str, s_type: str, direction: str, score: float,
             magnitude_pct: float, z: Optional[float], reason: str, dedup_key: str,
             as_of: datetime, created_at: datetime) -> str:
    return canonical_json({
        "seq": seq, "symbol": symbol, "type": s_type, "direction": direction,
        "score": score, "magnitude_pct": magnitude_pct, "z": z, "reason": reason,
        "dedup_key": dedup_key, "as_of": to_iso(as_of), "created_at": to_iso(created_at),
    })


def _row_hash(prev_hash: str, payload: str) -> str:
    return sha256_hex(f"{prev_hash}|{payload}")


def append(session: Session, symbol: str, signal: Signal, *, now: Optional[datetime] = None,
           commit: bool = True) -> SignalLog:
    """Append one material event, extending the hash chain. Caller handles dedup."""
    created_at = (now or now_utc()).replace(microsecond=0, tzinfo=None)
    as_of = ensure_utc(signal.as_of or now_utc()).replace(microsecond=0, tzinfo=None)

    last = session.execute(select(SignalLog).order_by(SignalLog.seq.desc()).limit(1)).scalar_one_or_none()
    prev_hash = last.hash if last else GENESIS
    seq = (last.seq + 1) if last else 1

    payload = _payload(seq, symbol, signal.type.value, signal.direction, signal.score,
                       signal.magnitude_pct, signal.z, signal.reason, signal.dedup_key, as_of, created_at)
    row = SignalLog(
        seq=seq, symbol=symbol, type=signal.type.value, direction=signal.direction,
        score=signal.score, magnitude_pct=signal.magnitude_pct, z=signal.z, reason=signal.reason,
        dedup_key=signal.dedup_key, as_of=as_of, created_at=created_at,
        prev_hash=prev_hash, hash=_row_hash(prev_hash, payload),
    )
    session.add(row)
    # Flush so that multiple appends within one transaction see each other's seq/hash
    # (autoflush is off). Commit is left to the caller when batching a whole tick.
    session.flush()
    if commit:
        session.commit()
    return row


def verify_chain(session: Session) -> dict:
    """Recompute the whole chain and report the first break, if any."""
    rows = session.execute(select(SignalLog).order_by(SignalLog.seq.asc())).scalars().all()
    prev_hash = GENESIS
    for r in rows:
        payload = _payload(r.seq, r.symbol, r.type, r.direction, r.score, r.magnitude_pct,
                           r.z, r.reason, r.dedup_key, r.as_of, r.created_at)
        expected = _row_hash(prev_hash, payload)
        if r.prev_hash != prev_hash or r.hash != expected:
            return {"ok": False, "entries": len(rows), "broken_at_seq": r.seq}
        prev_hash = r.hash
    return {"ok": True, "entries": len(rows), "head_hash": prev_hash if rows else GENESIS}


def query_since(session: Session, symbols: list[str], since: Optional[datetime],
                limit: int = 100) -> list[SignalLog]:
    """Material events for the given symbols, newest first — powers "while you were away"."""
    if not symbols:
        return []
    stmt = select(SignalLog).where(SignalLog.symbol.in_(symbols))
    if since is not None:
        stmt = stmt.where(SignalLog.created_at > ensure_utc(since).replace(tzinfo=None))
    stmt = stmt.order_by(SignalLog.created_at.desc(), SignalLog.seq.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


def query_since_per_symbol(session: Session, cutoffs: dict[str, datetime], limit: int = 100) -> list[SignalLog]:
    """"While you were away", done right: each symbol is filtered against ITS OWN
    review time, and a symbol with no cutoff contributes nothing (the user was never
    away for it). This avoids a single global max(seen_at) hiding events for symbols
    reviewed longer ago — and avoids dumping history on a first-ever visit."""
    if not cutoffs:
        return []
    clauses = [
        and_(SignalLog.symbol == sym, SignalLog.created_at > ensure_utc(cut).replace(tzinfo=None))
        for sym, cut in cutoffs.items()
    ]
    stmt = (
        select(SignalLog).where(or_(*clauses))
        .order_by(SignalLog.created_at.desc(), SignalLog.seq.desc()).limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def row_to_dict(r: SignalLog) -> dict:
    return {
        "seq": r.seq, "symbol": r.symbol, "type": r.type, "direction": r.direction,
        "score": r.score, "magnitude_pct": r.magnitude_pct, "z": r.z, "reason": r.reason,
        "as_of": to_iso(r.as_of), "created_at": to_iso(r.created_at), "hash": r.hash,
    }
