from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app.drafts.included_items import normalize_included_items
from app.drafts.models import Draft

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_TEMPLATE_NAME = "listing_description.html"

_environment = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "xml"), default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_listing_description(draft: Draft) -> str:
    template = _environment.get_template(_TEMPLATE_NAME)
    context = build_listing_render_context(draft)
    return template.render(**context).strip()


def refresh_listing_description(draft: Draft) -> bool:
    description_html = render_listing_description(draft)
    if draft.listing.description_html == description_html:
        return False
    draft.listing.description_html = description_html
    return True


def build_listing_render_context(draft: Draft) -> dict[str, Any]:
    attributes = draft.listing.attributes if isinstance(draft.listing.attributes, dict) else {}

    explicit_items = [item.strip() for item in draft.listing.included_items if isinstance(item, str) and item.strip()]
    included_items = normalize_included_items(draft.listing.title, explicit_items)
    issues = [item.strip() for item in draft.listing.issues if isinstance(item, str) and item.strip()]

    return {
        "manufacturer": _render_text_paragraph(draft.listing.brand.strip()),
        "product_name": _render_text_paragraph(draft.listing.title.strip() or "Unbenannter Artikel"),
        "subtitle": _render_text_paragraph(draft.listing.subtitle.strip()),
        "condition": _render_text_paragraph(draft.listing.condition.strip()),
        "model": _render_text_paragraph(draft.listing.model.strip()),
        "purchase_date": _render_text_paragraph(_string_attribute(attributes, "purchase_date")),
        "product_identifier_type": _string_attribute(attributes, "product_identifier_type"),
        "product_identifier_value": _render_text_paragraph(_string_attribute(attributes, "product_identifier_value")),
        "key_technical_details_html": _render_list_html(_string_list_attribute(attributes, "keyTechnicalDetails")),
        "description_html": _render_description_html(draft.source.notes),
        "included_items_html": _render_list_html(included_items),
        "issues_html": _render_paragraph_list_html(issues),
    }


def _string_attribute(attributes: dict[str, Any], key: str) -> str:
    value = attributes.get(key)
    if not isinstance(value, str):
        return ""
    return value.strip()


def _string_list_attribute(attributes: dict[str, Any], key: str) -> list[str]:
    value = attributes.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _render_description_html(value: object) -> Markup:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return Markup("")

    paragraphs = [segment.strip() for segment in text.replace("\r\n", "\n").split("\n\n")]
    cleaned = [segment for segment in paragraphs if segment]
    if not cleaned:
        return Markup("")

    html = "".join(
        f"<p>{escape(segment).replace(chr(10), '<br>')}</p>"
        for segment in cleaned
    )
    return Markup(html)


def _render_text_paragraph(value: object) -> Markup:
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return Markup("")
    return Markup(f"<p>{escape(text)}</p>")


def _render_list_html(items: list[str]) -> Markup:
    if not items:
        return Markup("")

    html = "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"
    return Markup(html)


def _render_paragraph_list_html(items: list[str]) -> Markup:
    if not items:
        return Markup("")

    html = "".join(f"<p>{escape(item)}</p>" for item in items)
    return Markup(html)
