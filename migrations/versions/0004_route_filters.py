"""route noise filters

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("routes")}
    with op.batch_alter_table("routes") as batch:
        if "min_level" not in cols:
            batch.add_column(sa.Column("min_level", sa.String, nullable=True))
        if "actions" not in cols:
            batch.add_column(sa.Column("actions", sa.String, nullable=True))
        if "muted_until" not in cols:
            batch.add_column(sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("routes") as batch:
        batch.drop_column("muted_until")
        batch.drop_column("actions")
        batch.drop_column("min_level")
