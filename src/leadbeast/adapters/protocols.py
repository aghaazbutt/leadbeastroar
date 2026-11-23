"""Protocols for every external edge.

A Protocol here is the contract a pipeline stage sees. Concrete adapters
(csv, google_places, ses, listmonk, ollama, anthropic, espocrm, weasy) each
implement exactly one Protocol. Contract tests live alongside the Protocol
and run against every registered adapter.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from leadbeast.db.models import Confidence, EvidenceState


# --- Shared value objects -----------------------------------------------


@dataclass(frozen=True)
class HealthReport:
    key: str
    status: Literal["healthy", "slow", "degraded", "off"]
    detail: str = ""
    latency_ms: int | None = None
    checked_at: datetime | None = None


@dataclass(frozen=True)
class SourceRecordIn:
    source_key: str
    external_id: str
    name: str
    website: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    category: str | None = None
    employee_count_est: int | None = None
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectorResult:
    signal: str
    state: EvidenceState
    value: dict[str, object] | None = None
    confidence: Confidence = Confidence.MEDIUM
    ai_extracted: bool = False
    ai_span: str | None = None
    detector_version: str = "0.1.0"
    cost_cents: int = 0


@dataclass(frozen=True)
class DraftRequest:
    business_id: uuid.UUID
    campaign_id: uuid.UUID
    channel: Literal["email", "call", "linkedin"]
    offer_summary: str
    evidence: dict[str, object]
    recipient_name: str | None = None


@dataclass(frozen=True)
class SendResult:
    ok: bool
    external_id: str | None
    error: str | None = None


# --- Protocols ----------------------------------------------------------


@runtime_checkable
class SourceAdapter(Protocol):
    key: str
    cost_cents_per_record: int

    async def fetch(self, *, query: dict[str, object]) -> AsyncIterator[SourceRecordIn]: ...
    async def health(self) -> HealthReport: ...


@runtime_checkable
class ContactProvider(Protocol):
    key: str

    async def enrich(self, *, business_id: uuid.UUID) -> dict[str, object]: ...
    async def health(self) -> HealthReport: ...


@runtime_checkable
class CrmAdapter(Protocol):
    key: str

    async def upsert_business(
        self, *, business_id: uuid.UUID, fields: dict[str, object]
    ) -> str: ...
    async def health(self) -> HealthReport: ...


@runtime_checkable
class ChannelAdapter(Protocol):
    key: str

    async def send(
        self,
        *,
        to: str,
        subject: str | None,
        body: str,
        correlation_id: str,
    ) -> SendResult: ...
    async def health(self) -> HealthReport: ...


@runtime_checkable
class ModelClient(Protocol):
    key: str

    async def generate(
        self, *, system: str, prompt: str, max_tokens: int = 1024
    ) -> str: ...
    async def health(self) -> HealthReport: ...


@runtime_checkable
class ReportRenderer(Protocol):
    key: str

    async def render_pdf(self, *, template: str, context: dict[str, object]) -> bytes: ...


@runtime_checkable
class DetectorProtocol(Protocol):
    signal: str
    version: str
    cost_cents: int
    window_days: int
    needs_render: bool

    async def run(self, *, business: dict[str, object]) -> Iterable[DetectorResult]: ...
