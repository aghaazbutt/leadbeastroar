"""FastAPI entrypoint.

- Mounts /v1 API routers.
- Mounts /ui HTMX routes (and / redirects to /ui/opportunities).
- Registers adapters per env config.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from leadbeast.adapters import ChannelAdapter, CrmAdapter, ModelClient, ReportRenderer
from leadbeast.adapters.channel.listmonk import ListmonkChannel
from leadbeast.adapters.channel.null import NullChannel
from leadbeast.adapters.channel.ses import SesChannel
from leadbeast.adapters.crm.espo import EspoCrm
from leadbeast.adapters.crm.null import NullCrm
from leadbeast.adapters.model.anthropic import AnthropicModel
from leadbeast.adapters.model.null import NullModel
from leadbeast.adapters.model.ollama import OllamaModel
from leadbeast.adapters.registry import registry
from leadbeast.adapters.report.weasy import WeasyReportRenderer
from leadbeast.api.v1 import (
    businesses,
    campaigns,
    connectors,
    cost,
    drafts,
    market,
    outcomes,
)
from leadbeast.config import get_settings
from leadbeast.db.session import SessionLocal
from leadbeast.logging import configure_logging, get_logger
from leadbeast.packs import seed_default_packs, seed_demo_businesses
from leadbeast.ui import routes as ui_routes

log = get_logger("app")


def _register_adapters() -> None:
    s = get_settings()

    if s.model_provider == "anthropic":
        registry.register(ModelClient, AnthropicModel())
    elif s.model_provider == "ollama":
        registry.register(ModelClient, OllamaModel())
    else:
        registry.register(ModelClient, NullModel())

    if s.channel_provider == "ses":
        registry.register(ChannelAdapter, SesChannel())
    elif s.channel_provider == "listmonk":
        registry.register(ChannelAdapter, ListmonkChannel())
    else:
        registry.register(ChannelAdapter, NullChannel())

    if s.crm_provider == "espo":
        registry.register(CrmAdapter, EspoCrm())
    else:
        registry.register(CrmAdapter, NullCrm())

    template_dir = Path(__file__).parent / "ui" / "templates" / "reports"
    registry.register(ReportRenderer, WeasyReportRenderer(template_dir))

    log.info(
        "adapters.registered",
        model=s.model_provider,
        channel=s.channel_provider,
        crm=s.crm_provider,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    _register_adapters()
    with SessionLocal() as session:
        inserted_packs = seed_default_packs(session)
        inserted_biz = seed_demo_businesses(
            session,
            csv_path=Path(__file__).parent.parent.parent / "seeds" / "businesses.csv",
        )
    if inserted_packs:
        log.info("packs.seeded", count=inserted_packs)
    if inserted_biz:
        log.info("demo_businesses.seeded", count=inserted_biz)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="LeadBeast",
        version="0.1.0",
        description="Single-operator lead-ops platform",
        lifespan=lifespan,
    )

    app.include_router(campaigns.router, prefix="/v1")
    app.include_router(businesses.router, prefix="/v1")
    app.include_router(drafts.router, prefix="/v1")
    app.include_router(outcomes.router, prefix="/v1")
    app.include_router(connectors.router, prefix="/v1")
    app.include_router(cost.router, prefix="/v1")
    app.include_router(market.router, prefix="/v1")
    app.include_router(ui_routes.router)

    @app.get("/", include_in_schema=False)
    def _root() -> RedirectResponse:
        return RedirectResponse(url="/ui/opportunities")

    static_dir = Path(__file__).parent / "ui" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()
