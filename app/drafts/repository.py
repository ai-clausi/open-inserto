from __future__ import annotations

import json
from pathlib import Path

from app.db.base import get_connection
from app.drafts.models import Draft, WorkflowStatus, utc_now

LEGACY_DRAFT_STATUSES = ("classified", "needs_attention", "ready_for_review", "ready_for_marketplace", "blocked")


class DraftRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def create_draft(self, draft: Draft) -> None:
        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO drafts(
                    id, sku, status, needs_review, marketplace_name,
                    inventory_item_key, offer_id, data_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._row_values(draft),
            )
            connection.commit()

    def save_draft(self, draft: Draft) -> None:
        draft.workflow.last_updated_at = utc_now()
        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO drafts(
                    id, sku, status, needs_review, marketplace_name,
                    inventory_item_key, offer_id, data_json, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    sku = excluded.sku,
                    status = excluded.status,
                    needs_review = excluded.needs_review,
                    marketplace_name = excluded.marketplace_name,
                    inventory_item_key = excluded.inventory_item_key,
                    offer_id = excluded.offer_id,
                    data_json = excluded.data_json,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                """,
                self._row_values(draft),
            )
            connection.commit()

    def get_draft(self, draft_id: str) -> Draft | None:
        with get_connection(self.database_path) as connection:
            row = connection.execute(
                "SELECT data_json FROM drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()

        if row is None:
            return None

        return Draft.model_validate(json.loads(row["data_json"]))

    def list_drafts(self, status: WorkflowStatus | None = None) -> list[Draft]:
        query = "SELECT data_json FROM drafts"
        params: tuple[object, ...] = ()
        if status is not None:
            if status is WorkflowStatus.DRAFT:
                placeholders = ", ".join("?" for _ in LEGACY_DRAFT_STATUSES)
                query += f" WHERE status = ? OR status IN ({placeholders})"
                params = (status.value, *LEGACY_DRAFT_STATUSES)
            else:
                query += " WHERE status = ?"
                params = (status.value,)
        query += " ORDER BY created_at ASC"

        with get_connection(self.database_path) as connection:
            rows = connection.execute(query, params).fetchall()

        return [Draft.model_validate(json.loads(row["data_json"])) for row in rows]

    def update_marketplace_refs(
        self,
        draft_id: str,
        *,
        inventory_item_key: str | None = None,
        offer_id: str | None = None,
    ) -> Draft:
        draft = self.get_draft(draft_id)
        if draft is None:
            msg = f"Draft not found: {draft_id}"
            raise KeyError(msg)

        draft.marketplace.ebay.inventory_item_key = inventory_item_key
        draft.marketplace.ebay.offer_id = offer_id
        self.save_draft(draft)
        return draft

    @staticmethod
    def _row_values(draft: Draft) -> tuple[object, ...]:
        payload = draft.model_dump(mode="json", by_alias=True)
        return (
            draft.id,
            draft.sku,
            draft.workflow.status.value,
            int(draft.workflow.needs_review),
            "ebay",
            draft.marketplace.ebay.inventory_item_key,
            draft.marketplace.ebay.offer_id,
            json.dumps(payload, ensure_ascii=False),
            draft.workflow.created_at.isoformat(),
            draft.workflow.last_updated_at.isoformat(),
        )
