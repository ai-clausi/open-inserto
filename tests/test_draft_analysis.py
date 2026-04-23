from pathlib import Path

from app.drafts.analysis import (
    HeuristicDraftAnalysisService,
    VisionDraftAnalysisService,
    apply_analysis_result,
    build_draft_analysis_service,
)
from app.drafts.models import Draft, WorkflowStatus


class StubVisionClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    def analyze(self, *, notes: str, user_input: dict, image_payloads: list[dict[str, str]]) -> dict:
        self.calls.append(
            {
                "notes": notes,
                "user_input": user_input,
                "image_payloads": image_payloads,
            }
        )
        return self.payload


class FailingVisionClient:
    def analyze(self, *, notes: str, user_input: dict, image_payloads: list[dict[str, str]]) -> dict:
        raise RuntimeError("provider down")


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


def write_image(project_dir: Path) -> None:
    image_path = project_dir / "data/drafts/draft_test1234/images/normalized/01-normalized.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"fake-image-bytes")


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
    assert analysis.workflow_status == WorkflowStatus.READY_FOR_REVIEW
    assert analysis.missing_information == []
    assert "MVP-Heuristik" in analysis.confidence_notes[0]


def test_heuristic_analysis_marks_missing_core_information():
    service = HeuristicDraftAnalysisService()
    draft = build_draft(user_input={"hints": "Funktionsstatus unklar"})

    analysis = service.analyze(draft)

    assert analysis.workflow_status == WorkflowStatus.BLOCKED
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


def test_vision_analysis_maps_structured_payload_and_uses_notes_and_images(tmp_path: Path):
    write_image(tmp_path)
    client = StubVisionClient(
        {
            "title": "Nintendo Switch OLED",
            "condition": "gebraucht",
            "brand": "Nintendo",
            "model": "OLED",
            "includedItems": ["Dock", "Netzteil"],
            "issues": ["leichte Gebrauchsspuren"],
            "categorySuggestion": "Spielkonsole",
            "missingInformation": [],
            "confidenceNotes": ["Seriennummer auf Bildern nicht sichtbar"],
            "confidenceLevel": "medium",
        }
    )
    service = VisionDraftAnalysisService(client=client, project_dir=tmp_path)
    draft = build_draft(
        user_input={
            "product_name": "Switch",
            "condition": "gebraucht",
            "accessories": "Dock",
            "hints": "Originalkarton fehlt",
        },
        notes="OLED-Modell mit Netzteil",
    )

    analysis = service.analyze(draft)

    assert analysis.listing.title == "Nintendo Switch OLED"
    assert analysis.listing.brand == "Nintendo"
    assert analysis.listing.model == "OLED"
    assert analysis.listing.category_suggestion == "Spielkonsole"
    assert analysis.listing.included_items == ["Dock", "Netzteil"]
    assert analysis.listing.issues == ["leichte Gebrauchsspuren", "Originalkarton fehlt", "OLED-Modell mit Netzteil"]
    assert analysis.workflow_status == WorkflowStatus.READY_FOR_REVIEW
    assert client.calls[0]["notes"] == "OLED-Modell mit Netzteil"
    assert client.calls[0]["user_input"]["hints"] == "Originalkarton fehlt"
    assert client.calls[0]["image_payloads"][0]["image_url"].startswith("data:image/jpeg;base64,")
    assert "KI-/Vision-Analyzer verwendet" in analysis.confidence_notes[-1]


def test_build_draft_analysis_service_falls_back_to_heuristic_when_vision_fails(tmp_path: Path):
    write_image(tmp_path)

    class SettingsStub:
        draft_analysis_backend = "vision"
        has_vision_config = True
        vision_api_key = "test-key"
        vision_model = "gpt-test"
        vision_timeout_seconds = 1.0
        project_dir = tmp_path

    draft = build_draft(user_input={"product_name": "Kamera", "hints": "Akku fehlt"})
    service = build_draft_analysis_service(SettingsStub())
    service.primary = VisionDraftAnalysisService(client=FailingVisionClient(), project_dir=tmp_path)

    analysis = service.analyze(draft)

    assert analysis.listing.title == "Kamera"
    assert analysis.workflow_status == WorkflowStatus.NEEDS_ATTENTION
    assert any("Fallback auf Heuristik" in note for note in analysis.confidence_notes)
