"""Initial schema.

Creates every table defined in leadbeast.db.models and applies the
`REVOKE UPDATE, DELETE ON evidence_event FROM PUBLIC` guard so the
ledger cannot be mutated through the ORM.

Revision ID: 20261124_0001
Revises:
Create Date: 2026-11-24

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from leadbeast.db.models import Base

revision: str = "20261124_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    # Evidence ledger is append-only. REVOKE at the role level so even a
    # buggy ORM write cannot UPDATE or DELETE a row.
    op.execute("REVOKE UPDATE, DELETE ON evidence_event FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON score_snapshot FROM PUBLIC")


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
