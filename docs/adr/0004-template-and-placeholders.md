# ADR 0004 – HTML Template and Placeholder Strategy

## Status

Accepted

## Context

Für Open Inserto existiert bereits ein bestehendes HTML-Gerüst, das bisher manuell für eBay-Beschreibungen verwendet wurde.

Dieses Template ist für den MVP gut geeignet, weil es:

- klar strukturiert ist
- leicht lesbar ist
- typische Angebotsdaten bereits sinnvoll gliedert
- mit wenig Aufwand automatisiert befüllt werden kann

Gleichzeitig muss das System damit umgehen können, dass manche Informationen nicht immer vorhanden sind, z. B.:

- kein Kaufdatum
- keine EAN
- nur alternative Produktkennungen
- überhaupt keine Produktkennung

## Entscheidung

Das bestehende HTML-Gerüst wird als Grundlage übernommen und technisch in ein platzhalterbasiertes Template überführt.

Wichtige Felder werden als Platzhalter modelliert.
Pflichtfelder bleiben bewusst knapp, optionale Felder müssen sauber ausgelassen werden können.

## Grundprinzipien

- Template-Struktur bleibt nah am bestehenden HTML
- Platzhalter werden serverseitig befüllt
- optionale Felder dürfen vollständig fehlen
- leere Abschnitte sollen im finalen HTML nicht unschön erscheinen

## Unterstützte Platzhalter (erste Version)

### Basisfelder

- `manufacturer`
- `product_name`
- `condition`
- `description_html`
- `included_items_html`

### Optionale Felder

- `purchase_date`
- `product_identifier_type`
- `product_identifier_value`

## Produktkennung bewusst flexibel

Statt nur `ean` fest zu modellieren, wird eine allgemeinere Struktur verwendet.

Beispiele:
- EAN
- GTIN
- MPN
- Hersteller-Teilenummer
- interne Kennung

Oder auch:
- keine Kennung vorhanden

## Beispiel für Template-Logik

### Anzeige nur wenn vorhanden

Wenn `purchase_date` fehlt:
- Kaufdatum-Zeile nicht anzeigen

Wenn keine Produktkennung vorhanden ist:
- Kennungs-Zeile nicht anzeigen

Wenn Kennung vorhanden ist:
- Label dynamisch aus `product_identifier_type`
- Wert aus `product_identifier_value`

## Beispielhafte Template-Felder

```text
{{ manufacturer }}
{{ product_name }}
{{ condition }}
{{ description_html }}
{{ included_items_html }}
{{ purchase_date }}
{{ product_identifier_type }}
{{ product_identifier_value }}
```

## Rendering-Regeln

### Regel 1

Pflichtnahe Felder wie Hersteller/Produkt/Zustand/Beschreibung sollen möglichst immer vorhanden sein oder im Review explizit bestätigt werden.

### Regel 2

Optionale Felder dürfen fehlen, ohne dass das Template kaputt aussieht.

### Regel 3

Listen wie Lieferumfang werden bereits als HTML-Fragment oder sicher renderbare Mehrzeilenstruktur vorbereitet.

## Warum diese Entscheidung?

### Vorteile

- nah am bereits genutzten Template
- keine Übermodellierung
- auch für unscharfe / generische Artikel geeignet
- funktioniert sowohl für Technikprodukte als auch für Alltagsgegenstände

### Nachteile

- Template-Rendering braucht etwas Logik für optionale Abschnitte
- freie Beschreibungen müssen sauber normalisiert werden

## Nicht gewählt

### Stark starres Produktschema

Nicht gewählt, weil viele Verkaufsartikel keine sauberen Produktnummern oder Kaufdaten haben.

### Nur EAN als einziges Identifikationsfeld

Nicht gewählt, weil das in der Praxis zu eng wäre.

## Konsequenzen

- Kaufdatum ist optional
- Produktkennungen sind optional und typisiert
- auch Artikel ohne Kennung müssen vollständig unterstützt werden
- das Template-System muss bedingte Abschnitte sauber rendern können

## Nächster Schritt

Als Nächstes sollte definiert werden:

1. wie die Review-Seite mit fehlenden Feldern umgeht
2. wie Template-Blöcke technisch bedingt ein-/ausgeblendet werden
