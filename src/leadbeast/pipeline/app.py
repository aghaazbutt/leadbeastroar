"""Procrastinate app singleton — DB-as-queue."""

from __future__ import annotations

from procrastinate import App, PsycopgConnector

from leadbeast.config import get_settings

_settings = get_settings()

app = App(
    connector=PsycopgConnector(conninfo=_settings.procrastinate_dsn),
    import_paths=["leadbeast.pipeline.jobs"],
)
