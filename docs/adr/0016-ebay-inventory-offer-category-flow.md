# ADR 0016 – eBay Inventory Offer, Kategorie und Publish-Flow

## Status

Accepted

Ersetzt bzw. konkretisiert Teile von ADR 0006, ADR 0010 und ADR 0015.

## Kontext

Open Inserto soll Arbeit beim Einstellen von Artikeln abnehmen. Gleichzeitig hat sich im Live-Test gezeigt:

- die öffentliche eBay-API bietet keinen verlässlichen Seller-Hub-Draft-Endpunkt
- ein unveröffentlichter Inventory Offer ist der technisch nutzbare Zwischenzustand
- viele Publish-Fehler entstehen erst durch kategoriespezifische Pflichtmerkmale, Condition Policies oder ungeeignete Account-Policies
- Kategorie- und Pflichtfeldprobleme müssen vor dem Publish sichtbar werden

## Entscheidung

Der lokale Open-Inserto-Draft bleibt die führende Review- und Bearbeitungsoberfläche.

Der eBay-Flow besteht aus zwei expliziten Aktionen:

1. `eBay-Angebot vorbereiten`
2. `Bei eBay veröffentlichen`

### eBay-Angebot vorbereiten

Beim Vorbereiten validiert Open Inserto den Draft und erstellt bzw. aktualisiert:

- eBay Inventory Item
- unveröffentlichten eBay Inventory Offer
- lokale Referenzen wie SKU, Inventory Item Key, Offer ID und eBay-Bild-URLs

Bilder werden nur erneut zu eBay hochgeladen, wenn keine wiederverwendbaren eBay-Bild-URLs vorhanden sind oder die lokalen Bilder geändert wurden.

### Bei eBay veröffentlichen

Beim Veröffentlichen aktualisiert Open Inserto den bestehenden Inventory Item und Offer erneut und ruft danach `publishOffer` auf.

Damit wird verhindert, dass ein alter Offer-Stand veröffentlicht wird, wenn der lokale Draft seit dem Vorbereiten geändert wurde.

## Kategorieauswahl

Kategorien werden nicht als feste Projektliste gepflegt.

Open Inserto nutzt die eBay Taxonomy API:

- `get_category_suggestions` für Suchvorschläge
- lokale Bewertung der Treffer gegen Titel, Produkttyp, Marke, Modell und Nutzereingaben
- automatische Auswahl nur bei ausreichend sicherem Treffer
- ansonsten Anzeige der eBay-Vorschläge zur manuellen Auswahl

Die manuelle Kategorie-Suche auf der Draft-Seite läuft asynchron. Die Seite soll dabei nicht vollständig neu laden.

## Pflichtmerkmale

Nach Auswahl oder Auflösung einer Kategorie lädt Open Inserto die kategoriespezifischen Artikelmerkmale über `get_item_aspects_for_category`.

Pflichtmerkmale werden vor dem eBay-Schritt geprüft. Fehlende Pflichtmerkmale blockieren das Vorbereiten oder Veröffentlichen, bis sie vorhanden sind.

Open Inserto versucht Pflichtmerkmale automatisch zu füllen:

- deterministisch aus vorhandenen Draft-Daten
- aus erkannten Produktkennungen, Marke und Modell
- gezielt per KI, wenn die Datenlage dafür ausreicht

Die KI soll dabei keine frei erfundenen technischen Daten erzeugen. Unsichere Werte bleiben sichtbar offen.

## Condition Policies

Vor der eBay-Übergabe prüft Open Inserto die für die Kategorie erlaubten eBay-Zustandswerte.

Der interne Zustand wird auf einen zulässigen eBay-Condition-Wert abgebildet. Ist keine sichere Abbildung möglich, blockiert der eBay-Schritt mit einem sichtbaren Hinweis.

## Brand/MPN und Item Specifics

Wenn Marke und Herstellernummer vorhanden sind, werden sie sowohl passend im eBay-Produktblock als auch in den relevanten Item Specifics gesetzt.

Damit werden eBay-Fehler wie fehlende oder ungültige `BrandMPN`-Daten möglichst vor dem Publish vermieden.

## Konsequenzen

- Open Inserto verspricht keinen Seller-Hub-Draft-Link.
- Der lokale Draft ist die Arbeits- und Review-Quelle.
- Die eBay-Vorbereitung ist wiederholbar und aktualisiert vorhandene Offers statt blind neue anzulegen.
- Kategorie- und Pflichtmerkmalprobleme gehören in die Draft-UI, nicht erst in das Publish-Fehlerlog.
- Der Publish-Schritt bleibt eine bewusste Nutzeraktion.
