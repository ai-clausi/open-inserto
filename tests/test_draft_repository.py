import json

from app.db.base import get_connection
from app.db.init_db import initialize_database
from app.drafts.identity import derive_sku
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.repository import DraftRepository
from app.drafts.workflow import transition_draft


def make_draft() -> Draft:
    return Draft(
        id="draft_20260411_ab12cd34",
        sku=derive_sku("draft_20260411_ab12cd34"),
        source={
            "images": [
                {
                    "id": "img_01",
                    "originalFilename": "IMG_1234.jpg",
                    "storagePath": "/storage/drafts/draft_20260411_ab12cd34/images/01-original.jpg",
                    "mimeType": "image/jpeg",
                    "order": 1,
                    "kind": "original",
                }
            ]
        },
    )


def test_repository_persists_and_loads_draft(tmp_path):
    db_path = tmp_path / "open_inserto.db"
    initialize_database(db_path)
    repository = DraftRepository(db_path)
    draft = make_draft()

    repository.create_draft(draft)
    loaded = repository.get_draft(draft.id)

    assert loaded is not None
    assert loaded.id == draft.id
    assert loaded.sku == draft.sku
    assert loaded.source.images[0].storage_path.endswith("01-original.jpg")


def test_repository_filters_by_status_and_updates_marketplace_refs(tmp_path):
    db_path = tmp_path / "open_inserto.db"
    initialize_database(db_path)
    repository = DraftRepository(db_path)
    draft = make_draft()

    transition_draft(draft, WorkflowStatus.OFFER_CREATED)
    repository.save_draft(draft)
    updated = repository.update_marketplace_refs(
        draft.id,
        inventory_item_key="inv-123",
        offer_id="offer-456",
    )

    offer_created = repository.list_drafts(WorkflowStatus.OFFER_CREATED)

    assert len(offer_created) == 1
    assert offer_created[0].id == draft.id
    assert updated.marketplace.ebay.inventory_item_key == "inv-123"
    assert updated.marketplace.ebay.offer_id == "offer-456"


def test_repository_treats_legacy_readiness_statuses_as_drafts(tmp_path):
    db_path = tmp_path / "open_inserto.db"
    initialize_database(db_path)
    repository = DraftRepository(db_path)
    draft = make_draft()
    payload = draft.model_dump(mode="json", by_alias=True)
    payload["workflow"]["status"] = "ready_for_marketplace"
    repository.create_draft(draft)

    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE drafts SET status = ?, data_json = ? WHERE id = ?",
            ("ready_for_marketplace", json.dumps(payload), draft.id),
        )
        connection.commit()

    loaded = repository.list_drafts(WorkflowStatus.DRAFT)

    assert len(loaded) == 1
    assert loaded[0].workflow.status is WorkflowStatus.DRAFT
