from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.marketplaces.ebay.auth import EbayAuthStore, EbayTokenData, SCOPES


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
        refresh_token = stored_tokens.refresh_token or self.settings.ebay_refresh_token
        if refresh_token:
            token_data = self.exchange_refresh_token(refresh_token)
            if self.auth_store:
                self.auth_store.save_tokens(token_data)
            return EbayAccessToken(
                token=token_data.access_token or "",
                expires_in=token_data.expires_in,
                token_type=token_data.token_type,
            )

        access_token = stored_tokens.access_token or self.settings.ebay_access_token
        if access_token:
            return EbayAccessToken(token=access_token, token_type=stored_tokens.token_type)

        raise EbayAuthError("eBay credentials missing: access token or refresh token required")

    def exchange_refresh_token(self, refresh_token: str) -> EbayTokenData:
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
        self._raise_for_status(response, auth_failure_cls=EbayAuthError)
        payload = response.json()
        return EbayTokenData(
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token") or refresh_token,
            expires_in=payload.get("expires_in"),
            token_type=payload.get("token_type", "Bearer"),
        )

    def exchange_authorization_code(self, code: str) -> EbayTokenData:
        if not self.settings.ebay_ru_name:
            raise EbayAuthError("eBay Redirect-URI-ID (RuName) fehlt")
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
        self._raise_for_status(response, auth_failure_cls=EbayAuthError)
        payload = response.json()
        token_data = EbayTokenData(
            access_token=payload.get("access_token"),
            refresh_token=payload.get("refresh_token"),
            expires_in=payload.get("expires_in"),
            token_type=payload.get("token_type", "Bearer"),
        )
        if self.auth_store:
            self.auth_store.save_tokens(token_data)
        return token_data

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
