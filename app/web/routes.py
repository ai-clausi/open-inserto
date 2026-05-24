from pathlib import Path
import re
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings
from app.drafts.analysis import apply_analysis_result, autofill_ebay_required_aspects, build_draft_analysis_service
from app.drafts.repository import DraftRepository
from app.drafts.models import WorkflowStatus
from app.drafts.rendering import refresh_listing_description
from app.drafts.review import (
    CORE_FIELDS,
    OPTIONAL_FIELDS,
    get_analysis_state,
    evaluate_review_state,
    get_confidence_notes,
    get_field_sources,
    get_missing_core_fields,
    get_original_input,
    get_review_form_values,
    get_review_metadata,
    update_draft_from_review,
)
from app.drafts.upload_service import DraftUploadService, UploadAsset, UploadValidationError
from app.marketplaces.ebay.service import EbayMarketplaceService
from app.marketplaces.ebay.auth import EbayAuthStore, build_auth_connect_url, has_usable_auth_tokens
from app.marketplaces.ebay.client import EbayApiError, EbayAuthError, EbayClient, EbayValidationError, normalize_search_text
from app.marketplaces.ebay.configuration import DEFAULT_SHIPPING_PROFILE, PAYMENT_POLICY_NAME, RETURN_POLICY_NAME, SHIPPING_PROFILES, EbayConfigStore, normalize_shipping_profile
from app.marketplaces.ebay.taxonomy import get_category_resolution, get_optional_category_aspects, get_required_category_aspects, resolve_category_search_for_draft, resolve_category_suggestion_for_draft
from app.marketplaces.ebay.validation import collect_marketplace_notes, collect_marketplace_readiness_errors

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


EXTRA_FIELDS = [
    ("product_name", "Produktname"),
    ("condition", "Zustand"),
    ("accessories", "Lieferumfang"),
    ("hints", "Hinweise"),
]


STATUS_LABELS = {
    WorkflowStatus.DRAFT: "Neu",
    WorkflowStatus.OFFER_CREATED: "eBay-Draft erstellt",
    WorkflowStatus.PUBLISHED: "Veröffentlicht",
    WorkflowStatus.ERROR: "Fehler",
}


@dataclass(slots=True)
class DraftDisplayStatus:
    value: str
    label: str
    tone: str


def build_draft_display_status(
    draft,
    *,
    marketplace_readiness_errors: list[str],
    review_state: str | None = None,
) -> DraftDisplayStatus:
    if review_state is None:
        review_state = evaluate_review_state(draft)

    if draft.marketplace.ebay.listing_id or draft.workflow.status is WorkflowStatus.PUBLISHED:
        return DraftDisplayStatus("published", "Bei eBay veröffentlicht", "success")
    if draft.marketplace.ebay.offer_id or draft.workflow.status is WorkflowStatus.OFFER_CREATED:
        return DraftDisplayStatus("offer_created", "eBay-Angebot vorbereitet", "success")
    if draft.workflow.status is WorkflowStatus.ERROR:
        return DraftDisplayStatus("error", "Fehler", "warning")

    if review_state == "blocked":
        return DraftDisplayStatus("blocked", "Blockiert", "warning")
    if review_state == "needs_attention":
        return DraftDisplayStatus("needs_attention", "Angaben ergänzen", "warning")

    ebay_error = str(draft.marketplace.ebay.offer_data.get("lastError") or "").strip()
    if marketplace_readiness_errors:
        if any("ist nicht konfiguriert" in item or "eBay ist noch nicht verbunden" in item for item in marketplace_readiness_errors):
            return DraftDisplayStatus("ebay_setup", "eBay einrichten", "warning")
        return DraftDisplayStatus("marketplace_attention", "eBay-Angaben ergänzen", "warning")
    if ebay_error:
        return DraftDisplayStatus("retry", "Erneut senden möglich", "neutral")
    return DraftDisplayStatus("ready_for_ebay", "Bereit für eBay", "success")


def review_status_label(review_state: str) -> str:
    if review_state == "ready":
        return "Kernangaben vollständig"
    if review_state == "blocked":
        return "Blockiert"
    return "Angaben ergänzen"


def build_context(request: Request, **extra):
    settings = get_settings()
    auth_store = _ebay_auth_store(settings)
    config_store = _ebay_config_store(settings)
    token_data = auth_store.get_tokens()
    ebay_auth_connected = has_usable_auth_tokens(token_data)
    effective_config = config_store.get_effective_configuration()
    discovered_resources = config_store.get_discovered_resources()
    ai_configuration_status = _build_ai_configuration_status(settings)
    context = {
        "request": request,
        "app_name": settings.app_name,
        "ebay_mode": settings.ebay_mode,
        "ebay_seller_hub_drafts_url": _ebay_seller_hub_drafts_url(settings),
        "database_url": settings.database_url,
        "draft_analysis_backend": settings.draft_analysis_backend,
        "ai_configuration_status": ai_configuration_status,
        "extra_fields": EXTRA_FIELDS,
        "ebay_auth_connected": ebay_auth_connected,
        "ebay_effective_config": effective_config,
        "ebay_discovered_resources": discovered_resources,
        "ebay_shipping_profile_setup": get_shipping_profile_setup(effective_config),
        "ebay_policy_management_opted_in": extra.get("ebay_policy_management_opted_in"),
    }
    context.update(extra)
    return context


def _ebay_auth_store(settings):
    return EbayAuthStore(settings.database_path, mode=settings.ebay_mode)


def _ebay_config_store(settings):
    return EbayConfigStore(settings.database_path, mode=settings.ebay_mode)


def _ebay_seller_hub_drafts_url(settings) -> str:
    if settings.ebay_mode == "live" and settings.ebay_marketplace_id == "EBAY_DE":
        return "https://www.ebay.de/sh/lst/drafts"
    if settings.ebay_mode == "live":
        return "https://www.ebay.com/sh/lst/drafts"
    return "https://www.sandbox.ebay.com/sh/lst/drafts"


def _ebay_listing_url(settings, listing_id: str | None) -> str | None:
    if not listing_id:
        return None
    if settings.ebay_mode == "live" and settings.ebay_marketplace_id == "EBAY_DE":
        return f"https://www.ebay.de/itm/{listing_id}"
    if settings.ebay_mode == "live":
        return f"https://www.ebay.com/itm/{listing_id}"
    return f"https://www.sandbox.ebay.com/itm/{listing_id}"


def get_selected_shipping_profile(draft) -> str:
    return normalize_shipping_profile(str(draft.listing.shipping_suggestion.get("profile") or ""))


def get_ebay_aspect_values(draft) -> dict[str, str]:
    values = draft.listing.attributes.get("ebayAspects")
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def get_ebay_aspect_metadata(draft) -> dict[str, dict[str, str]]:
    values = draft.listing.attributes.get("ebayAspectsMeta")
    if not isinstance(values, dict):
        return {}
    metadata: dict[str, dict[str, str]] = {}
    for key, value in values.items():
        name = str(key).strip()
        if not name or not isinstance(value, dict):
            continue
        metadata[name] = {str(inner_key): str(inner_value) for inner_key, inner_value in value.items()}
    return metadata


def update_ebay_aspects_from_form(draft, form: Any) -> None:
    existing = get_ebay_aspect_values(draft)
    updated = dict(existing)
    for key, value in form.multi_items():
        if not str(key).startswith("ebay_aspect__"):
            continue
        name = str(key).removeprefix("ebay_aspect__").strip()
        text = str(value).strip()
        if not name:
            continue
        if text:
            updated[name] = text
        else:
            updated.pop(name, None)
    if updated:
        draft.listing.attributes["ebayAspects"] = updated
    else:
        draft.listing.attributes.pop("ebayAspects", None)


