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
    # NULL = deliver instantly; N = collect and send one digest every N minutes.
    digest_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Forum topic to post into (set automatically when the route is created inside a topic).
    thread_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class Project(Base):
    __tablename__ = "projects"

    slug: Mapped[str] = mapped_column(String, primary_key=True)
    org: Mapped[Optional[str]] = mapped_column(String, nullable=True)
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
    status: Mapped[str] = mapped_column(String, nullable=False)  # sent | failed | skipped | digest | retried
    error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tg_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    thread_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # The HTML we sent (or failed to send), kept so later lifecycle events can
    # edit the message and failed deliveries can be retried.
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DigestItem(Base):
    """An event waiting to be included in a chat's next digest message."""

    __tablename__ = "digest_items"
    __table_args__ = (Index("ix_digest_items_chat", "chat_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    route_id: Mapped[int] = mapped_column(Integer, nullable=False)
    project: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    environment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    issue_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    resource: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False, default="")
    level: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    web_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Quiet-hours hold: do not flush before this time (overrides the route period).
    not_before: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    thread_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class Installation(Base):
    """A Sentry integration installation (one per organisation that installed us)."""

    __tablename__ = "installations"

    uuid: Mapped[str] = mapped_column(String, primary_key=True)
    org_slug: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    app_slug: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    secret_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatSettings(Base):
    """Per-chat preferences."""

    __tablename__ = "chat_settings"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timezone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    quiet_start: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # "HH:MM" local
    quiet_end: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    format: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # html | plain
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEntry(Base):
    """Who changed what in a chat's configuration (routes, filters, settings)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_chat_ts", "chat_id", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
