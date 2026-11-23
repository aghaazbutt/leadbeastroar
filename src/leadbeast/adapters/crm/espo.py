"""EspoCRM adapter — STUB."""

from __future__ import annotations

import uuid

from leadbeast.adapters.protocols import CrmAdapter, HealthReport
from leadbeast.config import get_settings


class EspoCrm(CrmAdapter):
    key = "espo"

    def __init__(self) -> None:
        s = get_settings()
        self._ready = bool(s.espocrm_url and s.espocrm_api_key)

    async def upsert_business(self, *, business_id: uuid.UUID, fields: dict[str, object]) -> str:
        if not self._ready:
            raise RuntimeError("EspoCRM not configured")
        raise NotImplementedError("Espo HTTP client not wired yet")

    async def health(self) -> HealthReport:
        if not self._ready:
            return HealthReport(key=self.key, status="off", detail="Espo URL/key not set")
        return HealthReport(key=self.key, status="degraded", detail="stub — not implemented")
