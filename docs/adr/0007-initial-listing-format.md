# ADR 0007 – Initial Listing Format for the MVP

## Status

Accepted

## Context

Open Inserto soll im MVP erstmals echte eBay-Drafts erzeugen.

Dafür muss festgelegt werden, welches Listing-Format als erstes unterstützt wird.

Grundsätzlich kommen vor allem zwei Richtungen in Frage:

- **Auktion**
- **Festpreis / Buy It Now**

Da das Tool später erweitert werden kann, muss im MVP nicht sofort alles gleichzeitig unterstützt werden.

## Entscheidung

Im MVP wird zunächst **ein einziges primäres Listing-Format** unterstützt:

- **Festpreis / Buy It Now**

Auktions-Listings werden zunächst nicht als erster Standardfall umgesetzt.

## Warum Festpreis zuerst?

### 1. API- und Prozesslogik ist einfacher

Festpreis-Listings sind im Draft-/Offer-Modell meist einfacher zu behandeln als Auktionslogik mit:

- Startpreis
- Laufzeit
- Bietdynamik
- Endzeitpunkt

### 2. Besserer Fit für einen Draft-Workflow

Für einen ersten Review- und Draft-Prozess ist Festpreis oft einfacher:

- Preisvorschlag erzeugen
- Entwurf prüfen
- Offer anlegen
- später optional veröffentlichen

### 3. Geringeres Risiko im MVP

Auktionen bringen mehr Marktplatz-Spezifika und potenziell mehr Fehlkonfigurationen mit.

## Was heißt das konkret?

Der erste MVP unterstützt:

- genau einen Artikel
- genau einen Preis
- keine Varianten
- kein Auktionsende
- kein Bietverhalten

## Spätere Erweiterung

Auktionen sollen nicht ausgeschlossen werden.
Sie werden nur **nicht als erste Ausbaustufe** umgesetzt.

Mögliche spätere Erweiterung:

- `listingFormat = fixed_price`
- `listingFormat = auction`

## Konsequenzen für das Datenmodell

Für den MVP reicht zunächst:

- `priceSuggestion`
- ggf. später `listingFormat`

Noch nicht nötig im MVP:

- `auctionStartPrice`
- `auctionDuration`
- `reservePrice`
- `buyItNowPrice` bei Auktionsmodellen

## Vorteile

- schnellerer MVP
- einfacher zu testen
- klarerer erster API-Weg
- weniger eBay-spezifische Sonderlogik

## Nachteile

- erste Version deckt nicht alle realen Verkaufsfälle ab
- Nutzer, die primär Auktionen wollen, müssen auf spätere Erweiterung warten

## Nicht gewählt

### Direkt Auktion zuerst

Nicht gewählt, weil es für den MVP unnötig komplexer ist.

### Beides gleichzeitig

Nicht gewählt, weil das zu früh zu viele Pfade und Sonderfälle erzeugen würde.

## Nächster Schritt

Als Nächstes sollte geklärt werden:

1. wie interne SKUs / Draft-IDs erzeugt werden
2. wie Bilder technisch gespeichert und später an eBay übergeben werden
3. welche minimalen eBay-Policies beim Setup vorausgesetzt werden
