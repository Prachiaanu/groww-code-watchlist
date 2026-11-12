"""A deterministic market simulator.

Design choice worth defending: instead of two unrelated random feeds, there is ONE
ground-truth price process (``MarketSimulation``) and each ``SimulatedProvider`` is
an *imperfect view* of it — it can lag, add measurement noise, or drop a symbol.
That is what real multi-vendor setups look like, and it means staleness, delay and
cross-source conflict emerge naturally (and reproducibly) instead of being faked.

Why simulated at all? A free, real Indian-equity websocket that judges can run
without keys or rate limits does not exist. Hiding the data source behind
``MarketDataProvider`` lets us (a) run fully offline and deterministically, (b) unit
test messy-data handling precisely, and (c) swap in a real vendor by writing one
class. The trade-off — no real prices — is the right one for a 72-hour, must-run
submission, and is called out honestly in the README.
"""

from __future__ import annotations

import math
import random
from datetime import datetime
from typing import Optional

from ..config import settings
from ..util import ensure_utc
from .provider import Instrument, MarketDataProvider, Quote

# A slice of the NSE. Prices are plausible starting points, clearly simulated.
INDIA_UNIVERSE: list[Instrument] = [
    #          symbol         name                         sector          base     prevc    w52hi    w52lo    avgvol
    Instrument("RELIANCE",   "Reliance Industries",       "Energy",       2850.0,  2831.0,  3024.0,  2220.0, 8_000_000),
    Instrument("TCS",        "Tata Consultancy Services", "IT",           3905.0,  3888.0,  4254.0,  3311.0, 2_500_000),
    Instrument("HDFCBANK",   "HDFC Bank",                 "Financials",   1662.0,  1655.0,  1794.0,  1363.0, 15_000_000),
    Instrument("INFY",       "Infosys",                   "IT",           1548.0,  1560.0,  1729.0,  1351.0, 7_000_000),
    Instrument("ICICIBANK",  "ICICI Bank",                "Financials",   1152.0,  1148.0,  1257.0,   970.0, 12_000_000),
    Instrument("SBIN",       "State Bank of India",       "Financials",    822.0,   818.0,   912.0,   680.0, 18_000_000),
    Instrument("BHARTIARTL", "Bharti Airtel",             "Telecom",      1402.0,  1395.0,  1499.0,   999.0,  6_000_000),
    Instrument("ITC",        "ITC",                       "FMCG",          441.0,   443.0,   499.0,   399.0, 20_000_000),
    Instrument("LT",         "Larsen & Toubro",           "Infra",        3610.0,  3602.0,  3948.0,  2900.0,  2_000_000),
    Instrument("HINDUNILVR", "Hindustan Unilever",        "FMCG",         2452.0,  2461.0,  2844.0,  2172.0,  1_800_000),
    Instrument("MARUTI",     "Maruti Suzuki",             "Auto",        12810.0, 12750.0, 13675.0,  9738.0,    600_000),
    # Higher-volatility names — their z-score bar is *higher*, so a raw 2% move
    # here is far less "meaningful" than the same move in a large-cap above.
    # TATAMOTORS / ADANIENT open with a >2% gap vs prev close (demonstrates GAP).
    Instrument("TATAMOTORS", "Tata Motors",               "Auto",          988.0,  1012.0,  1179.0,   600.0, 22_000_000),
    Instrument("ADANIENT",   "Adani Enterprises",         "Conglomerate", 3105.0,  3038.0,  3743.0,  2025.0,  4_000_000),
    Instrument("ZOMATO",     "Zomato",                    "Tech",          188.0,   185.0,   298.0,   101.0, 40_000_000),
    Instrument("DMART",      "Avenue Supermarts",         "Retail",       4210.0,  4188.0,  5484.0,  3400.0,    900_000),
    Instrument("WIPRO",      "Wipro",                     "IT",            462.0,   466.0,   545.0,   375.0,  9_000_000),
]

# Per-sector per-tick volatility (std-dev of the per-tick return). Auto/Tech/
# Conglomerate are jumpier than FMCG/IT — this spread is the whole point of
# volatility-normalising "meaningful": the same % move means different things here.
_SECTOR_VOL: dict[str, float] = {
    "Energy": 0.0020, "IT": 0.0016, "Financials": 0.0022, "Telecom": 0.0020,
    "FMCG": 0.0014, "Infra": 0.0022, "Auto": 0.0038, "Conglomerate": 0.0055,
    "Tech": 0.0065, "Retail": 0.0026,
}


def _symbol_seed(global_seed: int, symbol: str) -> int:
    return (global_seed * 1_000_003) ^ (abs(hash(symbol)) & 0xFFFFFFFF)


