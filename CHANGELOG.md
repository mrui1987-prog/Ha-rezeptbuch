# Änderungen

## 0.2.0 – in Arbeit (Modul 02: Datenbank & Datenmodell)

- Rezeptserver: SQLite-Datenbank `/data/rezeptbuch.db` mit 18 Tabellen (Rohstoffe, Rezepte mit Versionen, Stückgewichten und Knetzeit, Chargengrößen, Aufträge, Chargen pro Teig, Wiegeprotokoll, Änderungsprotokoll)
- Mehrere Stückgewichte je Rezept, Knetzeit, Handzugabe nach Bedarf (0 g), Prüfmarkierung „*“ für importierte Mengen
- Datenintegrität über Fremdschlüssel, Prüfregeln und Trigger (fixierte Rezeptversionen, abgeschlossene Chargen und abgeschlossene Aufträge unveränderlich, Protokolle nur anhängbar; 38 Trigger)
- Nummerierte Migrationen mit automatischer Sicherungskopie und Rückrollen bei Fehlern
- Integritätsprüfung beim Start; bei Fehlern meldet `/api/v1/health` Status 503
- Doku: `docs/datenmodell.md` neu, `docs/bedienkonzept.md` an die Entscheidungen aus Modul 02 angepasst
- Add-on `rezeptbuch_waage` unverändert (0.1.0)

## 0.1.0 – in Arbeit

- Modul 01: Architektur und Bedienkonzept freigegeben
- Repository-Grundgerüst mit zwei Add-ons (`rezeptbuch`, `rezeptbuch_waage`)
