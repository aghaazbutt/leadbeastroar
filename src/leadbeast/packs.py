"""Built-in packs and their idempotent seeding.

A solo-operator install should never land on an empty `pack` table: with no
packs, Campaign Studio has nothing to attach a new campaign to and the POST
form silently 303s back with `?err=pack`. The app seeds these at startup.

Also provides a one-shot demo-data loader: when the `business` table is
empty at startup, ingest the shipped seeds/businesses.csv so a fresh deploy
has something to look at. Controlled by LB_AUTOSEED_DEMO (default on in dev,
off when LB_ENV=prod unless explicitly set).
"""

from __future__ import annotations

import csv
import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadbeast.db.models import Business, Campaign, Pack, ScoreSnapshot, SourceRecord

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


def _nullable(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    return s or None


def _as_decimal(v: str | None) -> Decimal | None:
    if not v or not v.strip():
        return None
    try:
        return Decimal(v.strip())
    except (InvalidOperation, ValueError):
        return None


def _as_int(v: str | None) -> int | None:
    if not v or not v.strip():
        return None
    try:
        return int(float(v.strip()))
    except (TypeError, ValueError):
        return None


def _normalize_name(name: str) -> str:
    return " ".join(name.lower().strip().split())


DEMO_CAMPAIGN_NAME = "Demo Visibility Gap"


def seed_demo_businesses(session: Session, *, csv_path: Path) -> int:
    """If the business table is empty, ingest the shipped CSV. Returns count."""
    biz_count = session.execute(select(func.count(Business.id))).scalar_one() or 0
    if biz_count > 0:
        return 0
    if not csv_path.exists():
        return 0

    pack = session.execute(
        select(Pack).where(Pack.key == "visibility_gap")
    ).scalar_one_or_none()
    if pack is None:
        return 0

    campaign = session.execute(
        select(Campaign).where(Campaign.name == DEMO_CAMPAIGN_NAME)
    ).scalar_one_or_none()
    if campaign is None:
        campaign = Campaign(name=DEMO_CAMPAIGN_NAME, pack_id=pack.id)
        session.add(campaign)
        session.flush()

    inserted = 0
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            name = _nullable(row.get("name"))
            if not name:
                continue
            seed = "|".join(
                [name, (row.get("address") or "").strip(), (row.get("city") or "").strip()]
            )
            external_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
            exists = session.execute(
                select(SourceRecord).where(
                    SourceRecord.source_key == "csv",
                    SourceRecord.external_id == external_id,
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue
            biz = Business(
                name=name,
                normalized_name=_normalize_name(name),
                website=_nullable(row.get("website")),
                phone=_nullable(row.get("phone")),
                email=_nullable(row.get("email")),
                address=_nullable(row.get("address")),
                city=_nullable(row.get("city")),
                region=_nullable(row.get("region")),
                country=_nullable(row.get("country")),
                category=_nullable(row.get("category")),
                latitude=_as_decimal(row.get("latitude")),
                longitude=_as_decimal(row.get("longitude")),
                employee_count_est=_as_int(row.get("employee_count_est")),
            )
            session.add(biz)
            session.flush()
            session.add(
                SourceRecord(
                    source_key="csv",
                    external_id=external_id,
                    business_id=biz.id,
                    raw={k: v for k, v in row.items()},
                )
            )
            inserted += 1

    if inserted:
        session.commit()
    return inserted


async def seed_demo_scores(session: Session) -> int:
    """Run detect + score for any demo-campaign business that isn't scored yet.

    Returns the number of businesses that got a fresh ScoreSnapshot. Safe to
    call on every boot — PipelineRun idempotency keys stop repeat work."""
    import uuid as _uuid

    from leadbeast.pipeline.stages import detect_stage, score_business

    campaign = session.execute(
        select(Campaign).where(Campaign.name == DEMO_CAMPAIGN_NAME)
    ).scalar_one_or_none()
    if campaign is None:
        return 0

    biz_ids = list(
        session.execute(
            select(Business.id)
            .outerjoin(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
            .where(ScoreSnapshot.id.is_(None))
            .limit(50)
        ).scalars()
    )
    if not biz_ids:
        return 0

    scored = 0
    run_id = _uuid.uuid4()
    for bid in biz_ids:
        try:
            await detect_stage(
                session, business_id=bid, campaign_id=campaign.id, run_id=run_id
            )
            snap = score_business(
                session, business_id=bid, campaign_id=campaign.id, run_id=run_id
            )
            if snap is not None:
                scored += 1
        except Exception:
            session.rollback()
            continue
    session.commit()
    return scored
