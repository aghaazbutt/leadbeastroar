"""Typer CLI: `lb` command. See README for examples."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import typer
from sqlalchemy import select

from leadbeast.adapters.source.csv_adapter import CsvSourceAdapter
from leadbeast.db.models import (
    Business,
    Campaign,
    Draft,
    DraftStatus,
    EvidenceEvent,
    Pack,
    SourceRecord,
)
from leadbeast.db.session import SessionLocal
from leadbeast.logging import configure_logging, get_logger
from leadbeast.packs import seed_default_packs
from leadbeast.pipeline.stages import (
    detect_stage,
    draft_stage,
    resolve_business,
    score_business,
)

app = typer.Typer(no_args_is_help=True, add_completion=False)
campaign_app = typer.Typer(help="Campaign management")
ingest_app = typer.Typer(help="Data ingestion")
app.add_typer(campaign_app, name="campaign")
app.add_typer(ingest_app, name="ingest")


@app.callback()
def _init() -> None:
    configure_logging()


@campaign_app.command("new")
def campaign_new(name: str, pack_key: str = "visibility_gap") -> None:
    """Create a new campaign tied to a pack."""
    with SessionLocal() as session:
        pack = session.execute(select(Pack).where(Pack.key == pack_key)).scalar_one_or_none()
        if pack is None:
            typer.echo(f"Pack '{pack_key}' not found. Run `lb pack seed` first.", err=True)
            raise typer.Exit(code=2)
        c = Campaign(name=name, pack_id=pack.id)
        session.add(c)
        session.commit()
        typer.echo(f"Created campaign {c.id} — {name}")


@app.command("pack-seed")
def pack_seed() -> None:
    """Install the default built-in packs."""
    with SessionLocal() as session:
        inserted = seed_default_packs(session)
    typer.echo(
        f"Seeded {inserted} pack(s)" if inserted else "Default packs already present"
    )


@ingest_app.command("csv")
def ingest_csv(path: Path, campaign: str) -> None:
    """Ingest a CSV file into a campaign."""
    asyncio.run(_ingest_csv(path, campaign))


async def _ingest_csv(path: Path, campaign_name: str) -> None:
    with SessionLocal() as session:
        c = session.execute(select(Campaign).where(Campaign.name == campaign_name)).scalar_one_or_none()
        if c is None:
            typer.echo(f"Campaign '{campaign_name}' not found", err=True)
            raise typer.Exit(code=2)

        adapter = CsvSourceAdapter(path)
        count = 0
        async for rec in adapter.fetch(query={}):
            existing = session.execute(
                select(SourceRecord).where(
                    SourceRecord.source_key == rec.source_key,
                    SourceRecord.external_id == rec.external_id,
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            sr = SourceRecord(
                source_key=rec.source_key,
                external_id=rec.external_id,
                raw={
                    "name": rec.name,
                    "website": rec.website,
                    "phone": rec.phone,
                    "email": rec.email,
                    "address": rec.address,
                    "city": rec.city,
                    "region": rec.region,
                    "country": rec.country,
                    "category": rec.category,
                    "latitude": str(rec.latitude) if rec.latitude is not None else None,
                    "longitude": str(rec.longitude) if rec.longitude is not None else None,
                    "employee_count_est": rec.employee_count_est,
                },
            )
            session.add(sr)
            session.flush()
            resolve_business(session, source_record_id=sr.id)
            count += 1
        session.commit()
        typer.echo(f"Ingested {count} records into {campaign_name}")


@app.command("run-pipeline")
def run_pipeline(campaign: str, limit: int = 50) -> None:
    """Run detect → score → draft for every unprocessed business in a campaign."""
    asyncio.run(_run_pipeline(campaign, limit))


async def _run_pipeline(campaign_name: str, limit: int) -> None:
    with SessionLocal() as session:
        c = session.execute(select(Campaign).where(Campaign.name == campaign_name)).scalar_one_or_none()
        if c is None:
            typer.echo(f"Campaign '{campaign_name}' not found", err=True)
            raise typer.Exit(code=2)

        businesses = list(
            session.execute(select(Business).limit(limit)).scalars().all()
        )
        from leadbeast.adapters.model.null import NullModel
        from leadbeast.adapters.protocols import ModelClient
        from leadbeast.adapters.registry import registry
        if not registry.has(ModelClient):
            registry.register(ModelClient, NullModel())

        for biz in businesses:
            run_id = uuid.uuid4()
            await detect_stage(session, business_id=biz.id, campaign_id=c.id, run_id=run_id)
            score_business(session, business_id=biz.id, campaign_id=c.id, run_id=run_id)
            await draft_stage(session, business_id=biz.id, campaign_id=c.id, run_id=run_id)
            session.commit()
        typer.echo(f"Pipeline complete for {len(businesses)} businesses in {campaign_name}")


@app.command("approve")
def approve(campaign: str, max: int = 10) -> None:
    """Auto-approve up to N pending drafts in a campaign (operator convenience)."""
    with SessionLocal() as session:
        c = session.execute(select(Campaign).where(Campaign.name == campaign)).scalar_one_or_none()
        if c is None:
            typer.echo(f"Campaign '{campaign}' not found", err=True)
            raise typer.Exit(code=2)
        drafts = session.execute(
            select(Draft).where(
                Draft.campaign_id == c.id, Draft.status == DraftStatus.PENDING
            ).limit(max)
        ).scalars().all()
        from leadbeast.pipeline.stages import approve_draft as _approve
        approved = 0
        for d in drafts:
            try:
                _approve(session, draft_id=d.id, approver_id=None)
                approved += 1
            except ValueError as exc:
                typer.echo(f"  skipped {d.id}: {exc}")
        session.commit()
        typer.echo(f"Approved {approved}/{len(drafts)} pending drafts")


@app.command("stats")
def stats() -> None:
    """Print quick DB counts."""
    with SessionLocal() as session:
        counts = {
            "campaigns": session.execute(select(Campaign)).scalars().all(),
            "businesses": session.execute(select(Business)).scalars().all(),
            "evidence": session.execute(select(EvidenceEvent)).scalars().all(),
            "drafts": session.execute(select(Draft)).scalars().all(),
        }
        for name, rows in counts.items():
            typer.echo(f"  {name}: {len(rows)}")


if __name__ == "__main__":
    app()


_ = get_logger  # keep import for future use