def is_ebay_setup_error(message: str) -> bool:
    return "ist nicht konfiguriert" in message or "eBay ist noch nicht verbunden" in message


def is_ebay_item_error(message: str) -> bool:
    return message.startswith("Artikelmerkmal ") or "Kategorie" in message


def split_marketplace_errors(errors: list[str]) -> dict[str, list[str]]:
    setup_errors = [item for item in errors if is_ebay_setup_error(item)]
    item_errors = [item for item in errors if item not in setup_errors]
    return {"setup": setup_errors, "item": item_errors}


def should_open_ebay_details(category_resolution: dict[str, Any], required_category_aspects: list[dict[str, Any]], marketplace_errors: list[str]) -> bool:
    state = str(category_resolution.get("state") or "")
    if state in {"needs_selection", "no_match", "lookup_failed", "config_missing", "empty"}:
        return True
    if not str(category_resolution.get("selected_id") or "").strip():
        return True
    if required_category_aspects:
        return True
    return any(is_ebay_item_error(error) for error in marketplace_errors)


def get_shipping_profile_options(draft, effective_config) -> list[dict[str, object]]:
    selected = get_selected_shipping_profile(draft)
    options = []
    for key, profile in SHIPPING_PROFILES.items():
        options.append(
            {
                "key": key,
                "label": profile["label"],
                "description": profile["description"],
                "policy_id": effective_config.fulfillment_policy_id_for_profile(key),
                "selected": key == selected,
            }
        )
    return options


def get_shipping_profile_setup(effective_config) -> dict[str, object]:
    profiles = []
    missing = []
    for key, profile in SHIPPING_PROFILES.items():
        policy_id = effective_config.fulfillment_policy_id_for_profile(key)
        item = {
            "key": key,
            "label": profile["label"],
            "description": profile["description"],
            "policy_id": policy_id,
            "configured": bool(policy_id),
        }
        profiles.append(item)
        if not policy_id:
            missing.append(item)
    return {"profiles": profiles, "missing": missing, "complete": not missing}


def sync_shipping_profile_policy_ids(config_store: EbayConfigStore, resources) -> dict[str, str]:
    policy_ids = {
        key: policy_id
        for key, profile in SHIPPING_PROFILES.items()
        if (policy_id := _find_resource_id_by_name(resources.fulfillment_policies, profile["policy_name"]))
    }
    config_store.save_shipping_profile_policy_ids(policy_ids)
    return policy_ids


def _build_ai_configuration_status(settings) -> dict[str, object]:
    config_ready = settings.has_vision_config
    backend = settings.draft_analysis_backend

    if backend == "heuristic":
        mode_label = "Basisanalyse"
        detail = "Keine KI-Konfiguration erforderlich"
    elif backend == "vision":
        mode_label = "KI-Analyse"
        detail = "Vision-Provider ist fest aktiviert"
    elif config_ready:
        mode_label = "KI mit Fallback"
        detail = "Bei Ausfall wird auf Basisanalyse zurückgefallen"
    else:
        mode_label = "Basisanalyse"
        detail = "Ohne vollständige KI-Konfiguration bleibt die Basisanalyse aktiv"

    return {
        "config_ready": config_ready,
        "config_label": "Erfüllt" if config_ready else "Nicht erfüllt",
        "mode_label": mode_label,
        "detail": detail,
    }


def build_draft_result_summary(
    *,
    draft,
    review_state: str,
    ebay_auth_connected: bool,
    marketplace_readiness_errors: list[str],
) -> dict[str, object]:
    ebay_error = str(draft.marketplace.ebay.offer_data.get("lastError") or "").strip()

    if draft.marketplace.ebay.offer_id:
        return {
            "headline": "eBay-Angebot vorbereitet",
            "body": "Das Angebot wurde bei eBay vorbereitet. Prüfe die Angaben final in Open Inserto und veröffentliche es erst danach.",
            "tone": "success",
            "primary_action_label": "Weiter prüfen",
            "primary_action_target": "technical-details",
        }

    if not ebay_auth_connected:
        return {
            "headline": "eBay muss neu verbunden werden",
            "body": "Die Verbindung zu eBay fehlt oder ist nicht mehr gültig. Danach kannst du den Draft direkt erneut senden.",
            "tone": "warning",
            "primary_action_label": "eBay erneut verbinden",
            "primary_action_target": "ebay-connect",
        }

    if marketplace_readiness_errors:
        return {
            "headline": "Es fehlen noch Angaben",
            "body": "Bevor der eBay-Schritt laufen kann, sollte der Draft noch an den markierten Punkten vervollständigt werden.",
            "tone": "warning",
            "primary_action_label": "Angaben ergänzen",
            "primary_action_target": "review-form",
        }

    if ebay_error:
        return {
            "headline": "eBay hat den letzten Versuch abgelehnt",
            "body": "Der lokale Draft ist erhalten geblieben. Du kannst den Schritt nach der kurzen Prüfung direkt erneut ausführen.",
            "tone": "error",
            "primary_action_label": "Erneut senden",
            "primary_action_target": "ebay-send",
        }

    if review_state != "ready":
        return {
            "headline": "Bitte kurz prüfen",
            "body": "Die Kernangaben sind noch nicht vollständig bestätigt. Danach kann der Marketplace-Schritt folgen.",
            "tone": "info",
            "primary_action_label": "Review öffnen",
            "primary_action_target": "review-form",
        }

    return {
        "headline": "Bereit für den nächsten Schritt",
        "body": "Der Draft wirkt vollständig. Du kannst jetzt das eBay-Angebot per API vorbereiten.",
        "tone": "info",
        "primary_action_label": "eBay-Angebot vorbereiten",
        "primary_action_target": "ebay-send",
    }


ASSISTANT_FIELD_LABELS = {
    "title": "Produktname",
    "condition": "Zustand",
    "included_items": "Lieferumfang",
    "description_html": "Beschreibung",
    "category_suggestion": "eBay-Kategorie",
}


ASSISTANT_PLACEHOLDER_VALUES = {
    "",
    "unbekannt",
    "unknown",
    "n/a",
    "keine angabe",
    "nicht erkannt",
}


def _assistant_flow_state(draft) -> dict[str, Any]:
    state = draft.listing.attributes.get("assistantFlow")
    return state if isinstance(state, dict) else {}


