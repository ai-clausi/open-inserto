from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OpenAIVisionAnalyzerClient:
    def __init__(self, *, api_key: str | None, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def analyze(self, *, notes: str, user_input: dict[str, Any], image_payloads: list[dict[str, str]]) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("Vision API key fehlt")
        if not image_payloads:
            raise ValueError("Keine Bilddaten für Vision-Analyse verfügbar")

        response_format = {
            "type": "json_schema",
            "name": "draft_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "condition": {"type": "string"},
                    "description": {"type": "string"},
                    "brand": {"type": "string"},
                    "model": {"type": "string"},
                    "includedItems": {"type": "array", "items": {"type": "string"}},
                    "issues": {"type": "array", "items": {"type": "string"}},
                    "categorySuggestion": {"type": "string"},
                    "missingInformation": {"type": "array", "items": {"type": "string"}},
                    "confidenceNotes": {"type": "array", "items": {"type": "string"}},
                    "confidenceLevel": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": [
                    "title",
                    "condition",
                    "description",
                    "brand",
                    "model",
                    "includedItems",
                    "issues",
                    "categorySuggestion",
                    "missingInformation",
                    "confidenceNotes",
                    "confidenceLevel",
                ],
                "additionalProperties": False,
            },
        }

        prompt = (
            "Analysiere die Bilder zusammen mit den Zusatzinfos für einen Verkaufsentwurf. "
            "Antworte ausschließlich im vorgegebenen JSON-Schema. "
            "Nutze sichtbare Bildinhalte plus notes und user_input gemeinsam. "
            "Fülle description als kurze, nüchterne Produktbeschreibung in 1-3 Sätzen. "
            "Wenn etwas unklar ist, nenne es explizit in missingInformation und confidenceNotes. "
            f"notes={notes!r}; user_input={user_input!r}"
        )

        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for image_payload in image_payloads:
            content.append(
                {
                    "type": "input_image",
                    "image_url": image_payload["image_url"],
                    "detail": image_payload.get("detail", "auto"),
                }
            )

        payload = {
            "model": self.model,
            "input": [{"role": "user", "content": content}],
            "text": {"format": response_format},
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.is_error:
                detail_levels = [image_payload.get("detail", "auto") for image_payload in image_payloads]
                logger.warning(
                    "OpenAI vision request failed: status=%s model=%s image_count=%s detail=%s body=%s",
                    response.status_code,
                    self.model,
                    len(image_payloads),
                    detail_levels,
                    _truncate_for_log(response.text),
                )
            response.raise_for_status()
            data = response.json()

        structured_output = _extract_structured_output(data)
        if structured_output:
            return structured_output

        logger.warning(
            "OpenAI vision response had no structured output: model=%s response_id=%s keys=%s",
            self.model,
            data.get("id"),
            sorted(data.keys()),
        )

        raise ValueError("Vision-Provider hat keine strukturierte Antwort geliefert")


def _truncate_for_log(value: str, *, limit: int = 1200) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _extract_structured_output(data: dict[str, Any]) -> dict[str, Any]:
    output_parsed = data.get("output_parsed")
    if isinstance(output_parsed, dict):
        return output_parsed

    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content_item in item.get("content", []):
            if not isinstance(content_item, dict):
                continue
            parsed = content_item.get("parsed")
            if isinstance(parsed, dict):
                return parsed
            text = content_item.get("text")
            if isinstance(text, str):
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    return decoded

    return {}
