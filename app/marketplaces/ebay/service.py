from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import Settings
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.repository import DraftRepository
from app.drafts.rendering import refresh_listing_description
from app.drafts.workflow import transition_draft
from app.marketplaces.ebay.auth import EbayAuthStore, has_usable_auth_tokens
from app.marketplaces.ebay.configuration import (
    DEFAULT_SHIPPING_PROFILE,
    PAYMENT_POLICY_NAME,
    RETURN_POLICY_NAME,
    SHIPPING_PROFILES,
    EbayAccountResources,
    EbayConfigStore,
    normalize_shipping_profile,
    validate_config_against_resources,
)
from app.marketplaces.ebay.client import EbayApiError, EbayAuthError, EbayClient, EbayOfferAlreadyExistsError, EbayValidationError
from app.marketplaces.ebay.mapping import build_inventory_item_payload, build_offer_payload, choose_supported_condition
from app.marketplaces.ebay.validation import MarketplaceValidationError, validate_marketplace_ready

logger = logging.getLogger(__name__)


class EbayMarketplaceService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: DraftRepository,
        client: EbayClient | None = None,
        config_store: EbayConfigStore | None = None,
    ):
        self.settings = settings
        self.repository = repository
        auth_store = EbayAuthStore(settings.database_path, mode=settings.ebay_mode)
        self.client = client or EbayClient(settings, auth_store=auth_store)
        self.config_store = config_store or EbayConfigStore(settings.database_path, mode=settings.ebay_mode)

    def create_unpublished_offer_for_draft(self, draft_id: str) -> Draft:
        draft = self.repository.get_draft(draft_id)
        if draft is None:
            raise KeyError(f"Draft not found: {draft_id}")
        refresh_listing_description(draft)

        try:
            logger.debug("Starting eBay draft creation: draft_id=%s sku=%s", draft.id, draft.sku)
            auth_connected = False
            if isinstance(self.client, EbayClient) and self.client.auth_store is not None:
                tokens = self.client.auth_store.get_tokens()
                auth_connected = has_usable_auth_tokens(tokens)
            elif not isinstance(self.client, EbayClient):
                auth_connected = True

            effective_config = self.config_store.get_effective_configuration()
            validate_marketplace_ready(draft, effective_config, auth_connected=auth_connected)
            access_token = self.client.get_access_token()
            resources = self.client.get_account_resources(access_token)
            self.config_store.save_discovered_resources(resources)
            resources = self._ensure_default_account_policies(access_token, resources)
            effective_config = self.config_store.get_effective_configuration()
            config_errors = validate_config_against_resources(
                effective_config,
                resources,
                self.settings.ebay_marketplace_id,
            )
            if config_errors:
                raise MarketplaceValidationError(config_errors)
            draft.marketplace.ebay.image_urls = self._ensure_image_urls(draft, access_token)
            condition_policy = self.client.get_item_condition_policies(
                access_token,
                category_id=draft.listing.category_suggestion.strip(),
            )
            self._apply_supported_condition(draft, condition_policy)

            inventory_payload = build_inventory_item_payload(draft, self.settings, effective_config)
            draft.marketplace.ebay.inventory_item_data = inventory_payload
            self.client.create_or_replace_inventory_item(access_token, sku=draft.sku, payload=inventory_payload)

            offer_payload = build_offer_payload(draft, self.settings, effective_config)
            if draft.marketplace.ebay.offer_id:
                offer_response = self.client.update_offer(
                    access_token,
                    offer_id=draft.marketplace.ebay.offer_id,
                    payload=offer_payload,
                )
                offer_response.setdefault("offerId", draft.marketplace.ebay.offer_id)
            else:
                try:
                    offer_response = self.client.create_offer(access_token, offer_payload)
                except EbayOfferAlreadyExistsError as exc:
                    offer_response = {"offerId": exc.offer_id, "status": "already_exists"}

            draft.marketplace.ebay.inventory_item_key = draft.sku
            draft.marketplace.ebay.offer_id = offer_response.get("offerId")
            draft.marketplace.ebay.offer_data = {**offer_payload, "response": offer_response}
            transition_draft(draft, WorkflowStatus.OFFER_CREATED)
            draft.workflow.missing_information = []
            self.repository.save_draft(draft)
            logger.info("eBay draft creation succeeded: draft_id=%s offer_id=%s", draft.id, draft.marketplace.ebay.offer_id)
            return draft
        except MarketplaceValidationError as exc:
            logger.warning("eBay draft blocked by validation: draft_id=%s errors=%s", draft.id, exc.errors)
            draft.workflow.missing_information = exc.errors
            draft.marketplace.ebay.offer_data["lastError"] = str(exc)
            self.repository.save_draft(draft)
            return draft
        except EbayAuthError as exc:
            logger.warning("eBay draft failed due to auth error: draft_id=%s error=%s", draft.id, exc)
            if isinstance(self.client, EbayClient) and self.client.auth_store is not None:
                self.client.auth_store.clear_tokens()
            draft.workflow.missing_information = []
            draft.marketplace.ebay.offer_data["lastError"] = str(exc)
            self.repository.save_draft(draft)
            return draft
        except (EbayValidationError, EbayApiError) as exc:
            logger.warning("eBay draft failed due to API error: draft_id=%s error=%s", draft.id, exc)
            draft.workflow.missing_information = []
            draft.marketplace.ebay.offer_data["lastError"] = str(exc)
            self.repository.save_draft(draft)
            return draft

    def publish_offer_for_draft(self, draft_id: str) -> Draft:
        draft = self.repository.get_draft(draft_id)
        if draft is None:
            raise KeyError(f"Draft not found: {draft_id}")

        try:
            if not draft.marketplace.ebay.offer_id:
                raise MarketplaceValidationError(["eBay-Angebot wurde noch nicht vorbereitet"])
            self.create_unpublished_offer_for_draft(draft_id)
            draft = self.repository.get_draft(draft_id) or draft
            if draft.marketplace.ebay.offer_data.get("lastError"):
                raise MarketplaceValidationError([str(draft.marketplace.ebay.offer_data["lastError"])])
            access_token = self.client.get_access_token()
            publish_response = self.client.publish_offer(access_token, draft.marketplace.ebay.offer_id)
            draft.marketplace.ebay.listing_id = str(publish_response.get("listingId") or "").strip() or None
            draft.marketplace.ebay.offer_data["publishResponse"] = publish_response
            draft.marketplace.ebay.offer_data.pop("lastError", None)
            if draft.workflow.status is not WorkflowStatus.OFFER_CREATED:
                transition_draft(draft, WorkflowStatus.OFFER_CREATED)
            transition_draft(draft, WorkflowStatus.PUBLISHED)
            draft.workflow.missing_information = []
            self.repository.save_draft(draft)
            logger.info(
                "eBay offer published: draft_id=%s offer_id=%s listing_id=%s",
                draft.id,
                draft.marketplace.ebay.offer_id,
                draft.marketplace.ebay.listing_id,
            )
            return draft
        except MarketplaceValidationError as exc:
            logger.warning("eBay publish blocked by validation: draft_id=%s errors=%s", draft.id, exc.errors)
            draft.workflow.missing_information = exc.errors
            draft.marketplace.ebay.offer_data["lastError"] = str(exc)
            self.repository.save_draft(draft)
            return draft
        except EbayAuthError as exc:
            logger.warning("eBay publish failed due to auth error: draft_id=%s error=%s", draft.id, exc)
            if isinstance(self.client, EbayClient) and self.client.auth_store is not None:
                self.client.auth_store.clear_tokens()
            draft.workflow.missing_information = []
            draft.marketplace.ebay.offer_data["lastError"] = str(exc)
            self.repository.save_draft(draft)
            return draft
        except (EbayValidationError, EbayApiError) as exc:
            logger.warning("eBay publish failed due to API error: draft_id=%s error=%s", draft.id, exc)
            draft.workflow.missing_information = []
            draft.marketplace.ebay.offer_data["lastError"] = str(exc)
            self.repository.save_draft(draft)
            return draft

    def _upload_images(self, draft: Draft, access_token) -> list[str]:
        uploads: list[dict] = []
        image_urls: list[str] = []
        for image in draft.source.images:
            image_path = self._resolve_storage_path(image.storage_path)
            response = self.client.upload_image(access_token, image_path)
            uploads.append(response)
            image_url = _extract_image_url(response)
            if image_url:
                image_urls.append(image_url)

        draft.marketplace.ebay.inventory_item_data["imageUploads"] = uploads
        if not image_urls:
            raise MarketplaceValidationError(["Keine eBay-Bild-URLs aus den lokalen Bildern ableitbar"])
        return image_urls

    def _ensure_image_urls(self, draft: Draft, access_token) -> list[str]:
        if len(draft.marketplace.ebay.image_urls) >= len(draft.source.images) and draft.marketplace.ebay.image_urls:
            logger.debug(
                "Reusing existing eBay image URLs: draft_id=%s image_count=%s",
                draft.id,
                len(draft.marketplace.ebay.image_urls),
            )
            return list(draft.marketplace.ebay.image_urls)
        return self._upload_images(draft, access_token)

    def _apply_supported_condition(self, draft: Draft, condition_policy: dict) -> None:
        supported_condition = choose_supported_condition(draft.listing.condition, condition_policy)
        draft.listing.attributes["ebayCondition"] = {
            "input": draft.listing.condition.strip(),
            "mapped": supported_condition,
            "policy": condition_policy,
        }

    def _resolve_storage_path(self, storage_path: str) -> Path:
        return (self.settings.project_dir / storage_path.lstrip("/")).resolve()

    def _ensure_default_account_policies(self, access_token, resources: EbayAccountResources) -> EbayAccountResources:
        policy_ids = _shipping_profile_policy_ids(resources)
        payment_policy_id = _find_resource_id_by_name(resources.payment_policies, PAYMENT_POLICY_NAME)
        return_policy_id = _find_resource_id_by_name(resources.return_policies, RETURN_POLICY_NAME)

        if payment_policy_id and return_policy_id and len(policy_ids) == len(SHIPPING_PROFILES):
            self.config_store.save_selected_configuration(
                payment_policy_id=payment_policy_id,
                fulfillment_policy_id=policy_ids.get(DEFAULT_SHIPPING_PROFILE),
                return_policy_id=return_policy_id,
            )
            self.config_store.save_shipping_profile_policy_ids(policy_ids)
            return resources

        shipping_services = self.client.get_shipping_services(access_token)
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
            raise MarketplaceValidationError(["DHL-Versandservices konnten bei eBay nicht automatisch aufgelöst werden"])

        if not payment_policy_id:
            _create_ignore_duplicate(
                lambda: self.client.create_payment_policy(
                    access_token,
                    {
                        "name": PAYMENT_POLICY_NAME,
                        "marketplaceId": self.settings.ebay_marketplace_id,
                        "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
                        "immediatePay": False,
                    },
                )
            )
        if not return_policy_id:
            _create_ignore_duplicate(
                lambda: self.client.create_return_policy(
                    access_token,
                    {
                        "name": RETURN_POLICY_NAME,
                        "marketplaceId": self.settings.ebay_marketplace_id,
                        "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
                        "returnsAccepted": False,
                        "description": "Privatverkauf ohne Rücknahme und Gewährleistung.",
                    },
                )
            )

        for profile_key, payload in _build_open_inserto_fulfillment_policy_payloads(
            marketplace_id=self.settings.ebay_marketplace_id,
            currency=self.settings.ebay_currency,
            dhl_paket_code=dhl_paket,
            dhl_paeckchen_code=dhl_paeckchen,
        ).items():
            if profile_key not in policy_ids:
                _create_ignore_duplicate(lambda payload=payload: self.client.create_fulfillment_policy(access_token, payload))

        resources = self.client.get_account_resources(access_token)
        self.config_store.save_discovered_resources(resources)
        policy_ids = _shipping_profile_policy_ids(resources)
        self.config_store.save_shipping_profile_policy_ids(policy_ids)
        self.config_store.save_selected_configuration(
            payment_policy_id=_find_resource_id_by_name(resources.payment_policies, PAYMENT_POLICY_NAME),
            fulfillment_policy_id=policy_ids.get(DEFAULT_SHIPPING_PROFILE),
            return_policy_id=_find_resource_id_by_name(resources.return_policies, RETURN_POLICY_NAME),
        )
        return resources


