"""Golden-set release gate.

A detector/version pair must clear 90% precision on hand-labeled samples
before its evidence can contribute to drafts or reports. Policy engine
reads from golden_run via get_signal_precisions(); below the threshold →
blocked.
"""

from leadbeast.golden.gate import evaluate_detector, get_signal_precisions

__all__ = ["evaluate_detector", "get_signal_precisions"]
