from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import Settings
from app.drafts.models import Draft, WorkflowStatus
from app.drafts.repository import DraftRepository
from app.drafts.workflow import transition_draft
from app.marketplaces.ebay.auth import has_usable_auth_tokens
from app.marketplaces.ebay.configuration import EbayConfigStore, validate_config_against_resources
from app.marketplaces.ebay.client import EbayApiError, EbayAuthError, EbayClient, EbayValidationError
from app.marketplaces.ebay.mapping import build_inventory_item_payload, build_offer_payload
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
        self.client = client or EbayClient(settings)
        self.config_store = config_store or EbayConfigStore(settings.database_path)

    def create_unpublished_offer_for_draft(self, draft_id: str) -> Draft:
        draft = self.repository.get_draft(draft_id)
        if draft is None:
            raise KeyError(f"Draft not found: {draft_id}")

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
            config_errors = validate_config_against_resources(
                effective_config,
                resources,
                self.settings.ebay_marketplace_id,
            )
            if config_errors:
                raise MarketplaceValidationError(config_errors)
            draft.marketplace.ebay.image_urls = self._upload_images(draft, access_token)

            inventory_payload = build_inventory_item_payload(draft, self.settings)
            self.client.create_or_replace_inventory_item(access_token, sku=draft.sku, payload=inventory_payload)

            offer_payload = build_offer_payload(draft, self.settings, effective_config)
            offer_response = self.client.create_offer(access_token, offer_payload)

            draft.marketplace.ebay.inventory_item_key = draft.sku
            draft.marketplace.ebay.offer_id = offer_response.get("offerId")
            draft.marketplace.ebay.inventory_item_data = inventory_payload
            draft.marketplace.ebay.offer_data = {**offer_payload, "response": offer_response}
            transition_draft(draft, WorkflowStatus.OFFER_CREATED)
            draft.workflow.missing_information = []
            self.repository.save_draft(draft)
            logger.info("eBay draft creation succeeded: draft_id=%s offer_id=%s", draft.id, draft.marketplace.ebay.offer_id)
            return draft
        except MarketplaceValidationError as exc:
            logger.warning("eBay draft blocked by validation: draft_id=%s errors=%s", draft.id, exc.errors)
            draft.workflow.status = WorkflowStatus.BLOCKED
            draft.workflow.missing_information = exc.errors
            draft.marketplace.ebay.offer_data["lastError"] = str(exc)
            self.repository.save_draft(draft)
            return draft
        except EbayAuthError as exc:
            logger.warning("eBay draft failed due to auth error: draft_id=%s error=%s", draft.id, exc)
            if isinstance(self.client, EbayClient) and self.client.auth_store is not None:
                self.client.auth_store.clear_tokens()
            draft.workflow.status = WorkflowStatus.READY_FOR_MARKETPLACE
            draft.workflow.missing_information = []
            draft.marketplace.ebay.offer_data["lastError"] = str(exc)
            self.repository.save_draft(draft)
            return draft
        except (EbayValidationError, EbayApiError) as exc:
            logger.warning("eBay draft failed due to API error: draft_id=%s error=%s", draft.id, exc)
            draft.workflow.status = WorkflowStatus.READY_FOR_MARKETPLACE
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

    def _resolve_storage_path(self, storage_path: str) -> Path:
        return (self.settings.project_dir / storage_path.lstrip("/")).resolve()


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
