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
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadbeast.db.models import (
    Business,
    Campaign,
    Confidence,
    Draft,
    DraftStatus,
    EvidenceEvent,
    EvidenceState,
    LeadClass,
    Pack,
    ScoreSnapshot,
    SourceRecord,
)

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
            select(ScoreSnapshot.lead_class)
            .where(ScoreSnapshot.campaign_id == campaign.id)
            .distinct()
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
        # Back-fill evidence for already-scored businesses that have no
        # evidence trail yet (e.g. older deploys scored before the
        # evidence seeder existed). Cheap no-op once populated.
        backfill = list(
            session.execute(
                select(Business, ScoreSnapshot.lead_class)
                .join(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
                .outerjoin(EvidenceEvent, EvidenceEvent.business_id == Business.id)
                .where(EvidenceEvent.id.is_(None))
                .where(ScoreSnapshot.campaign_id == campaign.id)
            ).all()
        )
        for biz, lc in backfill:
            _seed_demo_evidence(session, biz, lc)
        # Also back-fill a pending draft for Class A biz without one.
        draft_backfill = list(
            session.execute(
                select(Business, ScoreSnapshot)
                .join(ScoreSnapshot, ScoreSnapshot.business_id == Business.id)
                .outerjoin(
                    Draft,
                    (Draft.business_id == Business.id)
                    & (Draft.campaign_id == campaign.id),
                )
                .where(Draft.id.is_(None))
                .where(ScoreSnapshot.campaign_id == campaign.id)
                .where(ScoreSnapshot.lead_class == LeadClass.A)
            ).all()
        )
        for biz, _snap in draft_backfill:
            _seed_demo_draft(session, biz, campaign)
        if backfill or draft_backfill:
            session.commit()
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
        _seed_demo_evidence(session, biz, lead_class)
        if lead_class == LeadClass.A:
            _seed_demo_draft(session, biz, campaign)
        scored += 1

    session.commit()
    return scored


def _seed_demo_draft(session: Session, biz: Business, campaign: Campaign) -> None:
    """Attach a plausible-looking pending draft to a Class A business.

    Deterministic body so reruns don't create duplicates (checked via a
    unique (business_id, campaign_id, status) lookup first)."""
    exists = session.execute(
        select(Draft).where(
            Draft.business_id == biz.id,
            Draft.campaign_id == campaign.id,
            Draft.status == DraftStatus.PENDING,
        )
    ).scalar_one_or_none()
    if exists is not None:
        return

    name_short = biz.name.split(" ")[0]
    city = biz.city or "your area"
    subject = f"Quick note about {biz.name}'s online visibility"
    body = (
        f"Hi {name_short} team,\n\n"
        f"I was looking at how {biz.name} shows up when people in {city} "
        f"search for your service. A few competitors appear on the local "
        f"map pack and you don't, even with a similar footprint.\n\n"
        f"I put together a one-page summary of what I found — want me to "
        f"send it over?\n\n"
        f"— Sent via LeadBeast (demo draft · nothing was actually mailed)"
    )
    session.add(
        Draft(
            business_id=biz.id,
            campaign_id=campaign.id,
            channel="email",
            subject=subject,
            body=body,
            status=DraftStatus.PENDING,
        )
    )


# Each class gets a different evidence story:
#   A (Invisible)   : no website, listing not claimed, phone inferred
#   B (Weak site)   : website present but no reviews, chatbot absent
#   C (Unranked)    : present but low rank, few recent reviews
#   D (Active)      : all signals green — poor fit, low priority
_EVIDENCE_BY_CLASS: dict[LeadClass, list[tuple[str, EvidenceState, str, str | None]]] = {
    LeadClass.A: [
        ("own_website",          EvidenceState.NOT_DETECTED, "web_search", None),
        ("map_listing_claimed",  EvidenceState.OBSERVED_NO,  "google_maps", None),
        ("steady_customer_reviews", EvidenceState.OBSERVED_YES, "google_maps", None),
        ("paid_ads_seen",        EvidenceState.NOT_DETECTED, "ad_library", None),
        ("licence_active",       EvidenceState.OBSERVED_YES, "state_registry", None),
        ("owner_direct_phone",   EvidenceState.INFERRED,     "listing_plus_licence", None),
        ("google_rating",        EvidenceState.OBSERVED_YES, "google_profile", "4.6"),
        ("franchise_or_chain",   EvidenceState.OBSERVED_NO,  "listing_scan", None),
        ("schema_on_site",       EvidenceState.NOT_DETECTED, "web_crawl", None),
        ("named_by_ai_chat",     EvidenceState.UNKNOWN,      "ai_probes", None),
        ("named_in_ai_overview", EvidenceState.NOT_DETECTED, "google_aio", None),
        ("staff_count",          EvidenceState.UNKNOWN,      "manual", None),
    ],
    LeadClass.B: [
        ("own_website",          EvidenceState.OBSERVED_YES, "web_search", None),
        ("map_listing_claimed",  EvidenceState.OBSERVED_YES, "google_maps", None),
        ("steady_customer_reviews", EvidenceState.OBSERVED_NO, "google_maps", None),
        ("paid_ads_seen",        EvidenceState.NOT_DETECTED, "ad_library", None),
        ("licence_active",       EvidenceState.OBSERVED_YES, "state_registry", None),
        ("owner_direct_phone",   EvidenceState.OBSERVED_YES, "listing", None),
        ("google_rating",        EvidenceState.OBSERVED_YES, "google_profile", "3.7"),
        ("site_last_updated",    EvidenceState.OBSERVED_NO,  "web_crawl", ">12mo"),
        ("chatbot_present",      EvidenceState.NOT_DETECTED, "web_crawl", None),
        ("schema_on_site",       EvidenceState.OBSERVED_NO,  "web_crawl", None),
        ("mobile_friendly",      EvidenceState.CONFLICTING,  "lighthouse", None),
        ("staff_count",          EvidenceState.INFERRED,     "job_boards", "5-9"),
    ],
    LeadClass.C: [
        ("own_website",          EvidenceState.OBSERVED_YES, "web_search", None),
        ("map_listing_claimed",  EvidenceState.OBSERVED_YES, "google_maps", None),
        ("steady_customer_reviews", EvidenceState.OBSERVED_YES, "google_maps", None),
        ("paid_ads_seen",        EvidenceState.OBSERVED_NO,  "ad_library", None),
        ("licence_active",       EvidenceState.OBSERVED_YES, "state_registry", None),
        ("owner_direct_phone",   EvidenceState.OBSERVED_YES, "listing", None),
        ("google_rating",        EvidenceState.OBSERVED_YES, "google_profile", "4.2"),
        ("local_pack_rank",      EvidenceState.OBSERVED_NO,  "serp", "not in top-3"),
        ("recent_reviews_90d",   EvidenceState.OBSERVED_NO,  "google_maps", None),
        ("schema_on_site",       EvidenceState.OBSERVED_YES, "web_crawl", None),
        ("mobile_friendly",      EvidenceState.OBSERVED_YES, "lighthouse", None),
        ("staff_count",          EvidenceState.INFERRED,     "job_boards", "10-25"),
    ],
    LeadClass.D: [
        ("own_website",          EvidenceState.OBSERVED_YES, "web_search", None),
        ("map_listing_claimed",  EvidenceState.OBSERVED_YES, "google_maps", None),
        ("steady_customer_reviews", EvidenceState.OBSERVED_YES, "google_maps", None),
        ("paid_ads_seen",        EvidenceState.OBSERVED_YES, "ad_library", None),
        ("licence_active",       EvidenceState.OBSERVED_YES, "state_registry", None),
        ("google_rating",        EvidenceState.OBSERVED_YES, "google_profile", "4.8"),
        ("local_pack_rank",      EvidenceState.OBSERVED_YES, "serp", "top-3"),
        ("schema_on_site",       EvidenceState.OBSERVED_YES, "web_crawl", None),
        ("mobile_friendly",      EvidenceState.OBSERVED_YES, "lighthouse", None),
        ("named_by_ai_chat",     EvidenceState.OBSERVED_YES, "ai_probes", None),
        ("named_in_ai_overview", EvidenceState.OBSERVED_YES, "google_aio", None),
        ("staff_count",          EvidenceState.MANUALLY_VERIFIED, "manual", "26-50"),
    ],
}


def _seed_demo_evidence(
    session: Session, biz: Business, lead_class: LeadClass
) -> None:
    """Attach a realistic evidence trail to a demo business.

    Observed times are staggered so the Business 360 "Observed" column
    reads like real detectors landed over the past 2 weeks."""
    now = datetime.now(UTC)
    rows = _EVIDENCE_BY_CLASS[lead_class]
    for i, (signal, state, source, val_text) in enumerate(rows):
        observed_at = now - timedelta(days=i % 14, hours=i % 23)
        confidence = (
            Confidence.HIGH
            if state in (EvidenceState.OBSERVED_YES, EvidenceState.OBSERVED_NO, EvidenceState.MANUALLY_VERIFIED)
            else Confidence.MEDIUM
            if state in (EvidenceState.INFERRED, EvidenceState.CONFLICTING)
            else Confidence.LOW
        )
        session.add(
            EvidenceEvent(
                business_id=biz.id,
                signal=signal,
                state=state,
                value={"text": val_text} if val_text else None,
                source_key=source,
                detector_version="demo-0.1",
                confidence=confidence,
                ai_extracted=False,
                observed_at=observed_at,
            )
        )
