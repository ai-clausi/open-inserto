from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageOps

from app.core.config import Settings
from app.drafts.included_items import normalize_included_items
from app.drafts.models import Draft, ListingData
from app.drafts.rendering import render_listing_description
from app.drafts.vision import OpenAIVisionAnalyzerClient
from app.marketplaces.ebay.taxonomy import get_category_resolution, get_optional_category_aspects, get_required_category_aspects

logger = logging.getLogger(__name__)

VISION_IMAGE_MAX_SIDE = 1024
VISION_IMAGE_QUALITY = 72
VISION_IMAGE_DETAIL = "low"
VISION_MAX_IMAGES = 4


@dataclass(slots=True)
class DraftAnalysisResult:
    listing: ListingData
    needs_review: bool = True
    missing_information: list[str] | None = None
    confidence_notes: list[str] | None = None
    description_text: str = ""
    analysis_mode: str = "heuristic"
    analysis_label: str = "Basisanalyse durchgeführt"

    def __post_init__(self) -> None:
        if self.missing_information is None:
            self.missing_information = []
        if self.confidence_notes is None:
            self.confidence_notes = []


class DraftAnalysisService(Protocol):
    def analyze(self, draft: Draft) -> DraftAnalysisResult: ...


class HeuristicDraftAnalysisService:
    def analyze(self, draft: Draft) -> DraftAnalysisResult:
        user_input = draft.source.user_input
        notes = draft.source.notes.strip()

        product_name = _clean_text(user_input.get("product_name"))
        condition = _clean_text(user_input.get("condition"))
        accessories = _split_lines_or_csv(user_input.get("accessories"))
        included_items = normalize_included_items(product_name, accessories)
        issues = _collect_issues(user_input.get("hints"))

        missing_information: list[str] = []
        confidence_notes: list[str] = [
            "MVP-Heuristik: Vorschläge basieren nur auf Zusatzinfos und vorhandenen Bildern, nicht auf echter Bildanalyse.",
        ]

        if not product_name:
            missing_information.append("Produktname unklar")
        if not condition:
            missing_information.append("Zustand fehlt")
        if not notes and not issues:
            missing_information.append("Beschreibung unvollständig")

        if len(included_items) <= 1:
            confidence_notes.append("Kein weiterer Lieferumfang wurde sicher erkannt und bleibt leer, bis er bestätigt wird.")
        if draft.source.images:
            confidence_notes.append(
                f"{len(draft.source.images)} Bild(er) liegen vor, wurden aber im MVP noch nicht inhaltlich ausgewertet."
            )

        listing = ListingData(
            title=product_name,
            condition=condition,
            includedItems=included_items,
            issues=issues,
            descriptionHtml="",
        )

        rendered_draft = draft.model_copy(deep=True)
        rendered_draft.listing = listing.model_copy(deep=True)
        listing.description_html = render_listing_description(rendered_draft)

        return DraftAnalysisResult(
            listing=listing,
            needs_review=True,
            missing_information=missing_information,
            confidence_notes=confidence_notes,
            description_text=notes,
            analysis_mode="heuristic",
            analysis_label="Basisanalyse durchgeführt",
        )


