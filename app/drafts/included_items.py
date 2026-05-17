from __future__ import annotations

import re


def normalize_included_items(product_name: str, *item_groups: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    product_key = _dedupe_key(product_name)

    product = product_name.strip()
    if product:
        _append_unique(items, seen, product, product_key=product_key)

    for group in item_groups:
        for item in group:
            _append_unique(items, seen, item, product_key=product_key)

    return items


def _append_unique(items: list[str], seen: set[str], value: str, *, product_key: str = "") -> None:
    item = value.strip()
    if not item:
        return
    key = _dedupe_key(item)
    generic_key = _generic_item_key(item)
    if key in seen:
        return
    if product_key and key != product_key and product_key in key:
        return
    if product_key and generic_key and generic_key != product_key:
        product_tokens = set(product_key.split())
        generic_tokens = set(generic_key.split())
        if generic_tokens and generic_tokens.issubset(product_tokens):
            return
    seen.add(key)
    items.append(item)


def _dedupe_key(value: str) -> str:
    text = value.casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return " ".join(text.split())


def _generic_item_key(value: str) -> str:
    text = value.casefold()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b\d+\s*x\b", " ", text)
    text = re.sub(r"\b\d+\s*stück\b", " ", text)
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return " ".join(text.split())
