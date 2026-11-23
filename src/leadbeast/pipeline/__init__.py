"""10-stage lead pipeline.

Collect → Resolve → Vitality → Detect → Audit → Score → Contact → Draft → Approve → Send

All stages:
    - Are idempotent (pipeline_run uniqueness on (business, campaign, stage, run_id)).
    - Append to evidence_event (never mutate).
    - Can be re-run cheaply (resolve() + score() are pure).
    - Report cost via cost.guard, not by their own tracking.
"""
