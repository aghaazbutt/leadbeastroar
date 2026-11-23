"""Signal detectors.

Each detector implements DetectorProtocol:
    signal:        str             — unique signal key written into evidence_event
    version:       str             — bump when logic changes, triggers golden re-eval
    cost_cents:    int             — 0 for offline, >0 for paid lookups
    window_days:   int             — freshness window for fold()
    needs_render:  bool            — True if HTML rendering (playwright, etc.) is needed

    run(business)  → Iterable[DetectorResult]

Rules:
  - No detector may call another detector (keeps the Protocol flat and testable).
  - Every detector has fixtures in tests/detectors/fixtures/<signal>/.
  - "No fixtures, no merge."
"""

from leadbeast.detectors.hours import BusinessHoursDetector
from leadbeast.detectors.https import HttpsPresentDetector
from leadbeast.detectors.reachability import WebsiteReachabilityDetector

ALL_DETECTORS: list[type] = [
    WebsiteReachabilityDetector,
    HttpsPresentDetector,
    BusinessHoursDetector,
]

__all__ = [
    "ALL_DETECTORS",
    "BusinessHoursDetector",
    "HttpsPresentDetector",
    "WebsiteReachabilityDetector",
]