def _assistant_flow_events(draft) -> list[dict[str, str]]:
    events = _assistant_flow_state(draft).get("events")
    if not isinstance(events, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        text = str(item.get("text") or "").strip()
        if role and text:
            normalized.append({"role": role, "text": text})
    return normalized


def _append_assistant_event(draft, *, role: str, text: str) -> None:
    if not text.strip():
        return
    state = _assistant_flow_state(draft)
    events = _assistant_flow_events(draft)
    events.append({"role": role, "text": text.strip()})
    state["events"] = events[-12:]
    draft.listing.attributes["assistantFlow"] = state


def _assistant_confirmed_fields(draft) -> set[str]:
    fields = _assistant_flow_state(draft).get("confirmedFields")
    if not isinstance(fields, list):
        return set()
    return {str(item).strip() for item in fields if str(item).strip()}


def _set_assistant_confirmed_fields(draft, fields: set[str]) -> None:
    state = _assistant_flow_state(draft)
    state["confirmedFields"] = sorted(field for field in fields if field)
    draft.listing.attributes["assistantFlow"] = state


def _assistant_aspect_field(aspect_name: str) -> str:
    return f"ebay_aspect::{aspect_name.strip()}"


def _assistant_aspect_name(field: str) -> str:
    return field.removeprefix("ebay_aspect::").strip()


def _assistant_field_value(draft, field: str) -> str:
    if field == "title":
        return draft.listing.title.strip()
    if field == "condition":
        return draft.listing.condition.strip()
    if field == "included_items":
        items = [item.strip() for item in draft.listing.included_items if item.strip()]
        if len(items) == 1 and _dedupe_text(items[0]) == _dedupe_text(draft.listing.title):
            return ""
        return "\n".join(items)
    if field == "description_html":
        return draft.source.notes.strip()
    return ""


def _dedupe_text(value: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", value.casefold()).strip()


def _assistant_field_label(field: str) -> str:
    if field in ASSISTANT_FIELD_LABELS:
        return ASSISTANT_FIELD_LABELS[field]
    if field.startswith("ebay_aspect::"):
        return _assistant_aspect_name(field)
    return field


def _assistant_field_prompt(field: str) -> str:
    prompts = {
        "title": "Ich habe einen Produktnamen erkannt. Passt der so für dein Angebot?",
        "condition": "Welchen Zustand soll ich festhalten?",
        "included_items": "Was gehört alles zum Lieferumfang?",
        "description_html": "So würde ich den Beschreibungstext aktuell formulieren. Passt das für dich?",
        "category_suggestion": "Welche eBay-Kategorie passt am besten?",
    }
    if field.startswith("ebay_aspect::"):
        return f"Für eBay fehlt noch { _assistant_aspect_name(field) }."
    return prompts.get(field, f"Bitte bestätige { _assistant_field_label(field).lower() }.")


def _assistant_value_is_placeholder(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in ASSISTANT_PLACEHOLDER_VALUES:
        return True
    return normalized.startswith("unbekannt ") or normalized.endswith(" unbekannt")


def _assistant_response_field_values(draft) -> dict[str, str]:
    review_values = get_review_form_values(draft)
    category_resolution = get_category_resolution(draft)
    return {
        "title": draft.listing.title.strip(),
        "condition": draft.listing.condition.strip(),
        "included_items": review_values["included_items"],
        "description_html": review_values["description"],
        "category_suggestion": str(category_resolution.get("selected_name") or draft.listing.category_suggestion or "").strip(),
        "category_suggestion_id": str(category_resolution.get("selected_id") or draft.listing.category_suggestion or "").strip(),
    }


def _update_single_assistant_field(draft, field: str, value: str) -> None:
    current_values = get_review_form_values(draft)
    title = draft.listing.title
    condition = draft.listing.condition
    description = current_values["description"]
    included_items = current_values["included_items"]
    category_suggestion = draft.listing.category_suggestion
    ebay_aspects = get_ebay_aspect_values(draft)

    if field == "title":
        title = value
    elif field == "condition":
        condition = value
    elif field == "description_html":
        description = value
    elif field == "included_items":
        included_items = value
    elif field == "category_suggestion":
        category_suggestion = value
    elif field.startswith("ebay_aspect::"):
        aspect_name = _assistant_aspect_name(field)
        if value.strip():
            ebay_aspects[aspect_name] = value.strip()
        else:
            ebay_aspects.pop(aspect_name, None)

    update_draft_from_review(
        draft,
        title=title,
        condition=condition,
        description=description,
        included_items=included_items,
        brand=draft.listing.brand,
        model=draft.listing.model,
        subtitle=draft.listing.subtitle,
        category_suggestion=category_suggestion,
        hints=current_values["hints"],
        product_identifier_type=current_values["product_identifier_type"],
        product_identifier_value=current_values["product_identifier_value"],
        key_technical_details=current_values["key_technical_details"],
        shipping_profile=get_selected_shipping_profile(draft),
        confirm_fields=get_review_metadata(draft).get("confirmedFields", []),
        action="confirm",
    )
    if ebay_aspects:
        draft.listing.attributes["ebayAspects"] = ebay_aspects
    else:
        draft.listing.attributes.pop("ebayAspects", None)


def _category_suggestion_actions(draft, *, include_confirm: bool) -> list[dict[str, str]]:
    category_resolution = get_category_resolution(draft)
    suggestions = category_resolution.get("suggestions") if isinstance(category_resolution.get("suggestions"), list) else []
    selected_id = str(category_resolution.get("selected_id") or draft.listing.category_suggestion or "").strip()
    actions: list[dict[str, str]] = []
    if include_confirm and selected_id:
        actions.append({"kind": "confirm", "label": "Passt", "field": "category_suggestion"})
    for item in suggestions[:4]:
        if not isinstance(item, dict):
            continue
        category_id = str(item.get("id") or "").strip()
        label = str(item.get("name") or category_id).strip()
        if not category_id or not label or category_id == selected_id:
            continue
        actions.append({"kind": "select", "label": label[:48], "field": "category_suggestion", "value": category_id})
        if len(actions) >= (5 if include_confirm else 4):
            break
    actions.append({"kind": "edit", "label": "Eigene Suche", "field": "category_suggestion"})
    return actions


def _build_assistant_category_message(draft) -> dict[str, Any] | None:
    category_resolution = get_category_resolution(draft)
    state = str(category_resolution.get("state") or "")
    selected_id = str(category_resolution.get("selected_id") or draft.listing.category_suggestion or "").strip()
    selected_name = str(category_resolution.get("selected_name") or "").strip()

    if state == "needs_selection":
        return {
            "role": "assistant",
            "text": str(category_resolution.get("message") or "Ich habe mehrere passende eBay-Kategorien gefunden. Wähle bitte die beste aus oder antworte mit einem anderen Suchbegriff."),
            "field": "category_suggestion",
            "actions": _category_suggestion_actions(draft, include_confirm=False),
        }

    if selected_id:
        return {
            "role": "assistant",
            "text": f"Ich würde für eBay aktuell diese Kategorie verwenden: {selected_name or selected_id}.",
            "field": "category_suggestion",
            "actions": _category_suggestion_actions(draft, include_confirm=True),
        }

    return {
        "role": "assistant",
        "text": "Damit der eBay-Teil später sauber läuft, brauche ich noch eine passende Kategorie. Antworte mit einem Suchbegriff oder direkt mit einer eBay-Kategorie-ID.",
        "field": "category_suggestion",
        "actions": [{"kind": "edit", "label": "Kategorie angeben", "field": "category_suggestion"}],
    }


def _build_assistant_aspect_message(draft) -> dict[str, Any] | None:
    aspect_values = get_ebay_aspect_values(draft)
    for aspect in get_required_category_aspects(draft):
        name = str(aspect.get("name") or "").strip()
        if not name:
            continue
        field = _assistant_aspect_field(name)
        value = aspect_values.get(name, "").strip()
        options = [str(item).strip() for item in aspect.get("values") or [] if str(item).strip()][:4]
        if value:
            return {
                "role": "assistant",
                "text": f"Für {name} habe ich aktuell diesen Wert: {value}.",
                "field": field,
                "actions": [
                    {"kind": "confirm", "label": "Passt", "field": field},
                    {"kind": "edit", "label": "Wert ändern", "field": field},
                ],
            }
        actions = [{"kind": "select", "label": option[:40], "field": field, "value": option} for option in options]
        actions.append({"kind": "edit", "label": "Selbst eingeben", "field": field})
        return {
            "role": "assistant",
            "text": f"Für die eBay-Kategorie fehlt noch {name}.",
            "field": field,
            "actions": actions,
        }
    return None


def build_assistant_flow(draft) -> dict[str, Any]:
    confirmed_fields = set(get_review_metadata(draft).get("confirmedFields", []))
    assistant_confirmed_fields = _assistant_confirmed_fields(draft)
    messages: list[dict[str, Any]] = [
        {
            "role": "assistant",
            "text": (
                f"Ich habe {len(draft.source.images)} Bild{'er' if len(draft.source.images) != 1 else ''} analysiert "
                "und bereite den Verkaufsdialog Schritt für Schritt vor."
            ),
        }
    ]
    messages.extend(_assistant_flow_events(draft))

    pending_field = ""
    for field in ("title", "condition", "included_items", "description_html"):
        value = _assistant_field_value(draft, field)
        if _assistant_value_is_placeholder(value):
            value = ""
        label = ASSISTANT_FIELD_LABELS[field]
        if value and field in confirmed_fields:
            messages.append({
                "role": "assistant",
                "text": f"{label} ist bestätigt: {value.splitlines()[0]}",
                "tone": "confirmed",
            })
            continue
        if value:
            value_text = value.strip() if field == "description_html" else value.splitlines()[0]
            messages.append({
                "role": "assistant",
                "text": f"{_assistant_field_prompt(field)}\n\n{value_text}",
                "field": field,
                "actions": [
                    {"kind": "confirm", "label": "Super", "field": field},
                    {"kind": "edit", "label": "Ändern", "field": field},
                ],
            })
        else:
            messages.append({
                "role": "assistant",
                "text": _assistant_field_prompt(field),
                "field": field,
                "actions": [{"kind": "edit", "label": "Antworten", "field": field}],
            })
        pending_field = field
        break

    if not pending_field:
        category_message = _build_assistant_category_message(draft)
        if category_message and str(category_message.get("field") or "") not in assistant_confirmed_fields:
            messages.append(category_message)
            pending_field = str(category_message.get("field") or "")

    if not pending_field:
        aspect_message = _build_assistant_aspect_message(draft)
        if aspect_message and str(aspect_message.get("field") or "") not in assistant_confirmed_fields:
            messages.append(aspect_message)
            pending_field = str(aspect_message.get("field") or "")

    if not pending_field:
        messages.append({
            "role": "assistant",
            "text": "Perfekt, der Chat hat jetzt auch die eBay-relevanten Angaben zusammen. Wenn du willst, kannst du jetzt direkt den finalen Entwurf prüfen oder sofort den eBay-Schritt vorbereiten.",
            "actions": [
                {"kind": "link", "label": "Finalen Entwurf prüfen", "href": "#listing-editor"},
                {"kind": "link", "label": "eBay-Schritt öffnen", "href": "#ebay-send"},
            ],
            "tone": "confirmed",
        })

    return {
        "messages": messages,
        "pendingField": pending_field,
        "fieldLabels": ASSISTANT_FIELD_LABELS,
        "fieldValues": _assistant_response_field_values(draft),
    }


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.app_env,
        "ebay_mode": settings.ebay_mode,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", build_context(request))


@router.get("/drafts", response_class=HTMLResponse)
def draft_list(request: Request):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    auth_store = _ebay_auth_store(settings)
    config_store = _ebay_config_store(settings)
    ebay_auth_connected = has_usable_auth_tokens(auth_store.get_tokens())
    effective_config = config_store.get_effective_configuration()
    drafts = sorted(
        repository.list_drafts(),
        key=lambda draft: draft.workflow.last_updated_at,
        reverse=True,
    )
    draft_items = []
    for draft in drafts:
        if refresh_listing_description(draft):
            repository.save_draft(draft)
        marketplace_readiness_errors = collect_marketplace_readiness_errors(
            draft,
            effective_config,
            auth_connected=ebay_auth_connected,
        )
        review_state = evaluate_review_state(draft)
        display_status = build_draft_display_status(
            draft,
            marketplace_readiness_errors=marketplace_readiness_errors,
            review_state=review_state,
        )
        draft_items.append(
            {
            "id": draft.id,
            "sku": draft.sku,
            "status": display_status,
            "last_updated_at": draft.workflow.last_updated_at.strftime("%d.%m.%Y, %H:%M Uhr"),
            "created_at": draft.workflow.created_at.strftime("%d.%m.%Y, %H:%M Uhr"),
            "detail_url": f"/drafts/{draft.id}",
            "title": draft.listing.title.strip() or f"SKU {draft.sku}",
            "subtitle": draft.listing.subtitle.strip() or draft.listing.condition.strip() or "Entwurf bereit zum Weiterbearbeiten",
            "image_url": f"/{draft.source.images[0].storage_path}" if draft.source.images else None,
            "image_alt": draft.source.images[0].original_filename if draft.source.images else "Kein Vorschaubild vorhanden",
            "analysis_state": get_analysis_state(draft),
            }
        )
    return templates.TemplateResponse(
        request,
        "draft_list.html",
        build_context(request, drafts=draft_items),
    )


@router.get("/drafts/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse(
        request,
        "upload.html",
        build_context(request, errors=[], form_values={}),
    )


@router.post("/drafts/upload", response_class=HTMLResponse)
async def upload_draft(
    request: Request,
    images: list[UploadFile] = File(default_factory=list),
    notes: str = Form(default=""),
    product_name: str = Form(default=""),
    condition: str = Form(default=""),
    accessories: str = Form(default=""),
    hints: str = Form(default=""),
):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    service = DraftUploadService(settings.data_dir)
    analysis_service = build_draft_analysis_service(settings)
    form_values = {
        "notes": notes,
        "product_name": product_name,
        "condition": condition,
        "accessories": accessories,
        "hints": hints,
    }

    assets = [
        UploadAsset(filename=image.filename, content_type=image.content_type, stream=image.file)
        for image in images
        if image.filename
    ]

    try:
        result = service.create_draft_from_upload(
            files=assets,
            notes=notes,
            user_input={
                "product_name": product_name,
                "condition": condition,
                "accessories": accessories,
                "hints": hints,
            },
        )
        analysis = analysis_service.analyze(result.draft)
        apply_analysis_result(result.draft, analysis)
        resolve_category_suggestion_for_draft(result.draft, settings)
        autofill_ebay_required_aspects(result.draft, settings)
    except UploadValidationError as exc:
        return templates.TemplateResponse(
            request,
            "upload.html",
            build_context(request, errors=[str(exc)], form_values=form_values),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        for image in images:
            await image.close()

    repository.save_draft(result.draft)
    wants_json = "application/json" in str(request.headers.get("accept") or "")
    if wants_json:
        return JSONResponse(
            {
                "ok": True,
                "draftId": result.draft.id,
                "location": f"/drafts/{result.draft.id}",
                "assistant": build_assistant_flow(result.draft),
                "images": [
                    {"name": image.original_filename, "url": f"/{image.storage_path}", "order": image.order}
                    for image in result.draft.source.images
                ],
                "notes": result.draft.source.notes,
            }
        )
    return RedirectResponse(url=f"/drafts/{result.draft.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_detail(request: Request, draft_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    auth_store = _ebay_auth_store(settings)
    config_store = _ebay_config_store(settings)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    description_changed = refresh_listing_description(draft)
    aspects_changed = autofill_ebay_required_aspects(draft, settings)
    if description_changed or aspects_changed:
        repository.save_draft(draft)

    auth_tokens = auth_store.get_tokens()
    ebay_auth_connected = has_usable_auth_tokens(auth_tokens)
    effective_config = config_store.get_effective_configuration()
    marketplace_readiness_errors = collect_marketplace_readiness_errors(
        draft,
        effective_config,
        auth_connected=ebay_auth_connected,
    )
    marketplace_notes = collect_marketplace_notes(draft)
    review_state = evaluate_review_state(draft)
    display_status = build_draft_display_status(
        draft,
        marketplace_readiness_errors=marketplace_readiness_errors,
        review_state=review_state,
    )
    ebay_action_disabled = review_state != "ready" or bool(marketplace_readiness_errors)
    current_review_status_label = review_status_label(review_state)
    if draft.marketplace.ebay.listing_id or draft.workflow.status is WorkflowStatus.PUBLISHED:
        marketplace_status_label = "Veröffentlicht"
    elif draft.marketplace.ebay.offer_id:
        marketplace_status_label = "Angebot vorbereitet"
    elif not marketplace_readiness_errors and draft.marketplace.ebay.offer_data.get("lastError"):
        marketplace_status_label = "Retry möglich"
    elif not marketplace_readiness_errors:
        marketplace_status_label = "Bereit für eBay-Draft"
    elif any("ist nicht konfiguriert" in item for item in marketplace_readiness_errors):
        marketplace_status_label = "Blockiert durch Konfiguration"
    else:
        marketplace_status_label = "Noch Angaben prüfen"
    result_summary = build_draft_result_summary(
        draft=draft,
        review_state=review_state,
        ebay_auth_connected=ebay_auth_connected,
        marketplace_readiness_errors=marketplace_readiness_errors,
    )
    category_resolution = get_category_resolution(draft)
    required_category_aspects = get_required_category_aspects(draft)
    optional_category_aspects = get_optional_category_aspects(draft)

    return templates.TemplateResponse(
        request,
        "draft_detail.html",
        build_context(
            request,
            draft=draft,
            review_state=review_state,
            missing_core_fields=get_missing_core_fields(draft),
            confidence_notes=get_confidence_notes(draft),
            field_sources=get_field_sources(draft),
            original_input=get_original_input(draft),
            analysis_state=get_analysis_state(draft),
            category_resolution=category_resolution,
            required_category_aspects=required_category_aspects,
            optional_category_aspects=optional_category_aspects,
            ebay_aspect_values=get_ebay_aspect_values(draft),
            ebay_aspect_metadata=get_ebay_aspect_metadata(draft),
            open_ebay_details=should_open_ebay_details(category_resolution, required_category_aspects, marketplace_readiness_errors),
            review_form_values=get_review_form_values(draft),
            review_metadata=get_review_metadata(draft),
            shipping_profiles=get_shipping_profile_options(draft, effective_config),
            selected_shipping_profile=get_selected_shipping_profile(draft),
            marketplace_readiness_errors=marketplace_readiness_errors,
            marketplace_error_groups=split_marketplace_errors(marketplace_readiness_errors),
            marketplace_notes=marketplace_notes,
            ebay_action_disabled=ebay_action_disabled,
            ebay_effective_config=effective_config,
            marketplace_status_label=marketplace_status_label,
            review_status_label=current_review_status_label,
            review_state_label=current_review_status_label,
            display_status=display_status,
            assistant_flow=build_assistant_flow(draft),
            show_technical_workflow_hint=(review_state != "ready" or bool(marketplace_readiness_errors)),
            core_fields=CORE_FIELDS,
            optional_fields=OPTIONAL_FIELDS,
            ebay_auth_connected=ebay_auth_connected,
            ebay_listing_url=_ebay_listing_url(settings, draft.marketplace.ebay.listing_id),
            result_summary=result_summary,
        ),
    )


@router.post("/drafts/{draft_id}/analyze", response_class=HTMLResponse)
def draft_reanalyze(request: Request, draft_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    previous_category = get_category_resolution(draft)
    previous_category_id = str(previous_category.get("selected_id") or draft.listing.category_suggestion or "").strip()
    previous_category_metadata = dict(previous_category) if previous_category_id.isdigit() else None
    analysis_service = build_draft_analysis_service(settings)
    analysis = analysis_service.analyze(draft)
    apply_analysis_result(draft, analysis)
    if previous_category_metadata and previous_category_id:
        draft.listing.category_suggestion = previous_category_id
        draft.listing.attributes["ebayCategory"] = previous_category_metadata
    resolve_category_suggestion_for_draft(draft, settings)
    autofill_ebay_required_aspects(draft, settings)
    repository.save_draft(draft)
    return RedirectResponse(url=f"/drafts/{draft.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/assistant/message")
async def draft_assistant_message(request: Request, draft_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    payload = await request.json()
    action = str(payload.get("action") or "").strip()
    field = str(payload.get("field") or "").strip()
    value = str(payload.get("value") or "").strip()
    if field not in ASSISTANT_FIELD_LABELS and not field.startswith("ebay_aspect::"):
        raise HTTPException(status_code=400, detail="Ungültiges Feld")

    confirmed_fields = set(get_review_metadata(draft).get("confirmedFields", []))
    assistant_confirmed_fields = _assistant_confirmed_fields(draft)

    if action == "confirm":
        if field in ASSISTANT_FIELD_LABELS:
            confirmed_fields.add(field)
        assistant_confirmed_fields.add(field)
        _append_assistant_event(draft, role="user", text="Super")
        _append_assistant_event(draft, role="assistant", text=f"Alles klar, { _assistant_field_label(field) } ist übernommen.")
    elif action in {"answer", "select"}:
        field_completed = True
        if field == "category_suggestion":
            draft.listing.category_suggestion = value
            resolve_category_suggestion_for_draft(
                draft,
                settings,
                preserve_numeric_id=bool(value and value.isdigit()),
            )
            autofill_ebay_required_aspects(draft, settings)
            category_resolution = get_category_resolution(draft)
            category_state = str(category_resolution.get("state") or "")
            selected_id = str(category_resolution.get("selected_id") or draft.listing.category_suggestion or "").strip()
            field_completed = bool(selected_id) and category_state not in {"needs_selection", "no_match", "lookup_failed", "config_missing", "empty"}
        else:
            _update_single_assistant_field(draft, field, value)
            if field == "title":
                current_items = [item.strip() for item in draft.listing.included_items if item.strip()]
                if len(current_items) == 1 and _dedupe_text(current_items[0]) == _dedupe_text(value):
                    draft.listing.included_items = []
                resolve_category_suggestion_for_draft(draft, settings)
                autofill_ebay_required_aspects(draft, settings)
            if field.startswith("ebay_aspect::"):
                autofill_ebay_required_aspects(draft, settings)
        if field_completed and field in ASSISTANT_FIELD_LABELS:
            confirmed_fields.add(field)
        if field_completed:
            assistant_confirmed_fields.add(field)
        else:
            assistant_confirmed_fields.discard(field)
        _append_assistant_event(draft, role="user", text=value)
        if field == "category_suggestion" and not field_completed:
            _append_assistant_event(draft, role="assistant", text="Ich habe dazu neue eBay-Kategorievorschläge gesucht.")
        else:
            _append_assistant_event(draft, role="assistant", text=f"Danke, ich habe { _assistant_field_label(field) } aktualisiert.")
    elif action != "edit":
        raise HTTPException(status_code=400, detail="Ungültige Aktion")

    if action == "confirm" or field in ASSISTANT_FIELD_LABELS:
        draft.listing.attributes["review"] = {
            **get_review_metadata(draft),
            "confirmedFields": sorted(confirmed_fields),
        }

    _set_assistant_confirmed_fields(draft, assistant_confirmed_fields)

    repository.save_draft(draft)
    return JSONResponse({"ok": True, **build_assistant_flow(draft)})


@router.get("/drafts/{draft_id}/assistant/state")
def draft_assistant_state(draft_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    return JSONResponse(
        {
            "ok": True,
            "draftId": draft.id,
            "assistant": build_assistant_flow(draft),
            "images": [
                {"name": image.original_filename, "url": f"/{image.storage_path}", "order": image.order}
                for image in draft.source.images
            ],
            "notes": draft.source.notes,
        }
    )


@router.post("/drafts/{draft_id}/review", response_class=HTMLResponse)
async def draft_review_submit(
    request: Request,
    draft_id: str,
    title: str = Form(default=""),
    condition: str = Form(default=""),
    description: str = Form(default=""),
    included_items: str = Form(default=""),
    brand: str = Form(default=""),
    model: str = Form(default=""),
    subtitle: str = Form(default=""),
    category_suggestion: str = Form(default=""),
    selected_category_suggestion: str = Form(default=""),
    category_search_query: str = Form(default=""),
    hints: str = Form(default=""),
    product_identifier_type: str = Form(default=""),
    product_identifier_value: str = Form(default=""),
    key_technical_details: str = Form(default=""),
    shipping_profile: str = Form(default=DEFAULT_SHIPPING_PROFILE),
    confirm_fields: list[str] = Form(default_factory=list),
    action: str = Form(default="save"),
):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    form = await request.form()
    submitted_category_suggestion = (
        category_search_query.strip()
        if action == "search_category"
        else selected_category_suggestion.strip() or category_suggestion.strip()
    )

    update_draft_from_review(
        draft,
        title=title,
        condition=condition,
        description=description,
        included_items=included_items,
        brand=brand,
        model=model,
        subtitle=subtitle,
        category_suggestion=submitted_category_suggestion,
        hints=hints,
        product_identifier_type=product_identifier_type,
        product_identifier_value=product_identifier_value,
        key_technical_details=key_technical_details,
        shipping_profile=shipping_profile,
        confirm_fields=confirm_fields,
        action=action,
    )
    update_ebay_aspects_from_form(draft, form)
    resolve_category_suggestion_for_draft(
        draft,
        settings,
        preserve_numeric_id=bool(submitted_category_suggestion and submitted_category_suggestion.isdigit()),
    )
    autofill_ebay_required_aspects(draft, settings)
    repository.save_draft(draft)
    return RedirectResponse(url=f"/drafts/{draft.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/category/search")
async def draft_category_search(draft_id: str, request: Request):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    form = await request.form()
    query = str(form.get("query") or "").strip()
    if not query:
        return JSONResponse(
            {
                "ok": False,
                "message": "Bitte gib einen Suchbegriff ein.",
                "suggestions": [],
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    resolution = resolve_category_search_for_draft(draft, settings, query)
    autofill_ebay_required_aspects(draft, settings)
    repository.save_draft(draft)
    return {
        "ok": True,
        "categorySuggestion": draft.listing.category_suggestion,
        "selectedId": resolution.get("selected_id", ""),
        "selectedName": resolution.get("selected_name", ""),
        "selectedPath": resolution.get("selected_path", ""),
        "state": resolution.get("state", ""),
        "message": resolution.get("message", ""),
        "suggestions": resolution.get("suggestions", []),
        "requiredAspects": get_required_category_aspects(draft),
        "aspectValues": get_ebay_aspect_values(draft),
    }


@router.post("/drafts/{draft_id}/images", response_class=HTMLResponse)
async def draft_add_images(
    draft_id: str,
    images: list[UploadFile] = File(default_factory=list),
):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    service = DraftUploadService(settings.data_dir)
    assets = [
        UploadAsset(filename=image.filename, content_type=image.content_type, stream=image.file)
        for image in images
        if image.filename
    ]
    try:
        service.append_images_to_draft(draft, files=assets)
        draft.marketplace.ebay.image_urls = []
    except UploadValidationError as exc:
        draft.marketplace.ebay.offer_data["lastError"] = str(exc)
    finally:
        for image in images:
            await image.close()

    repository.save_draft(draft)
    return RedirectResponse(url=f"/drafts/{draft.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/images/{image_id}/delete", response_class=HTMLResponse)
def draft_delete_image(draft_id: str, image_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    removed = None
    remaining = []
    for image in draft.source.images:
        if image.id == image_id:
            removed = image
        else:
            remaining.append(image)
    if removed is None:
        raise HTTPException(status_code=404, detail="Image not found")

    image_path = Path(removed.storage_path)
    if not image_path.is_absolute():
        image_path = settings.project_dir / image_path
    try:
        image_path.unlink(missing_ok=True)
    except OSError:
        pass

    for index, image in enumerate(remaining, start=1):
        image.order = index
    draft.source.images = remaining
    draft.marketplace.ebay.image_urls = []
    repository.save_draft(draft)
    return RedirectResponse(url=f"/drafts/{draft.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/marketplace/ebay", response_class=HTMLResponse)
def draft_create_ebay_offer(draft_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    auth_store = _ebay_auth_store(settings)
    service = EbayMarketplaceService(
        settings=settings,
        repository=repository,
        client=EbayClient(settings, auth_store=auth_store),
        config_store=_ebay_config_store(settings),
    )
    service.create_unpublished_offer_for_draft(draft_id)
    return RedirectResponse(url=f"/drafts/{draft_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/drafts/{draft_id}/marketplace/ebay/publish", response_class=HTMLResponse)
def draft_publish_ebay_offer(draft_id: str):
    settings = get_settings()
    repository = DraftRepository(settings.database_path)
    draft = repository.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    auth_store = _ebay_auth_store(settings)
    service = EbayMarketplaceService(
        settings=settings,
        repository=repository,
        client=EbayClient(settings, auth_store=auth_store),
        config_store=_ebay_config_store(settings),
    )
    service.publish_offer_for_draft(draft_id)
    return RedirectResponse(url=f"/drafts/{draft_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/integrations/ebay/connect")
def ebay_connect():
    settings = get_settings()
    if not settings.ebay_client_id or not settings.ebay_ru_name:
        raise HTTPException(status_code=400, detail="eBay OAuth ist nicht vollständig konfiguriert")

    auth_store = _ebay_auth_store(settings)
    state = auth_store.issue_state()
    return RedirectResponse(url=build_auth_connect_url(settings, state), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/integrations/ebay/callback", response_class=HTMLResponse)
def ebay_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    settings = get_settings()
    auth_store = _ebay_auth_store(settings)
    config_store = _ebay_config_store(settings)

    if error:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Autorisierung fehlgeschlagen: {error}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    expected_state = auth_store.get_pending_state()
    if not state or state != expected_state:
        raise HTTPException(status_code=400, detail="Ungültiger eBay OAuth-Status")
    if not code:
        raise HTTPException(status_code=400, detail="eBay OAuth-Code fehlt")

    client = EbayClient(settings, auth_store=auth_store)
    message = "eBay wurde erfolgreich verbunden. Die Tokens werden jetzt in der App gespeichert."
    discovery_notice = None
    try:
        client.exchange_authorization_code(code)
        try:
            resources = client.get_account_resources(client.get_access_token())
            config_store.save_discovered_resources(resources)
            effective_config = config_store.auto_select_defaults(resources)
            sync_shipping_profile_policy_ids(config_store, resources)
            effective_config = config_store.get_effective_configuration()
            auto_selected = []
            if effective_config.payment_policy_id:
                auto_selected.append("Payment Policy")
            if effective_config.fulfillment_policy_id:
                auto_selected.append("Fulfillment Policy")
            if effective_config.return_policy_id:
                auto_selected.append("Return Policy")
            if effective_config.merchant_location_key:
                auto_selected.append("Merchant Location")
            if auto_selected:
                message += f" Erkannte Defaults: {', '.join(auto_selected)}."
        except (EbayValidationError, EbayApiError) as exc:
            discovery_notice = f"Die Account-Ressourcen konnten nach dem Login nicht automatisch geladen werden: {exc}"
    except EbayAuthError as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung konnte nicht hergestellt werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()
        auth_store.clear_state()

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, ebay_connect_success=message, ebay_connect_error=discovery_notice),
    )


@router.post("/integrations/ebay/defaults")
async def ebay_save_defaults(
    payment_policy_id: str = Form(default=""),
    fulfillment_policy_id: str = Form(default=""),
    return_policy_id: str = Form(default=""),
    merchant_location_key: str = Form(default=""),
):
    settings = get_settings()
    config_store = _ebay_config_store(settings)
    config_store.save_selected_configuration(
        payment_policy_id=payment_policy_id.strip() or None,
        fulfillment_policy_id=fulfillment_policy_id.strip() or None,
        return_policy_id=return_policy_id.strip() or None,
        merchant_location_key=merchant_location_key.strip() or None,
    )
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/integrations/ebay/discover")
def ebay_discover_defaults(request: Request):
    settings = get_settings()
    auth_store = _ebay_auth_store(settings)
    config_store = _ebay_config_store(settings)
    token_data = auth_store.get_tokens()
    if not has_usable_auth_tokens(token_data):
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error="Bitte zuerst mit eBay verbinden."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    client = EbayClient(settings, auth_store=auth_store)
    try:
        access_token = client.get_access_token()
        opted_in_programs = client.get_opted_in_programs(access_token)
        policy_management_opted_in = "SELLING_POLICY_MANAGEMENT" in opted_in_programs
        if not policy_management_opted_in:
            return templates.TemplateResponse(
                request,
                "index.html",
                build_context(
                    request,
                    ebay_policy_management_opted_in=False,
                    ebay_connect_error=(
                        "Der verbundene eBay-Account ist noch nicht für Business Policies freigeschaltet. "
                        "Bitte 'Selling Policy Management aktivieren' ausführen und danach die Ressourcen erneut laden."
                    ),
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        resources = client.get_account_resources(access_token)
        config_store.save_discovered_resources(resources)
        effective_config = config_store.auto_select_defaults(resources)
        sync_shipping_profile_policy_ids(config_store, resources)
        effective_config = config_store.get_effective_configuration()
    except EbayAuthError as exc:
        auth_store.clear_tokens()
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung ist nicht mehr gültig: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except (EbayValidationError, EbayApiError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"Die Account-Ressourcen konnten nicht geladen werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()

    found_counts = {
        "Payment Policies": len(resources.payment_policies),
        "Fulfillment Policies": len(resources.fulfillment_policies),
        "Return Policies": len(resources.return_policies),
        "Merchant Locations": len(resources.merchant_locations),
    }
    summary = ", ".join(f"{label}: {count}" for label, count in found_counts.items())

    auto_selected = []
    if effective_config.payment_policy_id:
        auto_selected.append("Payment Policy")
    if effective_config.fulfillment_policy_id:
        auto_selected.append("Fulfillment Policy")
    if effective_config.return_policy_id:
        auto_selected.append("Return Policy")
    if effective_config.merchant_location_key:
        auto_selected.append("Merchant Location")

    message = f"eBay-Account-Ressourcen aktualisiert. Gefunden: {summary}."
    if auto_selected:
        message += f" Automatisch gesetzt: {', '.join(auto_selected)}."

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, ebay_connect_success=message, ebay_policy_management_opted_in=True),
    )


@router.post("/integrations/ebay/programs/selling-policy-management/opt-in")
def ebay_opt_in_selling_policy_management(request: Request):
    settings = get_settings()
    auth_store = _ebay_auth_store(settings)
    token_data = auth_store.get_tokens()
    if not has_usable_auth_tokens(token_data):
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error="Bitte zuerst mit eBay verbinden."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    client = EbayClient(settings, auth_store=auth_store)
    try:
        access_token = client.get_access_token()
        client.opt_in_to_program(access_token, "SELLING_POLICY_MANAGEMENT")
    except EbayAuthError as exc:
        auth_store.clear_tokens()
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung ist nicht mehr gültig: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except (EbayValidationError, EbayApiError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"SELLING_POLICY_MANAGEMENT konnte nicht aktiviert werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(
            request,
            ebay_connect_success=(
                "SELLING_POLICY_MANAGEMENT wurde bei eBay angefordert. "
                "Die Aktivierung kann laut eBay bis zu 24 Stunden dauern. Danach bitte die Account-Ressourcen erneut laden."
            ),
            ebay_policy_management_opted_in=False,
        ),
    )


@router.post("/integrations/ebay/locations/create-default")
def ebay_create_default_location(request: Request):
    settings = get_settings()
    auth_store = _ebay_auth_store(settings)
    config_store = _ebay_config_store(settings)
    token_data = auth_store.get_tokens()
    if not has_usable_auth_tokens(token_data):
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error="Bitte zuerst mit eBay verbinden."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    client = EbayClient(settings, auth_store=auth_store)
    merchant_location_key = "open-inserto-default"
    payload = {
        "name": "Open Inserto Default",
        "phone": "+49 0000000000",
        "location": {
            "address": {
                "postalCode": "85049",
                "country": "DE",
            }
        },
        "locationTypes": ["WAREHOUSE"],
        "merchantLocationStatus": "ENABLED",
    }
    try:
        access_token = client.get_access_token()
        try:
            client.create_inventory_location(
                access_token,
                merchant_location_key=merchant_location_key,
                payload=payload,
            )
            success_message = "Standard-Merchant-Location wurde angelegt."
        except EbayValidationError as exc:
            if "already exists" in str(exc).lower():
                success_message = "Standard-Merchant-Location existiert bereits."
            else:
                raise

        discovery_notice = None
        try:
            resources = client.get_account_resources(access_token)
            config_store.save_discovered_resources(resources)
            effective_config = config_store.auto_select_defaults(resources)
            sync_shipping_profile_policy_ids(config_store, resources)
            effective_config = config_store.get_effective_configuration()
            if not effective_config.merchant_location_key:
                config_store.save_selected_configuration(merchant_location_key=merchant_location_key)
            success_message += " Account-Ressourcen wurden anschließend neu geladen."
        except (EbayValidationError, EbayApiError) as exc:
            discovery_notice = (
                "Die Location wurde angelegt, aber die Account-Ressourcen konnten danach noch nicht geladen werden: "
                f"{exc}"
            )
    except EbayAuthError as exc:
        auth_store.clear_tokens()
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung ist nicht mehr gültig: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except (EbayValidationError, EbayApiError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"Merchant Location konnte nicht angelegt werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(
            request,
            ebay_connect_success=success_message,
            ebay_connect_error=discovery_notice,
        ),
    )


@router.post("/integrations/ebay/policies/create-defaults")
def ebay_create_default_policies(request: Request):
    settings = get_settings()
    auth_store = _ebay_auth_store(settings)
    config_store = _ebay_config_store(settings)
    token_data = auth_store.get_tokens()
    if not has_usable_auth_tokens(token_data):
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error="Bitte zuerst mit eBay verbinden."),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    client = EbayClient(settings, auth_store=auth_store)
    try:
        access_token = client.get_access_token()
        shipping_services = client.get_shipping_services(access_token)
        dhl_paket = _resolve_shipping_service_code(
            shipping_services,
            preferred_codes=["DE_DHLPaket"],
            search_terms=["dhl", "paket"],
        )
        dhl_paeckchen = _resolve_shipping_service_code(
            shipping_services,
            preferred_codes=["DE_DHLPackchen", "DE_DHLPaeckchen"],
            search_terms=["dhl", "packchen"],
        )
        if not dhl_paket or not dhl_paeckchen:
            available = ", ".join(
                sorted(
                    {
                        str(item.get("description") or item.get("shippingServiceCode") or item.get("shippingService") or "").strip()
                        for item in shipping_services
                        if isinstance(item, dict)
                    }
                )[:10]
            )
            raise EbayValidationError(
                "Die benötigten DHL-Versandservices konnten für EBAY_DE nicht automatisch aufgelöst werden."
                + (f" Verfügbare Beispiele: {available}" if available else "")
            )

        payment_payload = {
            "name": PAYMENT_POLICY_NAME,
            "marketplaceId": settings.ebay_marketplace_id,
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "immediatePay": False,
        }
        return_payload = {
            "name": RETURN_POLICY_NAME,
            "marketplaceId": settings.ebay_marketplace_id,
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "returnsAccepted": False,
            "description": "Privatverkauf ohne Rücknahme und Gewährleistung.",
        }
        fulfillment_payloads = _build_open_inserto_fulfillment_policy_payloads(
            marketplace_id=settings.ebay_marketplace_id,
            currency=settings.ebay_currency,
            dhl_paket_code=dhl_paket,
            dhl_paeckchen_code=dhl_paeckchen,
        )

        created_labels: list[str] = []
        try:
            client.create_payment_policy(access_token, payment_payload)
            created_labels.append("Payment Policy")
        except EbayValidationError as exc:
            if not _is_duplicate_policy_error(exc):
                raise
        try:
            client.create_return_policy(access_token, return_payload)
            created_labels.append("Return Policy")
        except EbayValidationError as exc:
            if not _is_duplicate_policy_error(exc):
                raise
        for profile_key, fulfillment_payload in fulfillment_payloads.items():
            try:
                client.create_fulfillment_policy(access_token, fulfillment_payload)
                created_labels.append(SHIPPING_PROFILES[profile_key]["label"])
            except EbayValidationError as exc:
                if not _is_duplicate_policy_error(exc):
                    raise

        resources = client.get_account_resources(access_token)
        config_store.save_discovered_resources(resources)
        effective_config = config_store.auto_select_defaults(resources)
        shipping_profile_policy_ids = sync_shipping_profile_policy_ids(config_store, resources)
        config_store.save_selected_configuration(
            payment_policy_id=_find_resource_id_by_name(resources.payment_policies, payment_payload["name"]) or effective_config.payment_policy_id,
            fulfillment_policy_id=shipping_profile_policy_ids.get(DEFAULT_SHIPPING_PROFILE) or effective_config.fulfillment_policy_id,
            return_policy_id=_find_resource_id_by_name(resources.return_policies, return_payload["name"]) or effective_config.return_policy_id,
        )
        effective_config = config_store.get_effective_configuration()
    except EbayAuthError as exc:
        auth_store.clear_tokens()
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"eBay-Verbindung ist nicht mehr gültig: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except (EbayValidationError, EbayApiError) as exc:
        return templates.TemplateResponse(
            request,
            "index.html",
            build_context(request, ebay_connect_error=f"Standard-Business-Policies konnten nicht angelegt werden: {exc}"),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    finally:
        client.close()

    selected = []
    if effective_config.payment_policy_id:
        selected.append("Payment Policy")
    if effective_config.fulfillment_policy_id:
        selected.append("Fulfillment Policy")
    if effective_config.return_policy_id:
        selected.append("Return Policy")
    message = "Standard-Business-Policies wurden angelegt oder waren bereits vorhanden."
    if created_labels:
        message += f" Neu angelegt: {', '.join(created_labels)}."
    if selected:
        message += f" Automatisch gesetzt: {', '.join(selected)}."

    return templates.TemplateResponse(
        request,
        "index.html",
        build_context(request, ebay_connect_success=message),
    )


def _find_shipping_service_code(services: list[dict[str, object]], search_terms: list[str]) -> str | None:
    normalized_terms = [normalize_search_text(term) for term in search_terms]
    for item in services:
        description = normalize_search_text(str(item.get("description") or ""))
        if all(term in description for term in normalized_terms):
            return str(item.get("shippingServiceCode") or item.get("shippingService") or "").strip() or None
    return None


def _resolve_shipping_service_code(
    services: list[dict[str, object]],
    *,
    preferred_codes: list[str],
    search_terms: list[str],
) -> str | None:
    available_codes = {
        str(item.get("shippingServiceCode") or item.get("shippingService") or "").strip()
        for item in services
        if isinstance(item, dict)
    }
    for code in preferred_codes:
        if code in available_codes:
            return code
    return _find_shipping_service_code(services, search_terms)


def _build_open_inserto_fulfillment_policy_payloads(
    *,
    marketplace_id: str,
    currency: str,
    dhl_paket_code: str,
    dhl_paeckchen_code: str,
) -> dict[str, dict]:
    def shipping_policy(name: str, services: list[dict[str, str]]) -> dict:
        return {
            "name": name,
            "marketplaceId": marketplace_id,
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "handlingTime": {"value": 3, "unit": "DAY"},
            "shippingOptions": [
                {
                    "costType": "FLAT_RATE",
                    "optionType": "DOMESTIC",
                    "shippingServices": [
                        {
                            "sortOrder": index,
                            "shippingCarrierCode": "DHL",
                            "shippingServiceCode": service["code"],
                            "shippingCost": {"value": service["cost"], "currency": currency},
                            "additionalShippingCost": {"value": service["cost"], "currency": currency},
                        }
                        for index, service in enumerate(services, start=1)
                    ],
                }
            ],
        }

    return {
        "dhl_2kg": shipping_policy(
            SHIPPING_PROFILES["dhl_2kg"]["policy_name"],
            [
                {"code": dhl_paket_code, "cost": "6.19"},
                {"code": dhl_paeckchen_code, "cost": "5.19"},
            ],
        ),
        "dhl_5kg": shipping_policy(
            SHIPPING_PROFILES["dhl_5kg"]["policy_name"],
            [{"code": dhl_paket_code, "cost": "7.69"}],
        ),
        "dhl_10kg": shipping_policy(
            SHIPPING_PROFILES["dhl_10kg"]["policy_name"],
            [{"code": dhl_paket_code, "cost": "10.49"}],
        ),
        "dhl_20kg": shipping_policy(
            SHIPPING_PROFILES["dhl_20kg"]["policy_name"],
            [{"code": dhl_paket_code, "cost": "18.99"}],
        ),
        "pickup": {
            "name": SHIPPING_PROFILES["pickup"]["policy_name"],
            "marketplaceId": marketplace_id,
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "localPickup": True,
        },
    }


def _is_duplicate_policy_error(exc: EbayValidationError) -> bool:
    message = str(exc).lower()
    return (
        "duplicate policy" in message
        or "already exists" in message
        or "doppelt vorhanden" in message
        or "20400" in message
    )


def _find_resource_id_by_name(resources: list[dict[str, str]], expected_name: str) -> str | None:
    for item in resources:
        if item.get("name") == expected_name:
            value = item.get("id")
            if value:
                return value
    return None
