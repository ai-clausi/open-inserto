from __future__ import annotations

import re
from typing import Any

from app.core.config import Settings
from app.drafts.models import Draft
from app.marketplaces.ebay.client import EbayAuthError, EbayClient, EbayError

AUTO_SELECT_MIN_SCORE = 14
AUTO_SELECT_MIN_MARGIN = 8
AUTO_SELECT_STRONG_SCORE = 40


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
            existing_aspects = metadata.get("aspects")
            has_existing_aspects = isinstance(existing_aspects, list) and bool(existing_aspects)
            category_aspects = [] if has_existing_aspects else _fetch_category_aspects_for_id(settings, raw_value)
            aspect_payload = None if str(metadata.get("selected_id") or "") == raw_value and has_existing_aspects else category_aspects
            _store_category_metadata(
                draft,
                state="manual_id",
                query=raw_value,
                original_query=str(metadata.get("original_query") or metadata.get("query") or ""),
                selected_id=raw_value,
                selected_name=selected.get("name", "") if selected else str(metadata.get("selected_name") or ""),
                selected_path=selected.get("path", "") if selected else str(metadata.get("selected_path") or ""),
                suggestions=[item for item in suggestions if isinstance(item, dict)] if isinstance(suggestions, list) else [],
                aspects=aspect_payload,
            )
            return
        if metadata.get("state") == "resolved" and isinstance(suggestions, list) and suggestions:
            ranked_suggestions = _rank_category_suggestions(
                draft,
                str(metadata.get("original_query") or metadata.get("query") or raw_value),
                [item for item in suggestions if isinstance(item, dict)],
            )
            if ranked_suggestions and _can_auto_select_category(ranked_suggestions):
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
            aspects=_fetch_category_aspects_for_id(settings, raw_value) or None,
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
        ranked_suggestions: list[dict[str, str]] = []
        raw_suggestions: list[dict[str, str]] = []
        selected_query = raw_value
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
                selected_query = query
                raw_suggestions = _merge_raw_category_suggestions(raw_suggestions, suggestions)
                ranked_suggestions = _merge_ranked_category_suggestions(
                    ranked_suggestions,
                    _rank_category_suggestions(draft, query, suggestions),
                )
        if not ranked_suggestions:
            ranked_suggestions = _fallback_ranked_category_suggestions(raw_suggestions)
        if ranked_suggestions:
            if _can_auto_select_category(ranked_suggestions):
                top = ranked_suggestions[0]
                category_aspects = _fetch_category_aspects(
                    client,
                    access_token=access_token,
                    category_tree_id=category_tree_id,
                    category_id=top["id"],
                )
                draft.listing.category_suggestion = top["id"]
                _store_category_metadata(
                    draft,
                    state="resolved",
                    query=selected_query,
                    original_query=raw_value,
                    selected_id=top["id"],
                    selected_name=top["name"],
                    selected_path=top["path"],
                    suggestions=ranked_suggestions[:5],
                    aspects=category_aspects,
                )
                return
            _store_category_metadata(
                draft,
                state="needs_selection",
                query=selected_query,
                original_query=raw_value,
                suggestions=ranked_suggestions[:5],
                message=_category_selection_message(ranked_suggestions),
            )
            return
        _store_category_metadata(
            draft,
            state="no_match",
            query=selected_query,
            original_query=raw_value,
            message="Für diese Suche wurden keine passenden eBay-Kategorien gefunden.",
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


def get_required_category_aspects(draft: Draft) -> list[dict[str, Any]]:
    aspects = _category_metadata(draft).get("aspects")
    if not isinstance(aspects, list):
        return []
    return [
        item
        for item in aspects
        if isinstance(item, dict) and item.get("required") and str(item.get("name") or "").strip()
    ]


def _category_metadata(draft: Draft) -> dict[str, Any]:
    metadata = draft.listing.attributes.get("ebayCategory")
    return metadata if isinstance(metadata, dict) else {}


def resolve_category_search_for_draft(draft: Draft, settings: Settings, query: str) -> dict[str, Any]:
    draft.listing.category_suggestion = query.strip()
    resolve_category_suggestion_for_draft(draft, settings)
    return get_category_resolution(draft)


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
    aspects: list[dict[str, Any]] | None = None,
) -> None:
    existing = _category_metadata(draft)
    stored_aspects = list(aspects if aspects is not None else existing.get("aspects") or []) if selected_id else []
    draft.listing.attributes["ebayCategory"] = {
        "state": state,
        "query": query,
        "original_query": original_query,
        "selected_id": selected_id,
        "selected_name": selected_name,
        "selected_path": selected_path,
        "suggestions": list(suggestions or []),
        "message": message,
        "aspects": stored_aspects,
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
    title = draft.listing.title.strip()
    brand = draft.listing.brand.strip()
    model = draft.listing.model.strip()

    if brand or model or title:
        _append_query(candidates, " ".join(part for part in (brand, model, title) if part))
    if title:
        _append_query(candidates, title)
    for query in _product_category_queries(draft):
        _append_query(candidates, query)

    for separator in (">", "/", "|"):
        if separator in raw_value:
            leaf = raw_value.rsplit(separator, 1)[-1]
            _append_query(candidates, leaf)
            for query in _expanded_leaf_queries(leaf):
                _append_query(candidates, query)

    _append_query(candidates, raw_value)

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
    product_context = " ".join(
        part
        for part in (
            draft.listing.title,
            draft.listing.brand,
            draft.listing.model,
            " ".join(_string_list_attribute(draft.listing.attributes, "keyTechnicalDetails")),
            " ".join(draft.listing.included_items),
        )
        if part
    )
    product_tokens = _tokenize_category_text(product_context)
    query_tokens = _tokenize_category_text(query)
    context_tokens = product_tokens or query_tokens
    category_hint_tokens = query_tokens - product_tokens
    expanded_context_tokens = _expand_category_tokens(context_tokens)
    expanded_hint_tokens = _expand_category_tokens(category_hint_tokens)

    def score(item: dict[str, str]) -> tuple[int, int]:
        score_value = _score_category_suggestion(
            item,
            product_tokens=expanded_context_tokens,
            category_hint_tokens=expanded_hint_tokens,
            raw_query=query,
            draft=draft,
        )
        return score_value, -suggestions.index(item)

    return [
        _category_suggestion_with_score(item, score(item)[0])
        for item in sorted(suggestions, key=score, reverse=True)
    ]


def _score_category_suggestion(
    item: dict[str, str],
    *,
    product_tokens: set[str],
    category_hint_tokens: set[str],
    raw_query: str,
    draft: Draft,
) -> int:
    text = f"{item.get('name', '')} {item.get('path', '')}"
    item_tokens = _expand_category_tokens(_tokenize_category_text(text))
    product_overlap = product_tokens & item_tokens
    hint_overlap = category_hint_tokens & item_tokens
    score_value = len(product_overlap) * 12 + len(hint_overlap) * 3

    name = item.get("name", "").casefold()
    path = item.get("path", "").casefold()
    query = raw_query.casefold().strip()
    if query and name == query and product_overlap:
        score_value += 8
    if draft.listing.brand and draft.listing.brand.casefold() in text.casefold():
        score_value += 8
    if draft.listing.model and draft.listing.model.casefold() in text.casefold():
        score_value += 8
    if "sonstige" in name:
        score_value -= 20
    if "aufkleber" in text.casefold() and "aufkleber" not in product_tokens:
        score_value -= 30
    if ("teile" in path or "zubehör" in path) and not ({"teil", "teile", "zubehör", "adapter", "kabel"} & product_tokens):
        score_value -= 35
    if product_tokens and not product_overlap and hint_overlap:
        score_value -= 10
    return score_value


def _category_suggestion_with_score(item: dict[str, str], score: int) -> dict[str, str]:
    result = dict(item)
    result["score"] = str(score)
    return result


def _merge_ranked_category_suggestions(
    existing: list[dict[str, str]],
    new_items: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged_by_id: dict[str, dict[str, str]] = {}
    for item in [*existing, *new_items]:
        category_id = str(item.get("id") or "")
        if not category_id:
            continue
        current = merged_by_id.get(category_id)
        if current is None or int(item.get("score") or 0) > int(current.get("score") or 0):
            merged_by_id[category_id] = item
    relevant = [item for item in merged_by_id.values() if int(item.get("score") or 0) > 0]
    return sorted(relevant, key=lambda item: int(item.get("score") or 0), reverse=True)


def _merge_raw_category_suggestions(existing: list[dict[str, str]], new_items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = {str(item.get("id") or "") for item in existing}
    merged = list(existing)
    for item in new_items:
        category_id = str(item.get("id") or "")
        if not category_id or category_id in seen:
            continue
        seen.add(category_id)
        merged.append({str(key): str(value) for key, value in item.items() if key in {"id", "name", "path"}})
    return merged


def _fallback_ranked_category_suggestions(raw_items: list[dict[str, str]]) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    for item in raw_items[:5]:
        suggestion = dict(item)
        suggestion["score"] = "0"
        suggestions.append(suggestion)
    return suggestions


def _category_selection_message(ranked_suggestions: list[dict[str, str]]) -> str:
    if ranked_suggestions and all(int(item.get("score") or 0) <= 0 for item in ranked_suggestions):
        return (
            "eBay hat Kategorien geliefert, Open Inserto konnte sie aber nicht sicher automatisch bewerten. "
            "Bitte wähle eine passende Kategorie aus oder suche mit einem konkreteren Begriff."
        )
    return "Die eBay-Kategorie konnte nicht zuverlässig automatisch gewählt werden. Bitte wähle einen der Vorschläge aus."


def _can_auto_select_category(ranked_suggestions: list[dict[str, str]]) -> bool:
    if not ranked_suggestions:
        return False
    top_score = int(ranked_suggestions[0].get("score") or 0)
    if top_score < AUTO_SELECT_MIN_SCORE:
        return False
    if len(ranked_suggestions) == 1:
        return True
    second_score = int(ranked_suggestions[1].get("score") or 0)
    if top_score >= AUTO_SELECT_STRONG_SCORE and top_score > second_score:
        return True
    return top_score - second_score >= AUTO_SELECT_MIN_MARGIN


def _fetch_category_aspects(
    client: EbayClient,
    *,
    access_token: Any,
    category_tree_id: str,
    category_id: str,
) -> list[dict[str, Any]]:
    getter = getattr(client, "get_item_aspects_for_category", None)
    if not callable(getter):
        return []
    try:
        return getter(access_token, category_tree_id=category_tree_id, category_id=category_id)
    except (EbayError, EbayAuthError):
        return []


def _fetch_category_aspects_for_id(settings: Settings, category_id: str) -> list[dict[str, Any]]:
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        return []
    client = EbayClient(settings)
    try:
        access_token = client.get_application_access_token()
        category_tree_id = client.get_default_category_tree_id(access_token)
        return _fetch_category_aspects(
            client,
            access_token=access_token,
            category_tree_id=category_tree_id,
            category_id=category_id,
        )
    except (EbayError, EbayAuthError):
        return []
    finally:
        client.close()


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


def _expand_category_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    synonyms = {
        "audio": {"audio", "sound", "music", "musik", "lautsprecher", "speaker", "hifi"},
        "sound": {"audio", "sound", "music", "musik", "lautsprecher", "speaker", "hifi"},
        "music": {"audio", "sound", "music", "musik", "lautsprecher", "speaker", "hifi"},
        "musik": {"audio", "sound", "music", "musik", "lautsprecher", "speaker", "hifi"},
        "lautsprecher": {"audio", "sound", "music", "musik", "lautsprecher", "speaker", "hifi"},
        "speaker": {"audio", "sound", "music", "musik", "lautsprecher", "speaker", "hifi"},
        "spielkonsole": {"spielkonsole", "konsole", "konsolen", "gaming", "videospiele"},
        "konsole": {"spielkonsole", "konsole", "konsolen", "gaming", "videospiele"},
        "konsolen": {"spielkonsole", "konsole", "konsolen", "gaming", "videospiele"},
        "maus": {"maus", "mäuse", "mouse", "mice", "trackball", "touchpad", "pointing", "eingabegeräte"},
        "mäuse": {"maus", "mäuse", "mouse", "mice", "trackball", "touchpad", "pointing", "eingabegeräte"},
        "mouse": {"maus", "mäuse", "mouse", "mice", "trackball", "touchpad", "pointing", "eingabegeräte"},
        "mice": {"maus", "mäuse", "mouse", "mice", "trackball", "touchpad", "pointing", "eingabegeräte"},
        "trackball": {"maus", "mäuse", "mouse", "mice", "trackball", "touchpad", "pointing", "eingabegeräte"},
        "touchpad": {"maus", "mäuse", "mouse", "mice", "trackball", "touchpad", "pointing", "eingabegeräte"},
        "eingabegeräte": {"maus", "mäuse", "mouse", "mice", "trackball", "touchpad", "pointing", "eingabegeräte"},
        "lockenstab": {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen", "haarglätter", "haarglatter", "haarstyling", "styling"},
        "lockenstäbe": {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen", "haarglätter", "haarglatter", "haarstyling", "styling"},
        "lockenstabe": {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen", "haarglätter", "haarglatter", "haarstyling", "styling"},
        "glätteisen": {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen", "haarglätter", "haarglatter", "haarstyling", "styling"},
        "glatteisen": {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen", "haarglätter", "haarglatter", "haarstyling", "styling"},
        "haarglätter": {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen", "haarglätter", "haarglatter", "haarstyling", "styling"},
        "haarglatter": {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen", "haarglätter", "haarglatter", "haarstyling", "styling"},
        "monitor": {"monitor", "monitore", "display", "bildschirm"},
        "monitore": {"monitor", "monitore", "display", "bildschirm"},
        "display": {"monitor", "monitore", "display", "bildschirm"},
        "bildschirm": {"monitor", "monitore", "display", "bildschirm"},
        "router": {"router", "wifi", "wi-fi", "wlan", "netzwerk"},
        "wifi": {"router", "wifi", "wi-fi", "wlan", "netzwerk"},
        "wlan": {"router", "wifi", "wi-fi", "wlan", "netzwerk"},
        "kommode": {"kommode", "schrank", "moebel", "möbel"},
        "schrank": {"kommode", "schrank", "moebel", "möbel"},
        "moebel": {"kommode", "schrank", "moebel", "möbel"},
        "möbel": {"kommode", "schrank", "moebel", "möbel"},
    }
    for token in tokens:
        expanded.update(synonyms.get(token, set()))
    return expanded


def _product_category_queries(draft: Draft) -> list[str]:
    tokens = _expand_category_tokens(_tokenize_category_text(" ".join([draft.listing.title, draft.listing.brand, draft.listing.model])))
    queries: list[str] = []
    if {"maus", "mäuse", "mouse", "mice"} & tokens:
        queries.extend(["Mäuse Trackballs Touchpads", "Computer Maus", "Tastaturen Mäuse Pointing"])
    if {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen"} & tokens:
        queries.extend(["Lockenstäbe Glätteisen", "Elektrische Haarstyling Geräte", "Lockenstab"])
    return queries


def _expanded_leaf_queries(value: str) -> list[str]:
    tokens = _expand_category_tokens(_tokenize_category_text(value))
    queries: list[str] = []
    if {"maus", "mäuse", "mouse", "mice"} & tokens:
        queries.extend(["Mäuse Trackballs Touchpads", "Computer Maus"])
    if {"lockenstab", "lockenstäbe", "lockenstabe", "glätteisen", "glatteisen"} & tokens:
        queries.extend(["Lockenstäbe Glätteisen", "Elektrische Haarstyling Geräte"])
    return queries


def _string_list_attribute(attributes: dict[str, Any], key: str) -> list[str]:
    value = attributes.get(key)
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
