"""Dialer: call_task table + enums.

Revision ID: 20261125_0002
Revises: 20261124_0001
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261125_0002"
down_revision: str | None = "20261124_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    call_task_status = sa.Enum(
        "QUEUED", "IN_PROGRESS", "COMPLETED", "SKIPPED",
        name="call_task_status", create_type=False,
    )
    call_outcome = sa.Enum(
        "CONNECTED", "VOICEMAIL", "NO_ANSWER", "CALLBACK", "REJECTED", "WRONG_NUMBER",
        name="call_outcome", create_type=False,
    )
    op.execute(
        "CREATE TYPE call_task_status AS ENUM ('QUEUED', 'IN_PROGRESS', 'COMPLETED', 'SKIPPED')"
    )
    op.execute(
        "CREATE TYPE call_outcome AS ENUM ('CONNECTED', 'VOICEMAIL', 'NO_ANSWER', 'CALLBACK', 'REJECTED', 'WRONG_NUMBER')"
    )

    op.create_table(
        "call_task",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "business_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business.id"),
            nullable=False,
        ),
        sa.Column("status", call_task_status, nullable=False, server_default="QUEUED"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outcome", call_outcome, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("business_id", name="uq_call_task_business"),
    )
    op.create_index("ix_call_task_business_id", "call_task", ["business_id"])
    op.create_index("ix_call_task_status", "call_task", ["status"])
    op.create_index("ix_call_task_priority", "call_task", ["priority"])


def downgrade() -> None:
    op.drop_index("ix_call_task_priority", table_name="call_task")
    op.drop_index("ix_call_task_status", table_name="call_task")
    op.drop_index("ix_call_task_business_id", table_name="call_task")
    op.drop_table("call_task")
    op.execute("DROP TYPE IF EXISTS call_outcome")
    op.execute("DROP TYPE IF EXISTS call_task_status")
