from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Protocol

from app.drafts.models import Draft, ListingData, WorkflowStatus


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
            descriptionHtml=_build_description_html(
                product_name=product_name,
                condition=condition,
                accessories=accessories,
                notes=notes,
                issues=issues,
                missing_information=missing_information,
                confidence_notes=confidence_notes,
            ),
        )

        workflow_status = (
            WorkflowStatus.NEEDS_ATTENTION if missing_information else WorkflowStatus.CLASSIFIED
        )

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


def _build_description_html(
    *,
    product_name: str,
    condition: str,
    accessories: list[str],
    notes: str,
    issues: list[str],
    missing_information: list[str],
    confidence_notes: list[str],
) -> str:
    sections: list[str] = []

    title = product_name or "Unbenannter Artikel"
    sections.append(f"<p><strong>{escape(title)}</strong></p>")

    details: list[str] = []
    if condition:
        details.append(f"<li><strong>Zustand:</strong> {escape(condition)}</li>")
    if accessories:
        details.append(
            "<li><strong>Zubehör:</strong> " + ", ".join(escape(item) for item in accessories) + "</li>"
        )
    if details:
        sections.append("<ul>" + "".join(details) + "</ul>")

    if notes:
        sections.append(f"<p><strong>Notizen:</strong> {escape(notes)}</p>")

    if issues:
        sections.append(
            "<p><strong>Hinweise / offene Punkte:</strong></p><ul>"
            + "".join(f"<li>{escape(item)}</li>" for item in issues)
            + "</ul>"
        )

    if missing_information:
        sections.append(
            "<p><strong>Fehlende Informationen:</strong></p><ul>"
            + "".join(f"<li>{escape(item)}</li>" for item in missing_information)
            + "</ul>"
        )

    if confidence_notes:
        sections.append(
            "<p><strong>Unsicherheiten:</strong></p><ul>"
            + "".join(f"<li>{escape(item)}</li>" for item in confidence_notes)
            + "</ul>"
        )

    return "".join(sections)
