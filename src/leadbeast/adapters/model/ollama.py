"""Ollama ModelClient.

Default local LLM. Reads OLLAMA_HOST and OLLAMA_MODEL from settings. Falls
back to `off` health if the host is unreachable so the policy engine can
skip AI-flavored draft generation cleanly.
"""

from __future__ import annotations

import httpx

from leadbeast.adapters.protocols import HealthReport, ModelClient
from leadbeast.config import get_settings


class OllamaModel(ModelClient):
    key = "ollama"

    def __init__(self) -> None:
        s = get_settings()
        self._host = s.ollama_host.rstrip("/")
        self._model = s.ollama_model
        self._client = httpx.AsyncClient(timeout=60.0)

    async def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        resp = await self._client.post(
            f"{self._host}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("message", {}).get("content", "")).strip()

    async def health(self) -> HealthReport:
        try:
            resp = await self._client.get(f"{self._host}/api/tags", timeout=3.0)
            if resp.status_code == 200:
                return HealthReport(key=self.key, status="healthy", detail=self._model)
            return HealthReport(key=self.key, status="degraded", detail=f"HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            return HealthReport(key=self.key, status="off", detail=str(exc))
