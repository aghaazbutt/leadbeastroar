from __future__ import annotations

from decimal import Decimal

from leadbeast.db.models import Confidence, LeadClass
from leadbeast.evidence import ResolvedState
from leadbeast.policy import PolicyProfile, check
from leadbeast.scoring import ScoreResult


def _score(cls: LeadClass, conf: Confidence) -> ScoreResult:
    return ScoreResult(
        score=70,
        lead_class=cls,
        confidence=conf,
        sub_scores={},
        reasons=[{"signal": "x", "detector_version": "0.1.0"}],
        evidence_hash="",
    )


def test_email_blocked_when_no_contact_email() -> None:
    r = check(
        score=_score(LeadClass.A, Confidence.HIGH),
        resolved=ResolvedState(),
        channel="email",
        profile=PolicyProfile(),
        signal_precisions={},
        has_email=False,
        has_phone=True,
    )
    assert not r.allowed
    assert any("contact email" in x for x in r.reasons)


def test_email_allowed_when_meets_threshold() -> None:
    r = check(
        score=_score(LeadClass.A, Confidence.HIGH),
        resolved=ResolvedState(),
        channel="email",
        profile=PolicyProfile(),
        signal_precisions={},
        has_email=True,
        has_phone=False,
    )
    assert r.allowed


def test_golden_precision_blocks() -> None:
    r = check(
        score=_score(LeadClass.A, Confidence.HIGH),
        resolved=ResolvedState(),
        channel="email",
        profile=PolicyProfile(),
        signal_precisions={("x", "0.1.0"): Decimal("0.8")},
        has_email=True,
        has_phone=False,
    )
    assert not r.allowed
    assert any("golden threshold" in x for x in r.reasons)
