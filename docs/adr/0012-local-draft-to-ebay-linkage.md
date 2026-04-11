# ADR 0012 – Verknüpfung lokaler Drafts mit eBay

## Status

Accepted

## Entscheidung

Der lokale Draft bleibt die führende interne Datenquelle und speichert die Verknüpfung zu eBay-Objekten.

## Erforderliche Verknüpfungsdaten

- interne `draft_id`
- Marketplace-`sku`
- `inventoryItemKey`
- `offerId`
- aktueller lokaler Workflow-Status
- Zeitstempel für Erstellung und letzte Aktualisierung

## Grundprinzip

Der lokale Draft muss auch dann nutzbar bleiben, wenn die eBay-Offer-Erstellung fehlschlägt oder erneut versucht werden muss.

## Warum?

- stabiler Wiederaufnahmepfad
- Trennung zwischen lokaler Arbeit und externem API-Zustand
- einfachere Bearbeitung und Retries
