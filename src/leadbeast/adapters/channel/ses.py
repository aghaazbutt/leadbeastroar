"""Amazon SES channel — STUB.

Activated when LB_CHANNEL_PROVIDER=ses and AWS creds + SES_FROM_EMAIL are set.
"""

from __future__ import annotations

from leadbeast.adapters.protocols import ChannelAdapter, HealthReport, SendResult
from leadbeast.config import get_settings


class SesChannel(ChannelAdapter):
    key = "ses"

    def __init__(self) -> None:
        s = get_settings()
        self._ready = bool(s.aws_access_key_id and s.aws_secret_access_key and s.ses_from_email)

    async def send(
        self,
        *,
        to: str,
        subject: str | None,
        body: str,
        correlation_id: str,
    ) -> SendResult:
        if not self._ready:
            return SendResult(ok=False, external_id=None, error="SES credentials not configured")
        raise NotImplementedError("SES client not wired yet; add boto3 + aiobotocore")

    async def health(self) -> HealthReport:
        if not self._ready:
            return HealthReport(key=self.key, status="off", detail="AWS creds / sender not set")
        return HealthReport(key=self.key, status="degraded", detail="stub — not implemented")
