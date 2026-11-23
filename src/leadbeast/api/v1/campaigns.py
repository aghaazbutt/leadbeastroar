from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from leadbeast.api.deps import AuthDep, SessionDep
from leadbeast.api.v1.schemas import CampaignIn, CampaignOut
from leadbeast.db.models import Campaign, Pack

router = APIRouter(prefix="/campaigns", tags=["campaigns"], dependencies=[AuthDep])


@router.post("", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignIn,
    session: Annotated[Session, SessionDep],
) -> Campaign:
    pack = session.execute(select(Pack).where(Pack.key == payload.pack_key)).scalar_one_or_none()
    if pack is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"pack '{payload.pack_key}' not found",
        )
    c = Campaign(
        name=payload.name,
        pack_id=pack.id,
        targeting=payload.targeting,
        budget_cents_month=payload.budget_cents_month,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@router.get("", response_model=list[CampaignOut])
def list_campaigns(
    session: Annotated[Session, SessionDep],
    limit: int = 50,
) -> list[Campaign]:
    stmt = select(Campaign).order_by(Campaign.created_at.desc()).limit(limit)
    return list(session.execute(stmt).scalars().all())


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(
    campaign_id: uuid.UUID,
    session: Annotated[Session, SessionDep],
) -> Campaign:
    c = session.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c
