"""Configuration and — most importantly — the *operating points* of the system.

Every threshold here is a product decision, not a magic number. They are grouped,
named and commented so they can be defended in a review and tuned without touching
logic. This mirrors the "choose the operating point deliberately" discipline from
the ML work: the thresholds ARE the definition of "meaningful".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SignificanceConfig:
    """Defines what "meaningful" means. See ``significance.py`` for how it is used.

    Philosophy: a price move matters relative to *that stock's own* normal
    behaviour, not as a flat percentage. A 1.5% day is huge for a sleepy large-cap
    and noise for a volatile small-cap. So a move must clear BOTH bars to count:

      1. an absolute floor (kills rounding noise / micro-moves), AND
      2. a volatility-normalised bar (z-score vs the stock's recent realised vol).
    """

    # --- price move ---------------------------------------------------------
    min_abs_move_pct: float = 0.5      # floor: ignore moves smaller than this, always
    min_samples_for_z: int = 10        # need this many returns before trusting sigma
    sigma_notable: float = 1.0         # |z| >= 1  -> begins to matter
    sigma_major: float = 3.0           # |z| >= 3  -> saturates the move score
    move_score_at_major: float = 60.0  # score contributed by a "major" (|z|>=3) move
    # Cap the volatility-extrapolation horizon: sigma is estimated from a finite
    # window, so projecting it across an ever-growing tick count (sqrt-time) would
    # steadily inflate the expected move and blind us. Never extrapolate beyond the
    # window that produced sigma.
    max_horizon_ticks: int = 120

    # --- discrete events (each adds to the attention score) -----------------
    alert_cross_score: float = 40.0    # user's own price alert crossed (very intentional)
    week52_break_score: float = 35.0   # new 52-week high / low
    gap_score: float = 15.0            # overnight gap vs previous close
    gap_min_pct: float = 2.0
    volume_spike_score: float = 10.0
    volume_spike_mult: float = 1.8     # today's volume >= this x typical for the time of day

    # --- bucketing ----------------------------------------------------------
    meaningful_threshold: float = 25.0  # attention_score at/above this => surface it
    high_threshold: float = 60.0        # >= high => "high" severity in the UI

    # --- data quality (freshness / conflict) --------------------------------
    delayed_after_seconds: float = 6.0    # freshest quote older than this => DELAYED
    stale_after_seconds: float = 15.0     # ...older than this => STALE (do not trust as live)
    conflict_tolerance_pct: float = 0.75  # two fresh sources diverging beyond => CONFLICT


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Env-overridable so the same code runs in tests, dev and
    a container without edits."""

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./watchlist.db")
    tick_interval_seconds: float = float(os.getenv("TICK_INTERVAL_SECONDS", "2.0"))
    returns_window: int = int(os.getenv("RETURNS_WINDOW", "120"))  # returns kept per symbol for vol
    sim_seed: int = int(os.getenv("SIM_SEED", "42"))               # deterministic simulator
    enable_price_loop: bool = os.getenv("ENABLE_PRICE_LOOP", "1") == "1"  # off in tests
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-insecure-secret-change-me-in-production")
    token_ttl_hours: int = int(os.getenv("TOKEN_TTL_HOURS", "12"))          # shorter-lived session token
    stream_token_ttl_seconds: int = int(os.getenv("STREAM_TOKEN_TTL_SECONDS", "1800"))  # SSE-only, scoped
    app_env: str = os.getenv("APP_ENV", "dev")                             # "prod" enforces a real secret
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    significance: SignificanceConfig = field(default_factory=SignificanceConfig)

    @property
    def using_insecure_default_secret(self) -> bool:
        return self.jwt_secret.startswith("dev-only-insecure")


settings = Settings()

