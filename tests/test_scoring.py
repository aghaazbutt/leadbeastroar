"""Property tests for scoring.engine."""

from __future__ import annotations

from datetime import UTC, datetime

from leadbeast.db.models import Confidence, EvidenceState, LeadClass
from leadbeast.evidence import fold
from leadbeast.scoring import score
from tests.test_fold import _mk  # type: ignore[attr-defined]


def test_score_is_bounded() -> None:
    evs = [
        _mk("website_reachable", EvidenceState.OBSERVED_YES, 10),
        _mk("https_present", EvidenceState.OBSERVED_YES, 10),
    ]
    r = score(fold(evs), pack_version="test/0.0.1")
    assert 0 <= r.score <= 100


def test_score_deterministic() -> None:
    evs = [
        _mk("website_reachable", EvidenceState.OBSERVED_NO, 10),
        _mk("https_present", EvidenceState.OBSERVED_NO, 10),
        _mk("business_hours_on_site", EvidenceState.OBSERVED_NO, 10),
    ]
    a = score(fold(evs), pack_version="test/0.0.1")
    b = score(fold(evs), pack_version="test/0.0.1")
    assert a.score == b.score
    assert a.evidence_hash == b.evidence_hash


def test_empty_evidence_is_class_d() -> None:
    r = score(fold([]), pack_version="test/0.0.1")
    assert r.lead_class is LeadClass.D
    assert r.confidence is Confidence.LOW
