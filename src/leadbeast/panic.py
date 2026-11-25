"""Panic watch rule engine (no AI).

A PanicWatch is a saved rule. evaluate_watch() runs the rule once against
the current business/score state and emits PanicAlert rows for new matches.
Uniqueness on (watch_id, business_id) means repeated evaluations are safe —
a business that still matches won't double-fire.

Mockup semantics (see Product Feature Document §18): watches should re-check
around the clock and surface the moment a match appears. In v1 we expose a
manual "Run now" button on the UI; a scheduler can call evaluate_all_watches()
on a timer later.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadbeast.db.models import (
    Business,
    LeadClass,
    PanicAlert,
    PanicWatch,
    ScoreSnapshot,
)


_LEAD_ORDER = {LeadClass.A: 4, LeadClass.B: 3, LeadClass.C: 2, LeadClass.D: 1}


def _match_reason(watch: PanicWatch, biz: Business, snap: ScoreSnapshot | None) -> str:
    parts: list[str] = []
    if watch.city:
        parts.append(f"city={watch.city}")
    if watch.region:
        parts.append(f"region={watch.region}")
    if watch.category:
        parts.append(f"category={watch.category}")
    if watch.min_score is not None and snap is not None:
        parts.append(f"score {snap.score} ≥ {watch.min_score}")
    if watch.lead_class_at_least is not None and snap is not None:
        parts.append(f"class {snap.lead_class.value} ≥ {watch.lead_class_at_least.value}")
    if not parts:
        parts.append("any business")
    return "; ".join(parts)


def evaluate_watch(session: Session, watch: PanicWatch) -> int:
    """Run the watch once; create PanicAlert rows for new matches. Returns count inserted."""
    if not watch.enabled:
        return 0

    stmt = (
        select(Business, ScoreSnapshot)
        .outerjoin(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
    )
    if watch.city:
        stmt = stmt.where(Business.city == watch.city)
    if watch.region:
        stmt = stmt.where(Business.region == watch.region)
    if watch.category:
        stmt = stmt.where(Business.category == watch.category)
    if watch.min_score is not None:
        stmt = stmt.where(ScoreSnapshot.score >= watch.min_score)
    if watch.lead_class_at_least is not None:
        threshold = _LEAD_ORDER[watch.lead_class_at_least]
        wanted = [c.value for c, v in _LEAD_ORDER.items() if v >= threshold]
        stmt = stmt.where(ScoreSnapshot.lead_class.in_(wanted))

    existing = set(
        session.execute(
            select(PanicAlert.business_id).where(PanicAlert.watch_id == watch.id)
        ).scalars()
    )

    inserted = 0
    for biz, snap in session.execute(stmt).all():
        if biz.id in existing:
            continue
        session.add(
            PanicAlert(
                watch_id=watch.id,
                business_id=biz.id,
                reason=_match_reason(watch, biz, snap),
            )
        )
        inserted += 1

    watch.last_evaluated_at = datetime.now(UTC)
    session.add(watch)
    if inserted:
        session.commit()
    else:
        session.flush()
    return inserted


def evaluate_all_watches(session: Session, watches: Iterable[PanicWatch] | None = None) -> int:
    if watches is None:
        watches = list(
            session.execute(select(PanicWatch).where(PanicWatch.enabled.is_(True))).scalars()
        )
    total = 0
    for w in watches:
        total += evaluate_watch(session, w)
    return total
