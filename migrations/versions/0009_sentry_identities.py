"""sentry identities for issue action buttons

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("sentry_identities"):
        op.create_table(
            "sentry_identities",
            sa.Column("telegram_user_id", sa.BigInteger, primary_key=True),
            sa.Column("sentry_user", sa.String, nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("sentry_identities")
