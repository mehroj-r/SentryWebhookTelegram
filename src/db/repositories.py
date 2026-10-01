from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import Delivery, Environment, Project, Route, SeenRequest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseRepository:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker


# ── SeenRequest ────────────────────────────────────────────────────────────────


class SeenRequestRepository(BaseRepository):
    """Idempotency/dedup for Sentry Request-IDs."""

    async def exists(self, request_id: str) -> bool:
        async with self._sessionmaker() as session:
            result = await session.scalar(
                select(SeenRequest.request_id).where(SeenRequest.request_id == request_id)
            )
            return result is not None

    async def add_if_new(self, request_id: str) -> bool:
        """
        Atomically record a Request-ID.

        Returns True if this is the first time we see it, False if it was
        already recorded. A single INSERT ... ON CONFLICT DO NOTHING avoids the
        check-then-insert race between concurrent deliveries of the same hook.
        """
        async with self._sessionmaker() as session:
            stmt = (
                sqlite_insert(SeenRequest)
                .values(request_id=request_id, ts=_utcnow())
                .on_conflict_do_nothing(index_elements=["request_id"])
            )
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def add(self, request_id: str) -> None:
        await self.add_if_new(request_id)

    async def purge_older_than(self, max_age: timedelta) -> int:
        """Delete dedup records older than `max_age`. Returns rows removed."""
        cutoff = _utcnow() - max_age
        async with self._sessionmaker() as session:
            result = await session.execute(delete(SeenRequest).where(SeenRequest.ts < cutoff))
            await session.commit()
            return result.rowcount or 0


# ── Project ────────────────────────────────────────────────────────────────────


class ProjectRepository(BaseRepository):
    """Projects learned from inbound Sentry payloads — feeds the routing UI."""

    async def upsert(
        self,
        slug: str,
        ref_id: Optional[int] = None,
        name: Optional[str] = None,
    ) -> None:
        """Insert or update a project, preserving existing non-null ref_id/name."""
        async with self._sessionmaker() as session:
            stmt = sqlite_insert(Project).values(
                slug=slug,
                ref_id=ref_id,
                name=name,
                last_seen=_utcnow(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["slug"],
                set_=dict(
                    ref_id=func.coalesce(stmt.excluded.ref_id, Project.ref_id),
                    name=func.coalesce(stmt.excluded.name, Project.name),
                    last_seen=stmt.excluded.last_seen,
                ),
            )
            await session.execute(stmt)
            await session.commit()

    async def slug_for_ref_id(self, ref_id: int) -> Optional[str]:
        """Resolve a numeric project id to its slug (learned from previous payloads)."""
        async with self._sessionmaker() as session:
            return await session.scalar(
                select(Project.slug).where(Project.ref_id == ref_id)
            )

    async def list_all(self) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Project.slug, Project.ref_id, Project.name).order_by(Project.slug)
                )
            ).all()
            return [{"slug": r.slug, "ref_id": r.ref_id, "name": r.name} for r in rows]


# ── Environment ────────────────────────────────────────────────────────────────


class EnvironmentRepository(BaseRepository):
    """Environments seen per project — feeds the routing UI environment picker."""

    async def register(self, project: str, environment: str) -> None:
        async with self._sessionmaker() as session:
            stmt = (
                sqlite_insert(Environment)
                .values(project=project, environment=environment)
                .on_conflict_do_nothing(index_elements=["project", "environment"])
            )
            await session.execute(stmt)
            await session.commit()

    async def list_for_project(self, project: str) -> list[str]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Environment.environment)
                    .where(Environment.project == project)
                    .order_by(Environment.environment)
                )
            ).scalars().all()
            return list(rows)


# ── Route ──────────────────────────────────────────────────────────────────────


class RouteRepository(BaseRepository):
    """Routing rules: (project, environment) → chat_id."""

    async def add(
        self,
        project: str,
        environment: Optional[str],
        chat_id: int,
        created_by: Optional[int] = None,
    ) -> bool:
        """
        Insert a route. Returns True if newly added, False if already exists.

        When environment is NULL, SQLite's UNIQUE constraint doesn't catch
        duplicates (NULL != NULL in UNIQUE), so we pre-check explicitly.
        """
        async with self._sessionmaker() as session:
            if environment is None:
                existing = await session.scalar(
                    select(Route.id).where(
                        Route.project == project,
                        Route.environment.is_(None),
                        Route.chat_id == chat_id,
                    )
                )
                if existing is not None:
                    return False

            try:
                session.add(
                    Route(
                        project=project,
                        environment=environment,
                        chat_id=chat_id,
                        created_by=created_by,
                        created_at=_utcnow(),
                    )
                )
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    async def remove(self, route_id: int, chat_id: int) -> bool:
        """
        Delete a route, but only if it belongs to `chat_id`.

        Callback data can be forged by any Telegram client, so the chat scope
        is what prevents one chat from deleting another chat's routes.
        Returns True if a row was deleted.
        """
        async with self._sessionmaker() as session:
            result = await session.execute(
                delete(Route).where(Route.id == route_id, Route.chat_id == chat_id)
            )
            await session.commit()
            return bool(result.rowcount)

    async def list_for_chat(self, chat_id: int) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Route.id, Route.project, Route.environment)
                    .where(Route.chat_id == chat_id)
                    .order_by(Route.project, Route.environment)
                )
            ).all()
            return [
                {"id": r.id, "project": r.project, "environment": r.environment}
                for r in rows
            ]

    async def resolve_chats(self, project: str, environment: Optional[str]) -> list[int]:
        """
        Return chat IDs for (project, environment).

        - environment given: exact (project, environment) matches win; if there
          are none, fall back to the (project, NULL) "any environment" routes.
        - environment unknown (e.g. `issue` webhooks never carry one): deliver
          to every route for the project. Silently dropping the event because
          Sentry didn't tell us the environment would hide real alerts from
          chats that subscribed to a specific environment.
        """
        async with self._sessionmaker() as session:
            if environment:
                rows = (
                    await session.execute(
                        select(Route.chat_id)
                        .where(Route.project == project, Route.environment == environment)
                        .distinct()
                    )
                ).scalars().all()
                if rows:
                    return list(rows)
                where = (Route.project == project, Route.environment.is_(None))
            else:
                where = (Route.project == project,)

            rows = (
                await session.execute(select(Route.chat_id).where(*where).distinct())
            ).scalars().all()
            return list(rows)