class MarketSimulation:
    """Ground-truth price process. One per running app; advanced once per tick."""

    def __init__(self, instruments: list[Instrument], seed: int, history: int = 400):
        self.instruments = {i.symbol: i for i in instruments}
        self.tick_count = 0
        self._history_len = history
        self._rng = {i.symbol: random.Random(_symbol_seed(seed, i.symbol)) for i in instruments}
        self._vol = {i.symbol: _SECTOR_VOL.get(i.sector, 0.008) for i in instruments}
        # per-symbol running state
        self._price = {i.symbol: i.base_price for i in instruments}
        self._session_open = {i.symbol: i.base_price for i in instruments}
        self._day_high = {i.symbol: i.base_price for i in instruments}
        self._day_low = {i.symbol: i.base_price for i in instruments}
        self._cum_volume = {i.symbol: 0 for i in instruments}
        # bounded per-symbol history of (as_of, price, cum_volume, day_high, day_low)
        self._hist: dict[str, list[tuple[datetime, float, int, float, float]]] = {
            i.symbol: [] for i in instruments
        }

    def step(self, now: datetime) -> None:
        """Advance every symbol one tick using its own deterministic RNG stream."""
        now = ensure_utc(now)
        self.tick_count += 1
        for sym, inst in self.instruments.items():
            rng = self._rng[sym]
            vol = self._vol[sym]
            drift = 0.00015  # very slight upward drift
            z = rng.gauss(0.0, 1.0)
            new_price = self._price[sym] * math.exp((drift - 0.5 * vol * vol) + vol * z)
            new_price = round(max(new_price, 0.01), 2)
            self._price[sym] = new_price
            self._day_high[sym] = max(self._day_high[sym], new_price)
            self._day_low[sym] = min(self._day_low[sym], new_price)
            # volume grows each tick; occasional deterministic spike (~1 in 40 ticks)
            base_inc = inst.avg_daily_volume / 375.0  # ~ one trading day of minutes
            spike = 6.0 if rng.random() < 0.025 else 1.0
            self._cum_volume[sym] += int(base_inc * (0.5 + rng.random()) * spike)
            h = self._hist[sym]
            h.append((now, new_price, self._cum_volume[sym], self._day_high[sym], self._day_low[sym]))
            if len(h) > self._history_len:
                del h[0 : len(h) - self._history_len]

    def view_at_lag(self, symbol: str, lag_ticks: int) -> Optional[tuple[datetime, float, int, float, float]]:
        """The (as_of, price, volume, high, low) as it was ``lag_ticks`` ago.

        A lagging provider reads an older row, so its ``as_of`` is genuinely older
        and the engine will (correctly) mark it DELAYED or STALE."""
        h = self._hist.get(symbol)
        if not h:
            return None
        idx = len(h) - 1 - max(lag_ticks, 0)
        if idx < 0:
            idx = 0
        return h[idx]


class SimulatedProvider(MarketDataProvider):
    """A view onto a ``MarketSimulation``.

    The primary is clean and authoritative. A ``quirky`` secondary reproduces the
    three ways real vendors misbehave — on *deterministic, staggered* schedules so
    each data-quality state appears cleanly and reproducibly rather than constantly:

      * outage   -> stops quoting a symbol for a stretch; its last quote ages into
                    DELAYED then STALE.
      * bad print -> emits a divergent price for one tick; two FRESH sources now
                    disagree beyond tolerance -> CONFLICT.
      * late tick -> emits a quote stamped in the past; the engine's monotonic guard
                    rejects it (out-of-order).

    ``noise_pct`` adds sub-tolerance jitter so the secondary is realistically *not*
    bit-identical to the primary without ever tripping a false conflict.
    """

    def __init__(self, sim: MarketSimulation, source_id: str, *, quirky: bool = False,
                 noise_pct: float = 0.0, seed: int = 0):
        self.sim = sim
        self.source_id = source_id
        self.quirky = quirky
        self.noise_pct = noise_pct
        self._index = {s: i for i, s in enumerate(sim.instruments)}
        self._noise = random.Random((seed + 1) * 7919 + len(source_id))

    def list_instruments(self) -> list[Instrument]:
        return list(self.sim.instruments.values())

    # deterministic, phase-staggered schedules (functions of tick + symbol index)
    @staticmethod
    def _in_outage(tc: int, i: int) -> bool:
        return ((tc + i * 7) % 70) < 12          # ~17% of the time, staggered per symbol

    @staticmethod
    def _bad_print(tc: int, i: int) -> bool:
        return ((tc + i * 13) % 37) == 0         # ~1 tick in 37 per symbol

    @staticmethod
    def _late_tick(tc: int, i: int) -> bool:
        return ((tc + i * 5) % 53) == 0          # ~1 tick in 53 per symbol

    def poll(self, now: datetime) -> list[Quote]:
        now = ensure_utc(now)
        tc = self.sim.tick_count
        quotes: list[Quote] = []
        for sym, inst in self.sim.instruments.items():
            i = self._index[sym]
            row = self.sim.view_at_lag(sym, 0)
            if row is None:
                continue
            as_of, price, volume, day_high, day_low = row

            if self.quirky:
                if self._in_outage(tc, i):
                    continue  # feed outage: emit nothing; last quote will go stale
                if self._late_tick(tc, i):
                    old = self.sim.view_at_lag(sym, 3)  # a genuinely late/out-of-order tick
                    if old is not None:
                        as_of, price, volume, day_high, day_low = old
                elif self._bad_print(tc, i):
                    price = round(price * 1.013, 2)  # divergent print -> CONFLICT

            if self.noise_pct:
                price = round(price * (1.0 + self._noise.uniform(-self.noise_pct, self.noise_pct)), 2)

            quotes.append(Quote(
                symbol=sym, price=price, prev_close=inst.prev_close, as_of=as_of,
                source=self.source_id, volume=volume, day_high=day_high, day_low=day_low,
                currency=inst.currency,
            ))
        return quotes


def build_default_providers(
    seed: Optional[int] = None,
) -> tuple[MarketSimulation, list[SimulatedProvider]]:
    """A clean authoritative primary plus a realistically-imperfect secondary —
    together they exercise FRESH / DELAYED / STALE / CONFLICT / out-of-order."""
    seed = settings.sim_seed if seed is None else seed
    sim = MarketSimulation(INDIA_UNIVERSE, seed=seed)
    primary = SimulatedProvider(sim, "sim-primary", seed=seed)
    secondary = SimulatedProvider(sim, "sim-secondary", quirky=True, noise_pct=0.0005, seed=seed)
    return sim, [primary, secondary]
