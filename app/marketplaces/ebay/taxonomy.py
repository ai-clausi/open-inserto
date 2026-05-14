from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.drafts.models import Draft
from app.marketplaces.ebay.client import EbayAuthError, EbayClient, EbayError


def resolve_category_suggestion_for_draft(draft: Draft, settings: Settings) -> None:
    raw_value = draft.listing.category_suggestion.strip()
    if not raw_value:
        _store_category_metadata(draft, state="empty")
        return
    if raw_value.isdigit():
        _store_category_metadata(
            draft,
            state="manual_id",
            selected_id=raw_value,
            selected_name=_category_metadata(draft).get("selected_name", ""),
            query=raw_value,
        )
        return
    if settings.ebay_mode == "sandbox":
        _store_category_metadata(
            draft,
            state="sandbox_unavailable",
            query=raw_value,
            message="Automatische Kategorieauflösung ist in eBay Sandbox nicht verlässlich verfügbar.",
        )
        return
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        _store_category_metadata(
            draft,
            state="config_missing",
            query=raw_value,
            message="Für die automatische Kategorieauflösung fehlen eBay Client-ID oder Client-Secret.",
        )
        return

    client = EbayClient(settings)
    try:
        access_token = client.get_application_access_token()
        category_tree_id = client.get_default_category_tree_id(access_token)
        suggestions = client.get_category_suggestions(access_token, category_tree_id=category_tree_id, query=raw_value)
    except (EbayError, EbayAuthError) as exc:
        _store_category_metadata(
            draft,
            state="lookup_failed",
            query=raw_value,
            message=str(exc),
        )
        return
    finally:
        client.close()

    if suggestions:
        top = suggestions[0]
        draft.listing.category_suggestion = top["id"]
        _store_category_metadata(
            draft,
            state="resolved",
            query=raw_value,
            selected_id=top["id"],
            selected_name=top["name"],
            selected_path=top["path"],
            suggestions=suggestions[:5],
        )
        return

    _store_category_metadata(
        draft,
        state="no_match",
        query=raw_value,
        message="Für diesen Kategoriebegriff wurden keine eBay-Kategorien gefunden.",
    )


def get_category_resolution(draft: Draft) -> dict[str, Any]:
    metadata = _category_metadata(draft)
    if metadata:
        return metadata

    raw_value = draft.listing.category_suggestion.strip()
    if raw_value.isdigit():
        return {
            "state": "manual_id",
            "query": raw_value,
            "selected_id": raw_value,
            "selected_name": "",
            "selected_path": "",
            "suggestions": [],
            "message": "",
        }
    return {
        "state": "empty",
        "query": raw_value,
        "selected_id": "",
        "selected_name": "",
        "selected_path": "",
        "suggestions": [],
        "message": "",
    }


def _category_metadata(draft: Draft) -> dict[str, Any]:
    metadata = draft.listing.attributes.get("ebayCategory")
    return metadata if isinstance(metadata, dict) else {}


def _store_category_metadata(
    draft: Draft,
    *,
    state: str,
    query: str = "",
    selected_id: str = "",
    selected_name: str = "",
    selected_path: str = "",
    suggestions: list[dict[str, str]] | None = None,
    message: str = "",
) -> None:
    draft.listing.attributes["ebayCategory"] = {
        "state": state,
        "query": query,
        "selected_id": selected_id,
        "selected_name": selected_name,
        "selected_path": selected_path,
        "suggestions": list(suggestions or []),
        "message": message,
    }
