from pathlib import Path

from app.db.base import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    needs_review INTEGER NOT NULL,
    marketplace_name TEXT NOT NULL DEFAULT 'ebay',
    inventory_item_key TEXT,
    offer_id TEXT,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);
CREATE INDEX IF NOT EXISTS idx_drafts_sku ON drafts(sku);
CREATE INDEX IF NOT EXISTS idx_drafts_offer_id ON drafts(offer_id);
"""


def initialize_database(database_path: Path) -> None:
    with get_connection(database_path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            """
            INSERT INTO app_meta(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            ("schema_version", "2"),
        )
        connection.commit()
