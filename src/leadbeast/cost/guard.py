"""Cost guard.

reserve() checks caps and inserts a `reserve` row atomically. commit() flips
the reservation to `commit`. refund() negates a reservation. Free sources
write cents=0 so volume is still observable.

All caps are per-user in cents. 50/80/100% alerts emitted as structlog
events; UI reads cost_ledger directly for dashboard chips.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadbeast.config import get_settings
from leadbeast.db.models import CostLedger
from leadbeast.logging import get_logger

log = get_logger("cost.guard")


class BudgetExceeded(Exception):
    """Raised when a reserve would push a cap over 100%."""

    def __init__(self, cap_name: str, used_cents: int, cap_cents: int, requested_cents: int):
        super().__init__(
            f"Budget exceeded: {cap_name} would reach {used_cents + requested_cents}c "
            f"of {cap_cents}c cap"
        )
        self.cap_name = cap_name
        self.used_cents = used_cents
        self.cap_cents = cap_cents
        self.requested_cents = requested_cents


@dataclass(frozen=True)
class CostReservation:
    id: uuid.UUID
    run_id: uuid.UUID
    source_key: str
    cents: int


class CostGuard:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def reserve(
        self,
        *,
        run_id: uuid.UUID,
        source_key: str,
        cents: int,
        campaign_id: uuid.UUID | None = None,
        business_id: uuid.UUID | None = None,
        note: str | None = None,
    ) -> CostReservation:
        if cents < 0:
            raise ValueError("cents must be >= 0")
        if self.settings.dry_run and cents > 0:
            log.info(
                "cost.dry_run.block",
                source=source_key,
                cents=cents,
                note="dry-run mode: refusing paid reserve",
            )
            raise BudgetExceeded("dry_run", 0, 0, cents)
        if cents > 0:
            self._enforce_caps(run_id=run_id, requested=cents)

        row = CostLedger(
            run_id=run_id,
            campaign_id=campaign_id,
            business_id=business_id,
            source_key=source_key,
            kind="reserve",
            cents=cents,
            note=note,
        )
        self.session.add(row)
        self.session.flush()
        self._alert_thresholds(run_id=run_id)
        return CostReservation(id=row.id, run_id=run_id, source_key=source_key, cents=cents)

    def commit(self, reservation: CostReservation, *, note: str | None = None) -> None:
        self.session.add(
            CostLedger(
                run_id=reservation.run_id,
                source_key=reservation.source_key,
                kind="commit",
                cents=reservation.cents,
                note=note,
            )
        )
        self.session.flush()

    def refund(self, reservation: CostReservation, *, note: str | None = None) -> None:
        self.session.add(
            CostLedger(
                run_id=reservation.run_id,
                source_key=reservation.source_key,
                kind="refund",
                cents=-reservation.cents,
                note=note,
            )
        )
        self.session.flush()

    # --- internals -----------------------------------------------------

    def _enforce_caps(self, *, run_id: uuid.UUID, requested: int) -> None:
        now = datetime.now(UTC)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = day_start.replace(day=1)

        run_used = self._sum(cents_only_kind="commit", run_id=run_id)
        day_used = self._sum(cents_only_kind="commit", since=day_start)
        month_used = self._sum(cents_only_kind="commit", since=month_start)

        if run_used + requested > self.settings.cap_per_run_cents:
            raise BudgetExceeded(
                "per_run", run_used, self.settings.cap_per_run_cents, requested
            )
        if day_used + requested > self.settings.cap_per_day_cents:
            raise BudgetExceeded(
                "per_day", day_used, self.settings.cap_per_day_cents, requested
            )
        if month_used + requested > self.settings.cap_per_month_cents:
            raise BudgetExceeded(
                "per_month", month_used, self.settings.cap_per_month_cents, requested
            )

    def _sum(
        self,
        *,
        cents_only_kind: str,
        run_id: uuid.UUID | None = None,
        since: datetime | None = None,
    ) -> int:
        stmt = select(func.coalesce(func.sum(CostLedger.cents), 0)).where(
            CostLedger.kind == cents_only_kind
        )
        if run_id is not None:
            stmt = stmt.where(CostLedger.run_id == run_id)
        if since is not None:
            stmt = stmt.where(CostLedger.created_at >= since)
        return int(self.session.execute(stmt).scalar_one() or 0)

    def _alert_thresholds(self, *, run_id: uuid.UUID) -> None:
        caps = {
            "per_run": (self.settings.cap_per_run_cents, self._sum(cents_only_kind="commit", run_id=run_id)),
            "per_day": (
                self.settings.cap_per_day_cents,
                self._sum(
                    cents_only_kind="commit",
                    since=datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0),
                ),
            ),
        }
        for name, (cap, used) in caps.items():
            if cap == 0:
                continue
            ratio = used / cap
            if ratio >= 1.0:
                log.warning("cost.cap.reached", cap=name, used_cents=used, cap_cents=cap)
            elif ratio >= 0.8:
                log.warning("cost.cap.80pct", cap=name, used_cents=used, cap_cents=cap)
            elif ratio >= 0.5:
                log.info("cost.cap.50pct", cap=name, used_cents=used, cap_cents=cap)


@contextmanager
def cost_scope(session: Session):
    """Convenience: new CostGuard for a session with auto-commit on exit."""
    guard = CostGuard(session)
    try:
        yield guard
        session.commit()
    except Exception:
        session.rollback()
        raise


# re-exports to keep imports stable
__all__ = ["BudgetExceeded", "CostGuard", "CostReservation", "cost_scope"]


# Expose a few types mypy wants to see used
_ = timedelta