class VisionDraftAnalysisService:
    def __init__(
        self,
        *,
        client: Any,
        project_dir: Path,
        image_max_side: int = VISION_IMAGE_MAX_SIDE,
        image_quality: int = VISION_IMAGE_QUALITY,
        image_detail: str = VISION_IMAGE_DETAIL,
        max_images: int = VISION_MAX_IMAGES,
    ) -> None:
        self.client = client
        self.project_dir = project_dir
        self.image_max_side = image_max_side
        self.image_quality = image_quality
        self.image_detail = image_detail
        self.max_images = max_images

    def analyze(self, draft: Draft) -> DraftAnalysisResult:
        image_payloads = self._build_image_payloads(draft)
        payload = self.client.analyze(
            notes=draft.source.notes,
            user_input=draft.source.user_input,
            image_payloads=image_payloads,
        )

        missing_information = _normalize_string_list(payload.get("missingInformation"))
        confidence_notes = _normalize_string_list(payload.get("confidenceNotes"))
        description_text = _clean_text(payload.get("description")) or draft.source.notes.strip()
        issues = _collect_issues(payload.get("issues"), draft.source.user_input.get("hints"))

        title = _select_listing_title(payload.get("title"), draft.source.user_input.get("product_name"))
        payload_items = _normalize_string_list(payload.get("includedItems"))
        user_accessories = _split_lines_or_csv(draft.source.user_input.get("accessories"))

        listing = ListingData(
            title=title,
            condition=_clean_text(payload.get("condition")) or _clean_text(draft.source.user_input.get("condition")),
            brand=_clean_text(payload.get("brand")),
            model=_clean_text(payload.get("model")),
            categorySuggestion=_clean_text(payload.get("categorySuggestion")),
            includedItems=normalize_included_items(title, payload_items, user_accessories),
            issues=issues,
            descriptionHtml="",
        )
        product_identifier_type = _clean_text(payload.get("productIdentifierType"))
        product_identifier_value = _clean_text(payload.get("productIdentifierValue"))
        if product_identifier_type and product_identifier_value:
            listing.attributes["product_identifier_type"] = product_identifier_type
            listing.attributes["product_identifier_value"] = product_identifier_value
        key_technical_details = _normalize_string_list(payload.get("keyTechnicalDetails"))
        if key_technical_details:
            listing.attributes["keyTechnicalDetails"] = key_technical_details

        if not listing.title:
            missing_information.append("Produktname unklar")
        if not listing.condition:
            missing_information.append("Zustand fehlt")
        if not draft.source.images:
            missing_information.append("Keine Bilder vorhanden")

        confidence_level = _clean_text(payload.get("confidenceLevel")).lower() or "low"
        confidence_notes = list(dict.fromkeys(confidence_notes))
        confidence_notes.append(
            f"KI-/Vision-Analyzer verwendet ({self.client.__class__.__name__}, Confidence: {confidence_level})."
        )

        rendered_draft = draft.model_copy(deep=True)
        rendered_draft.source.notes = description_text
        rendered_draft.listing = listing.model_copy(deep=True)
        listing.description_html = render_listing_description(rendered_draft)

        return DraftAnalysisResult(
            listing=listing,
            needs_review=True,
            missing_information=list(dict.fromkeys(missing_information)),
            confidence_notes=confidence_notes,
            description_text=description_text,
            analysis_mode="vision",
            analysis_label="KI-Analyse durchgeführt",
        )

    def _build_image_payloads(self, draft: Draft) -> list[dict[str, str]]:
        image_payloads: list[dict[str, str]] = []
        for image in draft.source.images[: self.max_images]:
            image_path = Path(image.storage_path)
            if not image_path.is_absolute():
                image_path = self.project_dir / image_path
            if not image_path.exists():
                raise FileNotFoundError(f"Bilddatei nicht gefunden: {image_path}")
            encoded = self._encode_image_for_vision(image_path)
            image_payloads.append(
                {
                    "image_url": f"data:image/jpeg;base64,{encoded}",
                    "detail": self.image_detail,
                }
            )
        return image_payloads

    def _encode_image_for_vision(self, image_path: Path) -> str:
        with Image.open(image_path) as image:
            normalized = ImageOps.exif_transpose(image).convert("RGB")
            if max(normalized.size) > self.image_max_side:
                normalized.thumbnail((self.image_max_side, self.image_max_side), Image.Resampling.LANCZOS)

            buffer = BytesIO()
            normalized.save(buffer, format="JPEG", quality=self.image_quality, optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")


def autofill_ebay_required_aspects(draft: Draft, settings: Settings) -> bool:
    required_aspects = get_required_category_aspects(draft)
    optional_aspects = [aspect for aspect in get_optional_category_aspects(draft) if str(aspect.get("priority") or "") in {"high", "medium"}][:6]
    candidate_aspects = [*required_aspects, *optional_aspects]
    if not candidate_aspects:
        return False

    existing = _ebay_aspect_values(draft)
    updated = dict(existing)
    changed = False
    for aspect in candidate_aspects:
        name = _clean_text(aspect.get("name"))
        if not name or updated.get(name):
            continue
        value = _infer_aspect_value(draft, aspect)
        if value:
            updated[name] = value
            changed = True

    missing = [aspect for aspect in candidate_aspects if not updated.get(_clean_text(aspect.get("name")))]
    category_id = str(get_category_resolution(draft).get("selected_id") or draft.listing.category_suggestion or "").strip()
    autofill_metadata = draft.listing.attributes.get("ebayAspectsAutofill")
    autofill_metadata = autofill_metadata if isinstance(autofill_metadata, dict) else {}
    ai_already_attempted = str(autofill_metadata.get("categoryId") or "") == category_id and autofill_metadata.get("aiAttempted") is True
    if missing and settings.has_vision_config and draft.source.images and not ai_already_attempted:
        draft.listing.attributes["ebayAspectsAutofill"] = {"categoryId": category_id, "aiAttempted": True}
        try:
            vision_service = VisionDraftAnalysisService(
                client=OpenAIVisionAnalyzerClient(
                    api_key=settings.vision_api_key,
                    model=settings.vision_model,
                    timeout_seconds=settings.vision_timeout_seconds,
                ),
                project_dir=settings.project_dir,
                image_max_side=settings.vision_image_max_side,
                image_quality=settings.vision_image_quality,
                image_detail=settings.vision_image_detail,
                max_images=settings.vision_max_images,
            )
            ai_aspects = vision_service.client.analyze_ebay_aspects(
                notes=draft.source.notes,
                user_input=draft.source.user_input,
                listing=_listing_context(draft),
                category=get_category_resolution(draft),
                candidate_aspects=missing,
                image_payloads=vision_service._build_image_payloads(draft),
            )
            aspect_metadata = _ebay_aspect_metadata(draft)
            for item in ai_aspects:
                name = _clean_text(item.get("name"))
                if not name or updated.get(name):
                    continue
                aspect = next((candidate for candidate in missing if _clean_text(candidate.get("name")) == name), None)
                if not aspect:
                    continue
                value = _normalize_aspect_value(item.get("value"), aspect)
                if value:
                    updated[name] = value
                    aspect_metadata[name] = {
                        "source": "ai",
                        "confidence": _clean_text(item.get("confidence")).lower() or "medium",
                        "priority": str(aspect.get("priority") or ("high" if aspect.get("required") else "medium")),
                    }
                    changed = True
            if aspect_metadata:
                draft.listing.attributes["ebayAspectsMeta"] = aspect_metadata
        except Exception as exc:
            logger.warning("OpenAI eBay aspect autofill failed for draft %s: %s", draft.id, exc)

    if changed:
        aspect_metadata = _ebay_aspect_metadata(draft)
        for aspect in candidate_aspects:
            name = _clean_text(aspect.get("name"))
            if not name or not updated.get(name):
                continue
            aspect_metadata.setdefault(
                name,
                {
                    "source": "deterministic",
                    "confidence": "high",
                    "priority": str(aspect.get("priority") or ("high" if aspect.get("required") else "medium")),
                },
            )
        if aspect_metadata:
            draft.listing.attributes["ebayAspectsMeta"] = aspect_metadata

        draft.listing.attributes["ebayAspects"] = updated
        sources = draft.listing.attributes.get("fieldSources")
        if isinstance(sources, dict):
            sources["ebay_aspects"] = "KI"
    return changed


class ConfiguredDraftAnalysisService:
    def __init__(self, primary: DraftAnalysisService, fallback: DraftAnalysisService | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    def analyze(self, draft: Draft) -> DraftAnalysisResult:
        try:
            return self.primary.analyze(draft)
        except Exception as exc:
            if self.fallback is None:
                raise
            logger.warning("Primary draft analyzer failed, falling back to heuristic analyzer: %s", exc)
            analysis = self.fallback.analyze(draft)
            analysis.confidence_notes = list(analysis.confidence_notes or [])
            analysis.confidence_notes.append(
                f"KI-/Vision-Analyzer nicht verfügbar, Fallback auf Heuristik verwendet: {exc}"
            )
            analysis.analysis_mode = "fallback"
            analysis.analysis_label = "Basisanalyse durchgeführt"
            return analysis


def build_draft_analysis_service(settings: Settings) -> DraftAnalysisService:
    heuristic = HeuristicDraftAnalysisService()
    backend = settings.draft_analysis_backend

    if backend == "heuristic":
        return heuristic

    vision_service = VisionDraftAnalysisService(
        client=OpenAIVisionAnalyzerClient(
            api_key=settings.vision_api_key,
            model=settings.vision_model,
            timeout_seconds=settings.vision_timeout_seconds,
        ),
        project_dir=settings.project_dir,
        image_max_side=settings.vision_image_max_side,
        image_quality=settings.vision_image_quality,
        image_detail=settings.vision_image_detail,
        max_images=settings.vision_max_images,
    )

    if backend == "vision":
        return ConfiguredDraftAnalysisService(primary=vision_service, fallback=heuristic)

    if settings.has_vision_config:
        return ConfiguredDraftAnalysisService(primary=vision_service, fallback=heuristic)

    return heuristic


def apply_analysis_result(draft: Draft, analysis: DraftAnalysisResult) -> Draft:
    existing_original_input = draft.listing.attributes.get("originalInput")
    if isinstance(existing_original_input, dict):
        original_notes = str(existing_original_input.get("notes") or "")
        raw_user_input = existing_original_input.get("userInput")
        original_user_input = {
            str(key): str(value)
            for key, value in (raw_user_input.items() if isinstance(raw_user_input, dict) else [])
            if str(key).strip() and str(value).strip()
        }
    else:
        original_user_input = {
            key: value
            for key, value in draft.source.user_input.items()
            if isinstance(key, str) and isinstance(value, str) and value.strip()
        }
        original_notes = draft.source.notes.strip()

    draft.listing = analysis.listing
    draft.listing.title = _select_listing_title(draft.listing.title, original_user_input.get("product_name"))
    draft.listing.included_items = normalize_included_items(draft.listing.title, draft.listing.included_items)
    draft.workflow.needs_review = analysis.needs_review
    draft.workflow.missing_information = list(analysis.missing_information or [])
    draft.workflow.last_updated_at = draft.workflow.last_updated_at
    field_sources = _build_field_sources(draft, analysis, original_user_input)
    draft.source.notes = analysis.description_text.strip()

    confidence_notes = list(analysis.confidence_notes or [])
    if confidence_notes:
        draft.listing.attributes["confidenceNotes"] = confidence_notes
    else:
        draft.listing.attributes.pop("confidenceNotes", None)
    draft.listing.attributes["originalInput"] = {
        "notes": original_notes,
        "userInput": original_user_input,
    }
    draft.listing.attributes["fieldSources"] = field_sources
    draft.listing.attributes["analysis"] = {
        "performed": True,
        "mode": analysis.analysis_mode,
        "label": analysis.analysis_label,
    }

    return draft


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _split_lines_or_csv(value: object) -> list[str]:
    text = _clean_text(value)
    if not text:
        return []

    normalized = text.replace("\r", "\n")
    parts = [part.strip(" -•\t") for chunk in normalized.split("\n") for part in chunk.split(",")]
    return [part for part in parts if part]


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            text = _clean_text(item)
            if text:
                normalized.append(text)
        return normalized
    return _split_lines_or_csv(value)


def _ebay_aspect_values(draft: Draft) -> dict[str, str]:
    values = draft.listing.attributes.get("ebayAspects")
    if not isinstance(values, dict):
        return {}
    return {str(key).strip(): str(value).strip() for key, value in values.items() if str(key).strip() and str(value).strip()}


def _ebay_aspect_metadata(draft: Draft) -> dict[str, dict[str, str]]:
    raw_value = draft.listing.attributes.get("ebayAspectsMeta")
    if not isinstance(raw_value, dict):
        return {}
    metadata: dict[str, dict[str, str]] = {}
    for key, value in raw_value.items():
        name = str(key).strip()
        if not name or not isinstance(value, dict):
            continue
        metadata[name] = {str(inner_key).strip(): str(inner_value).strip() for inner_key, inner_value in value.items() if str(inner_key).strip() and str(inner_value).strip()}
    return metadata


def _infer_aspect_value(draft: Draft, aspect: dict[str, Any]) -> str:
    name = _clean_text(aspect.get("name"))
    name_key = name.casefold()
    if name_key in {"marke", "markenkompatibilität", "kompatible marke"}:
        return _normalize_aspect_value(draft.listing.brand, aspect)
    if name_key in {"modell", "modellkompatibilität", "kompatibles modell"}:
        return _normalize_aspect_value(draft.listing.model, aspect)
    if name_key in {"produktart", "typ", "art"}:
        value = _match_allowed_value(_product_context_text(draft), aspect)
        if value:
            return value
        category = get_category_resolution(draft)
        return _normalize_aspect_value(category.get("selected_name"), aspect)
    if name_key in {"farbe", "colour", "color"}:
        return _match_allowed_value(_product_context_text(draft), aspect)
    return _match_allowed_value(_product_context_text(draft), aspect)


def _normalize_aspect_value(value: object, aspect: dict[str, Any]) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    allowed = _allowed_aspect_values(aspect)
    if not allowed:
        return text
    for allowed_value in allowed:
        if text.casefold() == allowed_value.casefold():
            return allowed_value
    for allowed_value in allowed:
        if allowed_value.casefold() in text.casefold() or text.casefold() in allowed_value.casefold():
            return allowed_value
    return ""


def _match_allowed_value(context: str, aspect: dict[str, Any]) -> str:
    context_key = context.casefold()
    for value in _allowed_aspect_values(aspect):
        value_key = value.casefold()
        if value_key and value_key in context_key:
            return value
    return ""


def _allowed_aspect_values(aspect: dict[str, Any]) -> list[str]:
    values = aspect.get("values")
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _string_attribute(attributes: dict[str, Any], key: str) -> str:
    value = attributes.get(key)
    return value.strip() if isinstance(value, str) else ""


def _string_list_attribute(attributes: dict[str, Any], key: str) -> list[str]:
    value = attributes.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _product_context_text(draft: Draft) -> str:
    return " ".join(
        part
        for part in (
            draft.listing.title,
            draft.listing.brand,
            draft.listing.model,
            draft.source.notes,
            " ".join(draft.listing.included_items),
            " ".join(_string_list_attribute(draft.listing.attributes, "keyTechnicalDetails")),
            get_category_resolution(draft).get("selected_name", ""),
            get_category_resolution(draft).get("selected_path", ""),
        )
        if isinstance(part, str) and part.strip()
    )


def _listing_context(draft: Draft) -> dict[str, Any]:
    return {
        "title": draft.listing.title,
        "brand": draft.listing.brand,
        "model": draft.listing.model,
        "condition": draft.listing.condition,
        "includedItems": draft.listing.included_items,
        "issues": draft.listing.issues,
        "keyTechnicalDetails": _string_list_attribute(draft.listing.attributes, "keyTechnicalDetails"),
        "productIdentifierType": _string_attribute(draft.listing.attributes, "product_identifier_type"),
        "productIdentifierValue": _string_attribute(draft.listing.attributes, "product_identifier_value"),
    }


def _collect_issues(*values: object) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    fingerprints: list[set[str]] = []
    for value in values:
        for item in _normalize_string_list(value):
            item = _normalize_listing_issue_text(item)
            key = item.casefold()
            if key in seen:
                continue
            fingerprint = _issue_fingerprint(item)
            if any(_issue_similarity(fingerprint, existing) >= 0.68 for existing in fingerprints):
                continue
            seen.add(key)
            fingerprints.append(fingerprint)
            issues.append(item)
    return issues


def _normalize_listing_issue_text(value: str) -> str:
    text = value.strip()
    if not text:
        return ""

    lowered = text.casefold()
    if lowered in {
        "keine fernbedienung oder weiteres zubehör erkennbar.",
        "keine fernbedienung oder weiteres zubehör erkennbar",
    }:
        return "Fernbedienung und weiteres Zubehör sind nicht enthalten."
    if lowered.startswith("keine ") and lowered.endswith(" erkennbar."):
        subject = text[6:-11].strip()
        if subject:
            return f"{subject[0].upper() + subject[1:]} nicht enthalten."
    if lowered.startswith("keine ") and lowered.endswith(" erkennbar"):
        subject = text[6:-10].strip()
        if subject:
            return f"{subject[0].upper() + subject[1:]} nicht enthalten."
    if "gerät" in lowered:
        text = text.replace("Das Gerät", "Der Artikel")
        text = text.replace("das Gerät", "der Artikel")
        text = text.replace("Gerät", "Artikel")
        text = text.replace("gerät", "Artikel")
    return text


def _select_listing_title(ai_title: object, user_title: object) -> str:
    ai_text = _clean_text(ai_title)
    user_text = _clean_text(user_title)
    if not ai_text:
        return _normalize_title_casing(user_text)
    if _is_all_caps_title(user_text) and _same_title_tokens(ai_text, user_text):
        return _normalize_title_casing(ai_text)
    return _normalize_title_casing(ai_text)


def _normalize_title_casing(value: str) -> str:
    text = value.strip()
    if not _is_all_caps_title(text):
        return text
    brand_casing = {
        "SATECHI": "Satechi",
        "APPLE": "Apple",
        "SAMSUNG": "Samsung",
        "NINTENDO": "Nintendo",
        "BOSE": "Bose",
        "IKEA": "IKEA",
        "HP": "HP",
        "LG": "LG",
        "USB": "USB",
        "HDMI": "HDMI",
        "RJ45": "RJ45",
        "SD": "SD",
    }
    lowered_words = {"AND", "UND", "MIT", "OHNE", "FÜR", "FUER", "VON"}
    words = re.split(r"(\s+|-)", text)
    normalized: list[str] = []
    for word in words:
        if not word or word.isspace() or word == "-":
            normalized.append(word)
            continue
        stripped = word.strip(",;:()[]")
        prefix = word[: len(word) - len(word.lstrip(",;:()[]"))]
        suffix = word[len(word.rstrip(",;:()[]")) :]
        core = stripped
        if core in brand_casing:
            replacement = brand_casing[core]
        elif core in lowered_words:
            replacement = core.casefold()
        elif any(char.isdigit() for char in core):
            replacement = core
        elif len(core) <= 3:
            replacement = core
        else:
            replacement = core[:1].upper() + core[1:].casefold()
        normalized.append(f"{prefix}{replacement}{suffix}")
    return "".join(normalized)


def _is_all_caps_title(value: str) -> bool:
    letters = [char for char in value if char.isalpha()]
    return bool(letters) and sum(1 for char in letters if char.isupper()) / len(letters) > 0.78


def _same_title_tokens(left: str, right: str) -> bool:
    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = left_tokens & right_tokens
    return len(overlap) / max(len(left_tokens), len(right_tokens)) >= 0.75


def _title_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.casefold()) if len(token) > 1}


