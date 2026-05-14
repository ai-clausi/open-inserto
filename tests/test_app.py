from pathlib import Path
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.repository import DraftRepository
from app.main import create_app


def test_health_endpoint():
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_index_page_renders():
    client = TestClient(create_app())
    response = client.get("/")

    assert response.status_code == 200
    assert "Open Inserto" in response.text
    assert "MVP Upload Flow" in response.text
    assert "Zum Upload" in response.text
    assert "Drafts ansehen" in response.text
    assert "KI-Konfiguration" in response.text
    assert 'href="/drafts/upload"' in response.text
    assert 'href="/drafts"' in response.text


def test_draft_list_page_renders_empty_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/drafts")

    assert response.status_code == 200
    assert "Noch keine Drafts vorhanden" in response.text
    assert 'href="/drafts/upload"' in response.text
    get_settings.cache_clear()



def test_draft_list_page_shows_existing_drafts_sorted_by_last_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    get_settings.cache_clear()

    settings = get_settings()

    with TestClient(create_app()):
        pass

    repository = DraftRepository(settings.database_path)

    older = Draft.model_validate(
        {
            "id": "draft_old",
            "sku": "OIN-OLD",
            "listing": {
                "title": "Vintage Kamera",
                "condition": "Gebraucht, guter Zustand",
                "attributes": {
                    "analysis": {
                        "performed": True,
                        "mode": "vision",
                        "label": "KI-Analyse durchgeführt",
                    }
                },
            },
            "source": {
                "images": [
                    {
                        "id": "img-old",
                        "originalFilename": "kamera.jpg",
                        "storagePath": "data/drafts/draft_old/images/normalized/01-normalized.jpg",
                        "mimeType": "image/jpeg",
                        "order": 1,
                        "kind": "normalized",
                    }
                ]
            },
            "workflow": {
                "status": WorkflowStatus.READY_FOR_REVIEW,
                "needsReview": True,
                "createdAt": "2026-04-18T10:00:00+00:00",
                "lastUpdatedAt": "2026-04-18T11:00:00+00:00",
            },
        }
    )
    newer = Draft.model_validate(
        {
            "id": "draft_new",
            "sku": "OIN-NEW",
            "listing": {
                "title": "Nintendo Switch OLED",
                "subtitle": "Mit Dock und Netzteil",
            },
            "workflow": {
                "status": WorkflowStatus.READY_FOR_MARKETPLACE,
                "needsReview": False,
                "createdAt": "2026-04-19T10:00:00+00:00",
                "lastUpdatedAt": "2026-04-19T12:30:00+00:00",
            },
        }
    )
    repository.create_draft(older)
    repository.create_draft(newer)

    with TestClient(create_app()) as client:
        response = client.get("/drafts")

    assert response.status_code == 200
    assert "draft_old" in response.text
    assert "draft_new" in response.text
    assert "Vintage Kamera" in response.text
    assert "Nintendo Switch OLED" in response.text
    assert "Mit Dock und Netzteil" in response.text
    assert "/data/drafts/draft_old/images/normalized/01-normalized.jpg" in response.text
    assert 'href="/drafts/draft_old"' in response.text
    assert 'href="/drafts/draft_new"' in response.text
    assert "Öffnen" in response.text
    assert "Bereit für eBay" in response.text
    assert "KI-Analyse durchgeführt" in response.text
    assert "Keine Analyse hinterlegt" in response.text
    assert response.text.index("draft_new") < response.text.index("draft_old")
    get_settings.cache_clear()


def test_index_shows_missing_ai_configuration_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "KI-Konfiguration" in response.text
    assert "Nicht erfüllt" in response.text
    assert "Ohne vollständige KI-Konfiguration bleibt die Basisanalyse aktiv" in response.text
    get_settings.cache_clear()


