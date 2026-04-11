# ADR 0011 – Interne Statusübergänge

## Status

Accepted

## Entscheidung

Der MVP verwendet explizite interne Workflow-Status für jeden Draft.

## Statuswerte

- `draft`
- `classified`
- `needs_attention`
- `ready_for_review`
- `ready_for_marketplace`
- `offer_created`
- `published`
- `blocked`
- `error`

## Beispielhafte Übergänge

- Upload abgeschlossen -> `draft`
- erste Analyse abgeschlossen -> `classified`
- wichtige Informationen fehlen -> `needs_attention`
- Nutzer bestätigt oder korrigiert -> `ready_for_review`
- Review abgeschlossen -> `ready_for_marketplace`
- eBay-Offer erfolgreich erstellt -> `offer_created`
- spätere Veröffentlichung -> `published`
- offener Blocker -> `blocked`
- technischer Fehler -> `error`

## Warum?

- klarer UI-Zustand
- sichere Wiederaufnahme bei Unterbrechungen
- einfacheres Debugging und bessere Persistenz