def _issue_fingerprint(value: str) -> set[str]:
    normalized = value.casefold()
    normalized = normalized.replace("ethernetkabel", "ethernet kabel")
    normalized = normalized.replace("anschluss", "anschluss ")
    tokens = {
        token
        for token in re.split(r"[^a-z0-9äöüß]+", normalized)
        if len(token) > 2
        and token
        not in {
            "das",
            "der",
            "die",
            "von",
            "mir",
            "verwendete",
            "verwendeten",
            "hat",
            "hält",
            "haelt",
            "nicht",
            "sehr",
            "gut",
            "dem",
            "den",
            "ein",
            "eine",
            "einem",
        }
    }
    return tokens


def _issue_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _build_field_sources(
    draft: Draft,
    analysis: DraftAnalysisResult,
    user_input: dict[str, str],
) -> dict[str, str]:
    source = "KI" if analysis.analysis_mode == "vision" else "Eingabe"

    field_sources: dict[str, str] = {
        "title": source,
        "condition": source,
        "description": source,
        "included_items": source,
        "brand": source,
        "model": source,
        "category_suggestion": source,
        "issues": source,
        "product_identifier": source,
        "key_technical_details": source,
    }

    if _clean_text(user_input.get("product_name")) == analysis.listing.title.strip():
        field_sources["title"] = "Eingabe"
    if _clean_text(user_input.get("condition")) == analysis.listing.condition.strip():
        field_sources["condition"] = "Eingabe"
    if normalize_included_items(
        analysis.listing.title,
        _split_lines_or_csv(user_input.get("accessories")),
    ) == analysis.listing.included_items:
        field_sources["included_items"] = "Eingabe"
    if _collect_issues(user_input.get("hints")) == analysis.listing.issues:
        field_sources["issues"] = "Eingabe"

    return field_sources
