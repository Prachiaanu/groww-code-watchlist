"""The market-data seam.

The rest of the system depends only on ``MarketDataProvider``, ``Instrument`` and
``Quote`` — never on where the data came from. That is the whole point: a real
NSE/BSE feed, a delayed vendor, or the bundled simulator are interchangeable, and
we can compose several sources to exercise conflict/staleness handling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from ..config import SignificanceConfig
from ..util import ensure_utc


class Freshness(str, Enum):
    """How much to trust a quote's timeliness, decided at *read* time."""

    FRESH = "FRESH"
    DELAYED = "DELAYED"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class Instrument:
    """Static reference data for a tradable symbol (rarely changes)."""

    symbol: str
    name: str
    sector: str
    # Seeds used by the simulator and as sensible starting reference points.
    # NOTE: order matters — the universe table is built positionally. currency is
    # last (with a default) so a row need only list the numeric seeds.
    base_price: float = 100.0
    prev_close: float = 100.0
    week52_high: float = 120.0
    week52_low: float = 80.0
    avg_daily_volume: int = 1_000_000
    currency: str = "INR"


@dataclass(frozen=True, slots=True)
class Quote:
    """A single price observation for a symbol from one source.

    Carries the three timestamps/fields that make robust data handling possible:
    ``as_of`` (when the data is valid per the source), ``source`` (who said it),
    and — stamped on ingest — ``received_at`` (when we saw it). Everything about
    staleness, ordering and conflict resolution is derived from these.
    """

    symbol: str
    price: float
    prev_close: float
    as_of: datetime
    source: str
    volume: int = 0
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    currency: str = "INR"
    received_at: Optional[datetime] = None  # stamped by the engine on ingest

    def age_seconds(self, now: datetime) -> float:
        return (ensure_utc(now) - ensure_utc(self.as_of)).total_seconds()

    def freshness(self, now: datetime, cfg: SignificanceConfig) -> Freshness:
        age = self.age_seconds(now)
        if age >= cfg.stale_after_seconds:
            return Freshness.STALE
        if age >= cfg.delayed_after_seconds:
            return Freshness.DELAYED
        return Freshness.FRESH

    @property
    def day_change_pct(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close * 100.0


class MarketDataProvider(ABC):
    """Pull-based provider. The engine polls ``poll()`` every tick.

    A push/streaming vendor is adapted by wrapping its callback in a small buffer
    that ``poll()`` drains — the engine contract stays the same.
    """

    #: stable identifier written onto every Quote's ``source`` field
    source_id: str = "abstract"

    @abstractmethod
    def list_instruments(self) -> list[Instrument]:
        """Static universe this provider can quote."""

    @abstractmethod
    def poll(self, now: datetime) -> list[Quote]:
        """Latest quotes as of ``now``. May be empty, delayed, or out of order —
        the engine is responsible for making sense of that."""
