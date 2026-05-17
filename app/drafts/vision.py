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
                    "productIdentifierType": {"type": "string"},
                    "productIdentifierValue": {"type": "string"},
                    "keyTechnicalDetails": {"type": "array", "items": {"type": "string"}},
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
                    "productIdentifierType",
                    "productIdentifierValue",
                    "keyTechnicalDetails",
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
            "Fülle description als sachlichen eBay-Beschreibungstext im Stil "
            "'Angeboten wird ... aus dem Hause ...'. Beschreibe nur beobachtbare oder vom Nutzer genannte Eigenschaften. "
            "Vermeide Werbesprache und unbelegte objektive Qualitätsbehauptungen wie 'überzeugt', 'ideal', 'brillant', "
            "'farbintensiv' oder 'klar', außer sie wurden vom Nutzer als persönliche Einschätzung genannt. "
            "Subjektive Eindrücke aus notes/user_input müssen als Ich-Aussage formuliert werden, z. B. "
            "'Mich hat ... überzeugt' oder 'Ich habe ... genutzt'. "
            "Halte Mängel knapp getrennt in issues. "
            "Fülle title als reinen Artikelnamen ohne Zustandswort wie gebraucht, defekt oder neu. "
            "Fülle includedItems mit dem eigentlichen Artikel plus allen ausdrücklich genannten Zubehörteilen. "
            "Wenn auf Bildern eine EAN/GTIN, MPN, Artikelnummer oder eindeutige Modellbezeichnung sichtbar ist, "
            "fülle productIdentifierType mit EAN, GTIN, MPN, Modell-Nummer oder Artikelnummer und productIdentifierValue mit dem Wert. "
            "Übernimm sichtbare oder sicher genannte entscheidende technische Eckdaten in keyTechnicalDetails, "
            "z. B. Bluetooth-Version, WiFi-Standard, Mobilfunkstandard oder Anschlüsse wie 2x HDMI, 1x DisplayPort. "
            "Keine vollständigen Datenblätter erstellen und nichts raten; nur relevante Details für die Produktart nennen. "
            "Fülle issues nur mit inseratstauglichen Hinweisen zu Mängeln, fehlendem Lieferumfang oder offenen Prüfpunkten. "
            "Verwende dort niemals Bildanalyse-Formulierungen wie 'erkennbar', 'sichtbar', 'auf den Bildern', "
            "'scheint', 'wirkt' oder 'konnte nicht erkannt werden'. Formuliere stattdessen verkäufernah, z. B. "
            "'Fernbedienung ist nicht enthalten' oder 'Der Artikel zeigt Gebrauchsspuren'. "
            "Verwende produktneutrale oder produktspezifische Begriffe; schreibe bei Möbeln niemals 'Gerät'. "
            "Vermeide Lieferumfang-Duplikate wie den vollständigen Artikelnamen plus eine generische Variante desselben Artikels. "
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

    def analyze_ebay_aspects(
        self,
        *,
        notes: str,
        user_input: dict[str, Any],
        listing: dict[str, Any],
        category: dict[str, Any],
        required_aspects: list[dict[str, Any]],
        image_payloads: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not self.api_key:
            raise ValueError("Vision API key fehlt")
        if not required_aspects:
            return []

        response_format = {
            "type": "json_schema",
            "name": "ebay_category_aspects",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "aspects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                            },
                            "required": ["name", "value", "confidence"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["aspects"],
                "additionalProperties": False,
            },
        }
        prompt = (
            "Fülle nur die angefragten eBay-Kategoriepflichtmerkmale für den Verkaufsentwurf. "
            "Nutze vorhandene Entwurfsdaten, Nutzerangaben und sichtbare Bildinhalte. "
            "Erfinde keine Werte. Wenn ein Wert nicht sicher aus Titel, Marke, Modell, Nutzerangaben oder Bildern ableitbar ist, "
            "gib für dieses Merkmal einen leeren value zurück. "
            "Wenn allowedValues angegeben sind, muss value exakt einem allowedValue entsprechen oder leer bleiben. "
            "Für Markenkompatibilität darf die erkannte Produktmarke verwendet werden, wenn der Artikel offensichtlich zu dieser Marke gehört. "
            "Für Modellkompatibilität darf das erkannte Modell verwendet werden, wenn es um Zubehör, Ersatzteile oder Kompatibilität geht. "
            "Für Produktart verwende eine kurze sachliche Produktart, möglichst aus allowedValues oder der eBay-Kategorie. "
            f"notes={notes!r}; user_input={user_input!r}; listing={listing!r}; category={category!r}; "
            f"required_aspects={required_aspects!r}"
        )
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        for image_payload in image_payloads:
            content.append(
                {
                    "type": "input_image",
                    "image_url": image_payload["image_url"],
                    "detail": image_payload.get("detail", "low"),
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
                logger.warning(
                    "OpenAI eBay aspect request failed: status=%s model=%s aspect_count=%s body=%s",
                    response.status_code,
                    self.model,
                    len(required_aspects),
                    _truncate_for_log(response.text),
                )
            response.raise_for_status()
            data = response.json()

        structured_output = _extract_structured_output(data)
        aspects = structured_output.get("aspects") if isinstance(structured_output, dict) else None
        if not isinstance(aspects, list):
            raise ValueError("Vision-Provider hat keine eBay-Merkmale geliefert")
        return [
            {
                "name": str(item.get("name") or "").strip(),
                "value": str(item.get("value") or "").strip(),
                "confidence": str(item.get("confidence") or "").strip(),
            }
            for item in aspects
            if isinstance(item, dict)
        ]


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
