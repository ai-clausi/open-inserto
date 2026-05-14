from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from app.drafts.analysis import _collect_issues, _split_lines_or_csv
from app.drafts.included_items import normalize_included_items
from app.drafts.models import Draft
from app.drafts.rendering import render_listing_description

ReviewState = Literal["ready", "needs_attention", "blocked"]

CORE_FIELDS: dict[str, str] = {
    "title": "Titel / Produktname",
    "condition": "Zustand",
    "description_html": "Beschreibung",
    "included_items": "Lieferumfang",
}

OPTIONAL_FIELDS: dict[str, str] = {
    "brand": "Marke",
    "model": "Modell",
    "subtitle": "Untertitel",
    "category_suggestion": "eBay-Kategorie",
    "product_identifier": "Produktkennung",
    "key_technical_details": "Relevante Details",
}


def evaluate_review_state(draft: Draft) -> ReviewState:
    missing = get_missing_core_fields(draft)
    if is_blocked(draft):
        return "blocked"
    if missing:
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
        "included_items": ", ".join(normalize_included_items(draft.listing.title, draft.listing.included_items)),
    }

    for field, label in CORE_FIELDS.items():
        if checks[field] or field in confirmed:
            continue
        missing.append(label)

    return missing


def get_confidence_notes(draft: Draft) -> list[str]:
    notes = draft.listing.attributes.get("confidenceNotes", [])
    return [note for note in notes if isinstance(note, str) and note.strip()]


def get_analysis_metadata(draft: Draft) -> dict[str, Any]:
    metadata = draft.listing.attributes.get("analysis")
    return metadata if isinstance(metadata, dict) else {}


def get_field_sources(draft: Draft) -> dict[str, str]:
    metadata = draft.listing.attributes.get("fieldSources")
    if not isinstance(metadata, dict):
        sources: dict[str, str] = {}
    else:
        sources = {str(key): str(value) for key, value in metadata.items() if str(value).strip()}

    analysis = get_analysis_metadata(draft)
    if str(analysis.get("mode") or "").strip().lower() == "vision":
        if _product_identifier_form_value(draft.listing.attributes):
            sources.setdefault("product_identifier", "KI")
        if _string_list_attribute(draft.listing.attributes, "keyTechnicalDetails"):
            sources.setdefault("key_technical_details", "KI")
    return sources


def get_original_input(draft: Draft) -> dict[str, Any]:
    original_input = draft.listing.attributes.get("originalInput")
    if isinstance(original_input, dict):
        return original_input
    return {
        "notes": draft.source.notes.strip(),
        "userInput": dict(draft.source.user_input),
    }


def get_analysis_state(draft: Draft) -> dict[str, str | bool]:
    metadata = get_analysis_metadata(draft)
    if metadata.get("performed") is True:
        mode = str(metadata.get("mode") or "").strip().lower() or "heuristic"
        label = str(metadata.get("label") or "").strip() or "Analyse durchgeführt"
    else:
        notes = get_confidence_notes(draft)
        if any("KI-/Vision-Analyzer verwendet" in note for note in notes):
            mode = "vision"
            label = "KI-Analyse durchgeführt"
        elif notes:
            mode = "heuristic"
            label = "Basisanalyse durchgeführt"
        else:
            return {"performed": False, "mode": "none", "label": "Keine Analyse hinterlegt", "tone": "muted"}

    if mode == "vision":
        tone = "success"
    elif mode in {"heuristic", "fallback"}:
        tone = "info"
    else:
        tone = "muted"
    return {"performed": True, "mode": mode, "label": label, "tone": tone}


