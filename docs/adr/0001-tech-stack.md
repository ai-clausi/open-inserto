# ADR 0001 – Initial Tech Stack

## Status

Accepted

## Context

Open Inserto soll als einfache lokale Web-Anwendung starten, die z. B. in einem Docker-Container auf einer NAS laufen kann.

Geplanter Ablauf im MVP:

- Bilder im Browser hochladen
- Angebotsdaten strukturiert erzeugen
- HTML-Vorlage befüllen
- eBay-Draft vorbereiten
- Ergebnisse prüfen

Für den Start ist wichtig:

- geringer technischer Overhead
- lokal gut betreibbar
- leicht verständlicher Stack
- schnelle MVP-Umsetzung
- gute Eignung für API-Integrationen und KI-nahe Logik

## Entscheidung

Für den Start verwenden wir:

- **FastAPI** als Backend
- **SQLite** als erste Persistenzlösung
- **Docker** für Deployment und lokale/portable Ausführung
- **server-rendered Frontend** mit leichtem HTML-Ansatz
- optional **HTMX** für kleine interaktive UI-Verbesserungen ohne schweres SPA-Framework

## Warum dieser Stack?

### FastAPI

- schlank und modern
- gut für APIs und Dateiuploads
- passt gut zu Python-basierten Integrationen
- geeignet für KI-/Automatisierungslogik

### SQLite

- für den MVP völlig ausreichend
- einfach zu betreiben
- keine zusätzliche Datenbank-Infrastruktur nötig

### Docker

- ideal für Deployment auf einer NAS
- reproduzierbares Setup
- später leicht erweiterbar

### Server-rendered Frontend

- deutlich weniger Overhead als React/Vue im MVP
- schnell umsetzbar
- leicht verständlich
- gut geeignet für Formulare, Uploads und Review-Seiten

### HTMX

HTMX ist eine kleine Bibliothek, mit der HTML-Seiten dynamischer werden können, ohne gleich ein großes Frontend-Framework einzuführen.

Beispiele:
- Upload-Status aktualisieren
- Felder nachladen
- Teile einer Seite neu rendern
- Review-Bereiche aktualisieren

Damit bleibt die App einfach, aber trotzdem angenehm interaktiv.

## Konsequenzen

### Positiv

- schneller Start
- wenig Komplexität
- gut für Docker/NAS
- Python eignet sich gut für Bilder, Templates und eBay-Integration

### Negativ / bewusst in Kauf genommen

- SQLite ist nicht die Endlösung für große Skalierung
- HTMX ist weniger bekannt als React/Vue
- bei stark wachsendem UI-Anspruch müsste das Frontend später evtl. ausgebaut werden

## Nicht gewählt

### React / Vue / Next.js

Für den MVP unnötig schwergewichtig.

### Node.js als Hauptbackend

Wäre möglich, aber Python passt für den geplanten Mix aus Dateiverarbeitung, API-Integration und KI-Assistenz besser.

### PostgreSQL direkt zum Start

Für den MVP voraussichtlich unnötig aufwendig.

## Nächster Schritt

Auf Basis dieses Stacks sollten als Nächstes definiert werden:

1. internes Draft-Datenmodell
2. Upload- und Review-Flow
3. Template-Platzhalter
4. eBay-Auth-Handling
