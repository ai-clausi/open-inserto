from __future__ import annotations

from dataclasses import dataclass

from app.drafts.models import Draft
from app.marketplaces.ebay.configuration import EffectiveEbayConfiguration, normalize_shipping_profile
from app.marketplaces.ebay.taxonomy import get_required_category_aspects


def collect_marketplace_notes(draft: Draft) -> list[str]:
    notes: list[str] = []

    if draft.listing.price_suggestion is None:
        notes.append("Noch keine Preisschätzung vorhanden – für Auktionen wird aktuell trotzdem 1,00 € als Startpreis verwendet.")
    if not draft.listing.category_suggestion.strip():
        notes.append("Keine Kategorie gesetzt – für den eBay-Draft bitte noch eine passende Kategorie ergänzen.")

    return notes


@dataclass(slots=True)
class MarketplaceValidationError(Exception):
    errors: list[str]

    def __str__(self) -> str:
        return "; ".join(self.errors)


def collect_marketplace_readiness_errors(
    draft: Draft,
    config: EffectiveEbayConfiguration,
    *,
    auth_connected: bool | None = None,
) -> list[str]:
    errors: list[str] = []

    if not draft.listing.title.strip():
        errors.append("Titel fehlt")
    if not draft.listing.description_html.strip():
        errors.append("Beschreibung fehlt")
    if not draft.listing.condition.strip():
        errors.append("Zustand fehlt")
    if not draft.listing.category_suggestion.strip():
        errors.append("Kategorie fehlt")
    elif not draft.listing.category_suggestion.strip().isdigit():
        errors.append("eBay-Kategorie muss als numerische Category ID angegeben werden")
    for aspect in _missing_required_aspects(draft):
        errors.append(f"Artikelmerkmal {aspect} fehlt")
    if not draft.source.images:
        errors.append("Mindestens ein Bild ist erforderlich")

    required_settings = {
        "eBay-Zugang": auth_connected if auth_connected is not None else False,
        "Payment Policy": config.payment_policy_id,
        "Fulfillment Policy": config.fulfillment_policy_id_for_profile(_draft_shipping_profile(draft)),
        "Return Policy": config.return_policy_id,
        "Merchant Location": config.merchant_location_key,
    }
    for label, value in required_settings.items():
        if not value:
            if label == "eBay-Zugang":
                errors.append("eBay ist noch nicht verbunden")
            else:
                errors.append(f"{label} ist nicht konfiguriert")

    return errors


def validate_marketplace_ready(draft: Draft, config: EffectiveEbayConfiguration, *, auth_connected: bool | None = None) -> None:
    errors = collect_marketplace_readiness_errors(draft, config, auth_connected=auth_connected)
    if errors:
        raise MarketplaceValidationError(errors)


def _draft_shipping_profile(draft: Draft) -> str:
    return normalize_shipping_profile(str(draft.listing.shipping_suggestion.get("profile") or ""))


def _missing_required_aspects(draft: Draft) -> list[str]:
    values = draft.listing.attributes.get("ebayAspects")
    values = values if isinstance(values, dict) else {}
    details = draft.listing.attributes.get("keyTechnicalDetails")
    detail_labels = set()
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, str) and ":" in detail:
                detail_labels.add(detail.split(":", 1)[0].strip().casefold())
    missing: list[str] = []
    for aspect in get_required_category_aspects(draft):
        name = str(aspect.get("name") or "").strip()
        if not name:
            continue
        value = values.get(name)
        if str(value or "").strip():
            continue
        if name.casefold() in detail_labels:
            continue
        missing.append(name)
    return missing
