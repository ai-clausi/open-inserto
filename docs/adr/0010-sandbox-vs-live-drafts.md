# ADR 0010 – Sandbox vs. Live Draft Strategy

## Status

Accepted

## Context

Open Inserto soll eBay-Drafts erzeugen.

Vor der produktiven Nutzung stellt sich die Frage:

- erst in der eBay-Sandbox entwickeln und testen?
- oder direkt mit Live-Drafts arbeiten?

Beide Wege haben Vor- und Nachteile.

## Entscheidung

Für den MVP gilt folgende Strategie:

1. **technische Entwicklung und erste API-Tests** möglichst gegen **Sandbox**, soweit sinnvoll
2. **fachlich echter Draft-Workflow** anschließend mit **Live-Drafts**, weil nur dort der reale Verkäufer-Account und die echte spätere Veröffentlichung relevant sind

## Warum nicht nur Sandbox?

Die Sandbox ist sinnvoll für:

- OAuth-/API-Grundtests
- Payload-Struktur
- technische Integrationsfehler

Aber sie reicht oft nicht vollständig für den echten Nutzwert, weil:

- reale Verkäuferkonfigurationen fehlen können
- echte Policies / reale Konto-Setups abweichen können
- der echte Draft- und Veröffentlichungsprozess im Live-Account entscheidend ist

## Warum nicht nur Live?

Nur Live wäre für den Start unnötig riskant.

Deshalb:
- technische Grundlagen zuerst möglichst risikoarm testen
- danach gezielt auf Live-Drafts wechseln
- Veröffentlichung weiterhin bewusst getrennt halten

## Praktische MVP-Strategie

### Phase 1 – technische API-Validierung

- OAuth testen
- Inventory-Item-Flow testen
- Offer-Erstellung technisch testen
- Fehlerfälle verstehen

### Phase 2 – echter Draft-Workflow im Live-Account

- nur unveröffentlichte Offers erzeugen
- Review bleibt Pflicht
- Veröffentlichung nicht automatisieren, solange der Draft-Prozess nicht stabil ist

## Sicherheits- und Prozessgedanke

Der wichtige Schutz liegt nicht nur in Sandbox vs. Live, sondern auch in:

- Draft-first-Ansatz
- manueller Review
- keine automatische Veröffentlichung im MVP

## Konsequenzen

- die Anwendung sollte beide Modi grundsätzlich trennen können
- Konfiguration für Sandbox und Live muss sauber getrennt sein
- erste echte Nutzbarkeit entsteht über Live-Drafts
- Veröffentlichung bleibt zunächst ein bewusster separater Schritt

## Vorteile

- risikoärmerer Start
- realistischer Live-Nutzen bleibt möglich
- bessere Kontrolle beim Übergang in echte Listings

## Nachteile

- zwei Umgebungen erhöhen den Integrationsaufwand
- Sandbox kann nicht alle realen Bedingungen abbilden

## Nicht gewählt

### Nur Sandbox

Nicht gewählt, weil der echte Mehrwert des Tools dann zu spät überprüfbar wäre.

### Sofort voll auf Live ohne Vorprüfung

Nicht gewählt, weil das unnötige Fehler- und Account-Risiken erzeugen würde.

## Nächster Schritt

Als Nächstes sollte festgelegt werden:

1. welche internen Status ein Draft nach erfolgreicher Offer-Erstellung bekommt
2. wie die App lokale Drafts und externe eBay-Offer-IDs zusammenführt
3. wie die erste Review-/Statusseite nach erfolgreichem eBay-Draft aussehen soll
