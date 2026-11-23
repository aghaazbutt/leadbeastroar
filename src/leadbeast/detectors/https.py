"""https_present detector.

Observes whether the business's website serves over HTTPS (not just redirects
from http → https, but actually completes a TLS handshake).
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx

from leadbeast.adapters.protocols import DetectorResult
from leadbeast.db.models import Confidence, EvidenceState
from leadbeast.detectors._http import make_client


class HttpsPresentDetector:
    signal = "https_present"
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

        host = _bare_host(website)
        url = f"https://{host}"
        try:
            async with make_client() as client:
                resp = await client.get(url)
            scheme_ok = str(resp.url).startswith("https://")
            return [
                DetectorResult(
                    signal=self.signal,
                    state=(
                        EvidenceState.OBSERVED_YES
                        if scheme_ok and 200 <= resp.status_code < 400
                        else EvidenceState.OBSERVED_NO
                    ),
                    value={"final_url": str(resp.url), "status": resp.status_code},
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


def _bare_host(raw: str) -> str:
    stripped = raw.strip().lower()
    for prefix in ("https://", "http://"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break
    return stripped.split("/", 1)[0]
