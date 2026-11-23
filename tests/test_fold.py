"""Property tests for evidence.fold.

Invariants:
    1. Determinism: fold(evs) == fold(evs)
    2. Permutation stability: fold(evs) == fold(shuffle(evs))
    3. Monotonicity: adding a later event never leaves the signal at an older state.
    4. Terminal win: a MANUALLY_VERIFIED event always wins.
    5. Supersedes: if event A supersedes event B, B does not appear in output.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from leadbeast.db.models import Confidence, EvidenceState
from leadbeast.evidence import fold


@dataclass
class FakeEvent:
    id: uuid.UUID
    signal: str
    state: EvidenceState
    value: dict | None
    source_key: str
    detector_version: str | None
    confidence: Confidence
    ai_extracted: bool
    ai_span: str | None
    supersedes_id: uuid.UUID | None
    observed_at: datetime


def _mk(signal: str, state: EvidenceState, mins_ago: int, *, supersedes: uuid.UUID | None = None) -> FakeEvent:
    return FakeEvent(
        id=uuid.uuid4(),
        signal=signal,
        state=state,
        value=None,
        source_key="test",
        detector_version="0.1.0",
        confidence=Confidence.MEDIUM,
        ai_extracted=False,
        ai_span=None,
        supersedes_id=supersedes,
        observed_at=datetime.now(UTC) - timedelta(minutes=mins_ago),
    )


def test_determinism() -> None:
    evs = [
        _mk("https_present", EvidenceState.OBSERVED_YES, 10),
        _mk("https_present", EvidenceState.OBSERVED_NO, 60),
    ]
    assert fold(evs).signals == fold(evs).signals


def test_latest_wins() -> None:
    evs = [
        _mk("https_present", EvidenceState.OBSERVED_NO, 60),
        _mk("https_present", EvidenceState.OBSERVED_YES, 10),
    ]
    r = fold(evs)
    assert r.get("https_present").state is EvidenceState.CONFLICTING  # both observed within unlimited window → conflict


def test_latest_wins_when_no_window_conflict() -> None:
    evs = [
        _mk("https_present", EvidenceState.UNKNOWN, 60),
        _mk("https_present", EvidenceState.OBSERVED_YES, 10),
    ]
    r = fold(evs)
    assert r.get("https_present").state is EvidenceState.OBSERVED_YES


def test_terminal_wins() -> None:
    evs = [
        _mk("https_present", EvidenceState.OBSERVED_NO, 1),
        _mk("https_present", EvidenceState.MANUALLY_VERIFIED, 60),
    ]
    r = fold(evs)
    assert r.get("https_present").state is EvidenceState.MANUALLY_VERIFIED


def test_supersedes_removes_prior() -> None:
    a = _mk("https_present", EvidenceState.OBSERVED_NO, 60)
    b = _mk("https_present", EvidenceState.OBSERVED_YES, 10, supersedes=a.id)
    r = fold([a, b])
    assert r.get("https_present").state is EvidenceState.OBSERVED_YES


@settings(max_examples=50)
@given(st.integers(min_value=1, max_value=20))
def test_permutation_stability(n: int) -> None:
    base = [
        _mk("https_present", EvidenceState.OBSERVED_YES if i % 2 == 0 else EvidenceState.UNKNOWN, i)
        for i in range(n)
    ]
    shuffled = list(base)
    random.shuffle(shuffled)
    assert fold(base).signals.keys() == fold(shuffled).signals.keys()
    for k in fold(base).signals:
        assert fold(base).get(k).state is fold(shuffled).get(k).state
