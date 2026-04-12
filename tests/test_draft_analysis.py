from app.drafts.analysis import HeuristicDraftAnalysisService, apply_analysis_result
from app.drafts.models import Draft, WorkflowStatus


def build_draft(*, user_input: dict[str, str] | None = None, notes: str = "") -> Draft:
    return Draft(
        id="draft_test1234",
        sku="OIN-TEST1234",
        source={
            "images": [
                {
                    "id": "img_1",
                    "originalFilename": "front.jpg",
                    "storagePath": "data/drafts/draft_test1234/images/normalized/01-normalized.jpg",
                    "mimeType": "image/jpeg",
                    "order": 1,
                    "kind": "normalized",
                }
            ],
            "notes": notes,
            "userInput": user_input or {},
        },
    )


def test_heuristic_analysis_maps_known_fields_into_listing():
    service = HeuristicDraftAnalysisService()
    draft = build_draft(
        user_input={
            "product_name": "Nintendo Switch",
            "condition": "gebraucht",
            "accessories": "Dock, Netzteil",
            "hints": "kleiner Kratzer",
        },
        notes="Display funktioniert gut",
    )

    analysis = service.analyze(draft)

    assert analysis.listing.title == "Nintendo Switch"
    assert analysis.listing.condition == "gebraucht"
    assert analysis.listing.included_items == ["Dock", "Netzteil"]
    assert analysis.listing.issues == ["kleiner Kratzer", "Display funktioniert gut"]
    assert analysis.workflow_status == WorkflowStatus.CLASSIFIED
    assert analysis.missing_information == []
    assert "MVP-Heuristik" in analysis.confidence_notes[0]


def test_heuristic_analysis_marks_missing_core_information():
    service = HeuristicDraftAnalysisService()
    draft = build_draft(user_input={"hints": "Funktionsstatus unklar"})

    analysis = service.analyze(draft)

    assert analysis.workflow_status == WorkflowStatus.NEEDS_ATTENTION
    assert analysis.needs_review is True
    assert "Produktname unklar" in analysis.missing_information
    assert "Zustand fehlt" in analysis.missing_information
    assert analysis.listing.title == ""
    assert analysis.listing.condition == ""


def test_apply_analysis_result_updates_draft_fields():
    service = HeuristicDraftAnalysisService()
    draft = build_draft(
        user_input={
            "product_name": "Kamera",
            "hints": "Akku fehlt",
        }
    )

    analysis = service.analyze(draft)
    updated = apply_analysis_result(draft, analysis)

    assert updated.listing.title == "Kamera"
    assert updated.workflow.status == WorkflowStatus.NEEDS_ATTENTION
    assert updated.workflow.missing_information == ["Zustand fehlt"]
    assert "confidenceNotes" in updated.listing.attributes
