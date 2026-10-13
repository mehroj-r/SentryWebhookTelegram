"""
Minimal Sentry Web API client for the issue action buttons.

Only one endpoint is needed:
    PUT /api/0/organizations/{org}/issues/{issue_id}/
with {"status": "resolved" | "ignored"} or {"assignedTo": "<username|email>"}.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=15)


def pick_org(tokens: dict[str, str], event_org: Optional[str]) -> Optional[str]:
    """The configured org an event belongs to: an exact match, else the only one configured."""
    if event_org and event_org in tokens:
        return event_org
    if len(tokens) == 1:
        return next(iter(tokens))
    return None


class SentryAPI:
    def __init__(self, base_url: str, tokens: dict[str, str]) -> None:
        self._base = base_url.rstrip("/")
        self._tokens = dict(tokens)
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def orgs(self) -> list[str]:
        return sorted(self._tokens)

    async def update_issue(self, org: str, issue_id: str, data: dict[str, Any]) -> tuple[bool, str]:
        """Returns (ok, error message for the user)."""
        token = self._tokens.get(org)
        if not token:
            return False, "no API token for this organisation"
        if not issue_id.isdigit():
            return False, "invalid issue id"
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT)
        url = f"{self._base}/api/0/organizations/{quote(org, safe='')}/issues/{issue_id}/"
        try:
            async with self._session.put(
                url, json=data, headers={"Authorization": f"Bearer {token}"}
            ) as resp:
                if resp.status < 300:
                    return True, ""
                body = (await resp.text())[:300]
                log.warning("Sentry API %s %s → %s %s", "PUT", url, resp.status, body)
                detail = ""
                try:
                    payload = await resp.json(content_type=None)
                    if isinstance(payload, dict):
                        detail = str(payload.get("detail") or next(iter(payload.values()), ""))
                except Exception:  # noqa: BLE001
                    pass
                return False, f"HTTP {resp.status}" + (f": {detail[:150]}" if detail else "")
        except (aiohttp.ClientError, TimeoutError) as exc:
            log.warning("Sentry API request failed: %s", exc)
            return False, f"network error: {type(exc).__name__}"

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
