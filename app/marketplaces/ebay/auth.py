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


@dataclass(slots=True)
class EbayTokenData:
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str = "Bearer"


class EbayAuthStore:
    def __init__(self, database_path):
        self.database_path = database_path

    def get_tokens(self) -> EbayTokenData:
        try:
            with get_connection(self.database_path) as connection:
                rows = connection.execute(
                    "SELECT key, value FROM app_meta WHERE key IN (?, ?, ?, ?)",
                    TOKEN_KEYS,
                ).fetchall()
        except sqlite3.OperationalError:
            rows = []

        values = {row["key"]: row["value"] for row in rows}
        expires_in = values.get("ebay_token_expires_in")
        return EbayTokenData(
            access_token=values.get("ebay_access_token"),
            refresh_token=values.get("ebay_refresh_token"),
            expires_in=int(expires_in) if expires_in else None,
            token_type=normalize_token_type(values.get("ebay_token_type")),
        )

    def save_tokens(self, token_data: EbayTokenData) -> None:
        items = {
            "ebay_access_token": token_data.access_token or "",
            "ebay_refresh_token": token_data.refresh_token or "",
            "ebay_token_expires_in": "" if token_data.expires_in is None else str(token_data.expires_in),
            "ebay_token_type": normalize_token_type(token_data.token_type),
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
                row = connection.execute("SELECT value FROM app_meta WHERE key = ?", ("ebay_oauth_state",)).fetchone()
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
                ("ebay_oauth_state", state),
            )
            connection.commit()
        return state

    def clear_state(self) -> None:
        with get_connection(self.database_path) as connection:
            connection.execute("DELETE FROM app_meta WHERE key = ?", ("ebay_oauth_state",))
            connection.commit()

    def clear_tokens(self) -> None:
        try:
            with get_connection(self.database_path) as connection:
                connection.executemany("DELETE FROM app_meta WHERE key = ?", [(key,) for key in TOKEN_KEYS])
                connection.commit()
        except sqlite3.OperationalError:
            return


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
