# ADR 0011 – Interne Statusübergänge

## Status

Accepted, überarbeitet

## Entscheidung

Der MVP speichert nur echte Lebenszyklus-/Systemzustände in `workflow.status`.

UI-Zustände wie „Angaben ergänzen“, „eBay einrichten“ oder „Bereit für eBay“ werden zur Laufzeit berechnet. Grundlage sind `source`, `listing`, `marketplace`, die Review-Bewertung und die aktuelle eBay-Konfiguration.

## Statuswerte

- `draft`
- `offer_created`
- `published`
- `error`

## Beispielhafte Übergänge

- Upload abgeschlossen -> `draft`
- erste Analyse abgeschlossen -> `draft` bleibt erhalten, Review-Zustand wird berechnet
- wichtige Informationen fehlen -> `workflow.status` bleibt `draft`, UI zeigt `needs_attention`
- Nutzer bestätigt oder korrigiert -> `workflow.status` bleibt `draft`, Readiness wird neu berechnet
- eBay-Offer erfolgreich erstellt -> `offer_created`
- spätere Veröffentlichung -> `published`
- technischer Fehler -> `error`

## Warum?

- keine doppelte Wahrheit zwischen persistiertem Status und aktuellen Draft-Daten
- sichere Wiederaufnahme bei Unterbrechungen, weil Readiness aus den gespeicherten Daten reproduzierbar ist
- ältere persistierte Status wie `needs_attention`, `ready_for_review`, `ready_for_marketplace`, `classified` oder `blocked` werden beim Laden auf `draft` normalisiert
- eBay-Erfolg und externe IDs bleiben weiterhin eindeutig nachvollziehbar
