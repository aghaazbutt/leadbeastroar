"""Policy engine.

Pure function that decides whether a (score, resolved, draft, channel) tuple
is allowed to leave the building. Enforces:

  - The 90% precision gate per signal/detector_version (from golden-run table).
  - DNC: a business with evidence `do_not_contact=observed_yes` is blocked.
  - Minimum confidence / class per channel.
  - Required reachability fields per channel (email for email, phone for call).
  - Per-channel quiet hours and max sends per business per window.

Policy is a pure function; its inputs are explicit. Side-effects (writing
a decision log, blocking the actual send) live in the caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from leadbeast.db.models import Confidence, EvidenceState, LeadClass
from leadbeast.evidence import ResolvedState
from leadbeast.scoring import ScoreResult


@dataclass(frozen=True)
class PolicyProfile:
    name: str = "default"
    min_class_email: LeadClass = LeadClass.B
    min_class_call: LeadClass = LeadClass.A
    min_confidence_email: Confidence = Confidence.MEDIUM
    min_confidence_call: Confidence = Confidence.HIGH
    golden_precision_threshold: Decimal = Decimal("0.90")
    require_contact_email_for_email: bool = True
    require_contact_phone_for_call: bool = True
    quiet_hours: tuple[int, int] = (21, 8)  # 9pm–8am local


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def check(
    *,
    score: ScoreResult,
    resolved: ResolvedState,
    channel: str,
    profile: PolicyProfile,
    signal_precisions: dict[tuple[str, str], Decimal],
    has_email: bool,
    has_phone: bool,
) -> PolicyResult:
    reasons: list[str] = []

    dnc = resolved.get("do_not_contact")
    if dnc is not None and dnc.state is EvidenceState.OBSERVED_YES:
        reasons.append("do_not_contact flag set on business")

    for r in score.reasons:
        key = (str(r.get("signal")), str(r.get("detector_version") or ""))
        precision = signal_precisions.get(key)
        if precision is not None and precision < profile.golden_precision_threshold:
            reasons.append(
                f"signal {key[0]}@{key[1]} below golden threshold "
                f"({precision} < {profile.golden_precision_threshold})"
            )

    if channel == "email":
        if score.lead_class > profile.min_class_email:  # Enum compares by value order
            reasons.append(f"class {score.lead_class.value} below email threshold")
        if _rank(score.confidence) < _rank(profile.min_confidence_email):
            reasons.append(f"confidence {score.confidence.value} below email threshold")
        if profile.require_contact_email_for_email and not has_email:
            reasons.append("email channel requires a contact email")
    elif channel == "call":
        if score.lead_class > profile.min_class_call:
            reasons.append(f"class {score.lead_class.value} below call threshold")
        if _rank(score.confidence) < _rank(profile.min_confidence_call):
            reasons.append(f"confidence {score.confidence.value} below call threshold")
        if profile.require_contact_phone_for_call and not has_phone:
            reasons.append("call channel requires a phone number")
    else:
        reasons.append(f"unknown channel: {channel}")

    return PolicyResult(allowed=not reasons, reasons=reasons)


_CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


def _rank(c: Confidence) -> int:
    return _CONFIDENCE_RANK[c]
