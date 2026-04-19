from __future__ import annotations

from dataclasses import dataclass

from app.drafts.models import Draft, WorkflowStatus
from app.marketplaces.ebay.configuration import EffectiveEbayConfiguration


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
    include_workflow_status: bool = True,
    auth_connected: bool | None = None,
) -> list[str]:
    errors: list[str] = []

    if include_workflow_status and draft.workflow.status is not WorkflowStatus.READY_FOR_MARKETPLACE:
        errors.append("Draft ist nicht bereit für den Marketplace-Schritt")
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
    if not draft.source.images:
        errors.append("Mindestens ein Bild ist erforderlich")

    required_settings = {
        "eBay-Zugang": auth_connected if auth_connected is not None else False,
        "Payment Policy": config.payment_policy_id,
        "Fulfillment Policy": config.fulfillment_policy_id,
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
