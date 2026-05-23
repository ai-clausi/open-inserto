from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import get_settings
from app.drafts.identity import derive_sku
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.repository import DraftRepository
from app.main import create_app
from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData
from app.marketplaces.ebay.configuration import EbayConfigStore


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'data' / 'test.db'}")

    # Make these UI tests deterministic even when a developer has local eBay
    # credentials/policies configured via shell env or a repository .env file.
    for env_var in (
        "EBAY_CLIENT_ID",
        "EBAY_CLIENT_SECRET",
        "EBAY_RU_NAME",
        "EBAY_ACCESS_TOKEN",
        "EBAY_REFRESH_TOKEN",
        "EBAY_PAYMENT_POLICY_ID",
        "EBAY_FULFILLMENT_POLICY_ID",
        "EBAY_RETURN_POLICY_ID",
        "EBAY_MERCHANT_LOCATION_KEY",
    ):
        monkeypatch.delenv(env_var, raising=False)

    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def build_image_bytes(*, image_format: str = "JPEG", size: tuple[int, int] = (1200, 900), color=(64, 114, 255)) -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def test_upload_page_renders(client: TestClient):
    response = client.get("/drafts/upload")

    assert response.status_code == 200
    assert "Mehrfach-Upload mit Vorschau" in response.text
    assert "Draft erstellen" in response.text


def test_post_upload_creates_draft_and_files(client: TestClient):
    files = [
        ("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg")),
        ("images", ("back.png", build_image_bytes(image_format="PNG"), "image/png")),
    ]
    data = {
        "notes": "Leichte Gebrauchsspuren",
        "product_name": "Testgerät",
        "condition": "gebraucht",
        "accessories": "Netzteil",
        "hints": "Seriennummer verdeckt",
    }

    response = client.post("/drafts/upload", files=files, data=data, follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/drafts/draft_")

    detail = client.get(location)
    assert detail.status_code == 200
    assert "Finaler Entwurf" in detail.text
    assert "Leichte Gebrauchsspuren" in detail.text
    assert "Testgerät" in detail.text
    assert "eBay einrichten" in detail.text
    assert "Kernangaben vollständig" in detail.text
    assert "Basisanalyse durchgeführt" in detail.text
    assert "Netzteil" in detail.text
    assert "Seriennummer verdeckt" in detail.text
    assert "Live-Vorschau" in detail.text
    assert "Originaleingabe" in detail.text
    assert "Verkaufstext" in detail.text
    assert "Wichtiger Hinweis:" in detail.text
    assert "MVP-Heuristik" in detail.text
    assert "front.jpg" in detail.text
    assert "back.png" in detail.text

    settings = get_settings()
    originals = sorted(settings.data_dir.glob("drafts/*/images/originals/*"))
    normalized = sorted(settings.data_dir.glob("drafts/*/images/normalized/*"))
    assert len(originals) == 2
    assert len(normalized) == 2


def test_draft_detail_can_trigger_analysis_again_from_ui(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    files = [("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg"))]
    response = client.post(
        "/drafts/upload",
        files=files,
        data={"product_name": "Lampe", "condition": "gut", "notes": "Kleine Lampe", "accessories": "Kabel"},
        follow_redirects=False,
    )

    location = response.headers["location"]

    class StubAnalysisService:
        def analyze(self, draft: Draft):
            draft_copy = draft.model_copy(deep=True)
            draft_copy.listing.title = "Neu analysierte Lampe"
            draft_copy.listing.condition = "sehr gut"
            draft_copy.listing.included_items = ["Kabel", "Ersatzbirne"]
            draft_copy.listing.issues = ["Leichte Kratzer", "Schirm leicht verzogen"]
            draft_copy.listing.attributes["confidenceNotes"] = ["Neu ausgewertet"]
            from app.drafts.analysis import DraftAnalysisResult

            return DraftAnalysisResult(
                listing=draft_copy.listing,
                needs_review=True,
                missing_information=[],
                confidence_notes=["Neu ausgewertet"],
                description_text="Schlichte Tischlampe in gutem Gesamtzustand.",
                analysis_mode="vision",
                analysis_label="KI-Analyse durchgeführt",
            )

    monkeypatch.setattr("app.web.routes.build_draft_analysis_service", lambda settings: StubAnalysisService())

    rerun = client.post(f"{location}/analyze", follow_redirects=False)

    assert rerun.status_code == 303
    assert rerun.headers["location"] == location

    detail = client.get(location)
    assert "KI-Vorschlag neu erstellen" in detail.text
    assert "Neu analysierte Lampe" in detail.text
    assert "KI-Analyse durchgeführt" in detail.text
    assert "Neu ausgewertet" in detail.text
    assert "Schlichte Tischlampe in gutem Gesamtzustand." in detail.text
    assert "Neu analysierte Lampe\nKabel\nErsatzbirne" in detail.text
    assert "Leichte Kratzer\nSchirm leicht verzogen" in detail.text


def test_draft_detail_exposes_assistant_flow_and_accepts_async_reply(client: TestClient):
    files = [("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg"))]
    response = client.post(
        "/drafts/upload",
        files=files,
        data={"product_name": "iPhone", "condition": "gut", "notes": "Leichte Spuren", "accessories": "Ladekabel"},
        follow_redirects=False,
    )

    location = response.headers["location"]
    detail = client.get(location)
    assert "Assistenten-Flow" in detail.text
    assert "Chat-artige Rückfragen ohne Reload" in detail.text
    assert "Ich habe produktname erkannt" in detail.text

    assistant = client.post(
        f"{location}/assistant/message",
        json={"action": "answer", "field": "title", "value": "Apple iPhone 13"},
    )

    assert assistant.status_code == 200
    payload = assistant.json()
    assert payload["ok"] is True
    assert any("Apple iPhone 13" in message["text"] for message in payload["messages"])

    updated_detail = client.get(location)
    assert "Apple iPhone 13" in updated_detail.text


