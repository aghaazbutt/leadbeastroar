"""Pure fold over evidence events.

Collapses an unordered sequence of EvidenceEvent-shaped records into a stable
current state per signal. Pure function → referentially transparent, tested
under hypothesis.

Rules (from spec, Section 15.3):
  - Later observations supersede earlier ones for the same signal.
  - `supersedes_id` explicitly supersedes a specific prior event.
  - Two conflicting "observed" states within the freshness window → CONFLICTING.
  - Manual verification always wins.
  - Unknown is never a weakness — missing signals stay Unknown, not No.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from leadbeast.db.models import Confidence, EvidenceState


class EventLike(Protocol):
    id: object
    signal: str
    state: EvidenceState
    value: dict[str, object] | None
    source_key: str
    detector_version: str | None
    confidence: Confidence
    ai_extracted: bool
    ai_span: str | None
    supersedes_id: object | None
    observed_at: datetime


@dataclass(frozen=True)
class SignalState:
    signal: str
    state: EvidenceState
    value: dict[str, object] | None
    confidence: Confidence
    source_key: str
    detector_version: str | None
    observed_at: datetime


@dataclass(frozen=True)
class ResolvedState:
    signals: dict[str, SignalState] = field(default_factory=dict)

    def get(self, signal: str) -> SignalState | None:
        return self.signals.get(signal)


_CONFLICTING_PAIRS: frozenset[tuple[EvidenceState, EvidenceState]] = frozenset(
    {
        (EvidenceState.OBSERVED_YES, EvidenceState.OBSERVED_NO),
        (EvidenceState.OBSERVED_NO, EvidenceState.OBSERVED_YES),
    }
)


def _is_terminal(state: EvidenceState) -> bool:
    return state is EvidenceState.MANUALLY_VERIFIED


def fold(
    events: list[EventLike],
    *,
    freshness: dict[str, timedelta] | None = None,
    now: datetime | None = None,
) -> ResolvedState:
    """Reduce evidence events to a per-signal current state.

    Deterministic: given the same event set, returns the same resolved state.
    """
    if not events:
        return ResolvedState()

    freshness = freshness or {}
    superseded: set[object] = {e.supersedes_id for e in events if e.supersedes_id is not None}

    # Group by signal, keeping only non-superseded events.
    by_signal: dict[str, list[EventLike]] = {}
    for ev in events:
        if ev.id in superseded:
            continue
        by_signal.setdefault(ev.signal, []).append(ev)

    resolved: dict[str, SignalState] = {}
    for signal, evs in by_signal.items():
        evs.sort(key=lambda e: e.observed_at)

        terminal = next((e for e in reversed(evs) if _is_terminal(e.state)), None)
        if terminal is not None:
            resolved[signal] = _to_state(terminal)
            continue

        window = freshness.get(signal)
        ref_time = now or evs[-1].observed_at
        in_window = (
            [e for e in evs if ref_time - e.observed_at <= window] if window is not None else evs
        )
        if not in_window:
            in_window = [evs[-1]]

        latest = in_window[-1]

        # Detect active conflict within the window (ignoring unknown/inferred).
        hard = [
            e
            for e in in_window
            if e.state in (EvidenceState.OBSERVED_YES, EvidenceState.OBSERVED_NO)
        ]
        has_conflict = any(
            (a.state, b.state) in _CONFLICTING_PAIRS for a in hard for b in hard if a is not b
        )
        if has_conflict:
            # Promote to CONFLICTING but keep the latest source/version for traceability.
            resolved[signal] = SignalState(
                signal=signal,
                state=EvidenceState.CONFLICTING,
                value=latest.value,
                confidence=Confidence.LOW,
                source_key=latest.source_key,
                detector_version=latest.detector_version,
                observed_at=latest.observed_at,
            )
            continue

        resolved[signal] = _to_state(latest)

    return ResolvedState(signals=resolved)


def _to_state(e: EventLike) -> SignalState:
    return SignalState(
        signal=e.signal,
        state=e.state,
        value=e.value,
        confidence=e.confidence,
        source_key=e.source_key,
        detector_version=e.detector_version,
        observed_at=e.observed_at,
    )
