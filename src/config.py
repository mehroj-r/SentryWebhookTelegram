from __future__ import annotations

import re
from typing import Annotated, Any, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Telegram restricts the webhook secret token to 1-256 chars of [A-Za-z0-9_-].
_SECRET_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str
    tg_webhook_path: str = "/telegram/webhook"
    webhook_secret_token: str

    # Server
    webhook_base_url: str
    sentry_webhook_path: str = "/sentry/webhook"
    host: str = "0.0.0.0"
    port: int = 8080
    # Sentry error payloads with large stack traces can exceed aiohttp's 1 MiB default.
    max_body_bytes: int = 10 * 1024 * 1024
    # Back-pressure: when this many events are waiting for Telegram, new webhooks
    # get a 503 so Sentry retries them later instead of growing memory unbounded.
    queue_max_size: int = 1000

    # Collapse repeated error/event_alert hooks for the same issue inside this
    # window (seconds) into one summary message. 0 disables.
    burst_window_seconds: int = 600

    # Sentry
    sentry_client_secret: str

    # App
    db_path: str = "data.db"
    default_chat_id: Optional[int] = None
    # NoDecode: accept both JSON ("[1,2]") and comma-separated ("1,2") forms.
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    # How long to remember Sentry Request-IDs for de-duplication.
    seen_request_ttl_days: int = 7

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return list(value)
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            cleaned = value.strip().strip("[]")
            if not cleaned:
                return []
            return [int(part.strip()) for part in cleaned.split(",") if part.strip()]
        raise ValueError("ADMIN_IDS must be a list of integers")

    @field_validator("webhook_secret_token")
    @classmethod
    def _check_secret_token(cls, value: str) -> str:
        if not _SECRET_TOKEN_RE.match(value):
            raise ValueError(
                "WEBHOOK_SECRET_TOKEN must be 1-256 characters of A-Z, a-z, 0-9, '_' or '-'"
            )
        return value

    @field_validator("webhook_base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("WEBHOOK_BASE_URL must start with https:// (Telegram requires TLS)")
        return value

    @field_validator("tg_webhook_path", "sentry_webhook_path")
    @classmethod
    def _check_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("webhook paths must start with '/'")
        return value


settings = Settings()
