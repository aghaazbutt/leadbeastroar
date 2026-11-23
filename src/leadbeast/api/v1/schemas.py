"""Pydantic v2 schemas for v1 API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from leadbeast.db.models import (
    CampaignStatus,
    Confidence,
    DraftStatus,
    EvidenceState,
    LeadClass,
    OutcomeKind,
)


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


class CampaignIn(BaseModel):
    name: str
    pack_key: str = Field(default="visibility_gap")
    targeting: dict[str, object] = Field(default_factory=dict)
    budget_cents_month: int = 0


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    status: CampaignStatus
    pack_id: uuid.UUID
    targeting: dict[str, object]
    budget_cents_month: int
    created_at: datetime
    updated_at: datetime


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    website: str | None
    phone: str | None
    email: str | None
    city: str | None
    region: str | None
    country: str | None
    category: str | None


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    signal: str
    state: EvidenceState
    value: dict[str, object] | None
    source_key: str
    detector_version: str | None
    confidence: Confidence
    ai_extracted: bool
    observed_at: datetime


class ScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    business_id: uuid.UUID
    campaign_id: uuid.UUID
    score: int
    lead_class: LeadClass
    confidence: Confidence
    sub_scores: dict[str, int]
    reasons: list[dict[str, object]]
    pack_version: str
    evidence_hash: str
    created_at: datetime


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    business_id: uuid.UUID
    campaign_id: uuid.UUID
    channel: str
    subject: str | None
    body: str
    status: DraftStatus
    sent_at: datetime | None
    created_at: datetime


class DraftApproveIn(BaseModel):
    edited_body: str | None = None


class OutcomeIn(BaseModel):
    draft_id: uuid.UUID
    kind: OutcomeKind
    note: str | None = None


class OutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    draft_id: uuid.UUID
    kind: OutcomeKind
    note: str | None
    observed_at: datetime


class HealthOut(BaseModel):
    key: str
    status: Literal["healthy", "slow", "degraded", "off"]
    detail: str = ""


class CostSummary(BaseModel):
    per_run_cents: int
    per_day_cents: int
    per_month_cents: int
    cap_per_run_cents: int
    cap_per_day_cents: int
    cap_per_month_cents: int


class MarketSummary(BaseModel):
    found: int
    passed_filters: int
    approved: int
    sent: int
    replied: int
    won: int
    gap_distribution: dict[str, int]
