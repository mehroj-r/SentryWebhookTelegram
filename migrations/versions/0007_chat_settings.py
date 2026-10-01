"""chat settings, route thread ids, digest not_before

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table("chat_settings"):
        op.create_table(
            "chat_settings",
            sa.Column("chat_id", sa.BigInteger, primary_key=True),
            sa.Column("timezone", sa.String, nullable=True),
            sa.Column("quiet_start", sa.String, nullable=True),
            sa.Column("quiet_end", sa.String, nullable=True),
            sa.Column("language", sa.String, nullable=True),
            sa.Column("format", sa.String, nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "thread_id" not in {c["name"] for c in insp.get_columns("routes")}:
        with op.batch_alter_table("routes") as batch:
            batch.add_column(sa.Column("thread_id", sa.BigInteger, nullable=True))
    if "not_before" not in {c["name"] for c in insp.get_columns("digest_items")}:
        with op.batch_alter_table("digest_items") as batch:
            batch.add_column(sa.Column("not_before", sa.DateTime(timezone=True), nullable=True))
    if "thread_id" not in {c["name"] for c in insp.get_columns("digest_items")}:
        with op.batch_alter_table("digest_items") as batch:
            batch.add_column(sa.Column("thread_id", sa.BigInteger, nullable=True))
    if "thread_id" not in {c["name"] for c in insp.get_columns("deliveries")}:
        with op.batch_alter_table("deliveries") as batch:
            batch.add_column(sa.Column("thread_id", sa.BigInteger, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("deliveries") as batch:
        batch.drop_column("thread_id")
    with op.batch_alter_table("digest_items") as batch:
        batch.drop_column("thread_id")
        batch.drop_column("not_before")
    with op.batch_alter_table("routes") as batch:
        batch.drop_column("thread_id")
    op.drop_table("chat_settings")
