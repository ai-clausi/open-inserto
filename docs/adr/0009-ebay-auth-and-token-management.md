# ADR 0009 – eBay Auth and Token Management

## Status

Accepted

## Context

Open Inserto soll im MVP eBay-Drafts über die Sell Inventory API vorbereiten.

Dafür braucht die Anwendung:

- einen sicheren Authentifizierungsweg zu eBay
- eine praktikable Tokenverwaltung
- einen Weg, lokale Entwicklung und produktiven Betrieb zu trennen

Gerade bei Verkaufsplattformen ist wichtig:

- keine Secrets im Code
- klare Trennung zwischen Konfiguration und Anwendung
- Tokens und Refresh-Mechanismen sauber handhaben

## Entscheidung

Im MVP wird eBay über OAuth angebunden.

Zugangsdaten und Tokens werden:

- **nicht im Code** gespeichert
- **nicht in Git** gespeichert
- über Umgebungsvariablen und sichere Laufzeitkonfiguration bereitgestellt

## Grundprinzipien

- eBay App-Credentials liegen in der Laufzeitumgebung
- Access Tokens werden zur Laufzeit verwendet
- Refresh-Mechanismen werden vorbereitet
- produktive Secrets gehören in `.env` / Container-Umgebung / Secret-Management, nicht ins Repo

## MVP-Ansatz

### Benötigte Konfigurationswerte

Voraussichtlich u. a.:

- eBay Client ID
- eBay Client Secret
- Redirect URI / RuName
- Marketplace / Site-Konfiguration
- Access Token
- ggf. Refresh Token

### Speicherung

Für den MVP bevorzugt:

- `.env` für lokale Entwicklung
- Docker-Umgebungsvariablen für Containerbetrieb

Optional später:
- Secret Store / Vault / NAS-spezifisches Secret-Management

## Was nicht ins Repo darf

- Client Secret
- Access Tokens
- Refresh Tokens
- Session-Daten
- Account-spezifische Live-Credentials

## Trennung der Umgebungen

Es soll zumindest logisch getrennt werden zwischen:

- **Sandbox / Test**
- **Live / Produktion**

### Warum?

- Draft-Workflow zuerst risikoarm testen
- Live-Listings nicht versehentlich erzeugen
- spätere Freigabe kontrollierbar machen

## Token-Verhalten

### Access Token

- kurzlebig
- zur Laufzeit nutzbar
- nicht dauerhaft hart im Code abgelegt

### Refresh Token

- falls für den gewählten Flow nötig, besonders sensibel behandeln
- nur lokal sicher speichern
- nicht in Logs schreiben

## Logging-Regeln

Die Anwendung darf niemals loggen:

- vollständige Tokens
- Secrets
- Authorization-Header
- Client Secret

Wenn Auth-Fehler auftreten, dann nur als technische Fehlermeldung ohne Secret-Leak.

## Warum diese Entscheidung?

### Vorteile

- sauberer Sicherheitsstandard für den MVP
- Docker/NAS-tauglich
- später gut aufrüstbar
- kein unnötiges Secret-Risiko im Repo

### Nachteile

- etwas mehr Setup-Aufwand am Anfang
- eBay-OAuth-Flow muss sauber verstanden und getestet werden

## Nicht gewählt

### Credentials fest im Code

Nicht gewählt, weil sicherheitstechnisch inakzeptabel.

### Manuelle Token-Eingabe pro Request

Nicht gewählt, weil unpraktisch und fehleranfällig.

## Konsequenzen

- das Projekt braucht früh eine saubere `.env`-Strategie
- `.gitignore` muss Secrets ausschließen
- produktive eBay-Zugangsdaten bleiben außerhalb des Repos
- spätere OAuth-Implementierung muss als eigener technischer Baustein betrachtet werden

## Nächster Schritt

Als Nächstes sollte festgelegt werden:

1. ob wir im MVP zuerst Sandbox oder direkt Live-Drafts ansteuern
2. wie das lokale Review-Ergebnis in einen eBay-Offer-Erstellungsprozess überführt wird
3. welche Statusübergänge intern nach erfolgreicher Offer-Erstellung gelten
