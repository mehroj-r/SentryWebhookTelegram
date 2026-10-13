from __future__ import annotations

import fnmatch
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import (
    AuditEntry,
    ChatSettings,
    Delivery,
    DigestItem,
    Environment,
    Installation,
    Project,
    Route,
    SeenRequest,
    SentryIdentity,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _insert(session: AsyncSession, model):  # noqa: ANN001, ANN202
    """INSERT that supports ON CONFLICT for the session's dialect (SQLite or PostgreSQL)."""
    if session.bind.dialect.name == "postgresql":
        return pg_insert(model)
    return sqlite_insert(model)


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
                _insert(session, SeenRequest)
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
        org: Optional[str] = None,
    ) -> None:
        """Insert or update a project, preserving existing non-null ref_id/name/org."""
        async with self._sessionmaker() as session:
            stmt = _insert(session, Project).values(
                slug=slug,
                ref_id=ref_id,
                name=name,
                org=org,
                last_seen=_utcnow(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["slug"],
                set_=dict(
                    ref_id=func.coalesce(stmt.excluded.ref_id, Project.ref_id),
                    name=func.coalesce(stmt.excluded.name, Project.name),
                    org=func.coalesce(stmt.excluded.org, Project.org),
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
                    select(Project.slug, Project.ref_id, Project.name, Project.org).order_by(Project.slug)
                )
            ).all()
            return [{"slug": r.slug, "ref_id": r.ref_id, "name": r.name, "org": r.org} for r in rows]


# ── Installation ───────────────────────────────────────────────────────────────


class InstallationRepository(BaseRepository):
    """Sentry integration installations → organisation slugs."""

    async def upsert(
        self,
        uuid: str,
        *,
        org_slug: Optional[str] = None,
        app_slug: Optional[str] = None,
        status: Optional[str] = None,
        secret_label: Optional[str] = None,
    ) -> None:
        now = _utcnow()
        async with self._sessionmaker() as session:
            stmt = _insert(session, Installation).values(
                uuid=uuid, org_slug=org_slug, app_slug=app_slug, status=status,
                secret_label=secret_label, first_seen=now, last_seen=now,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["uuid"],
                set_=dict(
                    org_slug=func.coalesce(stmt.excluded.org_slug, Installation.org_slug),
                    app_slug=func.coalesce(stmt.excluded.app_slug, Installation.app_slug),
                    status=func.coalesce(stmt.excluded.status, Installation.status),
                    secret_label=func.coalesce(stmt.excluded.secret_label, Installation.secret_label),
                    last_seen=stmt.excluded.last_seen,
                ),
            )
            await session.execute(stmt)
            await session.commit()

    async def org_for(self, uuid: str) -> Optional[str]:
        async with self._sessionmaker() as session:
            return await session.scalar(select(Installation.org_slug).where(Installation.uuid == uuid))

    async def list_all(self) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (await session.execute(select(Installation).order_by(Installation.first_seen))).scalars().all()
            return [
                {"uuid": r.uuid, "org_slug": r.org_slug, "app_slug": r.app_slug, "status": r.status,
                 "secret_label": r.secret_label, "first_seen": r.first_seen, "last_seen": r.last_seen}
                for r in rows
            ]


# ── Environment ────────────────────────────────────────────────────────────────


class EnvironmentRepository(BaseRepository):
    """Environments seen per project — feeds the routing UI environment picker."""

    async def register(self, project: str, environment: str) -> None:
        async with self._sessionmaker() as session:
            stmt = (
                _insert(session, Environment)
                .values(project=project, environment=environment)
                .on_conflict_do_nothing(index_elements=["project", "environment"])
            )
            await session.execute(stmt)
            await session.commit()

    async def list_all(self) -> dict[str, list[str]]:
        """project → sorted environments."""
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Environment.project, Environment.environment).order_by(
                        Environment.project, Environment.environment
                    )
                )
            ).all()
        out: dict[str, list[str]] = {}
        for project, env in rows:
            out.setdefault(project, []).append(env)
        return out

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
        thread_id: Optional[int] = None,
    ) -> bool:
        """
        Insert a route. Returns True if newly added, False if already exists
        (in which case an existing route's thread_id is updated if given).

        When environment is NULL, SQLite's UNIQUE constraint doesn't catch
        duplicates (NULL != NULL in UNIQUE), so we pre-check explicitly.
        """
        async with self._sessionmaker() as session:
            existing = await session.scalar(
                select(Route).where(
                    Route.project == project,
                    Route.environment.is_(None) if environment is None else Route.environment == environment,
                    Route.chat_id == chat_id,
                )
            )
            if existing is not None:
                if thread_id is not None and existing.thread_id != thread_id:
                    existing.thread_id = thread_id
                    await session.commit()
                return False

            try:
                session.add(
                    Route(
                        project=project,
                        environment=environment,
                        chat_id=chat_id,
                        created_by=created_by,
                        created_at=_utcnow(),
                        thread_id=thread_id,
                    )
                )
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    async def import_routes(
        self, chat_id: int, routes: list[dict], created_by: Optional[int] = None
    ) -> tuple[int, int]:
        """
        Merge `routes` (validated dicts from `route_io.parse_import`) into the
        chat's routes in one transaction: new (project, environment) pairs are
        added, existing ones get their filter / digest / topic settings
        overwritten. Routes not in the import are left alone.
        Returns (added, updated).
        """
        added = updated = 0
        async with self._sessionmaker() as session:
            for r in routes:
                env = r["environment"]
                existing = await session.scalar(
                    select(Route).where(
                        Route.project == r["project"],
                        Route.environment.is_(None) if env is None else Route.environment == env,
                        Route.chat_id == chat_id,
                    )
                )
                if existing is None:
                    existing = Route(
                        project=r["project"],
                        environment=env,
                        chat_id=chat_id,
                        created_by=created_by,
                        created_at=_utcnow(),
                    )
                    session.add(existing)
                    added += 1
                else:
                    updated += 1
                existing.min_level = r["min_level"]
                existing.actions = r["actions"]
                existing.digest_minutes = r["digest_minutes"]
                existing.thread_id = r["thread_id"]
            await session.commit()
        return added, updated

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

    async def list_all(self) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(select(Route).order_by(Route.chat_id, Route.project, Route.environment))
            ).scalars().all()
            return [_route_dict(r) for r in rows]

    async def list_for_chat(self, chat_id: int) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Route)
                    .where(Route.chat_id == chat_id)
                    .order_by(Route.project, Route.environment)
                )
            ).scalars().all()
            return [_route_dict(r) for r in rows]

    async def set_filters(
        self,
        chat_id: int,
        project: Optional[str],
        *,
        min_level: Optional[str] = ...,  # type: ignore[assignment]
        actions: Optional[str] = ...,  # type: ignore[assignment]
        muted_until: Optional[datetime] = ...,  # type: ignore[assignment]
        digest_minutes: Optional[int] = ...,  # type: ignore[assignment]
    ) -> int:
        """
        Update filter columns on every route of `chat_id` (optionally only
        those for `project`). Arguments left as Ellipsis are not touched.
        Returns the number of routes updated.
        """
        values: dict = {}
        if min_level is not ...:
            values["min_level"] = min_level
        if actions is not ...:
            values["actions"] = actions
        if muted_until is not ...:
            values["muted_until"] = muted_until
        if digest_minutes is not ...:
            values["digest_minutes"] = digest_minutes
        if not values:
            return 0
        stmt = update(Route).where(Route.chat_id == chat_id).values(**values)
        if project:
            stmt = stmt.where(Route.project == project)
        async with self._sessionmaker() as session:
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def resolve_routes(self, project: str, environment: Optional[str]) -> list[dict]:
        """
        Return matching routes (with their filter columns) for (project, environment).

        Project matching: exact routes first; if none, wildcard routes whose
        pattern (fnmatch: `backend-*`, `*-prod`, `*`) matches the project.

        Environment matching within the chosen set:
        - environment given: exact (project, environment) matches win; if there
          are none, fall back to the (project, NULL) "any environment" routes.
        - environment unknown (e.g. `issue` webhooks never carry one): deliver
          to every route for the project. Silently dropping the event because
          Sentry didn't tell us the environment would hide real alerts from
          chats that subscribed to a specific environment.
        """
        async with self._sessionmaker() as session:
            exact = (await session.execute(select(Route).where(Route.project == project))).scalars().all()
            candidates = [_route_dict(r) for r in exact]
            if not candidates:
                patterns = (
                    await session.execute(select(Route).where(Route.project.like("%*%")))
                ).scalars().all()
                candidates = [
                    _route_dict(r) for r in patterns if fnmatch.fnmatchcase(project, r.project)
                ]
        if not candidates:
            return []
        if environment:
            exact_env = [r for r in candidates if r["environment"] == environment]
            if exact_env:
                return exact_env
            return [r for r in candidates if r["environment"] is None]
        return candidates

    async def resolve_chats(self, project: str, environment: Optional[str]) -> list[int]:
        """Distinct chat ids of `resolve_routes` (filters ignored)."""
        seen: list[int] = []
        for r in await self.resolve_routes(project, environment):
            if r["chat_id"] not in seen:
                seen.append(r["chat_id"])
        return seen


