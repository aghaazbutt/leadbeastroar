"""Simple DI container for adapters.

Rules:
    - One registered instance per Protocol per app lifetime (singleton).
    - Resolution by Protocol class, not by name. Swap by env.
    - Registration is explicit; no magic imports.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


class Registry:
    def __init__(self) -> None:
        self._instances: dict[type, object] = {}

    def register(self, protocol: type[T], instance: T) -> None:
        self._instances[protocol] = instance

    def get(self, protocol: type[T]) -> T:
        try:
            return self._instances[protocol]  # type: ignore[return-value]
        except KeyError as exc:
            raise LookupError(
                f"No adapter registered for {protocol.__name__}. "
                "Call register() during app startup."
            ) from exc

    def has(self, protocol: type) -> bool:
        return protocol in self._instances


registry = Registry()
