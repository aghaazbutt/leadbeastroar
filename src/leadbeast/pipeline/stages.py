"""Pipeline stage implementations.

Each stage is a plain async function that takes (session, business_id,
campaign_id, run_id) and progresses one unit of work. Workers wrap these in
a `pipeline_run` row for idempotency and error capture.

Side-effect split:
    Collect:  SourceAdapter.fetch → source_record rows
    Resolve:  dedupe/upsert → business row
    Vitality: cheap liveness check (website present) — gates expensive stages
    Detect:   run registered DetectorProtocol instances → evidence_event rows
    Audit:    enforce product rule 12 (AI-cited span) — rechecks persisted data
    Score:    fold() + score() → score_snapshot row (immutable)
    Contact:  ContactProvider.enrich (stub for v1)
    Draft:    ModelClient.generate → draft row (PENDING)
    Approve:  operator action from UI; worker just enforces policy.check()
    Send:     ChannelAdapter.send → marks draft SENT, emits outcome stub
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadbeast.adapters import ChannelAdapter, ModelClient
from leadbeast.adapters.registry import registry
from leadbeast.db.models import (
    Business,
    Campaign,
    Draft,
    DraftStatus,
    EvidenceEvent,
    EvidenceState,
    PipelineRun,
    ScoreSnapshot,
    SourceRecord,
    StageName,
)
from leadbeast.detectors import ALL_DETECTORS
from leadbeast.evidence import fold
from leadbeast.logging import get_logger
from leadbeast.policy import PolicyProfile, check as policy_check
from leadbeast.scoring import score as score_fn

log = get_logger("pipeline.stages")


def _begin_stage(
    session: Session,
    *,
    business_id: uuid.UUID,
    campaign_id: uuid.UUID,
    stage: StageName,
    run_id: uuid.UUID,
) -> PipelineRun | None:
    """Create a pipeline_run row. Returns None if (business, campaign, stage, run)
    already ran (idempotency)."""
    existing = session.execute(
        select(PipelineRun).where(
            PipelineRun.business_id == business_id,
            PipelineRun.campaign_id == campaign_id,
            PipelineRun.stage == stage,
            PipelineRun.run_id == run_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    row = PipelineRun(
        business_id=business_id,
        campaign_id=campaign_id,
        stage=stage,
        run_id=run_id,
        status="running",
    )
    session.add(row)
    session.flush()
    return row


def _finish_stage(session: Session, run_row: PipelineRun, *, error: str | None = None) -> None:
    run_row.finished_at = datetime.now(UTC)
    run_row.status = "failed" if error else "done"
    run_row.error = error
    session.add(run_row)
    session.flush()


# --- Resolve ------------------------------------------------------------


def resolve_business(session: Session, *, source_record_id: uuid.UUID) -> uuid.UUID:
    """Create or match a business from a source_record. Keyed by normalized name + city."""
    rec = session.get(SourceRecord, source_record_id)
    if rec is None:
        raise ValueError(f"SourceRecord {source_record_id} not found")
    if rec.business_id is not None:
        return rec.business_id

    name = str(rec.raw.get("name", "")).strip()
    city = str(rec.raw.get("city") or "").strip() or None
    normalized = _normalize_name(name)

    stmt = select(Business).where(Business.normalized_name == normalized)
    if city:
        stmt = stmt.where(Business.city == city)
    biz = session.execute(stmt).scalar_one_or_none()

    if biz is None:
        biz = Business(
            name=name,
            normalized_name=normalized,
            website=rec.raw.get("website") or None,
            phone=rec.raw.get("phone") or None,
            email=rec.raw.get("email") or None,
            address=rec.raw.get("address") or None,
            city=city,
            region=rec.raw.get("region") or None,
            country=rec.raw.get("country") or None,
            category=rec.raw.get("category") or None,
            latitude=_as_decimal(rec.raw.get("latitude")),
            longitude=_as_decimal(rec.raw.get("longitude")),
            employee_count_est=_as_int(rec.raw.get("employee_count_est")),
        )
        session.add(biz)
        session.flush()

    rec.business_id = biz.id
    session.add(rec)
    session.flush()
    return biz.id


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().strip().split())


def _as_decimal(v: object) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _as_int(v: object) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --- Detect -------------------------------------------------------------


async def detect_stage(
    session: Session,
    *,
    business_id: uuid.UUID,
    campaign_id: uuid.UUID,
    run_id: uuid.UUID,
) -> int:
    row = _begin_stage(
        session,
        business_id=business_id,
        campaign_id=campaign_id,
        stage=StageName.DETECT,
        run_id=run_id,
    )
    if row is None:
        return 0

    try:
        biz = session.get(Business, business_id)
        if biz is None:
            _finish_stage(session, row, error="business not found")
            return 0

        business_blob = {
            "name": biz.name,
            "website": biz.website,
            "phone": biz.phone,
            "email": biz.email,
            "address": biz.address,
            "city": biz.city,
            "region": biz.region,
            "country": biz.country,
        }
        written = 0
        for DetectorCls in ALL_DETECTORS:
            det = DetectorCls()
            results = await det.run(business=business_blob)
            for r in results:
                ev = EvidenceEvent(
                    business_id=business_id,
                    signal=r.signal,
                    state=r.state,
                    value=r.value,
                    source_key=det.key if hasattr(det, "key") else "detector",
                    detector_version=r.detector_version,
                    confidence=r.confidence,
                    ai_extracted=r.ai_extracted,
                    ai_span=r.ai_span,
                    observed_at=datetime.now(UTC),
                )
                session.add(ev)
                written += 1
        session.flush()
        _finish_stage(session, row)
        return written
    except Exception as exc:  # pragma: no cover
        _finish_stage(session, row, error=str(exc))
        raise


# --- Score --------------------------------------------------------------


def score_business(
    session: Session,
    *,
    business_id: uuid.UUID,
    campaign_id: uuid.UUID,
    run_id: uuid.UUID,
) -> ScoreSnapshot | None:
    row = _begin_stage(
        session,
        business_id=business_id,
        campaign_id=campaign_id,
        stage=StageName.SCORE,
        run_id=run_id,
    )
    if row is None:
        return None

    try:
        events = session.execute(
            select(EvidenceEvent).where(EvidenceEvent.business_id == business_id)
        ).scalars().all()
        resolved = fold(list(events))
        campaign = session.get(Campaign, campaign_id)
        pack_weights: dict[str, object] = {}
        pack_version = "default/0.1.0"
        if campaign is not None and campaign.pack is not None:
            pack_weights = dict(campaign.pack.weights or {})
            pack_version = f"{campaign.pack.key}/{campaign.pack.id}"

        result = score_fn(resolved, pack_version=pack_version, pack_weights=pack_weights)
        snap = ScoreSnapshot(
            business_id=business_id,
            campaign_id=campaign_id,
            score=result.score,
            lead_class=result.lead_class,
            confidence=result.confidence,
            sub_scores=result.sub_scores,  # type: ignore[arg-type]
            reasons=result.reasons,  # type: ignore[arg-type]
            pack_version=pack_version,
            evidence_hash=result.evidence_hash,
        )
        session.add(snap)
        session.flush()
        _finish_stage(session, row)
        return snap
    except Exception as exc:  # pragma: no cover
        _finish_stage(session, row, error=str(exc))
        raise


# --- Draft --------------------------------------------------------------


async def draft_stage(
    session: Session,
    *,
    business_id: uuid.UUID,
    campaign_id: uuid.UUID,
    run_id: uuid.UUID,
) -> Draft | None:
    row = _begin_stage(
        session,
        business_id=business_id,
        campaign_id=campaign_id,
        stage=StageName.DRAFT,
        run_id=run_id,
    )
    if row is None:
        return None

    try:
        biz = session.get(Business, business_id)
        campaign = session.get(Campaign, campaign_id)
        if biz is None or campaign is None:
            _finish_stage(session, row, error="business or campaign missing")
            return None

        latest_snap = session.execute(
            select(ScoreSnapshot)
            .where(
                ScoreSnapshot.business_id == business_id,
                ScoreSnapshot.campaign_id == campaign_id,
            )
            .order_by(ScoreSnapshot.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        model = registry.get(ModelClient)
        offer = campaign.pack.offer_summary if campaign.pack else "a 1-page visibility diagnostic"
        system = (
            "You write short, specific cold-outreach openers for local businesses. "
            "No fluff, 2-3 sentences, one clear ask. Never fabricate claims."
        )
        prompt = (
            f"Business: {biz.name}\n"
            f"City: {biz.city or 'unknown'}\n"
            f"Offer: {offer}\n"
            "Write an opener that references one specific visibility gap and asks for 10 minutes."
        )
        body = await model.generate(system=system, prompt=prompt, max_tokens=256)
        if not body.strip():
            body = f"Hi — quick note from {offer}. Interested in a 10-minute chat?"

        draft = Draft(
            business_id=business_id,
            campaign_id=campaign_id,
            channel="email",
            subject=f"A quick visibility note for {biz.name}",
            body=body,
            status=DraftStatus.PENDING,
            score_snapshot_id=latest_snap.id if latest_snap else None,
        )
        session.add(draft)
        session.flush()
        _finish_stage(session, row)
        return draft
    except Exception as exc:  # pragma: no cover
        _finish_stage(session, row, error=str(exc))
        raise


# --- Approve ------------------------------------------------------------


def approve_draft(
    session: Session,
    *,
    draft_id: uuid.UUID,
    approver_id: uuid.UUID | None,
    edited_body: str | None = None,
) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise ValueError(f"Draft {draft_id} not found")
    if draft.status not in (DraftStatus.PENDING, DraftStatus.EDITED):
        raise ValueError(f"Draft {draft_id} is {draft.status.value}, cannot approve")

    biz = session.get(Business, draft.business_id)
    if biz is None:
        raise ValueError("Business missing")

    latest_snap = session.execute(
        select(ScoreSnapshot)
        .where(ScoreSnapshot.business_id == draft.business_id)
        .order_by(ScoreSnapshot.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_snap is None:
        raise ValueError("No score snapshot — cannot run policy check")

    events = session.execute(
        select(EvidenceEvent).where(EvidenceEvent.business_id == draft.business_id)
    ).scalars().all()
    resolved = fold(list(events))

    from leadbeast.scoring import ScoreResult
    sr = ScoreResult(
        score=latest_snap.score,
        lead_class=latest_snap.lead_class,
        confidence=latest_snap.confidence,
        sub_scores=latest_snap.sub_scores,  # type: ignore[arg-type]
        reasons=latest_snap.reasons,  # type: ignore[arg-type]
        evidence_hash=latest_snap.evidence_hash,
    )

    result = policy_check(
        score=sr,
        resolved=resolved,
        channel=draft.channel,
        profile=PolicyProfile(),
        signal_precisions={},
        has_email=bool(biz.email),
        has_phone=bool(biz.phone),
    )
    if not result.allowed:
        raise ValueError(f"Policy blocked approval: {'; '.join(result.reasons)}")

    if edited_body is not None:
        draft.body = edited_body
        draft.status = DraftStatus.EDITED
    draft.status = DraftStatus.APPROVED
    draft.approved_by = approver_id
    draft.approved_at = datetime.now(UTC)
    session.add(draft)
    session.flush()
    return draft


# --- Send ---------------------------------------------------------------


async def send_draft(session: Session, *, draft_id: uuid.UUID) -> Draft:
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise ValueError(f"Draft {draft_id} not found")
    if draft.status != DraftStatus.APPROVED:
        raise ValueError(f"Draft {draft_id} not approved")

    biz = session.get(Business, draft.business_id)
    if biz is None or not biz.email:
        raise ValueError("Business missing or has no email")

    channel = registry.get(ChannelAdapter)
    result = await channel.send(
        to=biz.email,
        subject=draft.subject,
        body=draft.body,
        correlation_id=str(draft.id),
    )
    if not result.ok:
        draft.status = DraftStatus.FAILED
        session.add(draft)
        session.flush()
        raise RuntimeError(f"Send failed: {result.error}")

    draft.status = DraftStatus.SENT
    draft.sent_at = datetime.now(UTC)
    session.add(draft)
    session.flush()
    return draft
