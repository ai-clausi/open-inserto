from pathlib import Path

from app.core.config import Settings
from app.db.init_db import initialize_database
from app.drafts.identity import derive_sku
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.repository import DraftRepository
from app.marketplaces.ebay.mapping import build_inventory_item_payload, build_offer_payload
from app.marketplaces.ebay.service import EbayMarketplaceService


class FakeEbayClient:
    def __init__(self):
        self.inventory_payloads = []
        self.offer_payloads = []

    def get_access_token(self):
        return object()

    def upload_image(self, access_token, image_path: Path):
        return {"image": {"imageUrl": f"https://i.example.test/{image_path.name}"}}

    def create_or_replace_inventory_item(self, access_token, *, sku: str, payload: dict):
        self.inventory_payloads.append((sku, payload))
        return {"sku": sku}

    def create_offer(self, access_token, payload: dict):
        self.offer_payloads.append(payload)
        return {"offerId": "offer-123"}


def make_settings(tmp_path) -> Settings:
    return Settings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'open_inserto.db'}",
        ebay_payment_policy_id="pay-1",
        ebay_fulfillment_policy_id="ful-1",
        ebay_return_policy_id="ret-1",
        ebay_merchant_location_key="home",
    )


def make_draft(tmp_path) -> Draft:
    image_dir = tmp_path / "data" / "drafts" / "draft_20260411_ab12cd34" / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / "01-original.jpg"
    image_path.write_bytes(b"fake-image")

    draft = Draft(
        id="draft_20260411_ab12cd34",
        sku=derive_sku("draft_20260411_ab12cd34"),
        source={
            "images": [
                {
                    "id": "img_01",
                    "originalFilename": "IMG_1234.jpg",
                    "storagePath": "/data/drafts/draft_20260411_ab12cd34/images/01-original.jpg",
                    "mimeType": "image/jpeg",
                    "order": 1,
                    "kind": "original",
                }
            ]
        },
        listing={
            "title": "Nintendo Switch OLED",
            "descriptionHtml": "<p>Sehr guter Zustand.</p>",
            "condition": "gebraucht",
            "categorySuggestion": "139971",
            "brand": "Nintendo",
            "model": "OLED",
            "priceSuggestion": 199.99,
        },
    )
    draft.workflow.status = WorkflowStatus.READY_FOR_MARKETPLACE
    draft.workflow.needs_review = False
    return draft


def test_mapping_builds_inventory_and_offer_payloads(tmp_path):
    settings = make_settings(tmp_path)
    draft = make_draft(tmp_path)
    draft.marketplace.ebay.image_urls = ["https://i.example.test/01-original.jpg"]

    inventory_payload = build_inventory_item_payload(draft, settings)
    offer_payload = build_offer_payload(draft, settings)

    assert inventory_payload["product"]["title"] == "Nintendo Switch OLED"
    assert inventory_payload["product"]["imageUrls"] == ["https://i.example.test/01-original.jpg"]
    assert offer_payload["format"] == "AUCTION"
    assert offer_payload["pricingSummary"]["auctionStartPrice"]["value"] == "199.99"
    assert offer_payload["pricingSummary"]["auctionStartPrice"]["currency"] == "EUR"


def test_service_creates_offer_and_persists_marketplace_refs(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    repository.save_draft(draft)
    client = FakeEbayClient()

    service = EbayMarketplaceService(settings=settings, repository=repository, client=client)
    updated = service.create_unpublished_offer_for_draft(draft.id)

    assert updated.workflow.status is WorkflowStatus.OFFER_CREATED
    assert updated.marketplace.ebay.inventory_item_key == draft.sku
    assert updated.marketplace.ebay.offer_id == "offer-123"
    assert updated.marketplace.ebay.image_urls == ["https://i.example.test/01-original.jpg"]
    assert client.inventory_payloads[0][0] == draft.sku
    assert client.offer_payloads[0]["format"] == "AUCTION"


def test_mapping_falls_back_to_default_auction_start_price(tmp_path):
    settings = make_settings(tmp_path)
    draft = make_draft(tmp_path)
    draft.listing.price_suggestion = None

    offer_payload = build_offer_payload(draft, settings)

    assert offer_payload["pricingSummary"]["auctionStartPrice"]["value"] == "1.00"


def test_service_blocks_draft_when_required_fields_are_missing(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    draft.listing.category_suggestion = ""
    repository.save_draft(draft)

    service = EbayMarketplaceService(settings=settings, repository=repository, client=FakeEbayClient())
    updated = service.create_unpublished_offer_for_draft(draft.id)

    assert updated.workflow.status is WorkflowStatus.BLOCKED
    assert any("Kategorie fehlt" in item for item in updated.workflow.missing_information)