def test_post_upload_without_images_returns_validation_error(client: TestClient):
    response = client.post("/drafts/upload", data={"notes": "Ohne Bild"})

    assert response.status_code == 400
    assert "Bitte mindestens ein Bild auswählen." in response.text


def test_post_upload_rejects_invalid_file_type(client: TestClient):
    response = client.post(
        "/drafts/upload",
        files=[("images", ("notes.txt", b"keine bilddatei", "text/plain"))],
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "nicht unterstützten Bildtyp" in response.text or "kein unterstütztes Bildformat" in response.text


def test_post_upload_rejects_too_small_images(client: TestClient):
    response = client.post(
        "/drafts/upload",
        files=[("images", ("small.jpg", build_image_bytes(size=(320, 240)), "image/jpeg"))],
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "mindestens 500px" in response.text


def test_review_post_persists_changes_and_final_confirmation(client: TestClient):
    files = [("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg"))]
    response = client.post(
        "/drafts/upload",
        files=files,
        data={"product_name": "Lampe", "condition": "gut", "notes": "Kleine Lampe", "accessories": "Kabel"},
        follow_redirects=False,
    )

    location = response.headers["location"]
    detail = client.get(location)
    assert "eBay einrichten" in detail.text

    review_response = client.post(
        f"{location}/review",
        data={
            "title": "Lampe aus Metall",
            "condition": "sehr gut",
            "description": "Metalllampe, voll funktionsfähig",
            "included_items": "Kabel, Schalter",
            "brand": "NoName",
            "model": "Desk 2000",
            "subtitle": "Schreibtischlampe",
            "category_suggestion": "Lampen",
            "hints": "leichte Kratzer",
            "confirm_fields": ["title", "condition", "description_html", "included_items"],
            "action": "save",
        },
        follow_redirects=False,
    )

    assert review_response.status_code == 303

    updated_detail = client.get(location)
    assert "Kernangaben vollständig" in updated_detail.text
    assert "Lampe aus Metall" in updated_detail.text
    assert "Desk 2000" in updated_detail.text
    assert "Schreibtischlampe" in updated_detail.text
    assert "Hersteller:&lt;/b&gt;" in updated_detail.text
    assert "NoName" in updated_detail.text


def test_review_save_with_missing_core_fields_stays_in_needs_attention(client: TestClient):
    files = [("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg"))]
    response = client.post(
        "/drafts/upload",
        files=files,
        data={"product_name": "", "condition": "", "notes": "", "accessories": ""},
        follow_redirects=False,
    )

    location = response.headers["location"]
    review_response = client.post(
        f"{location}/review",
        data={
            "title": "",
            "condition": "",
            "description": "Nur grob beschrieben",
            "included_items": "",
            "action": "save",
        },
        follow_redirects=False,
    )

    assert review_response.status_code == 303
    updated_detail = client.get(location)
    assert "Angaben ergänzen" in updated_detail.text
    assert "Noch vor dem Senden ergänzen" in updated_detail.text
    assert "eBay braucht noch" in updated_detail.text


