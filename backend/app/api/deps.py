"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from ..services.ticker import MarketRuntime


def get_runtime(request: Request) -> MarketRuntime:
    """The single, shared market runtime created in the app lifespan."""
    return request.app.state.runtime
