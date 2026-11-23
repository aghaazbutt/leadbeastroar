"""website_reachable detector.

Observes whether a business's website responds to a GET with any 2xx/3xx.
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx

from leadbeast.adapters.protocols import DetectorResult
from leadbeast.db.models import Confidence, EvidenceState
from leadbeast.detectors._http import make_client


class WebsiteReachabilityDetector:
    signal = "website_reachable"
    version = "0.1.0"
    cost_cents = 0
    window_days = 7
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

        url = _normalize_url(website)
        try:
            async with make_client() as client:
                resp = await client.get(url)
            if 200 <= resp.status_code < 400:
                return [
                    DetectorResult(
                        signal=self.signal,
                        state=EvidenceState.OBSERVED_YES,
                        value={"status": resp.status_code, "final_url": str(resp.url)},
                        confidence=Confidence.HIGH,
                        detector_version=self.version,
                    )
                ]
            return [
                DetectorResult(
                    signal=self.signal,
                    state=EvidenceState.OBSERVED_NO,
                    value={"status": resp.status_code},
                    confidence=Confidence.HIGH,
                    detector_version=self.version,
                )
            ]
        except httpx.HTTPError as exc:
            return [
                DetectorResult(
                    signal=self.signal,
                    state=EvidenceState.OBSERVED_NO,
                    value={"error": str(exc)},
                    confidence=Confidence.MEDIUM,
                    detector_version=self.version,
                )
            ]


def _normalize_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith(("http://", "https://")):
        return raw
    return f"https://{raw}"
