from __future__ import annotations

import sqlite3
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

from app.core.config import Settings
from app.db.base import get_connection


SCOPES = (
    "https://api.ebay.com/oauth/api_scope/sell.inventory "
    "https://api.ebay.com/oauth/api_scope/sell.account"
)
TOKEN_KEYS = (
    "ebay_access_token",
    "ebay_refresh_token",
    "ebay_token_expires_in",
    "ebay_token_type",
)
TOKEN_KEY_NAMES = ("access_token", "refresh_token", "token_expires_in", "token_type")
STATE_KEY_NAME = "oauth_state"


@dataclass(slots=True)
class EbayTokenData:
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str = "Bearer"


class EbayAuthStore:
    def __init__(self, database_path, *, mode: str = "sandbox"):
        self.database_path = database_path
        self.mode = mode

    @property
    def token_keys(self) -> tuple[str, str, str, str]:
        return tuple(f"ebay_{self.mode}_{name}" for name in TOKEN_KEY_NAMES)

    @property
    def state_key(self) -> str:
        return f"ebay_{self.mode}_{STATE_KEY_NAME}"

    def get_tokens(self) -> EbayTokenData:
        token_keys = self.token_keys
        try:
            with get_connection(self.database_path) as connection:
                rows = connection.execute(
                    "SELECT key, value FROM app_meta WHERE key IN (?, ?, ?, ?)",
                    token_keys,
                ).fetchall()
        except sqlite3.OperationalError:
            rows = []

        values = {row["key"]: row["value"] for row in rows}
        if not values and self.mode == "sandbox":
            values = self._get_legacy_tokens()
        access_token_key, refresh_token_key, expires_in_key, token_type_key = token_keys
        expires_in = values.get(expires_in_key) or values.get("ebay_token_expires_in")
        return EbayTokenData(
            access_token=values.get(access_token_key) or values.get("ebay_access_token"),
            refresh_token=values.get(refresh_token_key) or values.get("ebay_refresh_token"),
            expires_in=int(expires_in) if expires_in else None,
            token_type=normalize_token_type(values.get(token_type_key) or values.get("ebay_token_type")),
        )

    def save_tokens(self, token_data: EbayTokenData) -> None:
        access_token_key, refresh_token_key, expires_in_key, token_type_key = self.token_keys
        items = {
            access_token_key: token_data.access_token or "",
            refresh_token_key: token_data.refresh_token or "",
            expires_in_key: "" if token_data.expires_in is None else str(token_data.expires_in),
            token_type_key: normalize_token_type(token_data.token_type),
        }
        with get_connection(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO app_meta(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                list(items.items()),
            )
            connection.commit()

    def get_pending_state(self) -> str | None:
        try:
            with get_connection(self.database_path) as connection:
                row = connection.execute("SELECT value FROM app_meta WHERE key = ?", (self.state_key,)).fetchone()
        except sqlite3.OperationalError:
            return None
        return row["value"] if row else None

    def issue_state(self) -> str:
        state = secrets.token_urlsafe(24)
        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO app_meta(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (self.state_key, state),
            )
            connection.commit()
        return state

    def clear_state(self) -> None:
        with get_connection(self.database_path) as connection:
            connection.execute("DELETE FROM app_meta WHERE key = ?", (self.state_key,))
            connection.commit()

    def clear_tokens(self) -> None:
        try:
            with get_connection(self.database_path) as connection:
                keys = list(self.token_keys)
                if self.mode == "sandbox":
                    keys.extend(TOKEN_KEYS)
                connection.executemany("DELETE FROM app_meta WHERE key = ?", [(key,) for key in keys])
                connection.commit()
        except sqlite3.OperationalError:
            return

    def _get_legacy_tokens(self) -> dict[str, str]:
        try:
            with get_connection(self.database_path) as connection:
                rows = connection.execute(
                    "SELECT key, value FROM app_meta WHERE key IN (?, ?, ?, ?)",
                    TOKEN_KEYS,
                ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {row["key"]: row["value"] for row in rows}


def has_usable_auth_tokens(token_data: EbayTokenData) -> bool:
    return bool(token_data.refresh_token)


def normalize_token_type(token_type: str | None) -> str:
    value = (token_type or "").strip()
    if not value:
        return "Bearer"
    if value.lower() == "bearer":
        return "Bearer"
    if value.lower() == "user access token":
        return "Bearer"
    return "Bearer"


def build_auth_connect_url(settings: Settings, state: str) -> str:
    query = urlencode(
        {
            "client_id": settings.ebay_client_id or "",
            "redirect_uri": settings.ebay_ru_name or "",
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "prompt": "login",
        }
    )
    return f"{settings.ebay_auth_base_url}/oauth2/authorize?{query}"
