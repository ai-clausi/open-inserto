from __future__ import annotations

from app.core.config import Settings
from app.drafts.models import Draft


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

    product = {
        "title": draft.listing.title.strip(),
        "description": draft.listing.description_html.strip(),
        "imageUrls": list(draft.marketplace.ebay.image_urls),
    }
    if aspects:
        product["aspects"] = aspects

    return {
        "availability": {"shipToLocationAvailability": {"quantity": 1}},
        "condition": map_condition(draft.listing.condition),
        "product": product,
    }


def build_offer_payload(draft: Draft, settings: Settings) -> dict:
    price = draft.listing.price_suggestion
    return {
        "sku": draft.sku,
        "marketplaceId": settings.ebay_marketplace_id,
        "format": "AUCTION",
        "availableQuantity": 1,
        "categoryId": draft.listing.category_suggestion.strip(),
        "merchantLocationKey": settings.ebay_merchant_location_key,
        "listingPolicies": {
            "paymentPolicyId": settings.ebay_payment_policy_id,
            "fulfillmentPolicyId": settings.ebay_fulfillment_policy_id,
            "returnPolicyId": settings.ebay_return_policy_id,
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
