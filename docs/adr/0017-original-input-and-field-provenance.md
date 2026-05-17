# ADR 0017 – Originaleingabe und Feldherkunft

## Status

Accepted

Konkretisiert ADR 0003 und ADR 0005.

## Kontext

Im Review-Flow muss nachvollziehbar bleiben:

- was der Nutzer ursprünglich eingegeben hat
- was die KI vorgeschlagen hat
- was später manuell geändert wurde

Wenn normale Speichervorgänge die Originaleingabe überschreiben oder alle Felder pauschal als bearbeitet markieren, wird die UI unverständlich und die Review-Logik verliert ihren Nutzen.

## Entscheidung

Open Inserto behandelt die ursprüngliche Nutzereingabe als unveränderliche Referenz.

Die Originaleingabe wird beim Anlegen des Drafts gespeichert und danach nicht durch Review-Speichern, KI-Neuanalyse oder eBay-spezifische Ergänzungen überschrieben.

## Feldherkunft

Für finale Draft-Felder wird die Herkunft separat geführt.

Mögliche Quellen sind:

- Eingabe
- KI
- Bearbeitet
- Entwurf/System

Ein normales `Änderungen speichern` darf nicht automatisch alle Werte auf `Bearbeitet` setzen.

Die Feldherkunft ändert sich nur, wenn:

- der konkrete Feldwert vom Nutzer geändert wurde
- die KI einen neuen konkreten Vorschlag erzeugt
- ein Systemschritt einen technischen Wert setzt

## UI-Regeln

Die Draft-Seite zeigt Originaleingabe und finalen Entwurf getrennt.

Die Originaleingabe dient nur der Nachvollziehbarkeit. Der finale Entwurf ist die Datenquelle für Vorschau, eBay-Mapping und Veröffentlichung.

Fehlende oder unsichere eBay-Daten werden dort angezeigt, wo der Nutzer sie direkt bearbeiten kann. Versteckte Pflichtangaben sollen vermieden werden.

## Konsequenzen

- Review-Speichern darf `source.user_input` bzw. die gespeicherte Originaleingabe nicht überschreiben.
- Feld-Badges müssen aus echter Herkunft abgeleitet werden, nicht aus dem letzten Formular-Submit.
- KI-Neuanalysen dürfen ursprüngliche Nutzereingaben nicht nachträglich umdeuten.
- Die UI kann klar zwischen Eingabe, KI-Vorschlag und manueller Änderung unterscheiden.
