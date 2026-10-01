"""digest routes

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("routes")}
    if "digest_minutes" not in cols:
        with op.batch_alter_table("routes") as batch:
            batch.add_column(sa.Column("digest_minutes", sa.Integer, nullable=True))
    if not sa.inspect(bind).has_table("digest_items"):
        op.create_table(
            "digest_items",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("chat_id", sa.BigInteger, nullable=False),
            sa.Column("route_id", sa.Integer, nullable=False),
            sa.Column("project", sa.String, nullable=True),
            sa.Column("environment", sa.String, nullable=True),
            sa.Column("issue_id", sa.String, nullable=True),
            sa.Column("resource", sa.String, nullable=False),
            sa.Column("action", sa.String, nullable=False),
            sa.Column("level", sa.String, nullable=True),
            sa.Column("title", sa.String, nullable=False),
            sa.Column("web_url", sa.String, nullable=True),
        )
        op.create_index("ix_digest_items_chat", "digest_items", ["chat_id", "created_at"])


def downgrade() -> None:
    op.drop_table("digest_items")
    with op.batch_alter_table("routes") as batch:
        batch.drop_column("digest_minutes")
