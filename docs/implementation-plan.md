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

1. bestehendes MVP stabil halten und den Review-Flow weiter absichern
2. Conversation-Modell für Assistenten-Nachrichten und Antwortoptionen ergänzen
3. Design-System und mobile-first UI auf Basis des in ADR 0018 beschriebenen Stacks aufbauen
4. dynamische Nachrichten-Updates ohne Full-Page-Reload einführen
5. Review und Publish schrittweise in einen chat-artigen Assisted-Selling-Flow überführen
