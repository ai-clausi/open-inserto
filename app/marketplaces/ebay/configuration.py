from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.db.base import get_connection


SELECTION_KEYS = {
    "payment_policy_id": "ebay_selected_payment_policy_id",
    "fulfillment_policy_id": "ebay_selected_fulfillment_policy_id",
    "return_policy_id": "ebay_selected_return_policy_id",
    "merchant_location_key": "ebay_selected_merchant_location_key",
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
    def __init__(self, database_path):
        self.database_path = database_path

    def get_effective_configuration(self) -> EffectiveEbayConfiguration:
        return self.get_selected_configuration()

    def get_selected_configuration(self) -> EffectiveEbayConfiguration:
        values = self._get_values(tuple(SELECTION_KEYS.values()))
        return EffectiveEbayConfiguration(
            payment_policy_id=_clean(values.get(SELECTION_KEYS["payment_policy_id"])),
            fulfillment_policy_id=_clean(values.get(SELECTION_KEYS["fulfillment_policy_id"])),
            return_policy_id=_clean(values.get(SELECTION_KEYS["return_policy_id"])),
            merchant_location_key=_clean(values.get(SELECTION_KEYS["merchant_location_key"])),
        )

    def save_selected_configuration(self, **values: str | None) -> None:
        items: list[tuple[str, str]] = []
        for field, meta_key in SELECTION_KEYS.items():
            if field not in values:
                continue
            items.append((meta_key, values[field] or ""))
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
            (DISCOVERY_KEYS["payment_policies"], json.dumps(resources.payment_policies, ensure_ascii=False)),
            (DISCOVERY_KEYS["fulfillment_policies"], json.dumps(resources.fulfillment_policies, ensure_ascii=False)),
            (DISCOVERY_KEYS["return_policies"], json.dumps(resources.return_policies, ensure_ascii=False)),
            (DISCOVERY_KEYS["merchant_locations"], json.dumps(resources.merchant_locations, ensure_ascii=False)),
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
        values = self._get_values(tuple(DISCOVERY_KEYS.values()))
        return EbayAccountResources(
            payment_policies=_load_json_list(values.get(DISCOVERY_KEYS["payment_policies"])),
            fulfillment_policies=_load_json_list(values.get(DISCOVERY_KEYS["fulfillment_policies"])),
            return_policies=_load_json_list(values.get(DISCOVERY_KEYS["return_policies"])),
            merchant_locations=_load_json_list(values.get(DISCOVERY_KEYS["merchant_locations"])),
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


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
