"""Panic: watches + alerts.

Revision ID: 20261125_0003
Revises: 20261125_0002
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261125_0003"
down_revision: str | None = "20261125_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE panic_alert_status AS ENUM ('NEW', 'ACKNOWLEDGED', 'DISMISSED')"
    )
    panic_alert_status = sa.Enum(
        "NEW", "ACKNOWLEDGED", "DISMISSED",
        name="panic_alert_status", create_type=False,
    )
    lead_class = sa.Enum("A", "B", "C", "D", name="lead_class", create_type=False)

    op.create_table(
        "panic_watch",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("region", sa.String(120), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("category", sa.String(120), nullable=True),
        sa.Column("min_score", sa.Integer(), nullable=True),
        sa.Column("lead_class_at_least", lead_class, nullable=True),
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
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "panic_alert",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "watch_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("panic_watch.id"),
            nullable=False,
        ),
        sa.Column(
            "business_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business.id"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", panic_alert_status, nullable=False, server_default="NEW"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("watch_id", "business_id", name="uq_alert_watch_business"),
    )
    op.create_index("ix_panic_alert_watch_id", "panic_alert", ["watch_id"])
    op.create_index("ix_panic_alert_business_id", "panic_alert", ["business_id"])
    op.create_index("ix_panic_alert_status", "panic_alert", ["status"])


def downgrade() -> None:
    op.drop_index("ix_panic_alert_status", table_name="panic_alert")
    op.drop_index("ix_panic_alert_business_id", table_name="panic_alert")
    op.drop_index("ix_panic_alert_watch_id", table_name="panic_alert")
    op.drop_table("panic_alert")
    op.drop_table("panic_watch")
    op.execute("DROP TYPE IF EXISTS panic_alert_status")
