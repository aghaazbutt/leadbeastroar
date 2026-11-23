"""Procrastinate job wrappers for each stage.

Procrastinate auto-imports this module (see pipeline/app.py).
"""

from __future__ import annotations

import uuid

from leadbeast.db.session import SessionLocal
from leadbeast.logging import get_logger
from leadbeast.pipeline.app import app
from leadbeast.pipeline.stages import (
    detect_stage,
    draft_stage,
    resolve_business,
    score_business,
    send_draft,
)

log = get_logger("pipeline.jobs")


@app.task(name="pipeline.resolve", queue="resolve")
async def job_resolve(source_record_id: str) -> str:
    with SessionLocal() as session:
        bid = resolve_business(session, source_record_id=uuid.UUID(source_record_id))
        session.commit()
        return str(bid)


@app.task(name="pipeline.detect", queue="detect")
async def job_detect(business_id: str, campaign_id: str, run_id: str) -> int:
    with SessionLocal() as session:
        n = await detect_stage(
            session,
            business_id=uuid.UUID(business_id),
            campaign_id=uuid.UUID(campaign_id),
            run_id=uuid.UUID(run_id),
        )
        session.commit()
        return n


@app.task(name="pipeline.score", queue="score")
async def job_score(business_id: str, campaign_id: str, run_id: str) -> str | None:
    with SessionLocal() as session:
        snap = score_business(
            session,
            business_id=uuid.UUID(business_id),
            campaign_id=uuid.UUID(campaign_id),
            run_id=uuid.UUID(run_id),
        )
        session.commit()
        return str(snap.id) if snap else None


@app.task(name="pipeline.draft", queue="draft")
async def job_draft(business_id: str, campaign_id: str, run_id: str) -> str | None:
    with SessionLocal() as session:
        draft = await draft_stage(
            session,
            business_id=uuid.UUID(business_id),
            campaign_id=uuid.UUID(campaign_id),
            run_id=uuid.UUID(run_id),
        )
        session.commit()
        return str(draft.id) if draft else None


@app.task(name="pipeline.send", queue="send")
async def job_send(draft_id: str) -> str:
    with SessionLocal() as session:
        draft = await send_draft(session, draft_id=uuid.UUID(draft_id))
        session.commit()
        return draft.status.value
