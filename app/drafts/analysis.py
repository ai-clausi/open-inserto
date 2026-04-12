from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.drafts.models import Draft, ListingData, WorkflowStatus
from app.drafts.rendering import render_listing_description


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


def _collect_issues(*values: object) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _split_lines_or_csv(value):
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            issues.append(item)
    return issues

