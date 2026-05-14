from __future__ import annotations

import re
from typing import Any

from app.core.config import Settings
from app.drafts.models import Draft
from app.marketplaces.ebay.client import EbayAuthError, EbayClient, EbayError


def resolve_category_suggestion_for_draft(draft: Draft, settings: Settings, *, preserve_numeric_id: bool = False) -> None:
    raw_value = draft.listing.category_suggestion.strip()
    if not raw_value:
        _store_category_metadata(draft, state="empty")
        return
    if raw_value.isdigit():
        metadata = _category_metadata(draft)
        suggestions = metadata.get("suggestions")
        if preserve_numeric_id:
            selected = _find_suggestion_by_id(suggestions, raw_value)
            _store_category_metadata(
                draft,
                state="manual_id",
                query=raw_value,
                original_query=str(metadata.get("original_query") or metadata.get("query") or ""),
                selected_id=raw_value,
                selected_name=selected.get("name", "") if selected else str(metadata.get("selected_name") or ""),
                selected_path=selected.get("path", "") if selected else str(metadata.get("selected_path") or ""),
                suggestions=[item for item in suggestions if isinstance(item, dict)] if isinstance(suggestions, list) else [],
            )
            return
        if metadata.get("state") == "resolved" and isinstance(suggestions, list) and suggestions:
            ranked_suggestions = _rank_category_suggestions(
                draft,
                str(metadata.get("original_query") or metadata.get("query") or raw_value),
                [item for item in suggestions if isinstance(item, dict)],
            )
            if ranked_suggestions:
                top = ranked_suggestions[0]
                draft.listing.category_suggestion = top["id"]
                _store_category_metadata(
                    draft,
                    state="resolved",
                    query=str(metadata.get("query") or raw_value),
                    original_query=str(metadata.get("original_query") or metadata.get("query") or raw_value),
                    selected_id=top["id"],
                    selected_name=top["name"],
                    selected_path=top["path"],
                    suggestions=ranked_suggestions[:5],
                )
                return
        _store_category_metadata(
            draft,
            state="manual_id",
            selected_id=raw_value,
            selected_name=_category_metadata(draft).get("selected_name", ""),
            query=raw_value,
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
    queries = _build_category_queries(draft, raw_value)
    lookup_errors: list[str] = []
    try:
        access_token = client.get_application_access_token()
        category_tree_id = client.get_default_category_tree_id(access_token)
        for query in queries:
            try:
                suggestions = client.get_category_suggestions(
                    access_token,
                    category_tree_id=category_tree_id,
                    query=query,
                )
            except (EbayError, EbayAuthError) as exc:
                lookup_errors.append(str(exc))
                continue
            if suggestions:
                ranked_suggestions = _rank_category_suggestions(draft, query, suggestions)
                top = ranked_suggestions[0]
                draft.listing.category_suggestion = top["id"]
                _store_category_metadata(
                    draft,
                    state="resolved",
                    query=query,
                    original_query=raw_value,
                    selected_id=top["id"],
                    selected_name=top["name"],
                    selected_path=top["path"],
                    suggestions=ranked_suggestions[:5],
                )
                return
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

    _store_category_metadata(
        draft,
        state="no_match",
        query=raw_value,
        message=(
            "Für diesen Kategoriebegriff wurden keine eBay-Kategorien gefunden."
            if not lookup_errors
            else f"Kategorieauflösung fehlgeschlagen: {lookup_errors[-1]}"
        ),
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
    original_query: str = "",
    selected_id: str = "",
    selected_name: str = "",
    selected_path: str = "",
    suggestions: list[dict[str, str]] | None = None,
    message: str = "",
) -> None:
    draft.listing.attributes["ebayCategory"] = {
        "state": state,
        "query": query,
        "original_query": original_query,
        "selected_id": selected_id,
        "selected_name": selected_name,
        "selected_path": selected_path,
        "suggestions": list(suggestions or []),
        "message": message,
    }


def _find_suggestion_by_id(value: object, category_id: str) -> dict[str, str] | None:
    if not isinstance(value, list):
        return None
    for item in value:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "") == category_id:
            return {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
            }
    return None


def _build_category_queries(draft: Draft, raw_value: str) -> list[str]:
    candidates: list[str] = []
    _append_query(candidates, raw_value)

    for separator in (">", "/", "|"):
        if separator in raw_value:
            _append_query(candidates, raw_value.rsplit(separator, 1)[-1])

    title = draft.listing.title.strip()
    brand = draft.listing.brand.strip()
    model = draft.listing.model.strip()

    if brand or model or title:
        _append_query(candidates, " ".join(part for part in (brand, model, title) if part))
    if title:
        _append_query(candidates, title)

    return candidates


def _append_query(candidates: list[str], value: str) -> None:
    query = " ".join(value.strip().split())
    if not query:
        return
    if query.casefold() in {item.casefold() for item in candidates}:
        return
    candidates.append(query)


def _rank_category_suggestions(
    draft: Draft,
    query: str,
    suggestions: list[dict[str, str]],
) -> list[dict[str, str]]:
    context_tokens = _tokenize_category_text(
        " ".join(
            part
            for part in (
                query,
                draft.listing.title,
                draft.listing.brand,
                draft.listing.model,
            )
            if part
        )
    )

    def score(item: dict[str, str]) -> tuple[int, int]:
        text = f"{item.get('name', '')} {item.get('path', '')}"
        item_tokens = _tokenize_category_text(text)
        overlap = context_tokens & item_tokens
        score_value = len(overlap) * 10

        name = item.get("name", "").casefold()
        path = item.get("path", "").casefold()
        if draft.listing.brand and draft.listing.brand.casefold() in text.casefold():
            score_value += 8
        if draft.listing.model and draft.listing.model.casefold() in text.casefold():
            score_value += 8
        if "sonstige" in name:
            score_value -= 8
        if "aufkleber" in text.casefold() and "aufkleber" not in context_tokens:
            score_value -= 30
        if ("teile" in path or "zubehör" in path) and not ({"teil", "teile", "zubehör", "adapter", "kabel"} & context_tokens):
            score_value -= 6
        return score_value, -suggestions.index(item)

    return sorted(suggestions, key=score, reverse=True)


def _tokenize_category_text(value: str) -> set[str]:
    normalized = value.casefold()
    normalized = normalized.replace("&", " ")
    normalized = re.sub(r"[^a-z0-9äöüß]+", " ", normalized)
    stop_words = {
        "und",
        "oder",
        "mit",
        "ohne",
        "der",
        "die",
        "das",
        "ein",
        "eine",
        "aus",
        "fuer",
        "für",
        "system",
        "systems",
    }
    return {token for token in normalized.split() if len(token) > 2 and token not in stop_words}
