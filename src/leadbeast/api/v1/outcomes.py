from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, status
from sqlalchemy.orm import Session

from leadbeast.api.deps import AuthDep, SessionDep
from leadbeast.api.v1.schemas import OutcomeIn, OutcomeOut
from leadbeast.db.models import Outcome

router = APIRouter(prefix="/outcomes", tags=["outcomes"], dependencies=[AuthDep])


@router.post("", response_model=OutcomeOut, status_code=status.HTTP_201_CREATED)
def record_outcome(
    payload: OutcomeIn,
    session: Annotated[Session, SessionDep],
) -> Outcome:
    o = Outcome(
        draft_id=payload.draft_id,
        kind=payload.kind,
        note=payload.note,
        observed_at=datetime.now(UTC),
    )
    session.add(o)
    session.commit()
    session.refresh(o)
    return o
