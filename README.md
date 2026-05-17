# open-inserto

Open Inserto ist ein Tool zum Vorbereiten und perspektivisch auch Veröffentlichen von Verkaufsangeboten auf Online-Marktplätzen.

## Zielbild

Das Projekt soll dabei helfen, aus Bildern und wenigen Zusatzinfos automatisch strukturierte Angebotsdaten zu erzeugen:

- Artikel erkennen
- sinnvolle Titel und Beschreibungen erzeugen
- HTML-Vorlagen befüllen
- Angebotsdaten validieren
- Entwürfe bei Plattformen wie eBay anlegen
- später optional auch vollständige Veröffentlichungen unterstützen


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
