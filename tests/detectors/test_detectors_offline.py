"""Detectors must handle missing/invalid websites gracefully (no network)."""

from __future__ import annotations

import pytest

from leadbeast.db.models import EvidenceState
from leadbeast.detectors import (
    BusinessHoursDetector,
    HttpsPresentDetector,
    WebsiteReachabilityDetector,
)


@pytest.mark.asyncio
async def test_reachability_unknown_without_website() -> None:
    results = list(await WebsiteReachabilityDetector().run(business={"name": "X"}))
    assert results[0].state is EvidenceState.UNKNOWN


@pytest.mark.asyncio
async def test_https_unknown_without_website() -> None:
    results = list(await HttpsPresentDetector().run(business={"name": "X"}))
    assert results[0].state is EvidenceState.UNKNOWN


@pytest.mark.asyncio
async def test_hours_unknown_without_website() -> None:
    results = list(await BusinessHoursDetector().run(business={"name": "X"}))
    assert results[0].state is EvidenceState.UNKNOWN
