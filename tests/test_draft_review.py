from app.drafts.models import Draft, WorkflowStatus
from app.drafts.review import get_field_sources, get_review_form_values, update_draft_from_review


def build_draft(*, with_images: bool = True) -> Draft:
    draft = Draft(id="draft_review1234", sku="OIN-REVIEW1234")
    if with_images:
        draft.source.images = [
            {
                "id": "img_1",
                "originalFilename": "front.jpg",
                "storagePath": "data/drafts/draft_review1234/images/normalized/01-normalized.jpg",
                "mimeType": "image/jpeg",
                "order": 1,
                "kind": "normalized",
            }
        ]
    return draft


def test_review_confirmation_marks_review_complete_without_changing_lifecycle_status():
    draft = build_draft()

    update_draft_from_review(
        draft,
        title="Tischlampe",
        condition="gut",
        description="Voll funktionsfähig",
        included_items="Kabel",
        brand="NoName",
        model="L1",
        subtitle="Metall",
        category_suggestion="1234",
        hints="",
        confirm_fields=[],
        action="confirm",
    )

    assert draft.workflow.status is WorkflowStatus.DRAFT
    assert draft.workflow.needs_review is False
    assert draft.workflow.missing_information == []


def test_review_save_marks_review_needed_without_changing_lifecycle_status():
    draft = build_draft(with_images=False)

    update_draft_from_review(
        draft,
        title="Tischlampe",
        condition="gut",
        description="Voll funktionsfähig",
        included_items="Kabel",
        brand="NoName",
        model="L1",
        subtitle="Metall",
        category_suggestion="1234",
        hints="",
        confirm_fields=[],
        action="save",
    )

    assert draft.workflow.status is WorkflowStatus.DRAFT
    assert draft.workflow.needs_review is True
    assert draft.workflow.missing_information == []


def test_review_preserves_field_source_when_value_is_unchanged():
    draft = build_draft()
    draft.listing.title = "Tischlampe"
    draft.listing.condition = "gut"
    draft.listing.included_items = ["Tischlampe", "Kabel"]
    draft.listing.attributes["fieldSources"] = {
        "title": "KI",
        "condition": "Eingabe",
        "description": "KI",
        "included_items": "KI",
    }
    draft.source.notes = "Voll funktionsfähig"

    update_draft_from_review(
        draft,
        title="Tischlampe",
        condition="gut",
        description="Voll funktionsfähig",
        included_items="Tischlampe\nKabel",
        brand="NoName",
        model="L1",
        subtitle="Metall",
        category_suggestion="1234",
        hints="",
        confirm_fields=[],
        action="confirm",
    )

    assert draft.listing.attributes["fieldSources"]["title"] == "KI"
    assert draft.listing.attributes["fieldSources"]["condition"] == "Eingabe"
    assert draft.listing.attributes["fieldSources"]["description"] == "KI"
    assert draft.listing.attributes["fieldSources"]["brand"] == "Bearbeitet"


def test_review_exposes_and_updates_product_data_used_by_live_preview():
    draft = build_draft()
    draft.listing.attributes["product_identifier_type"] = "Modell-Nummer"
    draft.listing.attributes["product_identifier_value"] = "ABC-123"
    draft.listing.attributes["keyTechnicalDetails"] = ["Bluetooth: 5.3", "Anschlüsse: 2x HDMI, 1x DisplayPort"]

    values = get_review_form_values(draft)

    assert values["product_identifier_type"] == "Modell-Nummer"
    assert values["product_identifier_value"] == "ABC-123"
    assert values["key_technical_details"] == "Bluetooth: 5.3\nAnschlüsse: 2x HDMI, 1x DisplayPort"

    update_draft_from_review(
        draft,
        title="Soundbar",
        condition="gebraucht",
        description="Funktioniert.",
        included_items="Netzkabel",
        brand="Acme",
        model="S1",
        subtitle="",
        category_suggestion="14990",
        hints="",
        product_identifier_type="EAN",
        product_identifier_value="1234567890123",
        key_technical_details="Bluetooth: 5.4\nAnschlüsse: 2x HDMI, 1x DisplayPort",
        confirm_fields=[],
        action="save",
    )

    assert draft.listing.attributes["product_identifier_type"] == "EAN"
    assert draft.listing.attributes["product_identifier_value"] == "1234567890123"
    assert draft.listing.attributes["keyTechnicalDetails"] == [
        "Bluetooth: 5.4",
        "Anschlüsse: 2x HDMI, 1x DisplayPort",
    ]
    assert draft.listing.attributes["fieldSources"]["product_identifier"] == "Bearbeitet"
    assert draft.listing.attributes["fieldSources"]["key_technical_details"] == "Bearbeitet"


def test_field_sources_backfill_product_data_from_legacy_vision_draft():
    draft = build_draft()
    draft.listing.attributes["analysis"] = {"performed": True, "mode": "vision"}
    draft.listing.attributes["product_identifier_type"] = "Modell-Nummer"
    draft.listing.attributes["product_identifier_value"] = "ABC-123"
    draft.listing.attributes["keyTechnicalDetails"] = ["Bluetooth"]

    sources = get_field_sources(draft)

    assert sources["product_identifier"] == "KI"
    assert sources["key_technical_details"] == "KI"
