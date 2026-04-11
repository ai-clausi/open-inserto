from pathlib import Path

from app.db.base import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
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
            ("schema_version", "1"),
        )
        connection.commit()