def get_review_form_values(draft: Draft) -> dict[str, str]:
    attributes = draft.listing.attributes
    return {
        "description": draft.source.notes.strip(),
        "included_items": "\n".join(item.strip() for item in draft.listing.included_items if item.strip()),
        "hints": "\n".join(item.strip() for item in draft.listing.issues if item.strip()),
        "product_identifier_type": _string_attribute(attributes, "product_identifier_type"),
        "product_identifier_value": _string_attribute(attributes, "product_identifier_value"),
        "key_technical_details": "\n".join(_string_list_attribute(attributes, "keyTechnicalDetails")),
    }


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
    product_identifier_type: str = "",
    product_identifier_value: str = "",
    key_technical_details: str = "",
    confirm_fields: list[str] | None = None,
    action: str = "save",
) -> Draft:
    previous_values = {
        "title": draft.listing.title.strip(),
        "condition": draft.listing.condition.strip(),
        "description": draft.source.notes.strip(),
        "included_items": "\n".join(item.strip() for item in draft.listing.included_items if item.strip()),
        "brand": draft.listing.brand.strip(),
        "model": draft.listing.model.strip(),
        "category_suggestion": draft.listing.category_suggestion.strip(),
        "issues": "\n".join(item.strip() for item in draft.listing.issues if item.strip()),
        "product_identifier": _product_identifier_form_value(draft.listing.attributes),
        "key_technical_details": "\n".join(_string_list_attribute(draft.listing.attributes, "keyTechnicalDetails")),
    }
    previous_sources = get_field_sources(draft)

    draft.listing.title = title.strip()
    draft.listing.condition = condition.strip()
    draft.listing.brand = brand.strip()
    draft.listing.model = model.strip()
    draft.listing.subtitle = subtitle.strip()
    draft.listing.category_suggestion = category_suggestion.strip()
    explicit_included_items = _split_lines_or_csv(included_items)
    draft.listing.included_items = normalize_included_items(draft.listing.title, explicit_included_items)
    draft.listing.issues = _collect_issues(hints)
    _update_product_attributes(
        draft,
        product_identifier_type=product_identifier_type,
        product_identifier_value=product_identifier_value,
        key_technical_details=key_technical_details,
    )

    draft.source.user_input.update(
        {
            "product_name": draft.listing.title,
            "condition": draft.listing.condition,
            "accessories": "\n".join(explicit_included_items),
            "hints": hints.strip(),
        }
    )
    draft.source.notes = description.strip()
    draft.listing.description_html = render_listing_description(draft)
    current_values = {
        "title": draft.listing.title,
        "condition": draft.listing.condition,
        "description": draft.source.notes,
        "included_items": "\n".join(item.strip() for item in draft.listing.included_items if item.strip()),
        "brand": draft.listing.brand,
        "model": draft.listing.model,
        "category_suggestion": draft.listing.category_suggestion,
        "issues": "\n".join(item.strip() for item in draft.listing.issues if item.strip()),
        "product_identifier": _product_identifier_form_value(draft.listing.attributes),
        "key_technical_details": "\n".join(_string_list_attribute(draft.listing.attributes, "keyTechnicalDetails")),
    }
    draft.listing.attributes["fieldSources"] = {
        field: "Bearbeitet" if current_values[field].strip() != previous_values[field].strip() else previous_sources.get(field, "Entwurf")
        for field in current_values
    }

    review_metadata = {
        "confirmedFields": sorted({field for field in (confirm_fields or []) if field in CORE_FIELDS}),
        "reviewDecision": "confirmed" if action == "confirm" else "saved",
        "reviewedAt": datetime.now(timezone.utc).isoformat(),
    }
    draft.listing.attributes["review"] = review_metadata

    missing = get_missing_core_fields(draft)
    state = evaluate_review_state(draft)
    draft.workflow.missing_information = missing

    if state == "blocked":
        draft.workflow.needs_review = True
    elif state == "needs_attention":
        draft.workflow.needs_review = True
    else:
        draft.workflow.needs_review = False

    return draft


def is_blocked(draft: Draft) -> bool:
    has_images = bool(draft.source.images)
    has_title = bool(draft.listing.title.strip())
    has_description = bool(_plain_description_text(draft).strip())
    return not has_images or (not has_title and not has_description)


def _plain_description_text(draft: Draft) -> str:
    return draft.source.notes or ""


def _update_product_attributes(
    draft: Draft,
    *,
    product_identifier_type: str,
    product_identifier_value: str,
    key_technical_details: str,
) -> None:
    attributes = draft.listing.attributes
    identifier_type = product_identifier_type.strip()
    identifier_value = product_identifier_value.strip()
    if identifier_type and identifier_value:
        attributes["product_identifier_type"] = identifier_type
        attributes["product_identifier_value"] = identifier_value
    else:
        attributes.pop("product_identifier_type", None)
        attributes.pop("product_identifier_value", None)

    details = _split_lines(key_technical_details)
    if details:
        attributes["keyTechnicalDetails"] = details
    else:
        attributes.pop("keyTechnicalDetails", None)


def _product_identifier_form_value(attributes: dict[str, Any]) -> str:
    identifier_type = _string_attribute(attributes, "product_identifier_type")
    identifier_value = _string_attribute(attributes, "product_identifier_value")
    if not identifier_type and not identifier_value:
        return ""
    return f"{identifier_type}: {identifier_value}"


def _string_attribute(attributes: dict[str, Any], key: str) -> str:
    value = attributes.get(key)
    return value.strip() if isinstance(value, str) else ""


def _string_list_attribute(attributes: dict[str, Any], key: str) -> list[str]:
    value = attributes.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _split_lines(value: str) -> list[str]:
    normalized = value.replace("\r", "\n")
    parts = [part.strip(" -•\t") for part in normalized.split("\n")]
    return [part for part in parts if part]