def test_draft_detail_shows_marketplace_blockers_and_disables_ebay_action(client: TestClient):
    files = [("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg"))]
    response = client.post(
        "/drafts/upload",
        files=files,
        data={"product_name": "Lampe", "condition": "gut", "notes": "Kleine Lampe", "accessories": "Kabel"},
        follow_redirects=False,
    )

    location = response.headers["location"]
    detail = client.get(location)

    assert "Hinweise zum eBay-Draft" in detail.text
    assert "Noch keine Preisschätzung vorhanden – für Auktionen wird aktuell trotzdem 1,00 € als Startpreis verwendet." in detail.text
    assert "Diese Hinweise sind informativ und blockieren den eBay-Schritt nicht automatisch." in detail.text
    assert "eBay braucht noch" in detail.text
    assert "Payment Policy ist nicht konfiguriert" in detail.text
    assert "Fulfillment Policy ist nicht konfiguriert" in detail.text
    assert "Return Policy ist nicht konfiguriert" in detail.text
    assert "Merchant Location ist nicht konfiguriert" in detail.text
    assert "Zum eBay-Setup" in detail.text
    assert '<button class="button button--primary" type="submit" disabled>eBay-Angebot vorbereiten</button>' in detail.text


def test_draft_detail_enables_ebay_action_when_review_and_marketplace_data_are_complete(client: TestClient):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = Draft(
        id="draft_ready_stale",
        sku=derive_sku("draft_ready_stale"),
        source={
            "images": [{
                "id": "img_01",
                "originalFilename": "front.jpg",
                "storagePath": "/data/test/front.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "original",
            }],
            "notes": "Kleine Lampe",
        },
        listing={
            "title": "Lampe",
            "descriptionHtml": "<p>Kleine Lampe</p>",
            "condition": "gut",
            "categorySuggestion": "123",
        },
    )
    draft.workflow.status = WorkflowStatus.DRAFT
    draft.workflow.needs_review = True
    repository.save_draft(draft)

    EbayAuthStore(settings.database_path).save_tokens(EbayTokenData(refresh_token="refresh-123"))
    EbayConfigStore(settings.database_path).save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )

    detail = client.get(f"/drafts/{draft.id}")

    assert "Bereit für eBay-Draft" in detail.text
    assert '<button class="button button--primary" type="submit" >eBay-Angebot vorbereiten</button>' in detail.text


