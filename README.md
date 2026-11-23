# LeadBeast

Single-operator, self-hosted lead-ops platform. Finds, scores, triages, approves, reaches, and learns from local-business opportunities. Built to the spec in `LeadBeast — Developer Specification (Python) (2).pdf`.

## Stack

Python 3.12 · FastAPI + HTMX + Jinja2 · PostgreSQL 16 · Procrastinate (DB-as-queue) · SQLAlchemy 2 · Alembic · Pydantic v2 · structlog · Typer · WeasyPrint · Caddy · Docker Compose.

One datastore. No Redis, no Kafka. Modular monolith with Protocol-based adapters at every external edge (source, contact, CRM, channel, model, report).

## Quick start

```bash
cp .env.example .env            # edit secrets
make up                         # build + start postgres, app, worker, caddy
make migrate                    # run alembic upgrade head
make seed                       # load 20 fake businesses
open http://localhost
```

Operator login: use the `LB_API_TOKEN` from `.env` as the `Authorization: Bearer <token>` header or the single-operator login cookie.

## Pipeline

Collect → Resolve → Vitality → Detect → Audit → Score → Contact → Draft → Approve → Send.

Every stage is idempotent, keyed by `(business_id, campaign_id, stage, run_id)`. Append-only `evidence_event` ledger; immutable `score_snapshot`; pure `fold()` reduces evidence into current state.

## CLI

```bash
lb campaign new "Visibility Gap — Lahore"
lb ingest csv seeds/businesses.csv --campaign "Visibility Gap — Lahore"
lb run-pipeline --campaign "Visibility Gap — Lahore"
lb approve --campaign "Visibility Gap — Lahore" --class A
lb report business <business_id>
```

## Status

v1 Core: schema, pure engines, CSV adapter, 3 offline detectors, pipeline, cost guard, FastAPI + HTMX UI, golden-set gate.

Stubbed (ready for keys): Google Places, SES/Listmonk, Twilio, Anthropic/OpenAI, Mapbox, EspoCRM.

Not built: Panic Alerts crawlers, AEO/GEO visibility probes, e-signature, invoicing, trained ML scorer.

## Spec files

- `LeadBeast — Developer Specification (Python) (2).pdf` — authoritative stack
- `LeadBeast — Product Feature Document v3.6.pdf` — product scope
- `LeadBeast UI Design.pdf` — UI reference
