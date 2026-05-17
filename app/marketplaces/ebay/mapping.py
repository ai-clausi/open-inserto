from __future__ import annotations

from app.marketplaces.ebay.configuration import EffectiveEbayConfiguration, normalize_shipping_profile
from app.core.config import Settings
from app.drafts.models import Draft


DEFAULT_AUCTION_START_PRICE = 1.0
DEFAULT_AUCTION_DURATION = "DAYS_7"


CONDITION_MAP = {
    "neu": "NEW",
    "new": "NEW",
    "gebraucht": "USED_GOOD",
    "used": "USED_GOOD",
    "sehr gut": "USED_EXCELLENT",
    "gut": "USED_GOOD",
    "akzeptabel": "USED_ACCEPTABLE",
}

CONDITION_ID_TO_ENUM = {
    "1000": "NEW",
    "1500": "NEW_OTHER",
    "1750": "NEW_WITH_DEFECTS",
    "2000": "CERTIFIED_REFURBISHED",
    "2010": "EXCELLENT_REFURBISHED",
    "2020": "VERY_GOOD_REFURBISHED",
    "2030": "GOOD_REFURBISHED",
    "2500": "SELLER_REFURBISHED",
    "2750": "LIKE_NEW",
    "2990": "PRE_OWNED_EXCELLENT",
    "3000": "USED_EXCELLENT",
    "3010": "PRE_OWNED_FAIR",
    "4000": "USED_VERY_GOOD",
    "5000": "USED_GOOD",
    "6000": "USED_ACCEPTABLE",
    "7000": "FOR_PARTS_OR_NOT_WORKING",
}


def build_inventory_item_payload(
    draft: Draft,
    settings: Settings,
    config: EffectiveEbayConfiguration | None = None,
) -> dict:
    aspects: dict[str, list[str]] = {}
    if draft.listing.brand.strip():
        aspects["Marke"] = [draft.listing.brand.strip()]
    if draft.listing.model.strip():
        aspects["Modell"] = [draft.listing.model.strip()]
    product_identifier_type = _string_attribute(draft, "product_identifier_type")
    product_identifier_value = _string_attribute(draft, "product_identifier_value")
    mpn_value = _mpn_value(draft, product_identifier_type, product_identifier_value)
    if product_identifier_type and product_identifier_value:
        aspects[product_identifier_type] = [product_identifier_value]
    if mpn_value:
        aspects.setdefault("Herstellernummer", [mpn_value])
    for detail in _string_list_attribute(draft, "keyTechnicalDetails"):
        if ":" not in detail:
            continue
        label, value = [part.strip() for part in detail.split(":", 1)]
        if label and value:
            aspects[label] = [value]
    for label, value in _ebay_aspects(draft).items():
        if label and value:
            aspects[label] = [value]

    product = {
        "title": draft.listing.title.strip(),
        "description": draft.listing.description_html.strip(),
        "imageUrls": list(draft.marketplace.ebay.image_urls),
    }
    if draft.listing.brand.strip():
        product["brand"] = draft.listing.brand.strip()
    if product_identifier_value and product_identifier_type.upper() in {"EAN", "GTIN"}:
        product["ean"] = [product_identifier_value]
    if mpn_value:
        product["mpn"] = mpn_value
    if aspects:
        product["aspects"] = aspects

    ship_to_location_availability: dict = {"quantity": 1}
    if config and config.merchant_location_key:
        ship_to_location_availability["availabilityDistributions"] = [
            {
                "merchantLocationKey": config.merchant_location_key,
                "quantity": 1,
            }
        ]

    return {
        "availability": {"shipToLocationAvailability": ship_to_location_availability},
        "condition": _string_attribute(draft, "ebay_condition_mapped") or _ebay_condition(draft) or map_condition(draft.listing.condition),
        "product": product,
    }


def build_offer_payload(draft: Draft, settings: Settings, config: EffectiveEbayConfiguration) -> dict:
    price = draft.listing.price_suggestion if draft.listing.price_suggestion is not None else DEFAULT_AUCTION_START_PRICE
    shipping_profile = normalize_shipping_profile(str(draft.listing.shipping_suggestion.get("profile") or ""))
    return {
        "sku": draft.sku,
        "marketplaceId": settings.ebay_marketplace_id,
        "format": "AUCTION",
        "listingDuration": DEFAULT_AUCTION_DURATION,
        "categoryId": draft.listing.category_suggestion.strip(),
        "merchantLocationKey": config.merchant_location_key,
        "listingPolicies": {
            "paymentPolicyId": config.payment_policy_id,
            "fulfillmentPolicyId": config.fulfillment_policy_id_for_profile(shipping_profile),
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


def choose_supported_condition(condition: str, condition_policy: dict | None) -> str:
    desired = map_condition(condition)
    supported = supported_condition_enums(condition_policy)
    if not supported or desired in supported:
        return desired

    lowered = condition.strip().casefold()
    if lowered in {"neu", "new"}:
        preference = ["NEW", "NEW_OTHER", "NEW_WITH_DEFECTS"]
    elif lowered in {"akzeptabel"}:
        preference = ["USED_ACCEPTABLE", "USED_GOOD", "USED_VERY_GOOD", "USED_EXCELLENT"]
    elif lowered in {"sehr gut"}:
        preference = ["USED_EXCELLENT", "USED_VERY_GOOD", "USED_GOOD", "USED_ACCEPTABLE"]
    else:
        preference = ["USED_GOOD", "USED_EXCELLENT", "USED_VERY_GOOD", "USED_ACCEPTABLE", "LIKE_NEW"]

    for candidate in preference:
        if candidate in supported:
            return candidate
    return supported[0]


def supported_condition_enums(condition_policy: dict | None) -> list[str]:
    if not isinstance(condition_policy, dict):
        return []
    item_conditions = condition_policy.get("itemConditions")
    if not isinstance(item_conditions, list):
        return []
    supported: list[str] = []
    for item in item_conditions:
        if not isinstance(item, dict):
            continue
        condition_id = str(item.get("conditionId") or "").strip()
        condition_enum = CONDITION_ID_TO_ENUM.get(condition_id)
        if condition_enum and condition_enum not in supported:
            supported.append(condition_enum)
    return supported


def _string_attribute(draft: Draft, key: str) -> str:
    value = draft.listing.attributes.get(key)
    return value.strip() if isinstance(value, str) else ""


def _string_list_attribute(draft: Draft, key: str) -> list[str]:
    value = draft.listing.attributes.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _ebay_aspects(draft: Draft) -> dict[str, str]:
    value = draft.listing.attributes.get("ebayAspects")
    if not isinstance(value, dict):
        return {}
    return {str(key).strip(): str(item).strip() for key, item in value.items() if str(key).strip() and str(item).strip()}


def _mpn_value(draft: Draft, product_identifier_type: str, product_identifier_value: str) -> str:
    identifier_type = product_identifier_type.upper()
    if product_identifier_value and identifier_type in {"MPN", "MODELL-NUMMER", "ARTIKELNUMMER"}:
        return product_identifier_value.strip()
    if draft.listing.model.strip() and draft.listing.brand.strip():
        return draft.listing.model.strip()
    return ""


def _ebay_condition(draft: Draft) -> str:
    value = draft.listing.attributes.get("ebayCondition")
    if not isinstance(value, dict):
        return ""
    mapped = value.get("mapped")
    return mapped.strip() if isinstance(mapped, str) else ""