def _route_dict(r: Route) -> dict:
    return {
        "id": r.id,
        "project": r.project,
        "environment": r.environment,
        "chat_id": r.chat_id,
        "created_by": r.created_by,
        "created_at": r.created_at,
        "min_level": r.min_level,
        "actions": r.actions,
        "muted_until": r.muted_until,
        "digest_minutes": r.digest_minutes,
        "thread_id": r.thread_id,
    }


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
        thread_id: Optional[int] = None,
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
                thread_id=thread_id,
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

    async def retryable(self, chat_id: Optional[int] = None, limit: int = 10) -> list[dict]:
        """Most recent failed deliveries that kept their text (all chats when chat_id is None), oldest first."""
        stmt = (
            select(Delivery)
            .where(Delivery.status == "failed", Delivery.text.is_not(None))
            .order_by(Delivery.created_at.desc(), Delivery.id.desc())
            .limit(limit)
        )
        if chat_id is not None:
            stmt = stmt.where(Delivery.chat_id == chat_id)
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [_delivery_dict(r) for r in reversed(rows)]

    async def count_retryable(self) -> int:
        async with self._sessionmaker() as session:
            return (
                await session.scalar(
                    select(func.count()).select_from(Delivery).where(
                        Delivery.status == "failed", Delivery.text.is_not(None)
                    )
                )
            ) or 0

    async def set_status(self, delivery_id: int, status: str) -> None:
        async with self._sessionmaker() as session:
            await session.execute(update(Delivery).where(Delivery.id == delivery_id).values(status=status))
            await session.commit()

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

    async def counts_by_project(self, chat_id: int, since: datetime) -> dict[str, dict[str, int]]:
        """project → {status: count} for one chat's deliveries since `since` (digest sends excluded)."""
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(Delivery.project, Delivery.status, func.count())
                    .where(
                        Delivery.chat_id == chat_id,
                        Delivery.created_at >= since,
                        Delivery.resource != "digest",
                    )
                    .group_by(Delivery.project, Delivery.status)
                )
            ).all()
        out: dict[str, dict[str, int]] = {}
        for project, status, count in rows:
            out.setdefault(project or "?", {})[status] = count
        return out

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
        "thread_id": r.thread_id,
    }


