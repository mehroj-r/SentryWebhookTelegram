"""multi-organisation: installations table, projects.org

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("installations"):
        op.create_table(
            "installations",
            sa.Column("uuid", sa.String, primary_key=True),
            sa.Column("org_slug", sa.String, nullable=True),
            sa.Column("app_slug", sa.String, nullable=True),
            sa.Column("status", sa.String, nullable=True),
            sa.Column("secret_label", sa.String, nullable=True),
            sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        )
    cols = {c["name"] for c in sa.inspect(bind).get_columns("projects")}
    if "org" not in cols:
        with op.batch_alter_table("projects") as batch:
            batch.add_column(sa.Column("org", sa.String, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("org")
    op.drop_table("installations")
