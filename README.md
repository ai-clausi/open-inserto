# open-inserto

Open Inserto ist ein Tool zum Vorbereiten und Veröffentlichen von Verkaufsangeboten auf Online-Marktplätzen.

## Zielbild

Das Projekt soll dabei helfen, aus Bildern und wenigen Zusatzinfos automatisch strukturierte Angebotsdaten zu erzeugen:

- Artikel erkennen
- sinnvolle Titel und Beschreibungen erzeugen
- HTML-Vorlagen befüllen
- Angebotsdaten validieren
- Angebotsdaten lokal prüfen und korrigieren
- eBay Inventory-Offers vorbereiten
- geprüfte Angebote bei eBay veröffentlichen

Wichtig: Die öffentliche eBay-API bietet keinen sauberen Weg, echte Seller-Hub-Entwürfe anzulegen. Open Inserto verwendet deshalb einen lokalen Draft als Review-Oberfläche. Der eBay-Schritt erstellt bzw. aktualisiert ein Inventory Item und einen unveröffentlichten Inventory Offer; erst der separate Veröffentlichungs-Schritt schaltet das Angebot live.

## MVP Scaffold lokal starten

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Dann ist die App unter <http://127.0.0.1:8000> erreichbar.

Hinweis: Für Container- und Remote-Szenarien ist das explizite Host-Binding auf `0.0.0.0` wichtig, damit die Anwendung nicht nur innerhalb des Containers erreichbar ist.

## Aktueller eBay-Ablauf

Der lokale Draft bleibt die führende Arbeitsfläche. Dort sind Originaleingabe, KI-Vorschläge, manuelle Änderungen, Bilder, Kategorie, Versandprofil und fehlende eBay-Merkmale sichtbar.

1. Beim Anlegen werden Bilder und Eingaben analysiert. Die ursprüngliche Eingabe bleibt als unveränderte Referenz erhalten.
2. Die App schlägt Titel, Beschreibung, Lieferumfang, Zustand, Kategorie und relevante Merkmale vor.
3. Die Kategorie wird über die eBay Taxonomy API gesucht. Nur sichere Treffer werden automatisch ausgewählt; sonst zeigt die App Vorschläge zur Auswahl.
4. Für die gewählte Kategorie lädt die App die von eBay geforderten Artikelmerkmale und versucht sie aus vorhandenen Daten bzw. gezielt per KI zu füllen.
5. `eBay-Angebot vorbereiten` validiert die Daten, lädt fehlende Bilder zu eBay hoch bzw. verwendet vorhandene eBay-Bild-URLs wieder, erstellt/aktualisiert das Inventory Item und erstellt/aktualisiert den unveröffentlichten Offer.
6. `Bei eBay veröffentlichen` aktualisiert den vorbereiteten Offer erneut und ruft danach `publishOffer` auf.

Fehlende Pflichtmerkmale, eine fehlende Kategorie oder ungültige eBay-Konditionswerte blockieren den eBay-Schritt vorab, damit Fehler nicht erst beim finalen Publish sichtbar werden.

## Kategorie und Pflichtmerkmale

Die Kategorieauswahl ist nicht hart im Code verdrahtet. Open Inserto nutzt eBay `get_category_suggestions` und bewertet die Treffer lokal gegen Titel, Produkttyp, erkannte Marke/Modell-Daten und Nutzereingaben.

Die Kategorie-Suche auf der Draft-Seite läuft asynchron. Wird keine passende Kategorie automatisch gewählt, bleibt der Draft bearbeitbar und die eBay-Angaben werden geöffnet, damit Kategorie und fehlende Merkmale direkt sichtbar sind.

Nach Auswahl einer Kategorie lädt Open Inserto die Kategorie-Merkmale über eBay `get_item_aspects_for_category`. Pflichtmerkmale werden vor dem Vorbereiten oder Veröffentlichen geprüft. Zusätzlich priorisiert die App optionale Merkmale heuristisch und zeigt nur die relevantesten als KI-gestützte Vorschläge im Draft an.

## KI-Analyse

Die KI-Analyse läuft über `DRAFT_ANALYSIS_BACKEND=auto` oder `vision`. Ohne vollständige OpenAI-Konfiguration fällt Open Inserto auf eine einfache lokale Basisanalyse zurück.

An OpenAI werden die Nutzernotizen, strukturierte Eingabefelder und bis zu `VISION_MAX_IMAGES` Bilder übertragen. Die Bilder werden vorher als JPEG verkleinert. Standardwerte:

