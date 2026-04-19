from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import unicodedata
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData, SCOPES, normalize_token_type
from app.marketplaces.ebay.configuration import EbayAccountResources

logger = logging.getLogger(__name__)


class EbayError(Exception):
    pass


class EbayValidationError(EbayError):
    pass


class EbayAuthError(EbayError):
    pass


class EbayApiError(EbayError):
    pass


@dataclass(slots=True)
class EbayAccessToken:
    token: str
    expires_in: int | None = None
    token_type: str = "Bearer"


class EbayClient:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None, auth_store: EbayAuthStore | None = None):
        self.settings = settings
        self._client = client or httpx.Client(timeout=30.0)
        self.auth_store = auth_store

    def close(self) -> None:
        self._client.close()

    def get_access_token(self) -> EbayAccessToken:
        stored_tokens = self.auth_store.get_tokens() if self.auth_store else EbayTokenData()
        refresh_token = stored_tokens.refresh_token
        if refresh_token:
            token_data = self.exchange_refresh_token(refresh_token)
            if self.auth_store:
                self.auth_store.save_tokens(token_data)
            return EbayAccessToken(
                token=token_data.access_token or "",
                expires_in=token_data.expires_in,
                token_type=normalize_token_type(token_data.token_type),
            )

        access_token = stored_tokens.access_token
        if access_token:
            return EbayAccessToken(token=access_token, token_type=normalize_token_type(stored_tokens.token_type))

        raise EbayAuthError("eBay credentials missing: access token or refresh token required")

    def exchange_refresh_token(self, refresh_token: str) -> EbayTokenData:
        logger.debug("Refreshing eBay access token via OAuth token endpoint")
        response = self._client.post(
            f"{self.settings.ebay_api_base_url}/identity/v1/oauth2/token",
            auth=(self.settings.ebay_client_id or "", self.settings.ebay_client_secret or ""),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": SCOPES,
            },
        )
        self._log_response("refresh_token_exchange", response)
        self._raise_for_status(response, auth_failure_cls=EbayAuthError)
        payload = response.json()
        return EbayTokenData(
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token") or refresh_token,
            expires_in=payload.get("expires_in"),
            token_type=normalize_token_type(payload.get("token_type")),
        )

    def exchange_authorization_code(self, code: str) -> EbayTokenData:
        if not self.settings.ebay_ru_name:
            raise EbayAuthError("eBay Redirect-URI-ID (RuName) fehlt")
        logger.debug("Exchanging eBay authorization code for tokens")
        response = self._client.post(
            f"{self.settings.ebay_api_base_url}/identity/v1/oauth2/token",
            auth=(self.settings.ebay_client_id or "", self.settings.ebay_client_secret or ""),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.settings.ebay_ru_name,
            },
        )
        self._log_response("authorization_code_exchange", response)
        self._raise_for_status(response, auth_failure_cls=EbayAuthError)
        payload = response.json()
        token_data = EbayTokenData(
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token"),
            expires_in=payload.get("expires_in"),
            token_type=normalize_token_type(payload.get("token_type")),
        )
        if self.auth_store:
            self.auth_store.save_tokens(token_data)
        return token_data

    def upload_image(self, access_token: EbayAccessToken, image_path: Path) -> dict[str, Any]:
        logger.debug("Uploading image to eBay media API: path=%s", image_path.name)
        with image_path.open("rb") as handle:
            response = self._client.post(
                f"{self.settings.ebay_api_base_url}/commerce/media/v1_beta/image/create_image_from_file",
                headers={
                    "Authorization": f"{access_token.token_type} {access_token.token}",
                    "Content-Language": self.settings.ebay_content_language,
                },
                files={"image": (image_path.name, handle, _guess_mime_type(image_path))},
            )
        self._log_response("upload_image", response)
        self._raise_for_status(response)
        return response.json()

    def create_or_replace_inventory_item(self, access_token: EbayAccessToken, *, sku: str, payload: dict[str, Any]) -> dict[str, Any]:
        logger.debug(
            "Creating/updating eBay inventory item: sku=%s payload_keys=%s",
            sku,
            sorted(payload.keys()),
        )
        response = self._client.put(
            f"{self.settings.ebay_api_base_url}/sell/inventory/v1/inventory_item/{sku}",
            headers=self._api_headers(access_token),
            json=payload,
        )
        self._log_response("create_or_replace_inventory_item", response)
        self._raise_for_status(response)
        return response.json() if response.content else {"sku": sku, "status": "updated"}

    def create_offer(self, access_token: EbayAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        logger.debug(
            "Creating eBay offer: sku=%s category_id=%s policy_ids=%s merchant_location=%s",
            payload.get("sku"),
            payload.get("categoryId"),
            payload.get("listingPolicies"),
            payload.get("merchantLocationKey"),
        )
        response = self._client.post(
            f"{self.settings.ebay_api_base_url}/sell/inventory/v1/offer",
            headers=self._api_headers(access_token),
            json=payload,
        )
        self._log_response("create_offer", response)
        self._raise_for_status(response)
        return response.json()

    def get_account_resources(self, access_token: EbayAccessToken) -> EbayAccountResources:
        payment_payload = self._get_labeled(
            access_token,
            label="Payment Policies",
            url=f"{self.settings.ebay_api_base_url}/sell/account/v1/payment_policy",
            params={"marketplace_id": self.settings.ebay_marketplace_id},
        )
        fulfillment_payload = self._get_labeled(
            access_token,
            label="Fulfillment Policies",
            url=f"{self.settings.ebay_api_base_url}/sell/account/v1/fulfillment_policy",
            params={"marketplace_id": self.settings.ebay_marketplace_id},
        )
        return_payload = self._get_labeled(
            access_token,
            label="Return Policies",
            url=f"{self.settings.ebay_api_base_url}/sell/account/v1/return_policy",
            params={"marketplace_id": self.settings.ebay_marketplace_id},
        )
        location_payload = self._get_labeled(
            access_token,
            label="Merchant Locations",
            url=f"{self.settings.ebay_api_base_url}/sell/inventory/v1/location",
        )
        return EbayAccountResources(
            payment_policies=[
                {"id": str(item.get("paymentPolicyId") or ""), "name": str(item.get("name") or "")}
                for item in payment_payload.get("paymentPolicies", [])
                if isinstance(item, dict) and item.get("paymentPolicyId")
            ],
            fulfillment_policies=[
                {"id": str(item.get("fulfillmentPolicyId") or ""), "name": str(item.get("name") or "")}
                for item in fulfillment_payload.get("fulfillmentPolicies", [])
                if isinstance(item, dict) and item.get("fulfillmentPolicyId")
            ],
            return_policies=[
                {"id": str(item.get("returnPolicyId") or ""), "name": str(item.get("name") or "")}
                for item in return_payload.get("returnPolicies", [])
                if isinstance(item, dict) and item.get("returnPolicyId")
            ],
            merchant_locations=[
                {
                    "key": str(item.get("merchantLocationKey") or ""),
                    "name": str(item.get("name") or item.get("merchantLocationKey") or ""),
                    "status": str(item.get("merchantLocationStatus") or ""),
                }
                for item in location_payload.get("locations", [])
                if isinstance(item, dict) and item.get("merchantLocationKey")
            ],
        )

    def get_opted_in_programs(self, access_token: EbayAccessToken) -> list[str]:
        payload = self._get_labeled(
            access_token,
            label="Seller-Programme",
            url=f"{self.settings.ebay_api_base_url}/sell/account/v1/program/get_opted_in_programs",
        )
        programs = payload.get("programs", [])
        return [
            str(item.get("programType"))
            for item in programs
            if isinstance(item, dict) and item.get("programType")
        ]

    def opt_in_to_program(self, access_token: EbayAccessToken, program_type: str) -> None:
        response = self._client.post(
            f"{self.settings.ebay_api_base_url}/sell/account/v1/program/opt_in",
            headers=self._api_headers(access_token),
            json={"programType": program_type},
        )
        self._log_response("opt_in_to_program", response)
        self._raise_for_status(response)

    def create_inventory_location(self, access_token: EbayAccessToken, *, merchant_location_key: str, payload: dict[str, Any]) -> None:
        logger.debug(
            "Creating eBay inventory location: merchant_location_key=%s payload_keys=%s",
            merchant_location_key,
            sorted(payload.keys()),
        )
        response = self._client.post(
            f"{self.settings.ebay_api_base_url}/sell/inventory/v1/location/{merchant_location_key}",
            headers=self._api_headers(access_token),
            json=payload,
        )
        self._log_response("create_inventory_location", response)
        self._raise_for_status(response)

    def get_shipping_services(self, access_token: EbayAccessToken) -> list[dict[str, Any]]:
        payload = self._get_labeled(
            access_token,
            label="Versandservices",
            url=f"{self.settings.ebay_api_base_url}/sell/metadata/v1/shipping/marketplace/{self.settings.ebay_marketplace_id}/get_shipping_services",
        )
        services = payload.get("shippingServices", [])
        return [item for item in services if isinstance(item, dict)]

    def create_payment_policy(self, access_token: EbayAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_labeled(
            access_token,
            label="Payment Policy",
            url=f"{self.settings.ebay_api_base_url}/sell/account/v1/payment_policy",
            payload=payload,
        )

    def create_return_policy(self, access_token: EbayAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_labeled(
            access_token,
            label="Return Policy",
            url=f"{self.settings.ebay_api_base_url}/sell/account/v1/return_policy",
            payload=payload,
        )

    def create_fulfillment_policy(self, access_token: EbayAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json_labeled(
            access_token,
            label="Fulfillment Policy",
            url=f"{self.settings.ebay_api_base_url}/sell/account/v1/fulfillment_policy",
            payload=payload,
        )

    def _api_headers(self, access_token: EbayAccessToken) -> dict[str, str]:
        return {
            "Authorization": f"{access_token.token_type} {access_token.token}",
            "Content-Type": "application/json",
            "Content-Language": self.settings.ebay_content_language,
        }

    def _api_get_headers(self, access_token: EbayAccessToken) -> dict[str, str]:
        return {
            "Authorization": f"{access_token.token_type} {access_token.token}",
        }

    def _get(self, access_token: EbayAccessToken, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        logger.debug("Calling eBay GET endpoint: url=%s params=%s", url, params or {})
        response = self._client.get(url, headers=self._api_get_headers(access_token), params=params)
        self._log_response("get_request", response)
        self._raise_for_status(response)
        return response.json()

    def _post_json_labeled(
        self,
        access_token: EbayAccessToken,
        *,
        label: str,
        url: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        logger.debug("Calling eBay POST endpoint: label=%s url=%s payload_keys=%s", label, url, sorted(payload.keys()))
        response = self._client.post(url, headers=self._api_headers(access_token), json=payload)
        self._log_response("post_request", response)
        try:
            self._raise_for_status(response)
        except (EbayValidationError, EbayApiError) as exc:
            raise type(exc)(f"{label} konnte nicht angelegt werden: {exc}") from exc
        if not response.content:
            return {}
        return response.json()

    def _get_labeled(
        self,
        access_token: EbayAccessToken,
        *,
        label: str,
        url: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._get(access_token, url, params=params)
        except (EbayValidationError, EbayApiError) as exc:
            raise type(exc)(f"{label} konnten nicht geladen werden: {exc}") from exc

    def _log_response(self, operation: str, response: httpx.Response) -> None:
        if response.status_code < 400:
            logger.debug(
                "eBay response ok: operation=%s status=%s url=%s",
                operation,
                response.status_code,
                response.request.url,
            )
            return
        logger.warning(
            "eBay response error: operation=%s status=%s url=%s body=%s",
            operation,
            response.status_code,
            response.request.url,
            _safe_response_excerpt(response),
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, auth_failure_cls: type[Exception] | None = None) -> None:
        if response.status_code < 400:
            return
        message = _extract_error_message(response)
        if auth_failure_cls is not None and response.status_code == 400:
            raise auth_failure_cls(message)
        if response.status_code in {401, 403}:
            raise (auth_failure_cls or EbayAuthError)(message)
        if response.status_code in {400, 409, 422}:
            raise EbayValidationError(message)
        raise EbayApiError(message)


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return f"eBay API error ({response.status_code})"

    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        messages = []
        for error in errors:
            if isinstance(error, dict):
                parts = [
                    str(error.get("message") or "").strip(),
                    str(error.get("longMessage") or "").strip(),
                    str(error.get("errorId") or "").strip(),
                ]
                if isinstance(error.get("inputRefIds"), list) and error["inputRefIds"]:
                    parts.append(f"Felder: {', '.join(str(item) for item in error['inputRefIds'])}")
                message = " | ".join(part for part in parts if part)
                if message:
                    messages.append(message)
        if messages:
            return "; ".join(messages)

    parts = [
        str(payload.get("error_description") or "").strip(),
        str(payload.get("message") or "").strip(),
        str(payload.get("error") or "").strip(),
        str(payload.get("errorId") or "").strip(),
    ]
    description = " | ".join(part for part in parts if part)
    if description:
        return description
    return f"eBay API error ({response.status_code})"


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _safe_response_excerpt(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        text = response.text.strip()
        return text[:500]
    sanitized = _sanitize_payload(payload)
    return json.dumps(sanitized, ensure_ascii=False)[:800]


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(secret_key in lowered for secret_key in ("token", "authorization", "secret")):
                sanitized[key] = "***"
            else:
                sanitized[key] = _sanitize_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    return value


def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_only.lower() if ch.isalnum())
