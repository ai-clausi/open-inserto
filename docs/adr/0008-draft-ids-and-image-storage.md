# ADR 0008 – Draft IDs, SKUs and Image Storage

## Status

Accepted

## Context

Open Inserto benötigt für den MVP eine saubere Strategie für:

- interne Draft-IDs
- eBay-/Marketplace-SKUs
- Bildspeicherung
- Bildreferenzen innerhalb des Draft-Modells

Diese Entscheidungen sind wichtig, weil Drafts später:

- erneut geöffnet
- bearbeitet
- an eBay übergeben
- und ggf. mit externen IDs verknüpft werden sollen

## Entscheidung

Für den MVP wird zwischen **interner Draft-ID** und **Marketplace-SKU** unterschieden.

Zusätzlich werden hochgeladene Bilder lokal in einer strukturierten Dateispeicherung abgelegt und im Draft-Modell referenziert.

## 1. Interne Draft-ID

Jeder Draft erhält eine interne, systemeigene ID.

### Format

Beispiel:

```text
draft_20260410_ab12cd34
```

### Eigenschaften

- eindeutig
- unabhängig von eBay
- stabil über den gesamten Draft-Lebenszyklus
- geeignet für URLs, Datenbankeinträge und Dateipfade

## 2. Marketplace-SKU

Für eBay wird zusätzlich eine SKU benötigt.

### Grundsatz

Die SKU darf von der internen Draft-ID abgeleitet werden, sollte aber als eigener Wert behandelt werden.

### Beispiel

```text
oi-draft-20260410-ab12cd34
```

### Warum getrennt?

- interne IDs bleiben systemintern
- SKU bleibt marktplatzorientiert
- spätere Plattformen können eigene externe Kennungslogik bekommen

## 3. Bildspeicherung

Bilder werden im MVP lokal in der Anwendung gespeichert.

### Ziel

- einfacher Betrieb im Docker-/NAS-Setup
- stabile Referenzen pro Draft
- keine externe Bildabhängigkeit im ersten Schritt

### Vorgeschlagene Struktur

```text
/storage
  /drafts
    /draft_20260410_ab12cd34
      /images
        01-original.jpg
        02-original.jpg
        03-processed.jpg
```

## 4. Bildreferenzen im Draft-Modell

Im `source.images`-Block sollen Bilddaten strukturiert referenziert werden.

### Beispiel

```json
[
  {
    "id": "img_01",
    "originalFilename": "IMG_1234.jpg",
    "storagePath": "/storage/drafts/draft_20260410_ab12cd34/images/01-original.jpg",
    "mimeType": "image/jpeg",
    "order": 1,
    "kind": "original"
  }
]
```

## 5. Reihenfolge der Bilder

Die Reihenfolge soll explizit gespeichert werden.

### Warum?

- Hauptbild ist wichtig
- eBay-Bildreihenfolge muss reproduzierbar sein
- Nutzer soll Reihenfolge später anpassen können

## 6. Spätere Bildverarbeitung

Im MVP dürfen Bilder zunächst einfach nur gespeichert werden.

Spätere Erweiterungen könnten umfassen:

- verkleinerte Vorschaubilder
- Metadaten-Extraktion
- Duplikaterkennung
- einfache Bildoptimierung

## 7. Warum lokale Speicherung zuerst?

### Vorteile

- einfach im MVP
- keine zusätzliche Cloud-/Object-Storage-Abhängigkeit
- leicht auf NAS/Docker betreibbar

### Nachteile

- spätere Skalierung begrenzt
- Veröffentlichung an Marktplätze braucht später saubere Bild-Übergabe

## Nicht gewählt

### Nur eBay-IDs als Primärreferenz

Nicht gewählt, weil Drafts auch vor eBay-Integration stabil identifizierbar sein müssen.

### Externe Bildspeicherung von Anfang an

Nicht gewählt, weil das für den MVP unnötig komplex wäre.

## Konsequenzen

- jeder Draft bekommt eine stabile interne ID
- eBay bekommt eine getrennte SKU
- Bilder liegen lokal pro Draft in eigener Struktur
- Bildreihenfolge wird explizit gespeichert

## Nächster Schritt

Als Nächstes sollte geklärt werden:

1. wie eBay-Auth und Tokenverwaltung erfolgen
2. wie Bild-Uploads technisch an eBay übergeben werden
3. welche lokalen Statusübergänge beim Erstellen eines Offers gelten
