# Open Inserto – Implementation Plan

## Ziel

Open Inserto soll aus Bildern und wenigen Zusatzinformationen automatisiert Verkaufsangebote vorbereiten.

In der ersten Ausbaustufe liegt der Fokus auf eBay und einem sicheren Draft-Workflow:

1. Bilder eines Artikels werden bereitgestellt
2. der Artikel wird identifiziert
3. strukturierte Angebotsdaten werden erzeugt
4. ein HTML-Template wird befüllt
5. über die eBay API wird ein nicht veröffentlichtes Angebot vorbereitet
6. der Nutzer prüft den Entwurf und entscheidet anschließend selbst über die Veröffentlichung

## Hauptmodule

1. Input-Modul für Bilder und Zusatzinfos
2. Artikel-Erkennung / Draft-Analyse
3. internes Listing-Datenmodell
4. Template-Modul für HTML
5. eBay-Integrationsmodul für Inventory Item + unpublished Offer
6. Review-/Freigabeschritt
7. Persistenz / Zustandsverwaltung

## Architektur-Empfehlung

- kleine Applikation als Kern
- KI als Assistenzschicht für Erkennung und Formulierung
- n8n optional für Orchestrierung und Freigaben

## Nächste Schritte

1. Tech-Stack festlegen
2. internes Draft-Datenmodell definieren
3. Template-Platzhalter festlegen
4. eBay Auth-/API-Setup klären
5. MVP für „Bilder → Draft-Daten → HTML → eBay Draft“ bauen
