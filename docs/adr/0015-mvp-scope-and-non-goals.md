# ADR 0015 – MVP-Umfang und Nicht-Ziele

## Status

Accepted

Teilweise überholt durch ADR 0016. Die Veröffentlichung bleibt ein expliziter Nutzer-Schritt nach Review, ist aber inzwischen Teil des unterstützten eBay-Flows.

## MVP-Umfang

Die erste Version soll unterstützen:

- Single-Item-Listing-Flow
- Bildupload
- strukturierte Draft-Erzeugung
- HTML-Template-Rendering
- Review-Schritt
- eBay Inventory Item Erstellung
- unveröffentlichte eBay-Offer-Erstellung
- explizite eBay-Veröffentlichung nach Review
- lokale Persistenz von Draft + externen IDs

## Explizite Nicht-Ziele für den MVP

- automatische Veröffentlichung ohne explizite Nutzeraktion
- Auktionssupport als primärer Pfad
- Multi-Marketplace-Support
- Variantenprodukte
- komplexe Versandmatrix-Logik
- vollständige Abdeckung aller eBay-Item-Specifics
- schwergewichtiges SPA-Frontend
- Multi-User-Collaboration

## Warum?

Ein enger MVP reduziert Risiko und bringt den nützlichen Kern schneller zum Laufen.
