"""Replaceable provider protocols."""

from typing import Protocol

from ..models import Aircraft


class AircraftProvider(Protocol):
    async def nearby(
        self, latitude: float, longitude: float, radius_nm: float
    ) -> list[Aircraft]: ...


class ProviderError(RuntimeError):
    """Recoverable provider failure."""


class BudgetExhausted(ProviderError):
    """The locally enforced daily request budget has been exhausted."""


class RateLimited(ProviderError):
    """The provider returned HTTP 429."""
