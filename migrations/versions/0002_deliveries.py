"""delivery log

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("deliveries"):
        return
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chat_id", sa.BigInteger, nullable=False),
        sa.Column("resource", sa.String, nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("project", sa.String, nullable=True),
        sa.Column("environment", sa.String, nullable=True),
        sa.Column("issue_id", sa.String, nullable=True),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("tg_message_id", sa.BigInteger, nullable=True),
    )
    op.create_index("ix_deliveries_chat_created", "deliveries", ["chat_id", "created_at"])
    op.create_index("ix_deliveries_status", "deliveries", ["status"])
    op.create_index("ix_deliveries_issue", "deliveries", ["chat_id", "issue_id"])


def downgrade() -> None:
    op.drop_table("deliveries")
