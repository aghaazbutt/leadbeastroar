from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadbeast.api.deps import AuthDep, SessionDep
from leadbeast.api.v1.schemas import CostSummary
from leadbeast.config import get_settings
from leadbeast.db.models import CostLedger

router = APIRouter(prefix="/cost", tags=["cost"], dependencies=[AuthDep])


@router.get("", response_model=CostSummary)
def summary(session: Annotated[Session, SessionDep]) -> CostSummary:
    s = get_settings()
    now = datetime.now(UTC)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    def _sum(since: datetime | None = None) -> int:
        stmt = select(func.coalesce(func.sum(CostLedger.cents), 0)).where(
            CostLedger.kind == "commit"
        )
        if since is not None:
            stmt = stmt.where(CostLedger.created_at >= since)
        return int(session.execute(stmt).scalar_one() or 0)

    return CostSummary(
        per_run_cents=0,
        per_day_cents=_sum(day_start),
        per_month_cents=_sum(month_start),
        cap_per_run_cents=s.cap_per_run_cents,
        cap_per_day_cents=s.cap_per_day_cents,
        cap_per_month_cents=s.cap_per_month_cents,
    )
