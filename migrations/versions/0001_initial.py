"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _has_index(table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in sa.inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    # Databases created before Alembic was introduced already have the tables
    # (via metadata.create_all); only add what is missing.
    if not _has_table("routes"):
        op.create_table(
            "routes",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("project", sa.String, nullable=False),
            sa.Column("environment", sa.String, nullable=True),
            sa.Column("chat_id", sa.BigInteger, nullable=False),
            sa.Column("created_by", sa.BigInteger, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("project", "environment", "chat_id", name="uq_route"),
        )
    if not _has_index("routes", "ix_routes_chat_id"):
        op.create_index("ix_routes_chat_id", "routes", ["chat_id"])

    if not _has_table("projects"):
        op.create_table(
            "projects",
            sa.Column("slug", sa.String, primary_key=True),
            sa.Column("ref_id", sa.BigInteger, nullable=True),
            sa.Column("name", sa.String, nullable=True),
            sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        )
    if not _has_index("projects", "ix_projects_ref_id"):
        op.create_index("ix_projects_ref_id", "projects", ["ref_id"])

    if not _has_table("environments"):
        op.create_table(
            "environments",
            sa.Column("project", sa.String, primary_key=True),
            sa.Column("environment", sa.String, primary_key=True),
        )

    if not _has_table("seen_requests"):
        op.create_table(
            "seen_requests",
            sa.Column("request_id", sa.String, primary_key=True),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        )
    if not _has_index("seen_requests", "ix_seen_requests_ts"):
        op.create_index("ix_seen_requests_ts", "seen_requests", ["ts"])


def downgrade() -> None:
    op.drop_table("seen_requests")
    op.drop_table("environments")
    op.drop_table("projects")
    op.drop_table("routes")
