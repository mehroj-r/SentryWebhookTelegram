"""store sent text for later edits

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("deliveries")}
    if "text" not in cols:
        with op.batch_alter_table("deliveries") as batch:
            batch.add_column(sa.Column("text", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("deliveries") as batch:
        batch.drop_column("text")