def test_draft_detail_shows_category_suggestions_as_choices(client: TestClient):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = Draft(
        id="draft_category_choices",
        sku=derive_sku("draft_category_choices"),
        source={
            "images": [{
                "id": "img_01",
                "originalFilename": "front.jpg",
                "storagePath": "/data/test/front.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "original",
            }],
            "notes": "Audi RS3",
        },
        listing={
            "title": "Audi RS3",
            "descriptionHtml": "<p>Audi RS3</p>",
            "condition": "gebraucht",
            "categorySuggestion": "84992",
            "attributes": {
                "ebayCategory": {
                    "state": "resolved",
                    "query": "Fahrzeuge & Motorräder > Autos > Audi > RS3",
                    "original_query": "Fahrzeuge & Motorräder > Autos > Audi > RS3",
                    "selected_id": "84992",
                    "selected_name": "Autos",
                    "selected_path": "Spielzeug > Spielzeugautos > Autos",
                    "suggestions": [
                        {"id": "84992", "name": "Autos", "path": "Spielzeug > Spielzeugautos > Autos"},
                        {"id": "9801", "name": "Automobile", "path": "Auto & Motorrad > Fahrzeuge > Automobile"},
                    ],
                    "aspects": [
                        {"name": "Breite", "required": True, "values": []},
                    ],
                    "message": "",
                }
            },
        },
    )
    repository.save_draft(draft)

    detail = client.get(f"/drafts/{draft.id}")

    assert 'value="84992" checked' in detail.text
    assert 'value="9801"' in detail.text
    assert "Spielzeug &gt; Spielzeugautos &gt; Autos" in detail.text
    assert "Auto &amp; Motorrad &gt; Fahrzeuge &gt; Automobile" in detail.text


