from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadbeast.api.deps import AuthDep, SessionDep
from leadbeast.api.v1.schemas import MarketSummary
from leadbeast.db.models import (
    Business,
    Draft,
    DraftStatus,
    LeadClass,
    Outcome,
    OutcomeKind,
    ScoreSnapshot,
)

router = APIRouter(prefix="/market", tags=["market"], dependencies=[AuthDep])


@router.get("/summary", response_model=MarketSummary)
def summary(session: Annotated[Session, SessionDep]) -> MarketSummary:
    found = int(session.execute(select(func.count(Business.id))).scalar_one() or 0)
    approved = int(
        session.execute(
            select(func.count(Draft.id)).where(Draft.status == DraftStatus.APPROVED)
        ).scalar_one()
        or 0
    )
    sent = int(
        session.execute(
            select(func.count(Draft.id)).where(Draft.status == DraftStatus.SENT)
        ).scalar_one()
        or 0
    )
    replied = int(
        session.execute(
            select(func.count(Outcome.id)).where(Outcome.kind == OutcomeKind.REPLIED)
        ).scalar_one()
        or 0
    )
    won = int(
        session.execute(
            select(func.count(Outcome.id)).where(Outcome.kind == OutcomeKind.WON)
        ).scalar_one()
        or 0
    )

    class_rows = session.execute(
        select(ScoreSnapshot.lead_class, func.count(ScoreSnapshot.id)).group_by(
            ScoreSnapshot.lead_class
        )
    ).all()
    gap_distribution: dict[str, int] = {c.value: 0 for c in LeadClass}
    for cls, n in class_rows:
        gap_distribution[cls.value] = int(n)

    return MarketSummary(
        found=found,
        passed_filters=approved + sent,
        approved=approved,
        sent=sent,
        replied=replied,
        won=won,
        gap_distribution=gap_distribution,
    )
