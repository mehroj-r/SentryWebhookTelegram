from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, UniqueConstraint
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
