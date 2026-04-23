from __future__ import annotations

from typing import Any

import httpx


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
            "json_schema": {
                "name": "draft_analysis",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "condition": {"type": "string"},
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
            },
        }

        prompt = (
            "Analysiere die Bilder zusammen mit den Zusatzinfos für einen Verkaufsentwurf. "
            "Antworte ausschließlich im vorgegebenen JSON-Schema. "
            "Nutze sichtbare Bildinhalte plus notes und user_input gemeinsam. "
            "Wenn etwas unklar ist, nenne es explizit in missingInformation und confidenceNotes. "
            f"notes={notes!r}; user_input={user_input!r}"
        )

        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for image_payload in image_payloads:
            content.append({"type": "input_image", "image_url": image_payload["image_url"]})

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
            response.raise_for_status()
            data = response.json()

        for item in data.get("output", []):
            for content_item in item.get("content", []):
                if content_item.get("type") == "output_text":
                    return content_item.get("parsed") or {}

        raise ValueError("Vision-Provider hat keine strukturierte Antwort geliefert")
