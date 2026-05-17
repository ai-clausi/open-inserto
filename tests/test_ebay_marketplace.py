from pathlib import Path

import httpx

from app.core.config import Settings
from app.db.init_db import initialize_database
from app.drafts.identity import derive_sku
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.repository import DraftRepository
from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData
from app.marketplaces.ebay.client import EbayClient
from app.marketplaces.ebay.configuration import PAYMENT_POLICY_NAME, RETURN_POLICY_NAME, SHIPPING_PROFILES, EbayAccountResources, EbayConfigStore
from app.marketplaces.ebay.mapping import build_inventory_item_payload, build_offer_payload
from app.marketplaces.ebay.service import EbayMarketplaceService


class FakeEbayClient:
    def __init__(self):
        self.inventory_payloads = []
        self.offer_payloads = []
        self.updated_offer_payloads = []
        self.upload_calls = 0

    def get_access_token(self):
        return object()

    def upload_image(self, access_token, image_path: Path):
        self.upload_calls += 1
        return {"image": {"imageUrl": f"https://i.example.test/{image_path.name}"}}

    def create_or_replace_inventory_item(self, access_token, *, sku: str, payload: dict):
        self.inventory_payloads.append((sku, payload))
        return {"sku": sku}

    def create_offer(self, access_token, payload: dict):
        self.offer_payloads.append(payload)
        return {"offerId": "offer-123"}

    def update_offer(self, access_token, *, offer_id: str, payload: dict):
        self.updated_offer_payloads.append((offer_id, payload))
        return {"offerId": offer_id, "status": "updated"}

    def publish_offer(self, access_token, offer_id: str):
        return {"listingId": "listing-123"}

    def get_account_resources(self, access_token):
        return EbayAccountResources(
            payment_policies=[{"id": "pay-1", "name": PAYMENT_POLICY_NAME}],
            fulfillment_policies=[
                {"id": f"ful-{key}", "name": profile["policy_name"]}
                for key, profile in SHIPPING_PROFILES.items()
            ],
            return_policies=[{"id": "ret-1", "name": RETURN_POLICY_NAME}],
            merchant_locations=[{"key": "home", "name": "Warehouse", "status": "ENABLED"}],
        )

    def get_item_condition_policies(self, access_token, *, category_id: str):
        return {
            "categoryId": category_id,
            "itemConditionRequired": True,
            "itemConditions": [
                {"conditionId": "1000", "conditionDescription": "New"},
                {"conditionId": "5000", "conditionDescription": "Good"},
                {"conditionId": "6000", "conditionDescription": "Acceptable"},
            ],
        }


class ExistingOfferEbayClient(FakeEbayClient):
    def create_offer(self, access_token, payload: dict):
        from app.marketplaces.ebay.client import EbayOfferAlreadyExistsError

        self.offer_payloads.append(payload)
        raise EbayOfferAlreadyExistsError("offer-existing-123", "A user error has occurred. Offer entity already exists. | 25002")


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
    draft.workflow.status = WorkflowStatus.DRAFT
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

    inventory_payload = build_inventory_item_payload(draft, settings, config)
    offer_payload = build_offer_payload(draft, settings, config)

    assert inventory_payload["product"]["title"] == "Nintendo Switch OLED"
    assert inventory_payload["product"]["imageUrls"] == ["https://i.example.test/01-original.jpg"]
    assert inventory_payload["product"]["brand"] == "Nintendo"
    assert inventory_payload["product"]["mpn"] == "OLED"
    assert inventory_payload["product"]["aspects"]["Herstellernummer"] == ["OLED"]
    assert inventory_payload["condition"] == "USED_GOOD"
    assert inventory_payload["availability"]["shipToLocationAvailability"]["availabilityDistributions"] == [
        {"merchantLocationKey": "home", "quantity": 1}
    ]
    assert offer_payload["format"] == "AUCTION"
    assert offer_payload["listingDuration"] == "DAYS_7"
    assert "availableQuantity" not in offer_payload
    assert offer_payload["pricingSummary"]["auctionStartPrice"]["value"] == "199.99"
    assert offer_payload["pricingSummary"]["auctionStartPrice"]["currency"] == "EUR"


