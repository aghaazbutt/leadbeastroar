from __future__ import annotations

from pathlib import Path

import pytest

from leadbeast.adapters.source.csv_adapter import CsvSourceAdapter


@pytest.mark.asyncio
async def test_csv_adapter_reads_seed(tmp_path: Path) -> None:
    csv_path = tmp_path / "test.csv"
    csv_path.write_text(
        "name,website,city\n"
        "Acme Co,https://acme.example,Boise\n"
        "Beta Inc,,Lahore\n"
    )
    adapter = CsvSourceAdapter(csv_path)
    records = [r async for r in adapter.fetch(query={})]
    assert len(records) == 2
    assert records[0].name == "Acme Co"
    assert records[0].website == "https://acme.example"
    assert records[0].city == "Boise"
    assert records[1].website is None


@pytest.mark.asyncio
async def test_csv_adapter_health_off_when_missing(tmp_path: Path) -> None:
    adapter = CsvSourceAdapter(tmp_path / "nope.csv")
    h = await adapter.health()
    assert h.status == "off"
