"""Google Places SourceAdapter — STUB.

Not activated until GOOGLE_PLACES_API_KEY is set in .env. Reports `off`
in health until keys arrive. Interface locked so adding the live impl is
a function body change, not a Protocol change.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from leadbeast.adapters.protocols import HealthReport, SourceAdapter, SourceRecordIn
from leadbeast.config import get_settings


class GooglePlacesAdapter(SourceAdapter):
    key = "google_places"
    cost_cents_per_record = 2  # approx; verify against current Places pricing

    def __init__(self) -> None:
        self._api_key = get_settings().google_places_api_key

    async def fetch(self, *, query: dict[str, object]) -> AsyncIterator[SourceRecordIn]:
        if not self._api_key:
            return
            yield  # pragma: no cover  (makes mypy happy about AsyncIterator)
        raise NotImplementedError(
            "GooglePlacesAdapter.fetch not yet implemented. "
            "Key present but live call not wired. See docs for enabling."
        )

    async def health(self) -> HealthReport:
        if not self._api_key:
            return HealthReport(key=self.key, status="off", detail="GOOGLE_PLACES_API_KEY unset")
        return HealthReport(key=self.key, status="degraded", detail="stub — not implemented")
