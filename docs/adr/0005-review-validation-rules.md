# ADR 0005 – Review and Validation Rules

## Status

Accepted

## Context

Open Inserto erzeugt im MVP aus Bildern und wenigen Zusatzinfos zunächst nur einen Entwurf.

Vor einer eBay-Draft-Erstellung muss der Nutzer den Entwurf prüfen können.
Dabei ist wichtig:

- nicht alle Daten sind immer verfügbar
- fehlende Daten dürfen den Flow nicht unnötig blockieren
- gleichzeitig sollen wesentliche Angaben nicht stillschweigend fehlen

Deshalb braucht das Projekt klare Regeln:

- welche Felder im Review besonders wichtig sind
- welche Felder optional bleiben
- wann ein Entwurf als ausreichend vollständig gilt
- wann der Nutzer aktiv bestätigen oder ergänzen muss

## Entscheidung

Open Inserto verwendet im MVP drei Feldklassen:

1. **wichtige Kernfelder**
2. **optionale Komfortfelder**
3. **kontextabhängige Felder**

Ein Draft darf nur dann in den Marketplace-Schritt übergehen, wenn die wichtigen Kernfelder vorhanden oder vom Nutzer bewusst bestätigt wurden.

## 1. Wichtige Kernfelder

Diese Felder sollen möglichst vorhanden sein:

- `product_name`
- `condition`
- `description_html`
- `included_items_html`

Zusätzlich meist wichtig, aber nicht absolut technisch erzwungen:

- `manufacturer`

### Regel

Wenn eines dieser Felder leer oder offensichtlich unsicher ist, soll die Review-Seite dies sichtbar markieren.
Der Nutzer muss dann:

- den Wert ergänzen
- den Vorschlag korrigieren
- oder bewusst bestätigen, dass der Entwurf trotzdem so verwendet werden soll

## 2. Optionale Komfortfelder

Diese Felder dürfen fehlen, ohne den Flow zu blockieren:

- `purchase_date`
- `product_identifier_type`
- `product_identifier_value`
- `subtitle`
- feinere Attributfelder

### Regel

Diese Felder werden angezeigt, wenn vorhanden.
Fehlen sie, darf der Entwurf trotzdem weiterverwendet werden.

## 3. Kontextabhängige Felder

Manche Felder sind nur in bestimmten Situationen sinnvoll oder relevant, z. B.:

- Marke bei No-Name-Artikeln
- Produktkennung bei Einzelstücken
- genaue technische Merkmale bei Elektronik

### Regel

Diese Felder werden nicht global erzwungen.
Die App darf sie empfehlen oder hervorheben, aber nicht pauschal blockieren.

## Review-Regeln im MVP

### Regel 1 – Sichtbare Unsicherheiten

Wenn das System einen Wert nur mit geringer Sicherheit erkannt hat, soll das Feld als unsicher markiert werden.

### Regel 2 – Kein stilles Leerräumen

Wichtige Felder dürfen nicht unbemerkt leer bleiben.

### Regel 3 – Nutzerentscheidung zählt

Wenn der Nutzer einen unvollständigen, aber trotzdem ausreichend guten Entwurf bewusst bestätigt, darf der Flow weitergehen.

### Regel 4 – Optionale Felder blockieren nicht

Fehlende Kaufdaten oder fehlende Produktkennungen stoppen den Flow nicht.

## Praktisches Verhalten der Review-Seite

Die Review-Seite soll pro Feld oder Feldgruppe anzeigen:

- aktueller Wert
- Unsicherheits-/Fehlhinweis
- Bearbeitungsmöglichkeit

Zusätzlich soll es eine kompakte Zusammenfassung geben:

- `ready`
- `needs_attention`
- `blocked`

## Beispielhafte Bewertung

### `ready`

- alle Kernfelder vorhanden oder bestätigt
- keine gravierenden Unklarheiten

### `needs_attention`

- einzelne wichtige Felder unsicher oder leer
- Nutzer kann aber direkt nacharbeiten oder bewusst bestätigen

### `blocked`

- Entwurf technisch oder fachlich zu unklar
- z. B. Produktart nicht sinnvoll erkennbar
- Beschreibung unbrauchbar
- Bilder reichen offensichtlich nicht aus

## Warum diese Entscheidung?

### Vorteile

- praxistauglich
- kein unnötig starres Pflichtschema
- trotzdem Qualitätskontrolle vor externer Aktion
- funktioniert auch für ungewöhnliche Artikel

### Nachteile

- etwas mehr Review-Logik nötig
- Nutzer muss gelegentlich bewusst entscheiden statt nur durchzuklicken

## Nicht gewählt

### Starres Pflichtfeldschema für alle Artikel

Nicht gewählt, weil viele Alltagsartikel und Einzelstücke damit unnötig blockiert würden.

### Vollautomatische Freigabe ohne Review

Nicht gewählt, weil das zu Beginn zu riskant ist.

## Konsequenzen

- die Review-Seite wird ein zentraler Bestandteil des MVP
- Kernfelder werden hervorgehoben
- optionale Felder bleiben optional
- Nutzerbestätigung ist im Zweifelsfall wichtiger als technische Vollständigkeit

## Nächster Schritt

Als Nächstes sollte festgelegt werden:

1. wie eBay-Daten aus dem internen Modell gemappt werden
2. welche eBay-Felder für den ersten Draft-Workflow minimal nötig sind