def test_review_post_persists_selected_category_choice(client: TestClient):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = Draft(
        id="draft_category_select",
        sku=derive_sku("draft_category_select"),
        source={
            "images": [{
                "id": "img_01",
                "originalFilename": "front.jpg",
                "storagePath": "/data/test/front.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "original",
            }],
            "notes": "Audi RS3",
        },
        listing={
            "title": "Audi RS3",
            "descriptionHtml": "<p>Audi RS3</p>",
            "condition": "gebraucht",
            "categorySuggestion": "84992",
            "attributes": {
                "ebayCategory": {
                    "state": "resolved",
                    "query": "Fahrzeuge & Motorräder > Autos > Audi > RS3",
                    "original_query": "Fahrzeuge & Motorräder > Autos > Audi > RS3",
                    "selected_id": "84992",
                    "selected_name": "Autos",
                    "selected_path": "Spielzeug > Spielzeugautos > Autos",
                    "suggestions": [
                        {"id": "84992", "name": "Autos", "path": "Spielzeug > Spielzeugautos > Autos"},
                        {"id": "9801", "name": "Automobile", "path": "Auto & Motorrad > Fahrzeuge > Automobile"},
                    ],
                    "message": "",
                }
            },
        },
    )
    repository.save_draft(draft)

    response = client.post(
        f"/drafts/{draft.id}/review",
        data={
            "title": "Audi RS3",
            "condition": "gebraucht",
            "description": "Audi RS3",
            "included_items": "Audi RS3",
            "category_suggestion": "84992",
            "selected_category_suggestion": "9801",
            "ebay_aspect__Breite": "180 cm",
            "action": "save",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = repository.get_draft(draft.id)
    assert updated is not None
    assert updated.listing.category_suggestion == "9801"
    assert updated.listing.attributes["ebayCategory"]["selected_id"] == "9801"
    assert updated.listing.attributes["ebayCategory"]["selected_name"] == "Automobile"
    assert updated.listing.attributes["ebayAspects"]["Breite"] == "180 cm"


def test_review_post_can_refresh_category_suggestions_with_search_query(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    settings.ebay_client_id = "client-123"
    settings.ebay_client_secret = "secret-123"
    repository = DraftRepository(settings.database_path)
    draft = Draft(
        id="draft_category_search",
        sku=derive_sku("draft_category_search"),
        source={
            "images": [{
                "id": "img_01",
                "originalFilename": "front.jpg",
                "storagePath": "/data/test/front.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "original",
            }],
        },
        listing={
            "title": "Magic Mouse A1657 - MK2E3Z/A",
            "descriptionHtml": "<p>Magic Mouse</p>",
            "condition": "gebraucht",
            "categorySuggestion": "Computer Zubehör > Eingabegeräte > Mäuse",
        },
    )
    repository.save_draft(draft)

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            if query == "Computer Maus":
                return [{"id": "23160", "name": "Mäuse, Trackballs & Touchpads", "path": "Computer > Tastaturen, Mäuse & Pointing > Mäuse, Trackballs & Touchpads"}]
            return []

        def get_item_aspects_for_category(self, access_token, *, category_tree_id: str, category_id: str):
            return []

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    response = client.post(
        f"/drafts/{draft.id}/review",
        data={
            "title": "Magic Mouse A1657 - MK2E3Z/A",
            "condition": "gebraucht",
            "description": "Magic Mouse",
            "included_items": "Magic Mouse",
            "category_suggestion": "Computer Zubehör > Eingabegeräte > Mäuse",
            "category_search_query": "Computer Maus",
            "action": "search_category",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    updated = repository.get_draft(draft.id)
    assert updated is not None
    assert updated.listing.category_suggestion == "23160"


def test_category_search_endpoint_returns_suggestions_without_page_reload(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    settings.ebay_client_id = "client-123"
    settings.ebay_client_secret = "secret-123"
    repository = DraftRepository(settings.database_path)
    draft = Draft(
        id="draft_category_async",
        sku=derive_sku("draft_category_async"),
        listing={
            "title": "Lockenstab",
            "descriptionHtml": "<p>Lockenstab</p>",
            "condition": "gebraucht",
            "categorySuggestion": "Lockenstab",
        },
    )
    repository.save_draft(draft)

    class FakeClient:
        def __init__(self, settings):
            self.settings = settings

        def get_application_access_token(self):
            return object()

        def get_default_category_tree_id(self, access_token):
            return "77"

        def get_category_suggestions(self, access_token, *, category_tree_id: str, query: str):
            return [{"id": "177659", "name": "Lockenstäbe & Glätteisen", "path": "Beauty > Haarstyling > Lockenstäbe & Glätteisen"}]

        def get_item_aspects_for_category(self, access_token, *, category_tree_id: str, category_id: str):
            return []

        def close(self):
            return None

    monkeypatch.setattr("app.marketplaces.ebay.taxonomy.EbayClient", FakeClient)

    response = client.post(f"/drafts/{draft.id}/category/search", data={"query": "Lockenstab"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["categorySuggestion"] == "177659"
    assert payload["suggestions"][0]["id"] == "177659"


def test_draft_detail_opens_ebay_details_when_category_needs_selection(client: TestClient):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = Draft(
        id="draft_category_open",
        sku=derive_sku("draft_category_open"),
        source={
            "images": [{
                "id": "img_01",
                "originalFilename": "front.jpg",
                "storagePath": "/data/test/front.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "original",
            }],
        },
        listing={
            "title": "Lockenstab",
            "descriptionHtml": "<p>Lockenstab</p>",
            "condition": "gebraucht",
            "categorySuggestion": "Lockenstäbe",
            "attributes": {
                "ebayCategory": {
                    "state": "no_match",
                    "query": "Lockenstäbe",
                    "selected_id": "",
                    "suggestions": [],
                    "message": "Für diese Suche wurden keine passenden eBay-Kategorien gefunden.",
                    "aspects": [],
                }
            },
        },
    )
    repository.save_draft(draft)

    response = client.get(f"/drafts/{draft.id}")

    assert '<details class="detail-disclosure" open>' in response.text
    assert "Für diese Suche wurden keine passenden eBay-Kategorien gefunden." in response.text


def test_draft_detail_blocks_non_numeric_ebay_category_id(client: TestClient):
    files = [("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg"))]
    response = client.post(
        "/drafts/upload",
        files=files,
        data={"product_name": "Lampe", "condition": "gut", "notes": "Kleine Lampe", "accessories": "Kabel"},
        follow_redirects=False,
    )

    location = response.headers["location"]
    review_response = client.post(
        f"{location}/review",
        data={
            "title": "Tischlampe",
            "condition": "gut",
            "description": "Kleine Lampe",
            "included_items": "Kabel",
            "category_suggestion": "Lampen",
            "action": "save",
        },
        follow_redirects=False,
    )

    assert review_response.status_code == 303
    detail = client.get(location)
    assert "eBay-Kategorie muss als numerische Category ID angegeben werden" in detail.text
    assert '<button class="button button--primary" type="submit" disabled>eBay-Angebot vorbereiten</button>' in detail.text


def test_draft_detail_shows_primary_reconnect_action_when_auth_is_missing(client: TestClient):
    files = [("images", ("front.jpg", build_image_bytes(image_format="JPEG"), "image/jpeg"))]
    response = client.post(
        "/drafts/upload",
        files=files,
        data={"product_name": "Lampe", "condition": "gut", "notes": "Kleine Lampe", "accessories": "Kabel"},
        follow_redirects=False,
    )

    detail = client.get(response.headers["location"])

    assert "eBay muss neu verbunden werden" in detail.text
    assert 'href="#ebay-connect"' in detail.text


def test_draft_detail_shows_retry_result_for_retryable_ebay_error(client: TestClient):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = Draft(
        id="draft_retry_case",
        sku=derive_sku("draft_retry_case"),
        source={
            "images": [{
                "id": "img_01",
                "originalFilename": "front.jpg",
                "storagePath": "/data/test/front.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "original",
            }],
            "notes": "Kleine Lampe",
        },
        listing={
            "title": "Lampe",
            "descriptionHtml": "<p>Kleine Lampe</p>",
            "condition": "gut",
            "categorySuggestion": "123",
        },
    )
    draft.workflow.status = WorkflowStatus.DRAFT
    draft.workflow.needs_review = False
    draft.marketplace.ebay.offer_data["lastError"] = "eBay timeout"
    repository.save_draft(draft)

    EbayAuthStore(settings.database_path).save_tokens(EbayTokenData(refresh_token="refresh-123"))
    EbayConfigStore(settings.database_path).save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )

    detail = client.get(f"/drafts/{draft.id}")

    assert "eBay hat den letzten Versuch abgelehnt" in detail.text
    assert "Der lokale Draft ist erhalten geblieben" in detail.text
    assert 'href="#ebay-send"' in detail.text


def test_draft_detail_shows_success_result_with_technical_details_link(client: TestClient):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = Draft(
        id="draft_success_case",
        sku=derive_sku("draft_success_case"),
        source={
            "images": [{
                "id": "img_01",
                "originalFilename": "front.jpg",
                "storagePath": "/data/test/front.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "original",
            }],
        },
        listing={
            "title": "Lampe",
            "descriptionHtml": "<p>Kleine Lampe</p>",
            "condition": "gut",
            "categorySuggestion": "123",
        },
    )
    draft.workflow.status = WorkflowStatus.OFFER_CREATED
    draft.workflow.needs_review = False
    draft.marketplace.ebay.offer_id = "offer-123"
    repository.save_draft(draft)

    EbayAuthStore(settings.database_path).save_tokens(EbayTokenData(refresh_token="refresh-123"))
    EbayConfigStore(settings.database_path).save_selected_configuration(
        payment_policy_id="pay-1",
        fulfillment_policy_id="ful-1",
        return_policy_id="ret-1",
        merchant_location_key="home",
    )

    detail = client.get(f"/drafts/{draft.id}")

    assert "eBay-Angebot vorbereitet" in detail.text
    assert 'href="#technical-details"' in detail.text
    assert 'href="/drafts"' in detail.text
    assert "Zurück zur Übersicht" in detail.text
    assert "Offer-ID:" in detail.text
    assert "offer-123" in detail.text
    assert "eBay Seller Hub öffnen" in detail.text
    assert "Bei eBay veröffentlichen" in detail.text
    assert 'href="https://www.sandbox.ebay.com/sh/lst/drafts"' in detail.text
    assert "Technische Details anzeigen" in detail.text
