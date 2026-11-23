"""business_hours_on_site detector.

Observes whether the business's homepage mentions opening hours. A pure
substring + regex check; cheap heuristic. Detects:
  - "Mon–Fri 9am–5pm" style ranges
  - "Hours:" / "Open" labels
  - "24/7" / "24 hours"

Not a visibility quality judgement — just whether the page tells a visitor
when they're open.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import httpx

from leadbeast.adapters.protocols import DetectorResult
from leadbeast.db.models import Confidence, EvidenceState
from leadbeast.detectors._http import make_client


_HOURS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)\w*\s*[-–—]\s*(mon|tue|wed|thu|fri|sat|sun)", re.I),
    re.compile(r"\b(\d{1,2})(:\d{2})?\s*(am|pm)\b\s*[-–—]\s*(\d{1,2})(:\d{2})?\s*(am|pm)\b", re.I),
    re.compile(r"\bhours\s*[:\-]", re.I),
    re.compile(r"\bopen\s+(\d|mon|tue)", re.I),
    re.compile(r"\b24\s*/?\s*7\b", re.I),
    re.compile(r"\b24\s+hours\b", re.I),
]


class BusinessHoursDetector:
    signal = "business_hours_on_site"
    version = "0.1.0"
    cost_cents = 0
    window_days = 30
    needs_render = False

    async def run(self, *, business: dict[str, object]) -> Iterable[DetectorResult]:
        website = business.get("website")
        if not website or not isinstance(website, str):
            return [
                DetectorResult(
                    signal=self.signal,
                    state=EvidenceState.UNKNOWN,
                    confidence=Confidence.LOW,
                    detector_version=self.version,
                )
            ]

        try:
            async with make_client() as client:
                resp = await client.get(_normalize(website))
            if resp.status_code >= 400:
                return [
                    DetectorResult(
                        signal=self.signal,
                        state=EvidenceState.UNKNOWN,
                        value={"status": resp.status_code},
                        confidence=Confidence.LOW,
                        detector_version=self.version,
                    )
                ]
            body = resp.text[:200_000]
        except httpx.HTTPError as exc:
            return [
                DetectorResult(
                    signal=self.signal,
                    state=EvidenceState.UNKNOWN,
                    value={"error": str(exc)},
                    confidence=Confidence.LOW,
                    detector_version=self.version,
                )
            ]

        matches = [p.pattern for p in _HOURS_PATTERNS if p.search(body)]
        if matches:
            return [
                DetectorResult(
                    signal=self.signal,
                    state=EvidenceState.OBSERVED_YES,
                    value={"matches": matches[:3]},
                    confidence=Confidence.MEDIUM,
                    detector_version=self.version,
                )
            ]
        return [
            DetectorResult(
                signal=self.signal,
                state=EvidenceState.OBSERVED_NO,
                value={"searched_bytes": len(body)},
                confidence=Confidence.MEDIUM,
                detector_version=self.version,
            )
        ]


def _normalize(raw: str) -> str:
    raw = raw.strip()
    return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"
