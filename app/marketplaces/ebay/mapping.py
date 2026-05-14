from __future__ import annotations

from app.marketplaces.ebay.configuration import EffectiveEbayConfiguration
from app.core.config import Settings
from app.drafts.models import Draft


DEFAULT_AUCTION_START_PRICE = 1.0
DEFAULT_AUCTION_DURATION = "DAYS_7"


CONDITION_MAP = {
    "neu": "NEW",
    "new": "NEW",
    "gebraucht": "USED_GOOD",
    "used": "USED_GOOD",
    "sehr gut": "USED_VERY_GOOD",
    "gut": "USED_GOOD",
    "akzeptabel": "USED_ACCEPTABLE",
}


def build_inventory_item_payload(draft: Draft, settings: Settings) -> dict:
    aspects: dict[str, list[str]] = {}
    if draft.listing.brand.strip():
        aspects["Marke"] = [draft.listing.brand.strip()]
    if draft.listing.model.strip():
        aspects["Modell"] = [draft.listing.model.strip()]
    product_identifier_type = _string_attribute(draft, "product_identifier_type")
    product_identifier_value = _string_attribute(draft, "product_identifier_value")
    if product_identifier_type and product_identifier_value:
        aspects[product_identifier_type] = [product_identifier_value]
    for detail in _string_list_attribute(draft, "keyTechnicalDetails"):
        if ":" not in detail:
            continue
        label, value = [part.strip() for part in detail.split(":", 1)]
        if label and value:
            aspects[label] = [value]

    product = {
        "title": draft.listing.title.strip(),
        "description": draft.listing.description_html.strip(),
        "imageUrls": list(draft.marketplace.ebay.image_urls),
    }
    if product_identifier_value and product_identifier_type.upper() in {"EAN", "GTIN"}:
        product["ean"] = [product_identifier_value]
    elif product_identifier_value and product_identifier_type.upper() in {"MPN", "MODELL-NUMMER", "ARTIKELNUMMER"}:
        product["mpn"] = product_identifier_value
    if aspects:
        product["aspects"] = aspects

    return {
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "condition": map_condition(draft.listing.condition),
        "product": product,
    }


def build_offer_payload(draft: Draft, settings: Settings, config: EffectiveEbayConfiguration) -> dict:
    price = draft.listing.price_suggestion if draft.listing.price_suggestion is not None else DEFAULT_AUCTION_START_PRICE
    return {
        "sku": draft.sku,
        "marketplaceId": settings.ebay_marketplace_id,
        "format": "AUCTION",
        "listingDuration": DEFAULT_AUCTION_DURATION,
        "categoryId": draft.listing.category_suggestion.strip(),
        "merchantLocationKey": config.merchant_location_key,
        "listingPolicies": {
            "paymentPolicyId": config.payment_policy_id,
            "fulfillmentPolicyId": config.fulfillment_policy_id,
            "returnPolicyId": config.return_policy_id,
        },
        "pricingSummary": {
            "auctionStartPrice": {
                "value": f"{price:.2f}",
                "currency": settings.ebay_currency,
            }
        },
    }


def map_condition(condition: str) -> str:
    return CONDITION_MAP.get(condition.strip().lower(), "USED_GOOD")


def _string_attribute(draft: Draft, key: str) -> str:
    value = draft.listing.attributes.get(key)
    return value.strip() if isinstance(value, str) else ""


def _string_list_attribute(draft: Draft, key: str) -> list[str]:
    value = draft.listing.attributes.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
