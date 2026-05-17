from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.db.base import get_connection


PAYMENT_POLICY_NAME = "Open Inserto - Auktion"
RETURN_POLICY_NAME = "Open Inserto - Keine Rücknahme"

SHIPPING_PROFILES = {
    "dhl_2kg": {
        "label": "DHL 2kg Paket + Päckchen M",
        "policy_name": "Open Inserto - DHL 2kg Paket + Päckchen M",
        "description": "Primär DHL Paket 2kg für 6,19 EUR, zusätzlich DHL Päckchen M 2kg für 5,19 EUR.",
    },
    "dhl_5kg": {
        "label": "DHL 5kg Paket",
        "policy_name": "Open Inserto - DHL 5kg Paket",
        "description": "DHL Paket 5kg für 7,69 EUR.",
    },
    "dhl_10kg": {
        "label": "DHL 10kg Paket",
        "policy_name": "Open Inserto - DHL 10kg Paket",
        "description": "DHL Paket 10kg für 10,49 EUR.",
    },
    "dhl_20kg": {
        "label": "DHL 20kg Paket",
        "policy_name": "Open Inserto - DHL 20kg Paket",
        "description": "DHL Paket 20kg für 18,99 EUR.",
    },
    "pickup": {
        "label": "Nur Selbstabholung",
        "policy_name": "Open Inserto - Selbstabholung",
        "description": "Für sperrige Artikel ohne Versand.",
    },
}
DEFAULT_SHIPPING_PROFILE = "dhl_2kg"


SELECTION_KEYS = {
    "payment_policy_id": "ebay_selected_payment_policy_id",
    "fulfillment_policy_id": "ebay_selected_fulfillment_policy_id",
    "return_policy_id": "ebay_selected_return_policy_id",
    "merchant_location_key": "ebay_selected_merchant_location_key",
    "shipping_profile_policy_ids": "ebay_selected_shipping_profile_policy_ids",
}

DISCOVERY_KEYS = {
    "payment_policies": "ebay_discovered_payment_policies",
    "fulfillment_policies": "ebay_discovered_fulfillment_policies",
    "return_policies": "ebay_discovered_return_policies",
    "merchant_locations": "ebay_discovered_merchant_locations",
}


@dataclass(slots=True)
class EffectiveEbayConfiguration:
    payment_policy_id: str | None = None
    fulfillment_policy_id: str | None = None
    return_policy_id: str | None = None
    merchant_location_key: str | None = None
    shipping_profile_policy_ids: dict[str, str] = None

    def __post_init__(self) -> None:
        self.shipping_profile_policy_ids = dict(self.shipping_profile_policy_ids or {})

    def fulfillment_policy_id_for_profile(self, profile_key: str | None) -> str | None:
        key = normalize_shipping_profile(profile_key)
        if key in self.shipping_profile_policy_ids:
            return self.shipping_profile_policy_ids[key]
        if key == DEFAULT_SHIPPING_PROFILE:
            return self.fulfillment_policy_id
        return None


@dataclass(slots=True)
class EbayAccountResources:
    payment_policies: list[dict[str, str]] = None
    fulfillment_policies: list[dict[str, str]] = None
    return_policies: list[dict[str, str]] = None
    merchant_locations: list[dict[str, str]] = None

    def __post_init__(self) -> None:
        self.payment_policies = list(self.payment_policies or [])
        self.fulfillment_policies = list(self.fulfillment_policies or [])
        self.return_policies = list(self.return_policies or [])
        self.merchant_locations = list(self.merchant_locations or [])


