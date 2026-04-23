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
    assert "Review- und Validierungsmaske" in detail.text
    assert "Leichte Gebrauchsspuren" in detail.text
    assert "Testgerät" in detail.text
    assert "ready_for_review" in detail.text
    assert "Kernangaben vollständig" in detail.text
    assert "Netzteil" in detail.text
    assert "Seriennummer verdeckt" in detail.text
    assert "Gerendertes Listing-HTML" in detail.text
    assert "Das HTML wird serverseitig aus den aktuellen Draft-Daten erzeugt, im Draft gespeichert" in detail.text
    assert "Beim Speichern oder Bestätigen wird derselbe gerenderte Stand erneut persistiert" in detail.text
    assert "Wichtiger Hinweis:" in detail.text
    assert "MVP-Heuristik" in detail.text
    assert "front.jpg" in detail.text
    assert "back.png" in detail.text

    settings = get_settings()
    originals = sorted(settings.data_dir.glob("drafts/*/images/originals/*"))
    normalized = sorted(settings.data_dir.glob("drafts/*/images/normalized/*"))
    assert len(originals) == 2
    assert len(normalized) == 2


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
    assert "ready_for_review" in detail.text

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
    assert "Review abgeschlossen" in updated_detail.text
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
    assert "needs_attention" in updated_detail.text
    assert "Kernangaben noch prüfen" in updated_detail.text
    assert "Jetzt zuerst ergänzen" in updated_detail.text
    assert "Noch offen vor dem eBay-Schritt" in updated_detail.text


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
    assert "Noch offen vor dem eBay-Schritt" in detail.text
    assert "Payment Policy ist nicht konfiguriert" in detail.text
    assert "Fulfillment Policy ist nicht konfiguriert" in detail.text
    assert "Return Policy ist nicht konfiguriert" in detail.text
    assert "Merchant Location ist nicht konfiguriert" in detail.text
    assert '<button class="button button--primary" type="submit" disabled>eBay-Draft senden</button>' in detail.text


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
    assert '<button class="button button--primary" type="submit" disabled>eBay-Draft senden</button>' in detail.text


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
    draft.workflow.status = WorkflowStatus.READY_FOR_MARKETPLACE
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

    assert "eBay-Draft erfolgreich erstellt" in detail.text
    assert 'href="#technical-details"' in detail.text
    assert 'href="/drafts"' in detail.text
    assert "Zurück zur Übersicht" in detail.text
    assert "Technische Details anzeigen" in detail.text
