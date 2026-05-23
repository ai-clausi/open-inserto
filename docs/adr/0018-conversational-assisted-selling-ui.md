# ADR 0018 – Konversationeller Assisted-Selling-Flow

## Status

Accepted

Ergänzt ADR 0001, konkretisiert Issue #27 und beschreibt die nächste UX-Ausbaustufe nach dem aktuellen MVP-Review-Flow.

## Kontext

Der aktuelle MVP funktioniert, fühlt sich aber noch wie ein klassischer Draft-Editor an:

- Bilder hochladen
- KI-Vorschlag prüfen
- viele Felder auf einer Detailseite bearbeiten
- eBay-spezifische Pflichtangaben manuell ergänzen

Für das Zielbild von Open Inserto reicht das mittelfristig nicht.

Der gewünschte Flow soll stärker einem Assistenten-Dialog ähneln:

- Einstieg über Bilder
- sichtbare Analysephase
- erkannte Angaben werden aktiv bestätigt oder korrigiert
- Rückfragen erscheinen nur bei Unsicherheit oder Pflichtbedarf
- Antworten erfolgen bevorzugt über Buttons, Chips oder kurze Freitexte
- neue Nachrichten laden dynamisch nach, ohne Full-Page-Reload

## Entscheidung

Open Inserto entwickelt die nächste UX-Stufe als **chat-artigen Assisted-Selling-Flow** auf Basis der bestehenden FastAPI/Jinja-Architektur weiter.

### Bevorzugter UI-Stack

- **Tailwind CSS** für das Design-System und mobile-first UI
- **HTMX** für servernahe, fragmentbasierte Interaktionen
- **Alpine.js** für kleine lokale UI-States
- **SSE bevorzugt**, optional WebSockets, für dynamische Assistenten-Nachrichten ohne klassischen Reload-Flow

Ein großer SPA-Neubau mit React, Next.js oder Vue ist für diese Phase nicht die bevorzugte Richtung.

## Begründung

### Warum Tailwind CSS

- schnell konsistente UI-Bausteine aufbauen
- gute Kontrolle über Spacing, States und Responsive-Verhalten
- passt gut zu einer kleinen serverseitigen Anwendung ohne komplexe Frontend-Build-Architektur als Zwang

### Warum HTMX

- harmoniert mit FastAPI und serverseitigem HTML-Rendering
- reduziert Frontend-Komplexität im Vergleich zu einem SPA
- eignet sich gut für fragmentbasierte Schritte wie neue Assistenten-Nachrichten, Bestätigungen und Auswahloptionen

### Warum Alpine.js

- genug für Scroll-to-bottom, Button-States, Composer-Zustand, Loading-Indikatoren und kleine UI-Maschinen
- deutlich leichter als ein vollwertiges Component-Framework

### Warum SSE zuerst

- neue Assistenten-Nachrichten können serverseitig inkrementell ausgeliefert werden
- geringerer Architektur- und Betriebsaufwand als bidirektionale Echtzeit-Logik für jeden Schritt
- reicht für das gewünschte Gefühl eines lebendigen, asynchronen Dialogs oft aus

## Zielbild der Interaktion

1. Nutzer lädt Bilder hoch.
2. Die Oberfläche zeigt direkt im Conversation-Stream einen Analysezustand.
3. Der Assistent sendet eine erste Zusammenfassung des erkannten Artikels.
4. Erfasste Attribute werden explizit bestätigt oder zur Korrektur angeboten.
5. Offene oder unsichere Angaben werden priorisiert abgefragt.
6. Der Server entscheidet nach jeder Antwort, welche nächste Frage den größten Erkenntnisgewinn bringt.
7. Am Ende erscheint eine kompakte Review- und Publish-Freigabe im selben Flow.

## Produktregeln

### 1. Bestätigung vor stiller Übernahme

Automatisch erkannte Daten sollen nicht unsichtbar übernommen werden. Der Nutzer muss relevante Erkennungen nachvollziehen und bei Bedarf korrigieren können.

Beispiel:

- „Ich habe die Farbe Schwarz erkannt.“
- Aktionen: `Super`, `Ändern`

### 2. Fragen nur bei echtem Mehrwert

Die Conversation Engine soll nur fragen, wenn:

- ein Pflichtwert fehlt
- die Erkennung unsicher ist
- mehrere plausible Varianten vorliegen
- ein Marktplatzfeld ohne Nutzersicht riskant wäre

### 3. Antwortmodus passend zum Feld

Je nach Feldtyp:

- Buttons / Chips für klare Auswahlmöglichkeiten
- Ja/Nein für Bestätigungen
- Freitext für offene Angaben
- Korrekturpfade für bereits erkannte Werte

### 4. eBay-Komplexität progressive offenlegen

Die Standard-UX bleibt menschlich und verkaufsorientiert. Technische eBay-Strukturen werden erst dann prominent sichtbar, wenn sie für den nächsten Schritt nötig sind.

## Architekturfolgen

### Servermodell

Neben dem bestehenden Draft-Modell wird ein Conversation-Modell benötigt, mindestens mit:

- Nachrichten
- Sprecherrolle
- Nachrichtentyp
- Antwortoptionen
- referenziertem Feld / Attribut
- Confidence bzw. Entscheidungsgrund

### UI-Bausteine

Benötigte Komponenten:

- Chat-Layout
- Message-Bubbles
- Choice-Buttons / Chips
- Composer für Freitext
- Analyse- / Typing-State
- kompakte Review- / Publish-Karte

### Migrationsstrategie

Die aktuelle Draft-Seite bleibt zunächst funktional. Der neue Assistenten-Flow wird schrittweise aufgebaut, statt den funktionierenden MVP-Workflow in einem großen Umbau zu ersetzen.

## Umsetzungsphasen

### Phase 1 – Design-System und Conversation-Shell

- Tailwind einführen
- visuelle Tokens und wiederverwendbare Komponenten definieren
- Upload und Draft-Einstieg auf Conversation-UX ausrichten
- statische bzw. serverseitig vorbereitete Assistenten-Sektionen ergänzen

### Phase 2 – Dynamische Conversation

- HTMX-gestützte Nachrichtenschritte
- SSE- oder WebSocket-basierte neue Assistenten-Nachrichten
- Bestätigen / Ändern / Nachfragen als echte Interaktionsmuster

### Phase 3 – Priorisierte Fragen-Engine

- Confidence-basierte Frageauswahl
- Korrektur-Loops für erkannte Attribute
- Review- und Publish-Freigabe im Conversation-Stream

## Konsequenzen

- Die bestehende FastAPI/Jinja-Architektur bleibt vorerst erhalten.
- Ein SPA-Neubau ist aktuell kein Standardpfad.
- UX-Arbeit priorisiert mobile-first, dynamische Conversations und progressive Offenlegung statt größerer Formularseiten.
- Dokumentation und künftige UI-Änderungen sollten sich an diesem Zielbild orientieren.
