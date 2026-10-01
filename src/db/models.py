from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("project", "environment", "chat_id", name="uq_route"),
        Index("ix_routes_chat_id", "chat_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Noise control (all optional): minimum level, comma-separated action
    # allowlist, and a mute deadline.
    min_level: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actions: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    muted_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Project(Base):
    __tablename__ = "projects"

    slug: Mapped[str] = mapped_column(String, primary_key=True)
    ref_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Environment(Base):
    __tablename__ = "environments"

    project: Mapped[str] = mapped_column(String, primary_key=True)
    environment: Mapped[str] = mapped_column(String, primary_key=True)


class SeenRequest(Base):
    __tablename__ = "seen_requests"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    # Indexed so periodic purging of old rows doesn't scan the whole table.
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class Delivery(Base):
    """One row per (event, target chat) delivery attempt — the audit trail for
    "why didn't I get that alert" and the data source for /last and /stats."""

    __tablename__ = "deliveries"
    __table_args__ = (
        Index("ix_deliveries_chat_created", "chat_id", "created_at"),
        Index("ix_deliveries_status", "status"),
        Index("ix_deliveries_issue", "chat_id", "issue_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resource: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False, default="")
    project: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    environment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    issue_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False)  # sent | failed | skipped
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tg_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # The HTML we sent, kept so later lifecycle events can edit the message.
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
