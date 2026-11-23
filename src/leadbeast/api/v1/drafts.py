from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from leadbeast.api.deps import AuthDep, SessionDep
from leadbeast.api.v1.schemas import DraftApproveIn, DraftOut
from leadbeast.db.models import Draft, DraftStatus
from leadbeast.pipeline.stages import approve_draft, send_draft

router = APIRouter(prefix="/drafts", tags=["drafts"], dependencies=[AuthDep])


@router.get("", response_model=list[DraftOut])
def list_drafts(
    session: Annotated[Session, SessionDep],
    status: DraftStatus | None = None,
    limit: int = 50,
) -> list[Draft]:
    stmt = select(Draft).order_by(Draft.created_at.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(Draft.status == status)
    return list(session.execute(stmt).scalars().all())


@router.get("/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: uuid.UUID, session: Annotated[Session, SessionDep]) -> Draft:
    d = session.get(Draft, draft_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return d


@router.post("/{draft_id}/approve", response_model=DraftOut)
def approve(
    draft_id: uuid.UUID,
    payload: DraftApproveIn,
    session: Annotated[Session, SessionDep],
) -> Draft:
    try:
        d = approve_draft(
            session,
            draft_id=draft_id,
            approver_id=None,
            edited_body=payload.edited_body,
        )
        session.commit()
        return d
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{draft_id}/skip", response_model=DraftOut)
def skip(draft_id: uuid.UUID, session: Annotated[Session, SessionDep]) -> Draft:
    d = session.get(Draft, draft_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    d.status = DraftStatus.SKIPPED
    session.add(d)
    session.commit()
    return d


@router.post("/{draft_id}/send", response_model=DraftOut)
async def send(draft_id: uuid.UUID, session: Annotated[Session, SessionDep]) -> Draft:
    try:
        d = await send_draft(session, draft_id=draft_id)
        session.commit()
        return d
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
