from app.drafts.analysis import HeuristicDraftAnalysisService
from app.drafts.models import Draft
from app.drafts.rendering import render_listing_description
from app.drafts.review import update_draft_from_review


def build_draft() -> Draft:
    return Draft(
        id="draft_render1234",
        sku="OIN-RENDER1234",
        source={
            "images": [
                {
                    "id": "img_1",
                    "originalFilename": "front.jpg",
                    "storagePath": "data/drafts/draft_render1234/images/normalized/01-normalized.jpg",
                    "mimeType": "image/jpeg",
                    "order": 1,
                    "kind": "normalized",
                }
            ],
            "notes": "Sauberer Zustand\n\nVoll funktionsfähig",
            "userInput": {
                "product_name": "Switch OLED",
                "condition": "gebraucht",
                "accessories": "Dock, Netzteil",
                "hints": "kleiner Kratzer",
            },
        },
        listing={
            "title": "Switch OLED",
            "brand": "Nintendo",
            "condition": "gebraucht",
            "includedItems": ["Dock", "Netzteil"],
            "issues": ["kleiner Kratzer"],
            "attributes": {
                "purchase_date": "2024-12-24",
                "product_identifier_value": "1234567890",
            },
        },
    )


def test_render_listing_description_includes_expected_sections():
    html = render_listing_description(build_draft())

    assert "<strong>Nintendo Switch OLED</strong>" in html
    assert "<strong>Zustand:</strong> gebraucht" in html
    assert "<strong>Kaufdatum:</strong> 2024-12-24" in html
    assert "<strong>Produktkennung:</strong> 1234567890" in html
    assert "<strong>Lieferumfang:</strong>" in html
    assert "<li>Dock</li>" in html
    assert "<li>Netzteil</li>" in html
    assert "<strong>Hinweise:</strong>" in html
    assert "<li>kleiner Kratzer</li>" in html


def test_render_listing_description_omits_empty_optional_blocks():
    draft = build_draft()
    draft.listing.brand = ""
    draft.listing.condition = ""
    draft.listing.model = ""
    draft.listing.included_items = []
    draft.listing.issues = []
    draft.listing.attributes = {}
    draft.source.notes = ""

    html = render_listing_description(draft)

    assert "<strong>Switch OLED</strong>" in html
    assert "Kaufdatum" not in html
    assert "Produktkennung" not in html
    assert "Lieferumfang" not in html
    assert "Hinweise" not in html
    assert "<ul>" not in html


def test_render_listing_description_escapes_user_text_and_preserves_structure():
    draft = build_draft()
    draft.listing.title = "<Script-Konsole>"
    draft.source.notes = "Zeile 1\nZeile 2 <b>unsafe</b>"
    draft.listing.included_items = ["Dock <b>unsafe</b>"]

    html = render_listing_description(draft)

    assert "&lt;Script-Konsole&gt;" in html
    assert "&lt;b&gt;unsafe&lt;/b&gt;" in html
    assert "<script>" not in html.lower()


def test_analysis_service_populates_rendered_description_html():
    service = HeuristicDraftAnalysisService()
    draft = build_draft()

    analysis = service.analyze(draft)

    assert "<strong>Switch OLED</strong>" in analysis.listing.description_html
    assert "<strong>Lieferumfang:</strong>" in analysis.listing.description_html
    assert "MVP-Heuristik" not in analysis.listing.description_html


def test_review_updates_rendered_description_html_from_current_draft_state():
    draft = build_draft()

    update_draft_from_review(
        draft,
        title="Steam Deck",
        condition="sehr gut",
        description="Portable Konsole",
        included_items="Case, Ladegerät",
        brand="Valve",
        model="OLED",
        subtitle="512 GB",
        category_suggestion="Gaming",
        hints="leichte Gebrauchsspuren",
        confirm_fields=["title", "condition", "description_html", "included_items"],
        action="confirm",
    )

    assert "<strong>Valve Steam Deck</strong>" in draft.listing.description_html
    assert "<strong>Modell:</strong> OLED" in draft.listing.description_html
    assert "<p>Portable Konsole</p>" in draft.listing.description_html
    assert "<li>Case</li>" in draft.listing.description_html
    assert "<li>Ladegerät</li>" in draft.listing.description_html
