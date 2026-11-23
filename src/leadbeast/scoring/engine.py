"""Pure scoring engine.

Takes a ResolvedState (signal → state) + pack weights → ScoreResult.
Deterministic. No I/O. Reruns are cheap by design.

Sub-scores are the four quadrants from the UI dossier:
    need            — gap evidence (low visibility, outdated site, no reviews)
    ability_to_pay  — operating indicators (website presence, employees, ad spend)
    timing          — recency signals (hiring, moved, new owner)
    reachability    — contact completeness
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from leadbeast.db.models import Confidence, EvidenceState, LeadClass
from leadbeast.evidence import ResolvedState


@dataclass(frozen=True)
class ScoreResult:
    score: int
    lead_class: LeadClass
    confidence: Confidence
    sub_scores: dict[str, int]
    reasons: list[dict[str, object]] = field(default_factory=list)
    evidence_hash: str = ""


# Default sub-score composition weights (sum = 1.0). Packs can override.
DEFAULT_SUB_WEIGHTS: dict[str, float] = {
    "need": 0.45,
    "ability_to_pay": 0.20,
    "timing": 0.15,
    "reachability": 0.20,
}

# Signal → (sub_score, contribution when OBSERVED_YES vs OBSERVED_NO).
# OBSERVED_YES contributes toward the GAP being present (bad for the business,
# good for the pitch). OBSERVED_NO contributes negatively (the gap isn't there).
DEFAULT_SIGNAL_MAP: dict[str, tuple[str, int, int]] = {
    "website_reachable":    ("ability_to_pay", -40, +30),
    "https_present":        ("ability_to_pay",  +0, +25),
    "business_hours_on_site": ("reachability", -15, +10),
    "has_phone":            ("reachability", -20, +20),
    "has_email":            ("reachability", -15, +15),
    "visibility_gap":       ("need",         +40, -10),
    "outdated_site":        ("need",         +30, -10),
    "no_recent_reviews":    ("need",         +20, -10),
    "recent_hiring":        ("timing",       +25,  +0),
    "recent_move":          ("timing",       +20,  +0),
    "ad_spend_detected":    ("ability_to_pay", +15, -10),
}


def score(
    resolved: ResolvedState,
    *,
    pack_version: str,
    pack_weights: dict[str, object] | None = None,
) -> ScoreResult:
    weights: dict[str, float] = dict(DEFAULT_SUB_WEIGHTS)
    signal_map: dict[str, tuple[str, int, int]] = dict(DEFAULT_SIGNAL_MAP)

    if pack_weights:
        if "sub_weights" in pack_weights and isinstance(pack_weights["sub_weights"], dict):
            for k, v in pack_weights["sub_weights"].items():  # type: ignore[union-attr]
                if isinstance(v, (int, float)):
                    weights[k] = float(v)
        if "signals" in pack_weights and isinstance(pack_weights["signals"], dict):
            for signal_name, override in pack_weights["signals"].items():  # type: ignore[union-attr]
                if (
                    isinstance(override, dict)
                    and "sub" in override
                    and "yes" in override
                    and "no" in override
                ):
                    signal_map[signal_name] = (
                        str(override["sub"]),
                        int(override["yes"]),
                        int(override["no"]),
                    )

    sub_raw: dict[str, int] = {k: 0 for k in weights}
    reasons: list[dict[str, object]] = []
    hard_signals = 0
    ai_signals = 0
    unknown_signals = 0

    for signal_name, (sub, yes_delta, no_delta) in signal_map.items():
        sig = resolved.get(signal_name)
        if sig is None or sig.state is EvidenceState.UNKNOWN:
            unknown_signals += 1
            continue
        if sig.state is EvidenceState.OBSERVED_YES or sig.state is EvidenceState.MANUALLY_VERIFIED:
            delta = yes_delta
            hard_signals += 1
        elif sig.state is EvidenceState.OBSERVED_NO:
            delta = no_delta
            hard_signals += 1
        elif sig.state is EvidenceState.INFERRED:
            delta = yes_delta // 2
            ai_signals += 1
        elif sig.state is EvidenceState.CONFLICTING:
            continue
        else:  # NOT_DETECTED
            delta = no_delta // 2

        sub_raw[sub] = max(-100, min(100, sub_raw[sub] + delta))
        reasons.append(
            {
                "signal": signal_name,
                "state": sig.state.value,
                "delta": delta,
                "source": sig.source_key,
                "detector_version": sig.detector_version,
            }
        )

    composed = 0.0
    for sub, w in weights.items():
        normalized = (sub_raw.get(sub, 0) + 100) / 2  # map [-100, 100] → [0, 100]
        composed += w * normalized
    final = max(0, min(100, round(composed)))

    lead_class = _classify(final, hard_signals, unknown_signals)
    confidence = _confidence(hard_signals, ai_signals, unknown_signals, len(signal_map))

    evidence_hash = _hash(resolved)

    return ScoreResult(
        score=final,
        lead_class=lead_class,
        confidence=confidence,
        sub_scores={k: (v + 100) // 2 for k, v in sub_raw.items()},
        reasons=reasons,
        evidence_hash=evidence_hash,
    )


def _classify(final: int, hard: int, unknown: int) -> LeadClass:
    if unknown > 7:
        return LeadClass.D
    if final >= 75 and hard >= 3:
        return LeadClass.A
    if final >= 55:
        return LeadClass.B
    if final >= 35:
        return LeadClass.C
    return LeadClass.D


def _confidence(hard: int, ai: int, unknown: int, total: int) -> Confidence:
    if total == 0:
        return Confidence.LOW
    coverage = (hard + ai) / total
    if coverage >= 0.7 and hard >= 3:
        return Confidence.HIGH
    if coverage >= 0.4:
        return Confidence.MEDIUM
    return Confidence.LOW


def _hash(resolved: ResolvedState) -> str:
    payload = json.dumps(
        {
            s: {
                "state": st.state.value,
                "source": st.source_key,
                "version": st.detector_version or "",
                "observed_at": st.observed_at.isoformat(),
            }
            for s, st in sorted(resolved.signals.items())
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