def test_index_shows_fulfilled_ai_configuration_when_vision_is_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("DRAFT_ANALYSIS_BACKEND", "vision")
    monkeypatch.setenv("VISION_PROVIDER", "openai")
    monkeypatch.setenv("VISION_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("VISION_API_KEY", "test-key")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "KI-Konfiguration" in response.text
    assert "Erfüllt" in response.text
    assert "KI-Analyse" in response.text
    get_settings.cache_clear()


def test_index_does_not_show_connected_for_env_token_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("EBAY_ACCESS_TOKEN", "env-access-token")
    monkeypatch.setenv("EBAY_REFRESH_TOKEN", "env-refresh-token")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "nicht verbunden" in response.text
    get_settings.cache_clear()


def test_index_does_not_use_env_policy_values_as_active_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("EBAY_CLIENT_ID", "client-123")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("EBAY_RU_NAME", "runame-123")
    monkeypatch.setenv("EBAY_PAYMENT_POLICY_ID", "env-pay")
    monkeypatch.setenv("EBAY_FULFILLMENT_POLICY_ID", "env-ful")
    monkeypatch.setenv("EBAY_RETURN_POLICY_ID", "env-ret")
    monkeypatch.setenv("EBAY_MERCHANT_LOCATION_KEY", "env-home")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData

        auth_store = EbayAuthStore(get_settings().database_path)
        auth_store.save_tokens(EbayTokenData(refresh_token="refresh-123"))
        response = client.get("/")

    assert response.status_code == 200
    assert "Payment Policy" in response.text
    assert "Fulfillment Policy" in response.text
    assert "Return Policy" in response.text
    assert "Merchant Location" in response.text
    assert ">–</strong>" in response.text
    get_settings.cache_clear()


def test_index_shows_discovery_action_and_empty_state_for_connected_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData

        auth_store = EbayAuthStore(get_settings().database_path)
        auth_store.save_tokens(EbayTokenData(refresh_token="refresh-123"))
        response = client.get("/")

    assert response.status_code == 200
    assert "Account-Ressourcen laden" in response.text
    assert "Noch keine eBay-Ressourcen geladen" in response.text
    get_settings.cache_clear()


def test_discover_route_loads_account_resources_and_renders_selection_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("EBAY_CLIENT_ID", "client-123")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("EBAY_RU_NAME", "runame-123")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 7200,
                    "token_type": "Bearer",
                },
            )
        if path.endswith("/sell/account/v1/program/get_opted_in_programs"):
            return httpx.Response(200, json={"programs": [{"programType": "SELLING_POLICY_MANAGEMENT"}]})
        if path.endswith("/sell/account/v1/payment_policy"):
            return httpx.Response(200, json={"paymentPolicies": [{"paymentPolicyId": "pay-1", "name": "Payment"}]})
        if path.endswith("/sell/account/v1/fulfillment_policy"):
            return httpx.Response(200, json={"fulfillmentPolicies": [{"fulfillmentPolicyId": "ful-1", "name": "Fulfillment"}]})
        if path.endswith("/sell/account/v1/return_policy"):
            return httpx.Response(200, json={"returnPolicies": [{"returnPolicyId": "ret-1", "name": "Return"}]})
        if path.endswith("/sell/inventory/v1/location"):
            return httpx.Response(200, json={"locations": [{"merchantLocationKey": "home", "name": "Warehouse", "merchantLocationStatus": "ENABLED"}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with TestClient(create_app()) as client:
        from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData
        from app.web import routes

        auth_store = EbayAuthStore(get_settings().database_path)
        auth_store.save_tokens(EbayTokenData(refresh_token="refresh-123"))
        fake_ebay_client = routes.EbayClient(get_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)), auth_store=auth_store)
        original = routes.EbayClient
        routes.EbayClient = lambda *args, **kwargs: fake_ebay_client
        try:
            response = client.post("/integrations/ebay/discover")
        finally:
            routes.EbayClient = original
            fake_ebay_client.close()

    assert response.status_code == 200
    assert "Gefundene Account-Ressourcen" in response.text
    assert 'value="pay-1"' in response.text
    assert 'value="home"' in response.text
    get_settings.cache_clear()


def test_discover_route_shows_opt_in_notice_when_selling_policy_management_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("EBAY_CLIENT_ID", "client-123")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("EBAY_RU_NAME", "runame-123")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 7200,
                    "token_type": "Bearer",
                },
            )
        if request.url.path.endswith("/sell/account/v1/program/get_opted_in_programs"):
            return httpx.Response(200, json={"programs": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with TestClient(create_app()) as client:
        from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData
        from app.web import routes

        auth_store = EbayAuthStore(get_settings().database_path)
        auth_store.save_tokens(EbayTokenData(refresh_token="refresh-123"))
        fake_ebay_client = routes.EbayClient(get_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)), auth_store=auth_store)
        original = routes.EbayClient
        routes.EbayClient = lambda *args, **kwargs: fake_ebay_client
        try:
            response = client.post("/integrations/ebay/discover")
        finally:
            routes.EbayClient = original
            fake_ebay_client.close()

    assert response.status_code == 400
    assert "Business Policies noch nicht aktiviert" in response.text
    assert "Selling Policy Management aktivieren" in response.text
    get_settings.cache_clear()