def _extract_image_url(response: dict) -> str | None:
    direct = response.get("imageUrl")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    image = response.get("image")
    if isinstance(image, dict):
        nested = image.get("imageUrl")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    location = response.get("location")
    if isinstance(location, str) and location.strip():
        return location.strip()
    return None


def _shipping_profile_policy_ids(resources: EbayAccountResources) -> dict[str, str]:
    return {
        key: policy_id
        for key, profile in SHIPPING_PROFILES.items()
        if (policy_id := _find_resource_id_by_name(resources.fulfillment_policies, profile["policy_name"]))
    }


def _find_resource_id_by_name(resources: list[dict[str, str]], expected_name: str) -> str | None:
    for item in resources:
        if item.get("name") == expected_name:
            value = item.get("id")
            if value:
                return value
    return None


def _create_ignore_duplicate(create_call) -> None:
    try:
        create_call()
    except EbayValidationError as exc:
        if not _is_duplicate_policy_error(exc):
            raise


def _is_duplicate_policy_error(exc: EbayValidationError) -> bool:
    message = str(exc).lower()
    return (
        "duplicate policy" in message
        or "already exists" in message
        or "doppelt vorhanden" in message
        or "20400" in message
    )


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


def _find_shipping_service_code(services: list[dict[str, object]], search_terms: list[str]) -> str | None:
    from app.marketplaces.ebay.client import normalize_search_text

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
