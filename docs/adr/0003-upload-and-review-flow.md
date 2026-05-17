# ADR 0003 – Upload and Review Flow

## Status

Accepted

Ergänzt durch ADR 0017 für die Trennung von unveränderter Originaleingabe, KI-generierten Werten und manuell bearbeiteten Feldern.

## Context

Open Inserto soll im MVP als einfache Web-Anwendung funktionieren:

- Nutzer lädt Bilder hoch
- System erzeugt einen Draft
- Nutzer prüft und korrigiert den Draft
- HTML wird erzeugt
- eBay-Draft / Offer wird vorbereitet

Damit dieser Ablauf verständlich und robust bleibt, braucht es einen klaren Upload- und Review-Flow.

## Entscheidung

Der MVP verwendet einen linearen Flow mit klaren Schritten:

1. **Upload**
2. **Analyse / Draft-Erzeugung**
3. **Review**
4. **Template-Rendering**
5. **Marketplace-Draft-Erstellung**
6. **Ergebnis / nächste Aktion**

## Geplanter Ablauf

### 1. Upload

Der Nutzer lädt hoch:

- 1 bis n Bilder
- optionale Notizen
- optionale manuelle Zusatzinfos

Beispiele:
- Produktname, falls bekannt
- Zustand
- Zubehör
- besondere Hinweise

### 2. Analyse / Draft-Erzeugung

Die Anwendung erzeugt daraus einen ersten Draft:

- Artikeltyp
- Marke / Modell
- Zustand
- Zubehörumfang
- erkannte Mängel / Unsicherheiten
- Vorschlag für Titel
- Vorschlag für Beschreibung
- Vorschlag für Kategorie

Wichtig:
- Unklarheiten werden nicht versteckt, sondern als fehlende Information markiert

### 3. Review

Der Nutzer bekommt eine Review-Seite mit:

- Bildern
- strukturierten Draft-Daten
- fehlenden / unsicheren Angaben
- HTML-Vorschau

Der Nutzer kann dabei:

- Felder korrigieren
- Angaben ergänzen
- Entwurf bestätigen

### 4. Template-Rendering

Nach Bestätigung wird das HTML-Gerüst final befüllt.

Dabei soll die App:
- strukturierte Felder in das Template einsetzen
- eine finale HTML-Beschreibung erzeugen
- diese Beschreibung speicherbar und erneut renderbar halten

### 5. Marketplace-Draft-Erstellung

Nach erfolgreichem Review erzeugt die App:

- eBay Inventory Item
- eBay Offer
- zunächst **nicht veröffentlicht**

### 6. Ergebnis

Die App zeigt danach:

- lokalen Draft-Status
- externe eBay-IDs
- Status wie z. B. `offer_created`
- nächsten sinnvollen Schritt

## UI-Prinzipien für den MVP

Die Oberfläche soll bewusst einfach bleiben.

### Bevorzugt
- server-rendered Seiten
- klassische Formulare
- wenige klare Ansichten

### Nicht nötig im MVP
- komplexe Single-Page-App
- Live-Collaboration
- umfangreiche Drag-and-Drop-Workflows

## Minimale Seiten / Ansichten

Für den MVP reichen voraussichtlich:

1. **Upload-Seite**
2. **Draft-/Review-Seite**
3. **Ergebnis-/Status-Seite**

Optional später:
- Draft-Liste
- erneute Bearbeitung bestehender Drafts
- Veröffentlichungs-Ansicht

## Fehler- und Blockerlogik

Wenn Informationen fehlen oder unklar sind:

- Draft bleibt lokal im Lebenszyklusstatus `draft`
- Review-Zustand wird aus den aktuellen Draft-Daten berechnet
- `workflow.missingInformation` wird gefüllt
- Nutzer muss bestätigen oder ergänzen

Wenn Marketplace-Erstellung fehlschlägt:

- Draft bleibt lokal erhalten
- Fehler wird separat ausgewiesen
- erneuter Versuch muss möglich sein

## Warum dieser Flow?

### Vorteile

- einfach verständlich
- gut für MVP
- klare Übergänge
- manuelle Qualitätskontrolle vor externer Aktion

### Nachteile

- noch kein stark paralleler Workflow
- manuelle Review bleibt notwendig

## Nicht gewählt

### Vollautomatische Veröffentlichung ohne Review

Nicht gewählt, weil das am Anfang zu riskant ist.

### Sehr freier, unstrukturierter Bearbeitungsfluss

Nicht gewählt, weil das für den MVP unnötig komplex wäre.

## Konsequenzen

- Review ist Pflicht vor eBay-Draft-Erstellung
- Draft-Erzeugung und Draft-Prüfung sind getrennte Schritte
- UI bleibt schlicht und robust

## Nächster Schritt

Als Nächstes sollte festgelegt werden:

1. wie das HTML-Template technisch eingebunden wird
2. welche Template-Platzhalter standardisiert unterstützt werden