def test_offer_payload_uses_selected_shipping_profile_policy(tmp_path):
    settings = make_settings(tmp_path)
    draft = make_draft(tmp_path)
    draft.listing.shipping_suggestion["profile"] = "pickup"
    config = EbayConfigStore(tmp_path / "missing.db").get_effective_configuration()
    config.payment_policy_id = "pay-1"
    config.fulfillment_policy_id = "ful-dhl"
    config.return_policy_id = "ret-1"
    config.merchant_location_key = "home"
    config.shipping_profile_policy_ids = {"pickup": "ful-pickup"}

    offer_payload = build_offer_payload(draft, settings, config)

    assert offer_payload["listingPolicies"]["fulfillmentPolicyId"] == "ful-pickup"


def test_ebay_config_store_separates_defaults_by_mode(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    sandbox_store = EbayConfigStore(settings.database_path, mode="sandbox")
    live_store = EbayConfigStore(settings.database_path, mode="live")

    sandbox_store.save_selected_configuration(
        payment_policy_id="sandbox-pay",
        fulfillment_policy_id="sandbox-ful",
        return_policy_id="sandbox-ret",
        merchant_location_key="sandbox-home",
    )
    live_store.save_selected_configuration(
        payment_policy_id="live-pay",
        fulfillment_policy_id="live-ful",
        return_policy_id="live-ret",
        merchant_location_key="live-home",
    )

    assert sandbox_store.get_effective_configuration().payment_policy_id == "sandbox-pay"
    assert live_store.get_effective_configuration().payment_policy_id == "live-pay"


def test_inventory_payload_omits_location_distribution_without_selected_location(tmp_path):
    settings = make_settings(tmp_path)
    draft = make_draft(tmp_path)
    draft.marketplace.ebay.image_urls = ["https://i.example.test/01-original.jpg"]

    inventory_payload = build_inventory_item_payload(draft, settings)

    ship_to_location = inventory_payload["availability"]["shipToLocationAvailability"]
    assert ship_to_location == {"quantity": 1}


def test_mapping_sends_product_identifiers_and_key_details_to_ebay(tmp_path):
    settings = make_settings(tmp_path)
    draft = make_draft(tmp_path)
    draft.listing.attributes["product_identifier_type"] = "EAN"
    draft.listing.attributes["product_identifier_value"] = "1234567890123"
    draft.listing.attributes["keyTechnicalDetails"] = ["Bluetooth: 5.3", "Anschlüsse: 2x HDMI, 1x DisplayPort"]
    draft.marketplace.ebay.image_urls = ["https://i.example.test/01-original.jpg"]

    inventory_payload = build_inventory_item_payload(draft, settings)

    assert inventory_payload["product"]["ean"] == ["1234567890123"]
    assert inventory_payload["product"]["aspects"]["EAN"] == ["1234567890123"]
    assert inventory_payload["product"]["aspects"]["Bluetooth"] == ["5.3"]
    assert inventory_payload["product"]["aspects"]["Anschlüsse"] == ["2x HDMI, 1x DisplayPort"]


def test_mapping_sends_brand_mpn_pair_for_model_number_identifier(tmp_path):
    settings = make_settings(tmp_path)
    draft = make_draft(tmp_path)
    draft.listing.brand = "Apple"
    draft.listing.model = "A1657"
    draft.listing.attributes["product_identifier_type"] = "Modell-Nummer"
    draft.listing.attributes["product_identifier_value"] = "A1657"
    draft.marketplace.ebay.image_urls = ["https://i.example.test/01-original.jpg"]

    inventory_payload = build_inventory_item_payload(draft, settings)

    assert inventory_payload["product"]["brand"] == "Apple"
    assert inventory_payload["product"]["mpn"] == "A1657"
    assert inventory_payload["product"]["aspects"]["Herstellernummer"] == ["A1657"]


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


def test_service_treats_existing_ebay_offer_as_success(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    repository.save_draft(draft)
    client = ExistingOfferEbayClient()
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
    assert updated.marketplace.ebay.offer_id == "offer-existing-123"
    assert updated.marketplace.ebay.offer_data["response"]["status"] == "already_exists"
    assert "lastError" not in updated.marketplace.ebay.offer_data


def test_service_updates_offer_when_offer_id_is_known(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    draft.marketplace.ebay.offer_id = "offer-known-123"
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
    assert updated.marketplace.ebay.offer_id == "offer-known-123"
    assert client.offer_payloads == []
    assert client.updated_offer_payloads[0][0] == "offer-known-123"


def test_service_reuses_existing_ebay_image_urls_when_updating_offer(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    draft.marketplace.ebay.offer_id = "offer-known-123"
    draft.marketplace.ebay.image_urls = ["https://i.example.test/existing.jpg"]
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

    assert updated.marketplace.ebay.image_urls == ["https://i.example.test/existing.jpg"]
    assert client.upload_calls == 0
    assert client.inventory_payloads[0][1]["product"]["imageUrls"] == ["https://i.example.test/existing.jpg"]


def test_service_uses_category_supported_condition(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    draft.listing.condition = "sehr gut"
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
    service.create_unpublished_offer_for_draft(draft.id)

    assert client.inventory_payloads[0][1]["condition"] == "USED_GOOD"


def test_service_publishes_prepared_offer(tmp_path):
    settings = make_settings(tmp_path)
    initialize_database(settings.database_path)
    repository = DraftRepository(settings.database_path)
    draft = make_draft(tmp_path)
    draft.marketplace.ebay.offer_id = "offer-123"
    repository.save_draft(draft)
    client = FakeEbayClient()
    config_store = EbayConfigStore(settings.database_path)
    config_store.save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-dhl_2kg",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )
    config_store.save_shipping_profile_policy_ids({key: f"ful-{key}" for key in SHIPPING_PROFILES})
    service = EbayMarketplaceService(settings=settings, repository=repository, client=client, config_store=config_store)

    updated = service.publish_offer_for_draft(draft.id)

    assert updated.workflow.status is WorkflowStatus.PUBLISHED
    assert updated.marketplace.ebay.listing_id == "listing-123"
    assert updated.marketplace.ebay.offer_data["publishResponse"]["listingId"] == "listing-123"


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

    assert updated.workflow.status is WorkflowStatus.DRAFT
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

    assert updated.workflow.status is WorkflowStatus.DRAFT
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


def test_upload_image_uses_ebay_media_host_in_live_mode(tmp_path):
    settings = make_settings(tmp_path)
    settings.ebay_mode = "live"
    captured_host = None
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"fake-image")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_host
        captured_host = request.url.host
        return httpx.Response(201, json={"imageUrl": "https://i.example.test/sample.jpg"})

    client = EbayClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        client.upload_image(
            type("Token", (), {"token_type": "Bearer", "token": "token-123"})(),
            image_path,
        )
    finally:
        client.close()

    assert captured_host == "apim.ebay.com"


def test_upload_image_retries_transient_ebay_media_error(tmp_path, monkeypatch):
    from app.marketplaces.ebay import client as ebay_client_module

    settings = make_settings(tmp_path)
    image_path = tmp_path / "sample.jpg"
    image_path.write_bytes(b"fake-image")
    calls = 0
    monkeypatch.setattr(ebay_client_module, "UPLOAD_RETRY_DELAYS_SECONDS", (0.0, 0.0))

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="<html>Internal Server Error - Write</html>")
        return httpx.Response(201, json={"imageUrl": "https://i.example.test/sample.jpg"})

    client = EbayClient(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))
    try:
        response = client.upload_image(
            type("Token", (), {"token_type": "Bearer", "token": "token-123"})(),
            image_path,
        )
    finally:
        client.close()

    assert calls == 2
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

    assert updated.workflow.status is WorkflowStatus.DRAFT
    assert any("Merchant Location 'missing-location' existiert im verbundenen eBay-Account nicht" in item for item in updated.workflow.missing_information)
