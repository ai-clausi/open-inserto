from pathlib import Path

import httpx

from app.core.config import Settings
from app.db.init_db import initialize_database
from app.drafts.identity import derive_sku
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.repository import DraftRepository
from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData
from app.marketplaces.ebay.client import EbayClient
from app.marketplaces.ebay.configuration import EbayAccountResources, EbayConfigStore
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

    def get_account_resources(self, access_token):
        return EbayAccountResources(
            payment_policies=[{"id": "pay-1", "name": "Payment"}],
            fulfillment_policies=[{"id": "ful-1", "name": "Fulfillment"}],
            return_policies=[{"id": "ret-1", "name": "Return"}],
            merchant_locations=[{"key": "home", "name": "Warehouse", "status": "ENABLED"}],
        )


def make_settings(tmp_path) -> Settings:
    return Settings(
        project_dir=tmp_path,
        data_dir=tmp_path / "data",
        database_url=f"sqlite:///{tmp_path / 'open_inserto.db'}",
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
    initialize_database(settings.database_path)
    draft = make_draft(tmp_path)
    draft.marketplace.ebay.image_urls = ["https://i.example.test/01-original.jpg"]
    config_store = EbayConfigStore(settings.database_path)
    config_store.save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )
    config = config_store.get_effective_configuration()

    inventory_payload = build_inventory_item_payload(draft, settings)
    offer_payload = build_offer_payload(draft, settings, config)

    assert inventory_payload["product"]["title"] == "Nintendo Switch OLED"
    assert inventory_payload["product"]["imageUrls"] == ["https://i.example.test/01-original.jpg"]
    assert offer_payload["format"] == "AUCTION"
    assert offer_payload["listingDuration"] == "DAYS_7"
    assert "availableQuantity" not in offer_payload
    assert offer_payload["pricingSummary"]["auctionStartPrice"]["value"] == "199.99"
    assert offer_payload["pricingSummary"]["auctionStartPrice"]["currency"] == "EUR"


def test_service_creates_offer_and_persists_marketplace_refs(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    repository.save_draft(draft)
    client = FakeEbayClient()
    config_store = EbayConfigStore(settings.database_path)
    config_store.save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )

    service = EbayMarketplaceService(settings=settings, repository=repository, client=client, config_store=config_store)
    updated = service.create_unpublished_offer_for_draft(draft.id)

    assert updated.workflow.status is WorkflowStatus.OFFER_CREATED
    assert updated.marketplace.ebay.inventory_item_key == draft.sku
    assert updated.marketplace.ebay.offer_id == "offer-123"
    assert updated.marketplace.ebay.image_urls == ["https://i.example.test/01-original.jpg"]
    assert client.inventory_payloads[0][0] == draft.sku
    assert client.offer_payloads[0]["format"] == "AUCTION"


def test_mapping_falls_back_to_default_auction_start_price(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    draft = make_draft(tmp_path)
    draft.listing.price_suggestion = None
    config_store = EbayConfigStore(settings.database_path)
    config_store.save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )
    config = config_store.get_effective_configuration()

    offer_payload = build_offer_payload(draft, settings, config)

    assert offer_payload["pricingSummary"]["auctionStartPrice"]["value"] == "1.00"


def test_service_blocks_draft_when_required_fields_are_missing(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    draft.listing.category_suggestion = ""
    repository.save_draft(draft)
    config_store = EbayConfigStore(settings.database_path)
    config_store.save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )

    service = EbayMarketplaceService(settings=settings, repository=repository, client=FakeEbayClient(), config_store=config_store)
    updated = service.create_unpublished_offer_for_draft(draft.id)

    assert updated.workflow.status is WorkflowStatus.BLOCKED
    assert any("Kategorie fehlt" in item for item in updated.workflow.missing_information)


