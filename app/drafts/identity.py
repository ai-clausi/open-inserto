from __future__ import annotations

from datetime import UTC, datetime
from secrets import token_hex


def generate_draft_id(now: datetime | None = None) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return f"draft_{current:%Y%m%d}_{token_hex(4)}"


def derive_sku(draft_id: str) -> str:
    prefix = "draft_"
    if not draft_id.startswith(prefix):
        msg = f"Unsupported draft ID format: {draft_id}"
        raise ValueError(msg)

    remainder = draft_id.removeprefix(prefix)
    try:
        date_part, suffix = remainder.split("_", 1)
    except ValueError as exc:
        msg = f"Unsupported draft ID format: {draft_id}"
        raise ValueError(msg) from exc

    return f"oi-draft-{date_part}-{suffix}"
