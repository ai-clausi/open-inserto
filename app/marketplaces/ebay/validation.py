from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.drafts.models import Draft, WorkflowStatus


@dataclass(slots=True)
class MarketplaceValidationError(Exception):
    errors: list[str]

    def __str__(self) -> str:
        return "; ".join(self.errors)


def collect_marketplace_readiness_errors(
    draft: Draft,
    settings: Settings,
    *,
    include_workflow_status: bool = True,
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
    if draft.listing.price_suggestion is None:
        errors.append("Preisvorschlag fehlt")
    if not draft.listing.category_suggestion.strip():
        errors.append("Kategorie fehlt")
    if not draft.source.images:
        errors.append("Mindestens ein Bild ist erforderlich")

    required_settings = {
        "Payment Policy": settings.ebay_payment_policy_id,
        "Fulfillment Policy": settings.ebay_fulfillment_policy_id,
        "Return Policy": settings.ebay_return_policy_id,
        "Merchant Location": settings.ebay_merchant_location_key,
    }
    for label, value in required_settings.items():
        if not value:
            errors.append(f"{label} ist nicht konfiguriert")

    return errors


def validate_marketplace_ready(draft: Draft, settings: Settings) -> None:
    errors = collect_marketplace_readiness_errors(draft, settings)
    if errors:
        raise MarketplaceValidationError(errors)
