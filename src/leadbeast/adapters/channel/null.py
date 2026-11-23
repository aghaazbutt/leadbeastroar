"""Null channel: logs sends and returns success. Safe default for dev/dry-run."""

from __future__ import annotations

import uuid

from leadbeast.adapters.protocols import ChannelAdapter, HealthReport, SendResult
from leadbeast.logging import get_logger

log = get_logger("channel.null")


class NullChannel(ChannelAdapter):
    key = "null"

    async def send(
        self,
        *,
        to: str,
        subject: str | None,
        body: str,
        correlation_id: str,
    ) -> SendResult:
        log.info(
            "channel.null.send",
            to=to,
            subject=subject,
            body_chars=len(body),
            correlation_id=correlation_id,
        )
        return SendResult(ok=True, external_id=str(uuid.uuid4()))

    async def health(self) -> HealthReport:
        return HealthReport(key=self.key, status="healthy", detail="null sink")
