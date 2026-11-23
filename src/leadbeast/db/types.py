from __future__ import annotations

import uuid

import uuid_utils


def uuid7() -> uuid.UUID:
    """Return a time-ordered UUIDv7 as a stdlib UUID."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)