def test_create_default_location_route_creates_location_and_renders_selection_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("EBAY_CLIENT_ID", "client-123")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("EBAY_RU_NAME", "runame-123")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 7200,
                    "token_type": "Bearer",
                },
            )
        if path.endswith("/sell/inventory/v1/location/open-inserto-default") and request.method == "POST":
            return httpx.Response(204)
        if path.endswith("/sell/account/v1/payment_policy"):
            return httpx.Response(200, json={"paymentPolicies": [{"paymentPolicyId": "pay-1", "name": "Payment"}]})
        if path.endswith("/sell/account/v1/fulfillment_policy"):
            return httpx.Response(200, json={"fulfillmentPolicies": [{"fulfillmentPolicyId": "ful-1", "name": "Fulfillment"}]})
        if path.endswith("/sell/account/v1/return_policy"):
            return httpx.Response(200, json={"returnPolicies": [{"returnPolicyId": "ret-1", "name": "Return"}]})
        if path.endswith("/sell/inventory/v1/location") and request.method == "GET":
            return httpx.Response(200, json={"locations": [{"merchantLocationKey": "open-inserto-default", "name": "Open Inserto Default", "merchantLocationStatus": "ENABLED"}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with TestClient(create_app()) as client:
        from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData
        from app.web import routes

        auth_store = EbayAuthStore(get_settings().database_path)
        auth_store.save_tokens(EbayTokenData(refresh_token="refresh-123"))
        fake_ebay_client = routes.EbayClient(get_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)), auth_store=auth_store)
        original = routes.EbayClient
        routes.EbayClient = lambda *args, **kwargs: fake_ebay_client
        try:
            response = client.post("/integrations/ebay/locations/create-default")
        finally:
            routes.EbayClient = original
            fake_ebay_client.close()

    assert response.status_code == 200
    assert "Standard-Merchant-Location wurde angelegt." in response.text
    assert 'value="open-inserto-default"' in response.text
    get_settings.cache_clear()


def test_create_default_policies_route_creates_standard_business_policies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("EBAY_CLIENT_ID", "client-123")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("EBAY_RU_NAME", "runame-123")
    get_settings.cache_clear()

    created_payloads: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 7200,
                    "token_type": "Bearer",
                },
            )
        if path.endswith("/sell/metadata/v1/shipping/marketplace/EBAY_DE/get_shipping_services"):
            return httpx.Response(
                200,
                json={
                    "shippingServices": [
                        {"description": "DHL Paket", "shippingServiceCode": "DE_DHLPaket"},
                        {"description": "DHL Päckchen", "shippingServiceCode": "DE_DHLPackchen"},
                    ]
                },
            )
        if path.endswith("/sell/account/v1/payment_policy") and request.method == "POST":
            created_payloads["payment"] = json.loads(request.content.decode())
            return httpx.Response(201, json={"paymentPolicyId": "pay-1"})
        if path.endswith("/sell/account/v1/return_policy") and request.method == "POST":
            created_payloads["return"] = json.loads(request.content.decode())
            return httpx.Response(201, json={"returnPolicyId": "ret-1"})
        if path.endswith("/sell/account/v1/fulfillment_policy") and request.method == "POST":
            created_payloads["fulfillment"] = json.loads(request.content.decode())
            return httpx.Response(201, json={"fulfillmentPolicyId": "ful-1"})
        if path.endswith("/sell/account/v1/payment_policy") and request.method == "GET":
            return httpx.Response(200, json={"paymentPolicies": [{"paymentPolicyId": "pay-1", "name": "Open Inserto - Sofortzahlung"}]})
        if path.endswith("/sell/account/v1/fulfillment_policy") and request.method == "GET":
            return httpx.Response(200, json={"fulfillmentPolicies": [{"fulfillmentPolicyId": "ful-1", "name": "Open Inserto - DHL Standard"}]})
        if path.endswith("/sell/account/v1/return_policy") and request.method == "GET":
            return httpx.Response(200, json={"returnPolicies": [{"returnPolicyId": "ret-1", "name": "Open Inserto - Keine Rücknahme"}]})
        if path.endswith("/sell/inventory/v1/location") and request.method == "GET":
            return httpx.Response(200, json={"locations": [{"merchantLocationKey": "open-inserto-default", "name": "Open Inserto Default", "merchantLocationStatus": "ENABLED"}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with TestClient(create_app()) as client:
        from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData
        from app.web import routes

        auth_store = EbayAuthStore(get_settings().database_path)
        auth_store.save_tokens(EbayTokenData(refresh_token="refresh-123"))
        fake_ebay_client = routes.EbayClient(get_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)), auth_store=auth_store)
        original = routes.EbayClient
        routes.EbayClient = lambda *args, **kwargs: fake_ebay_client
        try:
            response = client.post("/integrations/ebay/policies/create-defaults")
        finally:
            routes.EbayClient = original
            fake_ebay_client.close()

    assert response.status_code == 200
    assert "Standard-Business-Policies wurden angelegt oder waren bereits vorhanden." in response.text
    assert created_payloads["payment"]["immediatePay"] is True
    assert created_payloads["return"]["returnsAccepted"] is False
    services = created_payloads["fulfillment"]["shippingOptions"][0]["shippingServices"]
    assert {item["shippingServiceCode"] for item in services} == {"DE_DHLPaket", "DE_DHLPackchen"}
    assert created_payloads["fulfillment"]["handlingTime"]["value"] == 3
    get_settings.cache_clear()


def test_create_default_policies_route_reuses_existing_policies_after_duplicate_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")
    monkeypatch.setenv("EBAY_CLIENT_ID", "client-123")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret-123")
    monkeypatch.setenv("EBAY_RU_NAME", "runame-123")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/identity/v1/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "access-1",
                    "refresh_token": "refresh-1",
                    "expires_in": 7200,
                    "token_type": "Bearer",
                },
            )
        if path.endswith("/sell/metadata/v1/shipping/marketplace/EBAY_DE/get_shipping_services"):
            return httpx.Response(
                200,
                json={
                    "shippingServices": [
                        {"description": "DHL Paket", "shippingServiceCode": "DE_DHLPaket"},
                        {"description": "DHL Päckchen", "shippingServiceCode": "DE_DHLPackchen"},
                    ]
                },
            )
        if path.endswith("/sell/account/v1/payment_policy") and request.method == "POST":
            return httpx.Response(400, json={"errors": [{"errorId": 20400, "message": "Invalid request.", "longMessage": "Bedingung doppelt vorhanden", "inputRefIds": [None]}]})
        if path.endswith("/sell/account/v1/return_policy") and request.method == "POST":
            return httpx.Response(201, json={"returnPolicyId": "ret-1"})
        if path.endswith("/sell/account/v1/fulfillment_policy") and request.method == "POST":
            return httpx.Response(201, json={"fulfillmentPolicyId": "ful-1"})
        if path.endswith("/sell/account/v1/payment_policy") and request.method == "GET":
            return httpx.Response(200, json={"paymentPolicies": [{"paymentPolicyId": "pay-9", "name": "Open Inserto - Sofortzahlung"}]})
        if path.endswith("/sell/account/v1/fulfillment_policy") and request.method == "GET":
            return httpx.Response(200, json={"fulfillmentPolicies": [{"fulfillmentPolicyId": "ful-1", "name": "Open Inserto - DHL Standard"}]})
        if path.endswith("/sell/account/v1/return_policy") and request.method == "GET":
            return httpx.Response(200, json={"returnPolicies": [{"returnPolicyId": "ret-1", "name": "Open Inserto - Keine Rücknahme"}]})
        if path.endswith("/sell/inventory/v1/location") and request.method == "GET":
            return httpx.Response(200, json={"locations": [{"merchantLocationKey": "open-inserto-default", "name": "Open Inserto Default", "merchantLocationStatus": "ENABLED"}]})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with TestClient(create_app()) as client:
        from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData
        from app.web import routes

        auth_store = EbayAuthStore(get_settings().database_path)
        auth_store.save_tokens(EbayTokenData(refresh_token="refresh-123"))
        fake_ebay_client = routes.EbayClient(get_settings(), client=httpx.Client(transport=httpx.MockTransport(handler)), auth_store=auth_store)
        original = routes.EbayClient
        routes.EbayClient = lambda *args, **kwargs: fake_ebay_client
        try:
            response = client.post("/integrations/ebay/policies/create-defaults")
        finally:
            routes.EbayClient = original
            fake_ebay_client.close()

    assert response.status_code == 200
    assert "Standard-Business-Policies wurden angelegt oder waren bereits vorhanden." in response.text
    assert "pay-9" in response.text
    get_settings.cache_clear()
