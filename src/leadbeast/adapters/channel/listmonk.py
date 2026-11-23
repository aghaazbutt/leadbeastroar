"""Listmonk channel — STUB."""

from __future__ import annotations

from leadbeast.adapters.protocols import ChannelAdapter, HealthReport, SendResult
from leadbeast.config import get_settings


class ListmonkChannel(ChannelAdapter):
    key = "listmonk"

    def __init__(self) -> None:
        s = get_settings()
        self._ready = bool(s.listmonk_url and s.listmonk_user and s.listmonk_password)

    async def send(
        self,
        *,
        to: str,
        subject: str | None,
        body: str,
        correlation_id: str,
    ) -> SendResult:
        if not self._ready:
            return SendResult(ok=False, external_id=None, error="Listmonk not configured")
        raise NotImplementedError("Listmonk HTTP client not wired yet")

    async def health(self) -> HealthReport:
        if not self._ready:
            return HealthReport(key=self.key, status="off", detail="Listmonk URL/creds not set")
        return HealthReport(key=self.key, status="degraded", detail="stub — not implemented")
