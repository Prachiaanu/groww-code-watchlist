"""Pydantic request/response models — the API contract, validated at the edge."""

from __future__ import annotations

from typing import Annotated, Optional

from pydantic import BaseModel, Field, field_validator


# ---- auth ----
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(default="", max_length=120)

    @field_validator("email")
    @classmethod
    def _looks_like_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("invalid email")
        return v


class LoginResponse(BaseModel):
    token: str
    user_id: int
    email: str
    display_name: str


# ---- watchlist mutations ----
class AddItemRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    alert_above: Optional[float] = Field(default=None, gt=0)
    alert_below: Optional[float] = Field(default=None, gt=0)


class UpdateItemRequest(BaseModel):
    alert_above: Optional[float] = Field(default=None, gt=0)
    alert_below: Optional[float] = Field(default=None, gt=0)
    clear_alerts: bool = False


class MarkSeenRequest(BaseModel):
    # If omitted, marks every symbol in the user's watchlist as seen "now".
    # Bounded so a caller can't force an unbounded loop while holding the engine lock.
    symbols: Optional[list[Annotated[str, Field(max_length=32)]]] = Field(default=None, max_length=200)


class InstrumentOut(BaseModel):
    symbol: str
    name: str
    sector: str
    currency: str
