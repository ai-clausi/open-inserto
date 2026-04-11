# ADR 0014 – Fehler- und Retry-Strategie

## Status

Accepted

## Entscheidung

Der MVP muss den lokalen Draft-Zustand bei Fehlern erhalten und sichere Wiederholungen ermöglichen.

## Regeln

- lokaler Draft darf bei API-Fehlern nie verloren gehen
- Fehler werden als lokaler Zustand gespeichert
- Fehlermeldungen sollen verständlich und handlungsorientiert sein
- Marketplace-Erstellung muss erneut versucht werden können
- Validierungsfehler und externe API-Fehler werden getrennt behandelt

## Beispielhafte Fehlerkategorien

- Eingabe-/Validierungsfehler
- Template-Rendering-Fehler
- Bildverarbeitungs-/Speicherfehler
- eBay-Auth-Fehler
- eBay-API-Fehler

## Warum?

- Zuverlässigkeit statt stiller Fehler
- bessere Nutzerführung
- einfachere Fehlersuche
