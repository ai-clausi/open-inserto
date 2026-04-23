from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings
from app.drafts.models import Draft, ListingData, WorkflowStatus
from app.drafts.rendering import render_listing_description
from app.drafts.vision import OpenAIVisionAnalyzerClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DraftAnalysisResult:
    listing: ListingData
    workflow_status: WorkflowStatus
    needs_review: bool = True
    missing_information: list[str] | None = None
    confidence_notes: list[str] | None = None

    def __post_init__(self) -> None:
        if self.missing_information is None:
            self.missing_information = []
        if self.confidence_notes is None:
            self.confidence_notes = []


class DraftAnalysisService(Protocol):
    def analyze(self, draft: Draft) -> DraftAnalysisResult: ...


class HeuristicDraftAnalysisService:
    def analyze(self, draft: Draft) -> DraftAnalysisResult:
        user_input = draft.source.user_input
        notes = draft.source.notes.strip()

        product_name = _clean_text(user_input.get("product_name"))
        condition = _clean_text(user_input.get("condition"))
        accessories = _split_lines_or_csv(user_input.get("accessories"))
        issues = _collect_issues(user_input.get("hints"), notes)

        missing_information: list[str] = []
        confidence_notes: list[str] = [
            "MVP-Heuristik: Vorschläge basieren nur auf Zusatzinfos und vorhandenen Bildern, nicht auf echter Bildanalyse.",
        ]

        if not product_name:
            missing_information.append("Produktname unklar")
        if not condition:
            missing_information.append("Zustand fehlt")
        if not notes and not issues:
            missing_information.append("Beschreibung unvollständig")

        if not accessories:
            confidence_notes.append("Zubehör wurde nicht sicher erkannt und bleibt leer, bis es bestätigt wird.")
        if draft.source.images:
            confidence_notes.append(
                f"{len(draft.source.images)} Bild(er) liegen vor, wurden aber im MVP noch nicht inhaltlich ausgewertet."
            )

        listing = ListingData(
            title=product_name,
            condition=condition,
            includedItems=accessories,
            issues=issues,
            descriptionHtml="",
        )

        if not draft.source.images or (not product_name and not notes):
            workflow_status = WorkflowStatus.BLOCKED
        elif missing_information:
            workflow_status = WorkflowStatus.NEEDS_ATTENTION
        else:
            workflow_status = WorkflowStatus.READY_FOR_REVIEW

        rendered_draft = draft.model_copy(deep=True)
        rendered_draft.listing = listing.model_copy(deep=True)
        listing.description_html = render_listing_description(rendered_draft)

        return DraftAnalysisResult(
            listing=listing,
            workflow_status=workflow_status,
            needs_review=True,
            missing_information=missing_information,
            confidence_notes=confidence_notes,
        )


