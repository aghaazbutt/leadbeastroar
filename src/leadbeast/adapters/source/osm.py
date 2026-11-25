"""OpenStreetMap SourceAdapter via Overpass API.

Free, no API key. Queries `shop`, `office`, `amenity` nodes with names
inside a radius around a point. The Overpass public instance rate-limits
by User-Agent — set a descriptive one via OSM_USER_AGENT.

Expected query:
    {
        "lat": 40.7128,
        "lon": -74.0060,
        "radius_m": 5000,        # optional, default 5000
        "categories": ["shop",    # optional, default all three
                        "office",
                        "amenity"],
    }

OSM "amenity" is broad (includes benches, parking) — we filter for amenities
that typically represent businesses (restaurant, cafe, bar, bank, pharmacy,
clinic, dentist, veterinary, car_rental, fuel, car_wash, hotel).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from leadbeast.adapters.protocols import HealthReport, SourceAdapter, SourceRecordIn
from leadbeast.config import get_settings

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

_BUSINESS_AMENITIES = {
    "restaurant", "cafe", "bar", "pub", "fast_food", "food_court",
    "bank", "pharmacy", "clinic", "dentist", "doctors", "veterinary",
    "hospital", "car_rental", "fuel", "car_wash", "car_repair",
    "driving_school", "library", "theatre", "cinema", "nightclub",
}


class OsmOverpassAdapter(SourceAdapter):
    key = "osm"
    cost_cents_per_record = 0

    def __init__(self, timeout_s: float = 60.0) -> None:
        self._timeout = timeout_s
        self._user_agent = get_settings().osm_user_agent

    async def fetch(self, *, query: dict[str, object]) -> AsyncIterator[SourceRecordIn]:
        lat = _as_float(query.get("lat"))
        lon = _as_float(query.get("lon"))
        if lat is None or lon is None:
            raise ValueError("osm.fetch requires numeric 'lat' and 'lon'")

        radius_m = int(_as_float(query.get("radius_m")) or 5000)
        categories = query.get("categories") or ["shop", "office", "amenity"]
        if not isinstance(categories, list):
            raise ValueError("'categories' must be a list of OSM top-level tags")

        ql = _build_overpass_ql(lat, lon, radius_m, [str(c) for c in categories])
        elements = await self._post(ql)

        for el in elements:
            record = _element_to_record(el)
            if record is not None:
                yield record

    async def _post(self, ql: str) -> list[dict[str, object]]:
        headers = {"User-Agent": self._user_agent}
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(OVERPASS_URL, data=ql, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
        return list(data.get("elements", []))

    async def health(self) -> HealthReport:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://overpass-api.de/api/status",
                    headers={"User-Agent": self._user_agent},
                )
            if resp.status_code == 200:
                return HealthReport(key=self.key, status="healthy", detail="overpass.de reachable")
            return HealthReport(
                key=self.key, status="degraded", detail=f"overpass status {resp.status_code}"
            )
        except httpx.HTTPError as exc:
            return HealthReport(key=self.key, status="off", detail=str(exc))


def _build_overpass_ql(lat: float, lon: float, radius_m: int, categories: list[str]) -> str:
    body_lines = []
    for cat in categories:
        if cat == "amenity":
            amenities = "|".join(sorted(_BUSINESS_AMENITIES))
            body_lines.append(
                f'  node["amenity"~"^({amenities})$"]["name"](around:{radius_m},{lat},{lon});'
            )
        else:
            body_lines.append(
                f'  node["{cat}"]["name"](around:{radius_m},{lat},{lon});'
            )
    body = "\n".join(body_lines)
    return f"[out:json][timeout:60];\n(\n{body}\n);\nout body;\n"


def _element_to_record(el: dict[str, object]) -> SourceRecordIn | None:
    tags = el.get("tags")
    if not isinstance(tags, dict):
        return None
    name = str(tags.get("name") or "").strip()
    if not name:
        return None

    osm_id = el.get("id")
    external_id = f"node/{osm_id}" if osm_id else hashlib.sha256(name.encode()).hexdigest()[:24]

    phone = _first_nonempty(tags.get("phone"), tags.get("contact:phone"))
    website = _first_nonempty(tags.get("website"), tags.get("contact:website"))
    email = _first_nonempty(tags.get("email"), tags.get("contact:email"))

    address = _compose_address(tags)
    category = _pick_category(tags)

    return SourceRecordIn(
        source_key="osm",
        external_id=external_id,
        name=name,
        website=website,
        phone=phone,
        email=email,
        address=address,
        city=_opt(tags.get("addr:city")),
        region=_opt(tags.get("addr:state") or tags.get("addr:region")),
        country=_opt(tags.get("addr:country")),
        latitude=_as_decimal(el.get("lat")),
        longitude=_as_decimal(el.get("lon")),
        category=category,
        employee_count_est=None,
        raw={"id": osm_id, "tags": tags},
    )


def _as_float(v: object) -> float | None:
    if v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_decimal(v: object) -> Decimal | None:
    f = _as_float(v)
    if f is None:
        return None
    return Decimal(str(f))


def _opt(v: object) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s or None


def _first_nonempty(*vals: object) -> str | None:
    for v in vals:
        s = _opt(v)
        if s:
            return s
    return None


def _compose_address(tags: dict[str, object]) -> str | None:
    street = _opt(tags.get("addr:street"))
    housenumber = _opt(tags.get("addr:housenumber"))
    if not street:
        return None
    if housenumber:
        return f"{housenumber} {street}"
    return street


def _pick_category(tags: dict[str, object]) -> str | None:
    for key in ("shop", "office", "amenity", "craft"):
        v = _opt(tags.get(key))
        if v:
            return f"{key}:{v}"
    return None
