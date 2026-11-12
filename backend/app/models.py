"""ORM models.

Note the two persistence ideas that make the product work across sessions/devices:

  * ``SeenState`` — per user, per symbol: the price and time the user last "saw" a
    symbol. This is the anchor for "what changed since you last looked". Because it
    is keyed by user (not device/session), opening the app on another device shows a
    consistent baseline.

  * ``SignalLog`` — an append-only, hash-chained record of every material market
    event. Each row's hash covers the previous row's hash, so the history is
    tamper-evident: a returning user can trust the "while you were away" feed, and
    ``verify_chain`` proves the log was not edited after the fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    watchlists: Mapped[list["Watchlist"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="My Watchlist")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="watchlists")
    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", order_by="WatchlistItem.sort_order"
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    alert_above: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    alert_below: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")


class SeenState(Base):
    """The "since you last checked" anchor — one row per (user, symbol)."""

    __tablename__ = "seen_state"
    __table_args__ = (UniqueConstraint("user_id", "symbol", name="uq_user_symbol_seen"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    baseline_price: Mapped[float] = mapped_column(Float)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SignalLog(Base):
    """Append-only, hash-chained log of material market events (global / symbol-level)."""

    __tablename__ = "signal_log"
    __table_args__ = (Index("ix_signal_symbol_created", "symbol", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, unique=True, index=True)  # dense chain position
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(8))
    score: Mapped[float] = mapped_column(Float)
    magnitude_pct: Mapped[float] = mapped_column(Float, default=0.0)
    z: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String(256))
    dedup_key: Mapped[str] = mapped_column(String(96), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), index=True)