# ── Digest items ───────────────────────────────────────────────────────────────


class DigestRepository(BaseRepository):
    """Events parked for a chat's next digest."""

    async def add(
        self,
        *,
        chat_id: int,
        route_id: int,
        project: Optional[str],
        environment: Optional[str],
        issue_id: Optional[str],
        resource: str,
        action: str,
        level: Optional[str],
        title: str,
        web_url: Optional[str],
        not_before: Optional[datetime] = None,
        thread_id: Optional[int] = None,
    ) -> None:
        async with self._sessionmaker() as session:
            session.add(
                DigestItem(
                    created_at=_utcnow(),
                    chat_id=chat_id,
                    route_id=route_id,
                    project=project,
                    environment=environment,
                    issue_id=issue_id,
                    resource=resource,
                    action=action or "",
                    level=level,
                    title=title[:300],
                    web_url=web_url,
                    not_before=not_before,
                    thread_id=thread_id,
                )
            )
            await session.commit()

    async def due_chats(self, now: Optional[datetime] = None) -> list[int]:
        """
        Chats that have at least one parked item older than its route's
        digest period. The whole backlog for such a chat is then flushed.
        """
        now = now or _utcnow()
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(DigestItem.chat_id, DigestItem.created_at, DigestItem.not_before, Route.digest_minutes)
                    .join(Route, Route.id == DigestItem.route_id, isouter=True)
                )
            ).all()
        due: list[int] = []
        for chat_id, created_at, not_before, minutes in rows:
            if chat_id in due:
                continue
            if not_before is not None:
                if not_before.tzinfo is None:
                    not_before = not_before.replace(tzinfo=timezone.utc)
                if not_before <= now:
                    due.append(chat_id)
                continue
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at + timedelta(minutes=minutes or 0) <= now:
                due.append(chat_id)
        return due

    async def pop_for_chat(self, chat_id: int, now: Optional[datetime] = None) -> list[dict]:
        """Return and delete every parked item for a chat that may be sent now."""
        now = now or _utcnow()
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(DigestItem).where(DigestItem.chat_id == chat_id).order_by(DigestItem.created_at)
                )
            ).scalars().all()
            ready = []
            for r in rows:
                nb = r.not_before
                if nb is not None and nb.tzinfo is None:
                    nb = nb.replace(tzinfo=timezone.utc)
                if nb is None or nb <= now:
                    ready.append(r)
            rows = ready
            items = [
                {
                    "id": r.id,
                    "thread_id": r.thread_id,
                    "created_at": r.created_at,
                    "project": r.project,
                    "environment": r.environment,
                    "issue_id": r.issue_id,
                    "resource": r.resource,
                    "action": r.action,
                    "level": r.level,
                    "title": r.title,
                    "web_url": r.web_url,
                }
                for r in rows
            ]
            if rows:
                await session.execute(delete(DigestItem).where(DigestItem.id.in_([r.id for r in rows])))
                await session.commit()
            return items

    async def pending_count(self, chat_id: int) -> int:
        async with self._sessionmaker() as session:
            return (
                await session.scalar(
                    select(func.count()).select_from(DigestItem).where(DigestItem.chat_id == chat_id)
                )
            ) or 0


