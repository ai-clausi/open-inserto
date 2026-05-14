# ADR 0002 – Initial Draft Data Model

## Status

Accepted

## Context

Open Inserto soll Verkaufsangebote aus Bildern und wenigen Zusatzinformationen vorbereiten.

Dafür braucht das Projekt ein internes Datenmodell, das:

- bildgestützte Eingaben aufnehmen kann
- semantische Artikelinformationen strukturiert speichert
- HTML-Templates befüllen kann
- eBay-spezifische Felder ableiten kann
- Review- und Draft-Zustände verwalten kann

Wichtig ist eine Trennung zwischen:

1. **generischen Listing-Daten**
2. **plattform-spezifischen Feldern**
3. **Prozess-/Statusinformationen**

## Entscheidung

Wir verwenden für den MVP ein internes Draft-Datenmodell mit drei Hauptblöcken:

- `source`
- `listing`
- `marketplace`

Zusätzlich kommt ein technischer Metablock hinzu:

- `workflow`

## Zielstruktur

```json
{
  "id": "draft_...",
  "source": {
    "images": [],
    "notes": "",
    "userInput": {}
  },
  "listing": {
    "title": "",
    "subtitle": "",
    "categorySuggestion": "",
    "condition": "",
    "brand": "",
    "model": "",
    "attributes": {},
    "includedItems": [],
    "issues": [],
    "descriptionHtml": "",
    "priceSuggestion": null,
    "shippingSuggestion": {}
  },
  "marketplace": {
    "ebay": {
      "inventoryItemData": {},
      "offerData": {},
      "inventoryItemKey": null,
      "offerId": null
    }
  },
  "workflow": {
    "status": "draft",
    "needsReview": true,
    "missingInformation": [],
    "lastUpdatedAt": "",
    "createdAt": ""
  }
}
```

## Bedeutung der Blöcke

### `source`

Enthält alles, was vom Nutzer oder aus dem Eingang kommt:

- Bildpfade / Bildreferenzen
- Freitextnotizen
- manuelle Zusatzinfos
- optionale Rohdaten

### `listing`

Enthält die fachliche Sicht auf das spätere Angebot:

- Titel
- Beschreibung
- Zustand
- Marke / Modell
- Zubehör
- Mängel
- Preisvorschlag
- Versandvorschlag

Dieser Block bleibt möglichst **plattformneutral**.

### `marketplace`

Enthält Übersetzungen in marktplatzspezifische Felder.

Im MVP zunächst:
- nur `ebay`

Dort liegen z. B.:
- Inventory-Item-Daten
- Offer-Daten
- externe IDs

### `workflow`

Enthält Steuerungs- und Statusinfos:

- persistierter Lebenszyklusstatus
- optional gecachte Review-Hinweise
- optional gecachte fehlende Angaben
- Zeitstempel

## Beispiel für erste Statuswerte

Persistierte Werte für `workflow.status`:

- `draft`
- `offer_created`
- `published`
- `error`

Review- und Readiness-Zustände wie `ready`, `needs_attention`, `blocked`, `eBay einrichten` oder `Bereit für eBay` werden aus `listing`, `source`, `marketplace` und eBay-Konfiguration abgeleitet. Sie werden nicht als zweite Wahrheit in `workflow.status` gespeichert.

## Warum dieses Modell?

### Vorteile

- klare Trennung zwischen Semantik und API-Feldern
- HTML-Template kann aus `listing` befüllt werden
- eBay-Logik bleibt in `marketplace.ebay`
- spätere Plattformen können ergänzt werden
- Workflow bleibt nachvollziehbar

### Nachteile

- etwas mehr Strukturaufwand am Anfang
- anfangs mehr Mapping-Arbeit zwischen Blöcken

## Nicht gewählt

### Direkt nur eBay-Felder modellieren

Nicht gewählt, weil das Modell dann zu früh zu stark an eBay gebunden wäre.

### Freie JSON-Strukturen ohne klares Schema

Nicht gewählt, weil das schnell unübersichtlich und fehleranfällig wird.

## Konsequenzen

- HTML-Rendering greift primär auf `listing` zu
- eBay-API-Übersetzung greift primär auf `listing` + `marketplace.ebay` zu
- Review-UI zeigt `listing` + `workflow.missingInformation`
- Bilder und Rohinput bleiben in `source`

## Nächster Schritt

Als Nächstes sollte der konkrete **Upload- und Review-Flow** festgelegt werden:

1. Bilder hochladen
2. Draft erzeugen
3. Draft prüfen
4. HTML rendern
5. eBay-Offer erstellen
