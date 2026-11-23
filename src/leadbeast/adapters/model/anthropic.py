"""Anthropic ModelClient — STUB.

Activated when LB_MODEL_PROVIDER=anthropic and ANTHROPIC_API_KEY is set.
Uses httpx directly to avoid an SDK dependency for the stub; swap in
`anthropic` package when live. Default model is claude-sonnet-4-6.
"""

from __future__ import annotations

import httpx

from leadbeast.adapters.protocols import HealthReport, ModelClient
from leadbeast.config import get_settings


class AnthropicModel(ModelClient):
    key = "anthropic"

    def __init__(self) -> None:
        s = get_settings()
        self._api_key = s.anthropic_api_key
        self._model = s.anthropic_model
        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            timeout=60.0,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )

    async def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        if not self._api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        resp = await self._client.post(
            "/v1/messages",
            json={
                "model": self._model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        blocks = data.get("content", [])
        if blocks and isinstance(blocks, list):
            return str(blocks[0].get("text", "")).strip()
        return ""

    async def health(self) -> HealthReport:
        if not self._api_key:
            return HealthReport(key=self.key, status="off", detail="ANTHROPIC_API_KEY unset")
        return HealthReport(key=self.key, status="healthy", detail=self._model)
