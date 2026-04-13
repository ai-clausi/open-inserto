from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from app.drafts.analysis import _collect_issues, _split_lines_or_csv
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.rendering import render_listing_description

ReviewState = Literal["ready", "needs_attention", "blocked"]

CORE_FIELDS: dict[str, str] = {
    "title": "Titel / Produktname",
    "condition": "Zustand",
    "description_html": "Beschreibung",
    "included_items": "Zubehör",
}

OPTIONAL_FIELDS: dict[str, str] = {
    "brand": "Marke",
    "model": "Modell",
    "subtitle": "Untertitel",
    "category_suggestion": "Kategorie-Vorschlag",
}


def evaluate_review_state(draft: Draft) -> ReviewState:
    missing = get_missing_core_fields(draft)
    if is_blocked(draft):
        return "blocked"
    if missing or get_confidence_notes(draft):
        return "needs_attention"
    return "ready"


def get_missing_core_fields(draft: Draft) -> list[str]:
    review = get_review_metadata(draft)
    confirmed = {field for field in review.get("confirmedFields", []) if isinstance(field, str)}
    missing: list[str] = []

    checks = {
        "title": draft.listing.title.strip(),
        "condition": draft.listing.condition.strip(),
        "description_html": _plain_description_text(draft).strip(),
        "included_items": ", ".join(item.strip() for item in draft.listing.included_items if item.strip()),
    }

    for field, label in CORE_FIELDS.items():
        if checks[field] or field in confirmed:
            continue
        missing.append(label)

    return missing


def get_confidence_notes(draft: Draft) -> list[str]:
    notes = draft.listing.attributes.get("confidenceNotes", [])
    return [note for note in notes if isinstance(note, str) and note.strip()]


def get_review_metadata(draft: Draft) -> dict[str, Any]:
    review = draft.listing.attributes.get("review")
    return review if isinstance(review, dict) else {}


def update_draft_from_review(
    draft: Draft,
    *,
    title: str,
    condition: str,
    description: str,
    included_items: str,
    brand: str,
    model: str,
    subtitle: str,
    category_suggestion: str,
    hints: str,
    confirm_fields: list[str],
    action: str,
) -> Draft:
    draft.listing.title = title.strip()
    draft.listing.condition = condition.strip()
    draft.listing.brand = brand.strip()
    draft.listing.model = model.strip()
    draft.listing.subtitle = subtitle.strip()
    draft.listing.category_suggestion = category_suggestion.strip()
    draft.listing.included_items = _split_lines_or_csv(included_items)
    draft.listing.issues = _collect_issues(hints)

    draft.source.user_input.update(
        {
            "product_name": draft.listing.title,
            "condition": draft.listing.condition,
            "accessories": included_items.strip(),
            "hints": hints.strip(),
        }
    )
    draft.source.notes = description.strip()
    draft.listing.description_html = render_listing_description(draft)

    missing = get_missing_core_fields(draft)
    state = evaluate_review_state(draft)

    review_metadata = {
        "confirmedFields": sorted({field for field in confirm_fields if field in CORE_FIELDS}),
        "reviewDecision": "confirmed" if action == "confirm" else "saved",
        "reviewedAt": datetime.now(timezone.utc).isoformat(),
    }
    draft.listing.attributes["review"] = review_metadata
    draft.workflow.missing_information = missing

    if action == "confirm" and state != "blocked":
        draft.workflow.status = WorkflowStatus.READY_FOR_MARKETPLACE
        draft.workflow.needs_review = False
    elif state == "blocked":
        draft.workflow.status = WorkflowStatus.BLOCKED
        draft.workflow.needs_review = True
    elif state == "needs_attention":
        draft.workflow.status = WorkflowStatus.NEEDS_ATTENTION
        draft.workflow.needs_review = True
    else:
        draft.workflow.status = WorkflowStatus.READY_FOR_REVIEW
        draft.workflow.needs_review = True

    return draft


def is_blocked(draft: Draft) -> bool:
    has_images = bool(draft.source.images)
    has_title = bool(draft.listing.title.strip())
    has_description = bool(_plain_description_text(draft).strip())
    return not has_images or (not has_title and not has_description)


def _plain_description_text(draft: Draft) -> str:
    return draft.source.notes or ""
