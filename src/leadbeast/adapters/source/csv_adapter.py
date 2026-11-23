"""CSV SourceAdapter.

Offline-first: accepts a local CSV file. Required columns:
    name
Optional columns:
    website, phone, email, address, city, region, country,
    latitude, longitude, category, employee_count_est

Each row emits a SourceRecordIn. external_id defaults to a stable hash of
(name|address|city) so re-ingesting the same file is idempotent.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import AsyncIterator
from decimal import Decimal, InvalidOperation
from pathlib import Path

from leadbeast.adapters.protocols import HealthReport, SourceAdapter, SourceRecordIn


class CsvSourceAdapter(SourceAdapter):
    key = "csv"
    cost_cents_per_record = 0

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def fetch(self, *, query: dict[str, object]) -> AsyncIterator[SourceRecordIn]:
        if not self.path.exists():
            raise FileNotFoundError(f"CSV not found: {self.path}")
        with self.path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                record = _row_to_record(row)
                if record is not None:
                    yield record

    async def health(self) -> HealthReport:
        if self.path.exists():
            return HealthReport(key=self.key, status="healthy", detail=str(self.path))
        return HealthReport(
            key=self.key, status="off", detail=f"CSV not found at {self.path}"
        )


def _row_to_record(row: dict[str, str]) -> SourceRecordIn | None:
    name = (row.get("name") or "").strip()
    if not name:
        return None

    external_id = (row.get("external_id") or "").strip()
    if not external_id:
        seed = "|".join(
            [
                name,
                (row.get("address") or "").strip(),
                (row.get("city") or "").strip(),
            ]
        )
        external_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]

    return SourceRecordIn(
        source_key="csv",
        external_id=external_id,
        name=name,
        website=_nullable(row.get("website")),
        phone=_nullable(row.get("phone")),
        email=_nullable(row.get("email")),
        address=_nullable(row.get("address")),
        city=_nullable(row.get("city")),
        region=_nullable(row.get("region")),
        country=_nullable(row.get("country")),
        latitude=_as_decimal(row.get("latitude")),
        longitude=_as_decimal(row.get("longitude")),
        category=_nullable(row.get("category")),
        employee_count_est=_as_int(row.get("employee_count_est")),
        raw=dict(row),
    )


def _nullable(v: str | None) -> str | None:
    if v is None:
        return None
    stripped = v.strip()
    return stripped or None


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
    except ValueError:
        return None
