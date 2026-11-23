"""SQLAlchemy models.

Core event-sourced model:
    business           — resolved real-world entity
    source_record      — raw rows from source adapters
    evidence_event     — APPEND-ONLY ledger; one row per observation
    score_snapshot     — IMMUTABLE scoring result tied to evidence state
    campaign / pack    — operator-defined targeting/offer bundle
    draft / outcome    — outreach draft and its downstream outcome
    cost_ledger        — reserve-then-commit spend tracking
    crm_sync           — mapping to EspoCRM (or other CRM) ids

Enforcement: evidence_event has a DB-level `REVOKE UPDATE, DELETE` applied by
migration — the ORM cannot override that even if it tries.
Product rule 12 (AI-cited span required) is a CHECK constraint on evidence_event.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from leadbeast.db.types import uuid7


class Base(DeclarativeBase):
    pass


# --- Enums --------------------------------------------------------------


class EvidenceState(str, enum.Enum):
    OBSERVED_YES = "observed_yes"
    OBSERVED_NO = "observed_no"
    NOT_DETECTED = "not_detected"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"
    INFERRED = "inferred"
    MANUALLY_VERIFIED = "manually_verified"


class LeadClass(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Confidence(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"


class DraftStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    SKIPPED = "skipped"
    SENT = "sent"
    FAILED = "failed"


class OutcomeKind(str, enum.Enum):
    REPLIED = "replied"
    MEETING_BOOKED = "meeting_booked"
    WON = "won"
    LOST = "lost"
    NO_REPLY = "no_reply"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"


class StageName(str, enum.Enum):
    COLLECT = "collect"
    RESOLVE = "resolve"
    VITALITY = "vitality"
    DETECT = "detect"
    AUDIT = "audit"
    SCORE = "score"
    CONTACT = "contact"
    DRAFT = "draft"
    APPROVE = "approve"
    SEND = "send"


# --- Users & auth -------------------------------------------------------


class User(Base):
    __tablename__ = "user_account"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="operator")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- Campaign / pack ----------------------------------------------------


class Pack(Base):
    __tablename__ = "pack"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    offer_summary: Mapped[str] = mapped_column(Text, nullable=False)
    weights: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    detectors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Campaign(Base):
    __tablename__ = "campaign"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    pack_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pack.id"), nullable=False
    )
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaign_status"),
        nullable=False,
        default=CampaignStatus.DRAFT,
    )
    targeting: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    budget_cents_month: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    pack: Mapped[Pack] = relationship()


# --- Business / source --------------------------------------------------


class Business(Base):
    __tablename__ = "business"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    employee_count_est: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_business_normalized_city", "normalized_name", "city"),
    )


class SourceRecord(Base):
    __tablename__ = "source_record"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business.id"), nullable=True
    )
    raw: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("source_key", "external_id", name="uq_source_external"),)


# --- Evidence (append-only) ---------------------------------------------


class EvidenceEvent(Base):
    __tablename__ = "evidence_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business.id"), nullable=False, index=True
    )
    signal: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[EvidenceState] = mapped_column(
        Enum(EvidenceState, name="evidence_state"), nullable=False
    )
    value: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_record.id"), nullable=True
    )
    detector_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[Confidence] = mapped_column(
        Enum(Confidence, name="confidence"), nullable=False, default=Confidence.MEDIUM
    )
    ai_extracted: Mapped[bool] = mapped_column(default=False, nullable=False)
    ai_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evidence_event.id"), nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Product rule 12: AI extraction must cite a span from source text.
        CheckConstraint(
            "ai_extracted = false OR (ai_span IS NOT NULL AND length(ai_span) > 0)",
            name="ck_ai_extracted_requires_span",
        ),
        Index("ix_evidence_business_signal_observed", "business_id", "signal", "observed_at"),
    )


# --- Scoring (immutable) ------------------------------------------------


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business.id"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=False, index=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_class: Mapped[LeadClass] = mapped_column(Enum(LeadClass, name="lead_class"), nullable=False)
    confidence: Mapped[Confidence] = mapped_column(
        Enum(Confidence, name="score_confidence"), nullable=False
    )
    sub_scores: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    reasons: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    pack_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="ck_score_range"),
        Index(
            "ix_score_business_campaign_created",
            "business_id",
            "campaign_id",
            "created_at",
        ),
    )


# --- Drafts / outcomes --------------------------------------------------


class Draft(Base):
    __tablename__ = "draft"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business.id"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[DraftStatus] = mapped_column(
        Enum(DraftStatus, name="draft_status"), nullable=False, default=DraftStatus.PENDING
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("score_snapshot.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "business_id", "campaign_id", "channel", name="uq_draft_business_campaign_channel"
        ),
    )


class Outcome(Base):
    __tablename__ = "outcome"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("draft.id"), nullable=False, index=True
    )
    kind: Mapped[OutcomeKind] = mapped_column(Enum(OutcomeKind, name="outcome_kind"), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# --- Cost ledger --------------------------------------------------------


class CostLedger(Base):
    __tablename__ = "cost_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=True, index=True
    )
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business.id"), nullable=True
    )
    source_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # reserve | commit | refund
    cents: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("kind IN ('reserve','commit','refund')", name="ck_cost_kind"),
    )


# --- CRM sync -----------------------------------------------------------


class CrmSync(Base):
    __tablename__ = "crm_sync"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business.id"), nullable=False, unique=True
    )
    crm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    crm_id: Mapped[str] = mapped_column(String(200), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- Pipeline run tracking ----------------------------------------------


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business.id"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaign.id"), nullable=False, index=True
    )
    stage: Mapped[StageName] = mapped_column(Enum(StageName, name="stage_name"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="started")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "business_id", "campaign_id", "stage", "run_id", name="uq_pipeline_run_idempotency"
        ),
    )


# --- Golden set ---------------------------------------------------------


class GoldenLabel(Base):
    __tablename__ = "golden_label"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    signal: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business.id"), nullable=False
    )
    expected_state: Mapped[EvidenceState] = mapped_column(
        Enum(EvidenceState, name="golden_expected_state"), nullable=False
    )
    labeler: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GoldenRun(Base):
    __tablename__ = "golden_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    signal: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    precision: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    recall: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False)
    passes_gate: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
