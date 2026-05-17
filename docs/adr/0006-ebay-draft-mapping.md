# ADR 0006 – Minimal eBay Mapping for the Draft Workflow

## Status

Accepted

Teilweise überholt durch ADR 0016. Insbesondere Kategorie-/Pflichtmerkmal-Handling, Condition Policies, Publish-Verhalten und die Aussage zu noch nicht automatisierten komplexen Kategorie-Merkmalen gelten in dieser Form nicht mehr.

## Context

Open Inserto soll im MVP einen sicheren eBay-Draft-Workflow unterstützen.

Dabei geht es **nicht** darum, sofort alle eBay-Details vollständig zu automatisieren, sondern einen belastbaren ersten Draft-Prozess zu schaffen.

Ziel:

- interne Draft-Daten erzeugen
- daraus die minimal nötigen eBay-Felder ableiten
- einen nicht veröffentlichten eBay-Entwurf vorbereiten
- manuelle Prüfung vor Live-Schaltung ermöglichen

## Entscheidung

Im MVP wird das interne Listing-Modell nur auf die **minimal nötigen eBay-Felder** abgebildet, die für einen ersten unveröffentlichten Offer-Workflow sinnvoll sind.

Komplexere Themen wie erweiterte Kategorieattribute, Varianten, Geschäftsregeln oder internationale Versandlogik werden zunächst zurückgestellt.

## Zielobjekte in eBay

Der MVP soll mit der Sell Inventory API arbeiten und dabei im Kern diese Objekte nutzen:

1. **Inventory Item**
2. **Offer**
3. **Publish** erst später / optional

## Minimale Mapping-Felder

### A. Inventory-Item-nahe Daten

Aus dem internen Modell sollen für eBay mindestens ableitbar sein:

- `sku` / interner eindeutiger Schlüssel
- `title`
- `description` (HTML)
- `condition`
- `product`-nahe Informationen, soweit sinnvoll vorhanden
- Bildreferenzen

### B. Offer-nahe Daten

Für den ersten Offer-Entwurf sollen mindestens ableitbar sein:

- Marketplace / Site
- Format / Listing-Typ (z. B. Festpreis oder Auktion – zunächst zu entscheiden)
- Preis oder Startpreis
- verfügbare Menge
- Kategorie
- Versand-/Fulfillment-Profil
- Zahlungs-/Policy-Referenzen
- Return-/Policy-Referenzen

## Interne zu externe Feldzuordnung (erste Version)

### Interne Felder

- `listing.title` -> eBay Title
- `listing.descriptionHtml` -> eBay Description
- `listing.condition` -> eBay Condition
- `listing.categorySuggestion` -> eBay Category / Category Proposal
- `source.images` / normalisierte Bilddaten -> eBay Image URLs
- `listing.priceSuggestion` -> eBay Price / Start Price
- `listing.includedItems` -> Teil der Beschreibung, nicht als separates eBay-Kernfeld
- `listing.attributes` -> zunächst optional / nur bei Bedarf

### Interne Workflow-Felder

- Die aktuelle eBay-Readiness wird aus Draft-Daten, Review-Bewertung, eBay-Konfiguration und Auth-Status abgeleitet
- `workflow.status` speichert nur echte Lebenszyklus-/Systemzustände wie `draft`, `offer_created`, `published` oder `error`
- `marketplace.ebay.inventoryItemKey` speichert eBay-Bezug
- `marketplace.ebay.offerId` speichert den unveröffentlichten Offer

## Was im MVP noch **nicht** zwingend automatisiert werden muss

Diese Themen dürfen zunächst bewusst vereinfacht oder manuell gehalten werden:

- komplexe Kategorie-Merkmale
- Variantenprodukte
- erweiterte Item Specifics
- differenzierte internationale Versandregeln
- Mehrmengenlogik
- mehrere Marktplätze parallel

## Minimaler technischer Zielzustand

Ein Draft gilt als MVP-seitig erfolgreich, wenn:

1. ein internes Draft-Modell vollständig genug ist
2. daraus ein eBay Inventory Item erzeugt/aktualisiert werden kann
3. daraus ein unveröffentlichter Offer erzeugt werden kann
4. die externe Offer-ID lokal gespeichert wird

## Warum diese Entscheidung?

### Vorteile

- schneller MVP
- weniger API-Komplexität
- konzentriert sich auf den wertstiftenden Kern
- reduziert Risiko bei externer Marktplatz-Integration

### Nachteile

- manche eBay-spezifischen Optimierungen fehlen zunächst
- bestimmte Produktklassen brauchen später zusätzliche Felder

## Nicht gewählt

### Vollständiges eBay-Mapping von Anfang an

Nicht gewählt, weil das zu viel Komplexität in den MVP bringen würde.

### Reine HTML-/Text-Automation ohne echtes Mapping

Nicht gewählt, weil das keinen sauberen API-Weg für echte Drafts schaffen würde.

## Offene Folgeentscheidungen

Auf Basis dieses ADR sollten als Nächstes geklärt werden:

1. welches Listing-Format im MVP zuerst unterstützt wird
   - Festpreis
   - Auktion
2. wie SKU/IDs intern generiert werden
3. wie Bildhosting / Bild-URLs für eBay gehandhabt werden
4. welche eBay-Policies im Setup vorausgesetzt werden