def test_service_clears_tokens_and_keeps_draft_retryable_on_auth_error(tmp_path):
    settings = make_settings(tmp_path)
    settings.ebay_client_id = "client-123"
    settings.ebay_client_secret = "secret-123"
    settings.ebay_ru_name = "runame-123"
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    repository.save_draft(draft)

    auth_store = EbayAuthStore(settings.database_path)
    auth_store.save_tokens(EbayTokenData(refresh_token="refresh-stored"))
    config_store = EbayConfigStore(settings.database_path)
    config_store.save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            400,
            json={"error_description": "the provided authorization refresh token is invalid or was issued to another client"},
        )
    )
    client = EbayClient(settings, client=httpx.Client(transport=transport), auth_store=auth_store)
    service = EbayMarketplaceService(settings=settings, repository=repository, client=client, config_store=config_store)
    try:
        updated = service.create_unpublished_offer_for_draft(draft.id)
    finally:
        client.close()

    assert updated.workflow.status is WorkflowStatus.READY_FOR_MARKETPLACE
    assert updated.workflow.missing_information == []
    assert "refresh token is invalid" in updated.marketplace.ebay.offer_data["lastError"]
    stored_tokens = auth_store.get_tokens()
    assert stored_tokens.refresh_token is None
    assert stored_tokens.access_token is None


def test_upload_image_uses_ebay_media_endpoint(tmp_path):
    settings = make_settings(tmp_path)
    captured_path = None
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"fake-image")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_path
        captured_path = request.url.path
        return httpx.Response(201, json={"imageUrl": "https://i.example.test/sample.jpg"})

    client = EbayClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        response = client.upload_image(
            type("Token", (), {"token_type": "Bearer", "token": "token-123"})(),
            image_path,
        )
    finally:
        client.close()

    assert captured_path == "/commerce/media/v1_beta/image/create_image_from_file"
    assert response["imageUrl"] == "https://i.example.test/sample.jpg"


def test_account_resource_get_requests_only_send_authorization_header(tmp_path):
    settings = make_settings(tmp_path)
    captured_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        path = request.url.path
        if path.endswith("/sell/account/v1/program/get_opted_in_programs"):
            return httpx.Response(200, json={"programs": [{"programType": "SELLING_POLICY_MANAGEMENT"}]})
        if path.endswith("/sell/account/v1/payment_policy"):
            return httpx.Response(200, json={"paymentPolicies": []})
        if path.endswith("/sell/account/v1/fulfillment_policy"):
            return httpx.Response(200, json={"fulfillmentPolicies": []})
        if path.endswith("/sell/account/v1/return_policy"):
            return httpx.Response(200, json={"returnPolicies": []})
        if path.endswith("/sell/inventory/v1/location"):
            return httpx.Response(200, json={"locations": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = EbayClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        access_token = type("Token", (), {"token_type": "Bearer", "token": "token-123"})()
        client.get_opted_in_programs(access_token)
        client.get_account_resources(access_token)
    finally:
        client.close()

    for headers in captured_headers:
        assert "authorization" in headers
        assert "content-type" not in headers
        assert "content-language" not in headers


def test_stored_user_access_token_type_is_normalized_to_bearer(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    auth_store = EbayAuthStore(settings.database_path)
    auth_store.save_tokens(
        EbayTokenData(
            access_token="access-123",
            token_type="User Access Token",
        )
    )

    client = EbayClient(settings, auth_store=auth_store)
    try:
        access_token = client.get_access_token()
    finally:
        client.close()

    assert access_token.token_type == "Bearer"


def test_service_blocks_when_selected_location_is_missing_for_connected_account(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    repository.save_draft(draft)
    config_store = EbayConfigStore(settings.database_path)
    config_store.save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="missing-location",
    )

    service = EbayMarketplaceService(
        settings=settings,
        repository=repository,
        client=FakeEbayClient(),
        config_store=config_store,
    )
    updated = service.create_unpublished_offer_for_draft(draft.id)

    assert updated.workflow.status is WorkflowStatus.BLOCKED
    assert any("Merchant Location 'missing-location' existiert im verbundenen eBay-Account nicht" in item for item in updated.workflow.missing_information)