class EbayConfigStore:
    def __init__(self, database_path, *, mode: str = "sandbox"):
        self.database_path = database_path
        self.mode = mode

    def _key(self, meta_key: str) -> str:
        return f"ebay_{self.mode}_{meta_key.removeprefix('ebay_')}"

    def get_effective_configuration(self) -> EffectiveEbayConfiguration:
        return self.get_selected_configuration()

    def get_selected_configuration(self) -> EffectiveEbayConfiguration:
        keys = {field: self._key(meta_key) for field, meta_key in SELECTION_KEYS.items()}
        values = self._get_values(tuple(keys.values()))
        if not values and self.mode == "sandbox":
            values = self._get_values(tuple(SELECTION_KEYS.values()))
            keys = SELECTION_KEYS
        return EffectiveEbayConfiguration(
            payment_policy_id=_clean(values.get(keys["payment_policy_id"])),
            fulfillment_policy_id=_clean(values.get(keys["fulfillment_policy_id"])),
            return_policy_id=_clean(values.get(keys["return_policy_id"])),
            merchant_location_key=_clean(values.get(keys["merchant_location_key"])),
            shipping_profile_policy_ids=_load_string_dict(values.get(keys["shipping_profile_policy_ids"])),
        )

    def save_selected_configuration(self, **values: str | None) -> None:
        items: list[tuple[str, str]] = []
        for field, meta_key in SELECTION_KEYS.items():
            if field not in values:
                continue
            value = values[field]
            if field == "shipping_profile_policy_ids" and isinstance(value, dict):
                items.append((self._key(meta_key), json.dumps(value, ensure_ascii=False)))
            else:
                items.append((self._key(meta_key), value or ""))
        if not items:
            return
        with get_connection(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO app_meta(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                items,
            )
            connection.commit()

    def save_discovered_resources(self, resources: EbayAccountResources) -> None:
        items = [
            (self._key(DISCOVERY_KEYS["payment_policies"]), json.dumps(resources.payment_policies, ensure_ascii=False)),
            (self._key(DISCOVERY_KEYS["fulfillment_policies"]), json.dumps(resources.fulfillment_policies, ensure_ascii=False)),
            (self._key(DISCOVERY_KEYS["return_policies"]), json.dumps(resources.return_policies, ensure_ascii=False)),
            (self._key(DISCOVERY_KEYS["merchant_locations"]), json.dumps(resources.merchant_locations, ensure_ascii=False)),
        ]
        with get_connection(self.database_path) as connection:
            connection.executemany(
                """
                INSERT INTO app_meta(key, value)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                items,
            )
            connection.commit()

    def get_discovered_resources(self) -> EbayAccountResources:
        keys = {field: self._key(meta_key) for field, meta_key in DISCOVERY_KEYS.items()}
        values = self._get_values(tuple(keys.values()))
        if not values and self.mode == "sandbox":
            values = self._get_values(tuple(DISCOVERY_KEYS.values()))
            keys = DISCOVERY_KEYS
        return EbayAccountResources(
            payment_policies=_load_json_list(values.get(keys["payment_policies"])),
            fulfillment_policies=_load_json_list(values.get(keys["fulfillment_policies"])),
            return_policies=_load_json_list(values.get(keys["return_policies"])),
            merchant_locations=_load_json_list(values.get(keys["merchant_locations"])),
        )

    def auto_select_defaults(self, resources: EbayAccountResources) -> EffectiveEbayConfiguration:
        effective = self.get_effective_configuration()
        updates: dict[str, str] = {}

        if not effective.payment_policy_id and len(resources.payment_policies) == 1:
            updates["payment_policy_id"] = resources.payment_policies[0]["id"]
        if not effective.fulfillment_policy_id and len(resources.fulfillment_policies) == 1:
            updates["fulfillment_policy_id"] = resources.fulfillment_policies[0]["id"]
        if not effective.return_policy_id and len(resources.return_policies) == 1:
            updates["return_policy_id"] = resources.return_policies[0]["id"]
        if not effective.merchant_location_key and len(resources.merchant_locations) == 1:
            updates["merchant_location_key"] = resources.merchant_locations[0]["key"]

        if updates:
            self.save_selected_configuration(**updates)
        return self.get_effective_configuration()

    def save_shipping_profile_policy_ids(self, policy_ids: dict[str, str]) -> None:
        cleaned = {
            normalize_shipping_profile(key): value.strip()
            for key, value in policy_ids.items()
            if normalize_shipping_profile(key) in SHIPPING_PROFILES and isinstance(value, str) and value.strip()
        }
        if cleaned:
            self.save_selected_configuration(shipping_profile_policy_ids=cleaned)

    def _get_values(self, keys: tuple[str, ...]) -> dict[str, str]:
        if not keys:
            return {}
        placeholders = ", ".join("?" for _ in keys)
        try:
            with get_connection(self.database_path) as connection:
                rows = connection.execute(
                    f"SELECT key, value FROM app_meta WHERE key IN ({placeholders})",
                    keys,
                ).fetchall()
        except sqlite3.OperationalError:
            return {}
        return {row["key"]: row["value"] for row in rows}


def validate_config_against_resources(config: EffectiveEbayConfiguration, resources: EbayAccountResources, marketplace_id: str) -> list[str]:
    errors: list[str] = []

    _validate_selection(
        errors,
        label="Payment Policy",
        selected_value=config.payment_policy_id,
        options=resources.payment_policies,
        option_id_key="id",
        empty_message=f"Im verbundenen eBay-Account existiert keine Payment Policy für {marketplace_id}",
    )
    _validate_selection(
        errors,
        label="Fulfillment Policy",
        selected_value=config.fulfillment_policy_id,
        options=resources.fulfillment_policies,
        option_id_key="id",
        empty_message=f"Im verbundenen eBay-Account existiert keine Fulfillment Policy für {marketplace_id}",
    )
    _validate_selection(
        errors,
        label="Return Policy",
        selected_value=config.return_policy_id,
        options=resources.return_policies,
        option_id_key="id",
        empty_message=f"Im verbundenen eBay-Account existiert keine Return Policy für {marketplace_id}",
    )
    _validate_selection(
        errors,
        label="Merchant Location",
        selected_value=config.merchant_location_key,
        options=resources.merchant_locations,
        option_id_key="key",
        empty_message="Im verbundenen eBay-Account existiert keine Merchant Location",
    )
    if config.merchant_location_key:
        selected_location = next(
            (item for item in resources.merchant_locations if item.get("key") == config.merchant_location_key),
            None,
        )
        if selected_location and selected_location.get("status") and selected_location.get("status") != "ENABLED":
            errors.append(f"Merchant Location '{config.merchant_location_key}' ist im verbundenen eBay-Account nicht aktiviert")
    return errors


def _validate_selection(
    errors: list[str],
    *,
    label: str,
    selected_value: str | None,
    options: list[dict[str, str]],
    option_id_key: str,
    empty_message: str,
) -> None:
    if not options:
        errors.append(empty_message)
        return
    if not selected_value:
        errors.append(f"{label} ist nicht konfiguriert")
        return
    available_values = {item.get(option_id_key) for item in options}
    if selected_value not in available_values:
        errors.append(f"{label} '{selected_value}' existiert im verbundenen eBay-Account nicht")


def _load_json_list(raw: str | None) -> list[dict[str, str]]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _load_string_dict(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items() if str(value).strip()}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_shipping_profile(value: str | None) -> str:
    key = (value or "").strip()
    if key in SHIPPING_PROFILES:
        return key
    return DEFAULT_SHIPPING_PROFILE
