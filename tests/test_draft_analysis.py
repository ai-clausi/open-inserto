from pathlib import Path
import base64
from io import BytesIO
import json

from PIL import Image

from app.drafts.analysis import (
    VISION_IMAGE_DETAIL,
    VISION_IMAGE_MAX_SIDE,
    VISION_MAX_IMAGES,
    HeuristicDraftAnalysisService,
    VisionDraftAnalysisService,
    apply_analysis_result,
    build_draft_analysis_service,
)
from app.drafts.models import Draft, SourceImage, WorkflowStatus
from app.drafts.vision import _extract_structured_output


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


def build_draft_with_images(count: int) -> Draft:
    draft = build_draft()
    draft.source.images = [
        SourceImage(
            id=f"img_{index}",
            originalFilename=f"front-{index}.jpg",
            storagePath=f"data/drafts/draft_test1234/images/normalized/{index:02d}-normalized.jpg",
            mimeType="image/jpeg",
            order=index,
            kind="normalized",
        )
        for index in range(1, count + 1)
    ]
    return draft


def write_image(project_dir: Path) -> None:
    image_path = project_dir / "data/drafts/draft_test1234/images/normalized/01-normalized.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (2400, 1600), color=(120, 160, 210))
    image.save(image_path, format="JPEG", quality=92)


def write_images(project_dir: Path, count: int) -> None:
    for index in range(1, count + 1):
        image_path = project_dir / f"data/drafts/draft_test1234/images/normalized/{index:02d}-normalized.jpg"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (2400, 1600), color=(120, 160, 210))
        image.save(image_path, format="JPEG", quality=92)


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
    assert analysis.listing.included_items == ["Nintendo Switch", "Dock", "Netzteil"]
    assert analysis.listing.issues == ["kleiner Kratzer"]
    assert analysis.missing_information == []
    assert "MVP-Heuristik" in analysis.confidence_notes[0]


def test_analysis_rephrases_image_analysis_language_in_listing_issues():
    service = HeuristicDraftAnalysisService()
    draft = build_draft(
        user_input={
            "product_name": "Bose SoundTouch 10",
            "condition": "gebraucht",
            "hints": "Keine Fernbedienung oder weiteres Zubehör erkennbar.",
        },
        notes="Wireless Music System",
    )

    analysis = service.analyze(draft)

    assert analysis.listing.issues == ["Fernbedienung und weiteres Zubehör sind nicht enthalten."]


def test_heuristic_analysis_marks_missing_core_information():
    service = HeuristicDraftAnalysisService()
    draft = build_draft(user_input={"hints": "Funktionsstatus unklar"})

    analysis = service.analyze(draft)

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
    assert updated.workflow.status == WorkflowStatus.DRAFT
    assert updated.workflow.missing_information == ["Zustand fehlt"]
    assert "confidenceNotes" in updated.listing.attributes
    assert updated.source.user_input["product_name"] == "Kamera"
    assert updated.source.user_input["hints"] == "Akku fehlt"


