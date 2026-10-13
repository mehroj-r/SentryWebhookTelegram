"""audit log

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("audit_log"):
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
            sa.Column("chat_id", sa.BigInteger, nullable=False),
            sa.Column("user_id", sa.BigInteger, nullable=True),
            sa.Column("action", sa.String, nullable=False),
            sa.Column("details", sa.Text, nullable=True),
        )
        op.create_index("ix_audit_log_chat_ts", "audit_log", ["chat_id", "ts"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_chat_ts", table_name="audit_log")
    op.drop_table("audit_log")