```env
VISION_IMAGE_MAX_SIDE=1024
VISION_IMAGE_QUALITY=72
VISION_IMAGE_DETAIL=low
VISION_MAX_IMAGES=4
```

Damit bleibt die Analyse bewusst token- und kostenarm. Für Pflichtmerkmale und priorisierte optionale Merkmale nutzt Open Inserto zusätzliche gezielte KI-Abfragen nur dann, wenn die Kategorie bekannt ist und noch eBay-relevante Angaben fehlen. Automatisch gesetzte Merkmale werden intern mit Quelle und Confidence markiert.

## eBay Modus

Sandbox und Production nutzen bei eBay unterschiedliche App-Credentials. In der lokalen `.env` können beide Sets parallel hinterlegt werden; umgeschaltet wird nur über `EBAY_MODE`:

```env
EBAY_MODE=sandbox

EBAY_SANDBOX_CLIENT_ID=...
EBAY_SANDBOX_CLIENT_SECRET=...
EBAY_SANDBOX_RU_NAME=...

EBAY_LIVE_CLIENT_ID=...
EBAY_LIVE_CLIENT_SECRET=...
EBAY_LIVE_RU_NAME=...
```

Die älteren Variablen `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` und `EBAY_RU_NAME` werden weiterhin als Fallback unterstützt. OAuth-Tokens und eBay-Account-Defaults werden intern getrennt nach `sandbox` und `live` gespeichert, damit Sandbox-IDs nicht versehentlich gegen die Production-API verwendet werden.

### Lokaler OAuth-Callback

Der eBay-Login wird über die offizielle eBay-Website gestartet. Im eBay Developer Portal muss dafür ein HTTPS-Redirect hinterlegt sein; bei einer rein lokal laufenden Open-Inserto-Instanz kann eBay deshalb nicht direkt auf `localhost` zurückleiten.

Für die lokale Entwicklung kann der Login trotzdem abgeschlossen werden:

1. In Open Inserto auf `eBay verbinden` klicken.
2. Den Login und die Autorisierung bei eBay durchführen.
3. Nach dem eBay-Redirect die Parameter `code` und `state` aus der Browser-URL kopieren.
4. Lokal folgende URL öffnen:

```text
http://localhost:8000/integrations/ebay/callback?code=<CODE>&state=<STATE>
```

`state` muss aus demselben Login-Vorgang stammen, weil Open Inserto diesen Wert lokal prüft. Der Login muss deshalb immer zuerst über den Button in Open Inserto gestartet werden.

## Nächste UX-Ausbaustufe

Das aktuelle MVP bleibt bewusst serverseitig und formularnah, ist aber nicht das endgültige Zielbild.

Die nächste Phase ist ein **chat-artiger Assisted-Selling-Flow**. Der aktuelle Stand bringt dafür bereits eine konkrete UI-Referenz mit:

- Einstieg über eine Tailwind-basierte, chat-artige Upload-Oberfläche
- sichtbare AI-Loading-Animation während der Analyse
- erkannte Kernangaben direkt im Assistenten-Flow bestätigen oder korrigieren
- fehlende Kerninfos werden schrittweise ohne Full-Page-Reload nachgefragt
- das klassische Review-Formular bleibt als Fallback und Feinjustierung bestehen

Die Architekturentscheidung dazu ist in [`docs/adr/0018-conversational-assisted-selling-ui.md`](docs/adr/0018-conversational-assisted-selling-ui.md) festgehalten.

## Tests

```bash
pytest
```

## eBay Production Setup

Für eBay Production muss eine Marketplace Account Deletion Notification URL im eBay Developer Portal hinterlegt werden. Das ist eine eBay-Vorgabe, bevor Production-API-Zugriff möglich ist.

Da Open Inserto lokal läuft, wird dieser kleine öffentliche HTTPS-Endpoint separat auf AWS Lambda betrieben. Die OpenTofu-Konfiguration liegt unter [`infra/`](infra/README.md). Lokale Secrets wie `terraform.tfvars` und Backend-Konfigurationen werden nicht versioniert; passende `.example` Dateien liegen im Repo.

## Docker

```bash
docker build -t open-inserto .
docker run --rm -p 8000:8000 --env-file .env -v $(pwd)/data:/app/data open-inserto
```

Der Container nutzt standardmäßig `APP_HOST=0.0.0.0` und `APP_PORT=8000`. Bei Bedarf können die Werte über Umgebungsvariablen überschrieben werden.

Alternativ mit Docker Compose:

```bash
docker compose up --build
```