def test_vision_analysis_maps_structured_payload_and_uses_notes_and_images(tmp_path: Path):
    write_image(tmp_path)
    client = StubVisionClient(
        {
            "title": "Nintendo Switch OLED",
            "condition": "gebraucht",
            "description": "Nintendo Switch OLED in gebrauchtem, gepflegtem Zustand.",
            "brand": "Nintendo",
            "model": "OLED",
            "productIdentifierType": "EAN",
            "productIdentifierValue": "1234567890123",
            "keyTechnicalDetails": ["Bluetooth: 4.1", "WLAN: 802.11ac"],
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
    assert analysis.listing.attributes["product_identifier_type"] == "EAN"
    assert analysis.listing.attributes["product_identifier_value"] == "1234567890123"
    assert analysis.listing.attributes["keyTechnicalDetails"] == ["Bluetooth: 4.1", "WLAN: 802.11ac"]
    assert analysis.listing.included_items == ["Nintendo Switch OLED", "Dock", "Netzteil"]
    assert analysis.listing.issues == ["leichte Gebrauchsspuren", "Originalkarton fehlt"]
    assert "Nintendo Switch OLED in gebrauchtem, gepflegtem Zustand." in analysis.listing.description_html
    assert "OLED-Modell mit Netzteil" not in analysis.listing.description_html
    assert analysis.description_text == "Nintendo Switch OLED in gebrauchtem, gepflegtem Zustand."
    assert client.calls[0]["notes"] == "OLED-Modell mit Netzteil"
    assert client.calls[0]["user_input"]["hints"] == "Originalkarton fehlt"
    assert client.calls[0]["image_payloads"][0]["image_url"].startswith("data:image/jpeg;base64,")
    assert client.calls[0]["image_payloads"][0]["detail"] == VISION_IMAGE_DETAIL
    encoded = client.calls[0]["image_payloads"][0]["image_url"].split(",", 1)[1]
    resized = Image.open(BytesIO(base64.b64decode(encoded)))
    assert max(resized.size) == VISION_IMAGE_MAX_SIDE
    assert "KI-/Vision-Analyzer verwendet" in analysis.confidence_notes[-1]


def test_vision_analysis_limits_number_of_images_and_uses_configured_image_settings(tmp_path: Path):
    write_images(tmp_path, 6)
    client = StubVisionClient(
        {
            "title": "Kamera",
            "condition": "gebraucht",
            "description": "Kamera in gebrauchtem Zustand.",
            "brand": "",
            "model": "",
            "productIdentifierType": "",
            "productIdentifierValue": "",
            "keyTechnicalDetails": [],
            "includedItems": [],
            "issues": [],
            "categorySuggestion": "",
            "missingInformation": [],
            "confidenceNotes": [],
            "confidenceLevel": "medium",
        }
    )
    service = VisionDraftAnalysisService(
        client=client,
        project_dir=tmp_path,
        image_max_side=768,
        image_quality=60,
        image_detail="low",
        max_images=2,
    )
    draft = build_draft_with_images(6)

    service.analyze(draft)

    payloads = client.calls[0]["image_payloads"]
    assert len(payloads) == 2
    assert all(payload["detail"] == "low" for payload in payloads)
    encoded = payloads[0]["image_url"].split(",", 1)[1]
    resized = Image.open(BytesIO(base64.b64decode(encoded)))
    assert max(resized.size) == 768


def test_build_draft_analysis_service_falls_back_to_heuristic_when_vision_fails(tmp_path: Path):
    write_image(tmp_path)

    class SettingsStub:
        draft_analysis_backend = "vision"
        has_vision_config = True
        vision_api_key = "test-key"
        vision_model = "gpt-test"
        vision_timeout_seconds = 1.0
        vision_image_max_side = VISION_IMAGE_MAX_SIDE
        vision_image_quality = 72
        vision_image_detail = VISION_IMAGE_DETAIL
        vision_max_images = VISION_MAX_IMAGES
        project_dir = tmp_path

    draft = build_draft(user_input={"product_name": "Kamera", "hints": "Akku fehlt"})
    service = build_draft_analysis_service(SettingsStub())
    service.primary = VisionDraftAnalysisService(client=FailingVisionClient(), project_dir=tmp_path)

    analysis = service.analyze(draft)

    assert analysis.listing.title == "Kamera"
    assert any("Fallback auf Heuristik" in note for note in analysis.confidence_notes)


def test_extract_structured_output_prefers_top_level_output_parsed():
    payload = {"output_parsed": {"title": "Switch OLED", "condition": "gebraucht"}}

    extracted = _extract_structured_output(payload)

    assert extracted == {"title": "Switch OLED", "condition": "gebraucht"}


def test_extract_structured_output_falls_back_to_output_text_json():
    payload = {
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"title": "Steam Deck", "condition": "sehr gut"}),
                    }
                ]
            }
        ]
    }

    extracted = _extract_structured_output(payload)

    assert extracted == {"title": "Steam Deck", "condition": "sehr gut"}
