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

## Tests

```bash
pytest
```

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
