"""Shared httpx helpers for detectors. Keeps timeouts consistent, obeys OSM-ish UA."""

from __future__ import annotations

import httpx

from leadbeast.config import get_settings

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


def make_client() -> httpx.AsyncClient:
    ua = get_settings().osm_user_agent
    return httpx.AsyncClient(
        headers={"User-Agent": ua},
        timeout=_DEFAULT_TIMEOUT,
        follow_redirects=True,
        verify=True,
    )