# ── Delivery log ───────────────────────────────────────────────────────────────


class DeliveryRepository(BaseRepository):
    """Audit trail of what was sent where."""

    async def record(
        self,
        *,
        chat_id: int,
        resource: str,
        action: str,
        project: Optional[str],
        environment: Optional[str],
        issue_id: Optional[str],
        title: str,
        status: str,
        error: Optional[str] = None,
        tg_message_id: Optional[int] = None,
        text: Optional[str] = None,
    ) -> int:
        async with self._sessionmaker() as session:
            row = Delivery(
                created_at=_utcnow(),
                chat_id=chat_id,
                resource=resource,
                action=action or "",
                project=project,
                environment=environment,
                issue_id=issue_id,
                title=title[:500],
                status=status,
                error=(error or None) and str(error)[:1000],
                tg_message_id=tg_message_id,
                text=text,
            )
            session.add(row)
            await session.commit()
            return row.id

    async def recent_for_chat(self, chat_id: int, limit: int = 10) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Delivery)
                    .where(Delivery.chat_id == chat_id)
                    .order_by(Delivery.created_at.desc(), Delivery.id.desc())
                    .limit(limit)
                )
            ).scalars().all()
            return [_delivery_dict(r) for r in rows]

    async def recent(self, limit: int = 50, status: Optional[str] = None) -> list[dict]:
        async with self._sessionmaker() as session:
            stmt = select(Delivery).order_by(Delivery.created_at.desc(), Delivery.id.desc()).limit(limit)
            if status:
                stmt = stmt.where(Delivery.status == status)
            rows = (await session.execute(stmt)).scalars().all()
            return [_delivery_dict(r) for r in rows]

    async def last_message_for_issue(self, chat_id: int, issue_id: str) -> Optional[int]:
        """Telegram message id of the most recent successful post about an issue."""
        row = await self.last_for_issue(chat_id, issue_id)
        return row["tg_message_id"] if row else None

    async def last_for_issue(self, chat_id: int, issue_id: str) -> Optional[dict]:
        """Most recent successfully sent delivery about an issue in a chat."""
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(Delivery)
                .where(
                    Delivery.chat_id == chat_id,
                    Delivery.issue_id == issue_id,
                    Delivery.status == "sent",
                    Delivery.tg_message_id.is_not(None),
                )
                .order_by(Delivery.created_at.desc(), Delivery.id.desc())
                .limit(1)
            )
            return _delivery_dict(row) if row else None

    async def update_text(self, delivery_id: int, text: str) -> None:
        async with self._sessionmaker() as session:
            await session.execute(
                update(Delivery).where(Delivery.id == delivery_id).values(text=text)
            )
            await session.commit()

    async def count_by_status(self, since: datetime) -> dict[str, int]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Delivery.status, func.count())
                    .where(Delivery.created_at >= since)
                    .group_by(Delivery.status)
                )
            ).all()
            return {status: count for status, count in rows}

    async def purge_older_than(self, max_age: timedelta) -> int:
        cutoff = _utcnow() - max_age
        async with self._sessionmaker() as session:
            result = await session.execute(delete(Delivery).where(Delivery.created_at < cutoff))
            await session.commit()
            return result.rowcount or 0


def _delivery_dict(r: Delivery) -> dict:
    return {
        "id": r.id,
        "created_at": r.created_at,
        "chat_id": r.chat_id,
        "resource": r.resource,
        "action": r.action,
        "project": r.project,
        "environment": r.environment,
        "issue_id": r.issue_id,
        "title": r.title,
        "status": r.status,
        "error": r.error,
        "tg_message_id": r.tg_message_id,
        "text": r.text,
    }


# ── Container ──────────────────────────────────────────────────────────────────


class Repositories:
    """Aggregates all repositories; constructed from the core Database's sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.seen = SeenRequestRepository(sessionmaker)
        self.projects = ProjectRepository(sessionmaker)
        self.environments = EnvironmentRepository(sessionmaker)
        self.routes = RouteRepository(sessionmaker)
        self.deliveries = DeliveryRepository(sessionmaker)
