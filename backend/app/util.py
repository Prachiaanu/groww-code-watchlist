"""Small, dependency-free helpers shared across the backend.

Kept deliberately tiny and pure so they are trivial to reason about and test.
Time is always tz-aware UTC; hashing/serialisation is canonical so the
hash-chained signal log (see ``signals_log.py``) is reproducible.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any


def now_utc() -> datetime:
    """Single source of truth for "now". Always tz-aware UTC.

    Centralising this makes the whole system clock-injectable in tests: callers
    pass an explicit ``now`` where determinism matters, and fall back to this.
    """
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    """Coerce a datetime to tz-aware UTC. Naive datetimes are assumed UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt: datetime) -> str:
    """ISO-8601 in UTC with a trailing ``Z`` (what the frontend expects)."""
    return ensure_utc(dt).isoformat().replace("+00:00", "Z")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace.

    Used for hashing — two equal payloads must serialise byte-for-byte identically
    regardless of dict insertion order.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_pct_change(new: float, base: float) -> float:
    """Percentage change new-vs-base, guarding divide-by-zero."""
    if base == 0:
        return 0.0
    return (new - base) / base * 100.0


def expected_sigma(sigma_per_tick: float, n_ticks: float) -> float:
    """Expected std-dev of a cumulative return spanning ``n_ticks``.

    Under a random-walk assumption variance grows linearly with time, so the
    std-dev of a move observed over N ticks is ``sigma_per_tick * sqrt(N)``.
    This is what lets us fairly compare a 5-minute move against a 2-hour move:
    we normalise each by the volatility appropriate to *its own* horizon.
    """
    return sigma_per_tick * math.sqrt(max(n_ticks, 1.0))
