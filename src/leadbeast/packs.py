"""Built-in packs and their idempotent seeding.

A solo-operator install should never land on an empty `pack` table: with no
packs, Campaign Studio has nothing to attach a new campaign to and the POST
form silently 303s back with `?err=pack`. The app seeds these at startup.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadbeast.db.models import Pack

DEFAULT_PACKS: list[dict[str, object]] = [
    {
        "key": "visibility_gap",
        "name": "Visibility Gap",
        "offer_summary": "a 1-page visibility diagnostic focused on missing basics",
        "weights": {},
        "detectors": ["website_reachable", "https_present", "business_hours_on_site"],
    },
]


def seed_default_packs(session: Session) -> int:
    """Insert any missing default packs. Returns count inserted."""
    inserted = 0
    for spec in DEFAULT_PACKS:
        exists = session.execute(
            select(Pack).where(Pack.key == spec["key"])
        ).scalar_one_or_none()
        if exists is not None:
            continue
        session.add(Pack(**spec))
        inserted += 1
    if inserted:
        session.commit()
    return inserted
