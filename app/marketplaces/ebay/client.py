from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings


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
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None):
        self.settings = settings
        self._client = client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def get_access_token(self) -> EbayAccessToken:
        if self.settings.ebay_refresh_token:
            response = self._client.post(
                f"{self.settings.ebay_api_base_url}/identity/v1/oauth2/token",
                auth=(self.settings.ebay_client_id or "", self.settings.ebay_client_secret or ""),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.settings.ebay_refresh_token,
                    "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory https://api.ebay.com/oauth/api_scope/sell.account",
                },
            )
            self._raise_for_status(response, auth_failure_cls=EbayAuthError)
            payload = response.json()
            return EbayAccessToken(
                token=payload["access_token"],
                expires_in=payload.get("expires_in"),
                token_type=payload.get("token_type", "Bearer"),
            )

        if self.settings.ebay_access_token:
            return EbayAccessToken(token=self.settings.ebay_access_token)

        raise EbayAuthError("eBay credentials missing: access token or refresh token required")

    def upload_image(self, access_token: EbayAccessToken, image_path: Path) -> dict[str, Any]:
        with image_path.open("rb") as handle:
            response = self._client.post(
                f"{self.settings.ebay_api_base_url}/commerce/media/v1_beta/image/create_from_file",
                headers={
                    "Authorization": f"{access_token.token_type} {access_token.token}",
                    "Content-Language": self.settings.ebay_content_language,
                },
                files={"image": (image_path.name, handle, _guess_mime_type(image_path))},
            )
        self._raise_for_status(response)
        return response.json()

    def create_or_replace_inventory_item(self, access_token: EbayAccessToken, *, sku: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.put(
            f"{self.settings.ebay_api_base_url}/sell/inventory/v1/inventory_item/{sku}",
            headers=self._api_headers(access_token),
            json=payload,
        )
        self._raise_for_status(response)
        return response.json() if response.content else {"sku": sku, "status": "updated"}

    def create_offer(self, access_token: EbayAccessToken, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            f"{self.settings.ebay_api_base_url}/sell/inventory/v1/offer",
            headers=self._api_headers(access_token),
            json=payload,
        )
        self._raise_for_status(response)
        return response.json()

    def _api_headers(self, access_token: EbayAccessToken) -> dict[str, str]:
        return {
            "Authorization": f"{access_token.token_type} {access_token.token}",
            "Content-Type": "application/json",
            "Content-Language": self.settings.ebay_content_language,
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, auth_failure_cls: type[Exception] | None = None) -> None:
        if response.status_code < 400:
            return
        message = _extract_error_message(response)
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
                messages.append(str(error.get("message") or error.get("longMessage") or "Unknown error"))
        if messages:
            return "; ".join(messages)

    description = payload.get("error_description") or payload.get("message")
    if isinstance(description, str) and description.strip():
        return description.strip()
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