class VisionDraftAnalysisService:
    def __init__(self, *, client: Any, project_dir: Path) -> None:
        self.client = client
        self.project_dir = project_dir

    def analyze(self, draft: Draft) -> DraftAnalysisResult:
        image_payloads = self._build_image_payloads(draft)
        payload = self.client.analyze(
            notes=draft.source.notes,
            user_input=draft.source.user_input,
            image_payloads=image_payloads,
        )

        missing_information = _normalize_string_list(payload.get("missingInformation"))
        confidence_notes = _normalize_string_list(payload.get("confidenceNotes"))
        issues = _collect_issues(payload.get("issues"), draft.source.user_input.get("hints"), draft.source.notes)

        listing = ListingData(
            title=_clean_text(payload.get("title")) or _clean_text(draft.source.user_input.get("product_name")),
            condition=_clean_text(payload.get("condition")) or _clean_text(draft.source.user_input.get("condition")),
            brand=_clean_text(payload.get("brand")),
            model=_clean_text(payload.get("model")),
            categorySuggestion=_clean_text(payload.get("categorySuggestion")),
            includedItems=_normalize_string_list(payload.get("includedItems"))
            or _split_lines_or_csv(draft.source.user_input.get("accessories")),
            issues=issues,
            descriptionHtml="",
        )

        if not listing.title:
            missing_information.append("Produktname unklar")
        if not listing.condition:
            missing_information.append("Zustand fehlt")
        if not draft.source.images:
            missing_information.append("Keine Bilder vorhanden")

        confidence_level = _clean_text(payload.get("confidenceLevel")).lower() or "low"
        if confidence_level == "low" or missing_information:
            workflow_status = WorkflowStatus.NEEDS_ATTENTION
        else:
            workflow_status = WorkflowStatus.READY_FOR_REVIEW

        if not draft.source.images or (not listing.title and not draft.source.notes):
            workflow_status = WorkflowStatus.BLOCKED

        confidence_notes = list(dict.fromkeys(confidence_notes))
        confidence_notes.append(
            f"KI-/Vision-Analyzer verwendet ({self.client.__class__.__name__}, Confidence: {confidence_level})."
        )

        rendered_draft = draft.model_copy(deep=True)
        rendered_draft.listing = listing.model_copy(deep=True)
        listing.description_html = render_listing_description(rendered_draft)

        return DraftAnalysisResult(
            listing=listing,
            workflow_status=workflow_status,
            needs_review=True,
            missing_information=list(dict.fromkeys(missing_information)),
            confidence_notes=confidence_notes,
        )

    def _build_image_payloads(self, draft: Draft) -> list[dict[str, str]]:
        image_payloads: list[dict[str, str]] = []
        for image in draft.source.images:
            image_path = Path(image.storage_path)
            if not image_path.is_absolute():
                image_path = self.project_dir / image_path
            if not image_path.exists():
                raise FileNotFoundError(f"Bilddatei nicht gefunden: {image_path}")
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            mime_type = image.mime_type or "image/jpeg"
            image_payloads.append({"image_url": f"data:{mime_type};base64,{encoded}"})
        return image_payloads


class ConfiguredDraftAnalysisService:
    def __init__(self, primary: DraftAnalysisService, fallback: DraftAnalysisService | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    def analyze(self, draft: Draft) -> DraftAnalysisResult:
        try:
            return self.primary.analyze(draft)
        except Exception as exc:
            if self.fallback is None:
                raise
            logger.warning("Primary draft analyzer failed, falling back to heuristic analyzer: %s", exc)
            analysis = self.fallback.analyze(draft)
            analysis.confidence_notes = list(analysis.confidence_notes or [])
            analysis.confidence_notes.append(
                f"KI-/Vision-Analyzer nicht verfügbar, Fallback auf Heuristik verwendet: {exc}"
            )
            return analysis


def build_draft_analysis_service(settings: Settings) -> DraftAnalysisService:
    heuristic = HeuristicDraftAnalysisService()
    backend = settings.draft_analysis_backend

    if backend == "heuristic":
        return heuristic

    vision_service = VisionDraftAnalysisService(
        client=OpenAIVisionAnalyzerClient(
            api_key=settings.vision_api_key,
            model=settings.vision_model,
            timeout_seconds=settings.vision_timeout_seconds,
        ),
        project_dir=settings.project_dir,
    )

    if backend == "vision":
        return ConfiguredDraftAnalysisService(primary=vision_service, fallback=heuristic)

    if settings.has_vision_config:
        return ConfiguredDraftAnalysisService(primary=vision_service, fallback=heuristic)

    return heuristic


def apply_analysis_result(draft: Draft, analysis: DraftAnalysisResult) -> Draft:
    draft.listing = analysis.listing
    draft.workflow.status = analysis.workflow_status
    draft.workflow.needs_review = analysis.needs_review
    draft.workflow.missing_information = list(analysis.missing_information or [])
    draft.workflow.last_updated_at = draft.workflow.last_updated_at

    confidence_notes = list(analysis.confidence_notes or [])
    if confidence_notes:
        draft.listing.attributes["confidenceNotes"] = confidence_notes
    else:
        draft.listing.attributes.pop("confidenceNotes", None)

    return draft


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _split_lines_or_csv(value: object) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []

    normalized = text.replace("\r", "\n")
    parts = [part.strip(" -•\t") for chunk in normalized.split("\n") for part in chunk.split(",")]
    return [part for part in parts if part]


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            text = _clean_text(item)
            if text:
                normalized.append(text)
        return normalized
    return _split_lines_or_csv(value)


def _collect_issues(*values: object) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _normalize_string_list(value):
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            issues.append(item)
    return issues
