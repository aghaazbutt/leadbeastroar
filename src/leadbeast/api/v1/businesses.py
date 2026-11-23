from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from leadbeast.api.deps import AuthDep, SessionDep
from leadbeast.api.v1.schemas import BusinessOut, EvidenceOut, ScoreOut
from leadbeast.db.models import Business, EvidenceEvent, ScoreSnapshot

router = APIRouter(prefix="/businesses", tags=["businesses"], dependencies=[AuthDep])


@router.get("", response_model=list[BusinessOut])
def list_businesses(
    session: Annotated[Session, SessionDep],
    city: str | None = Query(default=None),
    limit: int = 50,
) -> list[Business]:
    stmt = select(Business).order_by(Business.created_at.desc()).limit(limit)
    if city:
        stmt = stmt.where(Business.city == city)
    return list(session.execute(stmt).scalars().all())


@router.get("/{business_id}", response_model=BusinessOut)
def get_business(
    business_id: uuid.UUID,
    session: Annotated[Session, SessionDep],
) -> Business:
    b = session.get(Business, business_id)
    if b is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return b


@router.get("/{business_id}/evidence", response_model=list[EvidenceOut])
def business_evidence(
    business_id: uuid.UUID,
    session: Annotated[Session, SessionDep],
) -> list[EvidenceEvent]:
    stmt = (
        select(EvidenceEvent)
        .where(EvidenceEvent.business_id == business_id)
        .order_by(EvidenceEvent.observed_at.desc())
    )
    return list(session.execute(stmt).scalars().all())


@router.get("/{business_id}/scores", response_model=list[ScoreOut])
def business_scores(
    business_id: uuid.UUID,
    session: Annotated[Session, SessionDep],
) -> list[ScoreSnapshot]:
    stmt = (
        select(ScoreSnapshot)
        .where(ScoreSnapshot.business_id == business_id)
        .order_by(ScoreSnapshot.created_at.desc())
    )
    return list(session.execute(stmt).scalars().all())


@router.post("/{business_id}/rescore", response_model=ScoreOut)
def rescore_business(
    business_id: uuid.UUID,
    campaign_id: uuid.UUID,
    session: Annotated[Session, SessionDep],
) -> ScoreSnapshot:
    """Trigger an in-process rescore. Pure fold → score, no detector run."""
    from leadbeast.pipeline.stages import score_business as score_stage

    snap = score_stage(
        session,
        business_id=business_id,
        campaign_id=campaign_id,
        run_id=uuid.uuid4(),
    )
    session.commit()
    if snap is None:
        raise HTTPException(status_code=409, detail="Score for this run already exists")
    return snap
