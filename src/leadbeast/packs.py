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
    """Create a varied demo score distribution so the UI isn't all one class.

    The seeded businesses use `.example` URLs that real detectors can't reach,
    so a pure detect+score pass lands everything in Class D and makes the UI
    look broken. We hand-craft a realistic spread (some A, B, C, D) using
    deterministic positions in the business list — no fake detector run.

    Safe on every boot: existing ScoreSnapshots are skipped."""
    from leadbeast.db.models import Confidence, LeadClass

    campaign = session.execute(
        select(Campaign).where(Campaign.name == DEMO_CAMPAIGN_NAME)
    ).scalar_one_or_none()
    if campaign is None:
        return 0

    # If the campaign's existing snapshots are all one class (bad demo state
    # left over from an earlier boot that relied on real detectors on fake
    # URLs), wipe them so the hand-crafted spread below can replace them.
    existing_classes = {
        r[0]
        for r in session.execute(
            select(ScoreSnapshot.lead_class.distinct()).where(
                ScoreSnapshot.campaign_id == campaign.id
            )
        ).all()
    }
    if len(existing_classes) == 1:
        session.execute(
            ScoreSnapshot.__table__.delete().where(
                ScoreSnapshot.campaign_id == campaign.id
            )
        )
        session.commit()

    businesses = list(
        session.execute(
            select(Business)
            .outerjoin(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
            .where(ScoreSnapshot.id.is_(None))
            .order_by(Business.name.asc())
            .limit(50)
        ).scalars()
    )
    if not businesses:
        return 0

    # Deterministic spread: ~25% A, ~25% B, ~25% C, ~25% D.
    spread = [
        (LeadClass.A, Confidence.HIGH, 82, {"need": 34, "ability": 24, "timing": 7, "reachability": 17}),
        (LeadClass.A, Confidence.HIGH, 78, {"need": 32, "ability": 22, "timing": 8, "reachability": 16}),
        (LeadClass.B, Confidence.MEDIUM, 66, {"need": 24, "ability": 20, "timing": 6, "reachability": 16}),
        (LeadClass.B, Confidence.MEDIUM, 61, {"need": 22, "ability": 19, "timing": 5, "reachability": 15}),
        (LeadClass.C, Confidence.MEDIUM, 54, {"need": 18, "ability": 17, "timing": 5, "reachability": 14}),
        (LeadClass.C, Confidence.LOW, 47, {"need": 15, "ability": 15, "timing": 4, "reachability": 13}),
        (LeadClass.D, Confidence.LOW, 36, {"need": 10, "ability": 12, "timing": 3, "reachability": 11}),
        (LeadClass.D, Confidence.LOW, 28, {"need": 8, "ability": 10, "timing": 2, "reachability": 8}),
    ]
    reasons_by_class = {
        LeadClass.A: ["Invisible: no website found", "Listing not claimed", "Phone reachable"],
        LeadClass.B: ["Weak website presence", "Few reviews (<20)"],
        LeadClass.C: ["Unranked in local pack", "Marketing signals quiet"],
        LeadClass.D: ["Marketing inactive · low priority"],
    }

    scored = 0
    for i, biz in enumerate(businesses):
        spec = spread[i % len(spread)]
        lead_class, confidence, score, sub_scores = spec
        session.add(
            ScoreSnapshot(
                business_id=biz.id,
                campaign_id=campaign.id,
                score=score,
                lead_class=lead_class,
                confidence=confidence,
                sub_scores=sub_scores,
                reasons=reasons_by_class[lead_class],
                pack_version="demo/0.1.0",
                evidence_hash="demo",
            )
        )
        scored += 1

    session.commit()
    return scored