# ── Chat settings ──────────────────────────────────────────────────────────────


class ChatSettingsRepository(BaseRepository):
    async def get(self, chat_id: int) -> Optional[dict]:
        async with self._sessionmaker() as session:
            row = await session.get(ChatSettings, chat_id)
            return _chat_settings_dict(row) if row else None

    async def update(self, chat_id: int, **fields) -> dict:
        """Upsert the given fields (None clears a field)."""
        allowed = {"timezone", "quiet_start", "quiet_end", "language", "format"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown chat settings: {unknown}")
        async with self._sessionmaker() as session:
            row = await session.get(ChatSettings, chat_id)
            if row is None:
                row = ChatSettings(chat_id=chat_id, updated_at=_utcnow())
                session.add(row)
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = _utcnow()
            await session.commit()
            return _chat_settings_dict(row)


def _chat_settings_dict(r: ChatSettings) -> dict:
    return {
        "chat_id": r.chat_id,
        "timezone": r.timezone,
        "quiet_start": r.quiet_start,
        "quiet_end": r.quiet_end,
        "language": r.language,
        "format": r.format,
        "updated_at": r.updated_at,
    }


# ── Audit log ──────────────────────────────────────────────────────────────────


class AuditRepository(BaseRepository):
    async def record(
        self, chat_id: int, user_id: Optional[int], action: str, details: Optional[str] = None
    ) -> None:
        async with self._sessionmaker() as session:
            session.add(AuditEntry(ts=_utcnow(), chat_id=chat_id, user_id=user_id, action=action, details=details))
            await session.commit()

    async def purge_older_than(self, max_age: timedelta) -> int:
        cutoff = _utcnow() - max_age
        async with self._sessionmaker() as session:
            result = await session.execute(delete(AuditEntry).where(AuditEntry.ts < cutoff))
            await session.commit()
            return result.rowcount or 0

    async def recent_for_chat(self, chat_id: int, limit: int = 10) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(AuditEntry)
                    .where(AuditEntry.chat_id == chat_id)
                    .order_by(AuditEntry.ts.desc(), AuditEntry.id.desc())
                    .limit(limit)
                )
            ).scalars().all()
            return [
                {"ts": r.ts, "user_id": r.user_id, "action": r.action, "details": r.details}
                for r in rows
            ]


# ── Sentry identities ──────────────────────────────────────────────────────────


class SentryIdentityRepository(BaseRepository):
    async def get(self, telegram_user_id: int) -> Optional[str]:
        async with self._sessionmaker() as session:
            row = await session.get(SentryIdentity, telegram_user_id)
            return row.sentry_user if row else None

    async def set(self, telegram_user_id: int, sentry_user: Optional[str]) -> None:
        """Link (or with None, unlink) a Telegram user to a Sentry user."""
        async with self._sessionmaker() as session:
            row = await session.get(SentryIdentity, telegram_user_id)
            if sentry_user is None:
                if row is not None:
                    await session.delete(row)
            elif row is None:
                session.add(SentryIdentity(telegram_user_id=telegram_user_id, sentry_user=sentry_user, updated_at=_utcnow()))
            else:
                row.sentry_user, row.updated_at = sentry_user, _utcnow()
            await session.commit()


# ── Container ──────────────────────────────────────────────────────────────────


class Repositories:
    """Aggregates all repositories; constructed from the core Database's sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.seen = SeenRequestRepository(sessionmaker)
        self.projects = ProjectRepository(sessionmaker)
        self.installations = InstallationRepository(sessionmaker)
        self.environments = EnvironmentRepository(sessionmaker)
        self.routes = RouteRepository(sessionmaker)
        self.deliveries = DeliveryRepository(sessionmaker)
        self.digests = DigestRepository(sessionmaker)
        self.chat_settings = ChatSettingsRepository(sessionmaker)
        self.audit = AuditRepository(sessionmaker)
        self.identities = SentryIdentityRepository(sessionmaker)
