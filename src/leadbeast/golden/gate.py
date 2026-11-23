"""Golden-set evaluation + precision cache.

evaluate_detector(signal, version) runs the detector against labeled
businesses and inserts a golden_run row. The policy engine then reads
the latest passing precision via get_signal_precisions().
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadbeast.db.models import EvidenceState, GoldenLabel, GoldenRun
from leadbeast.detectors import ALL_DETECTORS
from leadbeast.logging import get_logger

log = get_logger("golden.gate")

PRECISION_THRESHOLD: Decimal = Decimal("0.90")


async def evaluate_detector(
    session: Session, *, signal: str, version: str
) -> GoldenRun:
    """Run the named detector against every labeled business and record precision."""
    labels = session.execute(
        select(GoldenLabel).where(
            GoldenLabel.signal == signal, GoldenLabel.detector_version == version
        )
    ).scalars().all()
    if not labels:
        run = GoldenRun(
            signal=signal,
            detector_version=version,
            precision=Decimal("0"),
            recall=Decimal("0"),
            samples=0,
            passes_gate=False,
        )
        session.add(run)
        session.flush()
        return run

    DetectorCls = next((d for d in ALL_DETECTORS if d.signal == signal), None)  # type: ignore[attr-defined]
    if DetectorCls is None:
        raise ValueError(f"No detector registered for signal={signal}")
    det = DetectorCls()

    tp = 0
    fp = 0
    fn = 0
    for label in labels:
        from leadbeast.db.models import Business

        biz = session.get(Business, label.business_id)
        if biz is None:
            continue
        results = await det.run(
            business={
                "name": biz.name,
                "website": biz.website,
                "phone": biz.phone,
                "email": biz.email,
            }
        )
        observed = next(iter(results), None)
        if observed is None:
            continue
        expected = label.expected_state
        if expected is EvidenceState.OBSERVED_YES:
            if observed.state is EvidenceState.OBSERVED_YES:
                tp += 1
            else:
                fn += 1
        elif expected is EvidenceState.OBSERVED_NO:
            if observed.state is EvidenceState.OBSERVED_YES:
                fp += 1

    precision = Decimal(tp) / Decimal(tp + fp) if (tp + fp) else Decimal("0")
    recall = Decimal(tp) / Decimal(tp + fn) if (tp + fn) else Decimal("0")
    passes = precision >= PRECISION_THRESHOLD

    run = GoldenRun(
        signal=signal,
        detector_version=version,
        precision=precision,
        recall=recall,
        samples=len(labels),
        passes_gate=passes,
    )
    session.add(run)
    session.flush()
    log.info(
        "golden.evaluated",
        signal=signal,
        version=version,
        precision=str(precision),
        recall=str(recall),
        passes=passes,
    )
    return run


def get_signal_precisions(session: Session) -> dict[tuple[str, str], Decimal]:
    """Return latest-per-(signal, version) precision for policy lookup."""
    rows = session.execute(
        select(GoldenRun).order_by(GoldenRun.created_at.desc())
    ).scalars().all()
    seen: dict[tuple[str, str], Decimal] = {}
    for r in rows:
        key = (r.signal, r.detector_version)
        if key not in seen:
            seen[key] = r.precision
    return seen
