"""Null model: deterministic template response. Safe for tests and dry-runs."""

from __future__ import annotations

from leadbeast.adapters.protocols import HealthReport, ModelClient


class NullModel(ModelClient):
    key = "null"

    async def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        return (
            "Hi there — I noticed a couple of visibility gaps on your site and wanted "
            "to share a 1-page diagnostic. No obligation. — LeadBeast (dry-run)"
        )

    async def health(self) -> HealthReport:
        return HealthReport(key=self.key, status="healthy", detail="deterministic stub")
