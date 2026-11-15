# Änderungen

## 0.3.4 – Korrektur nach Freigabeprüfung

- Ziffern-Sonderzeichen (z. B. „²“) in Rohstoffnummer oder Gebindegröße führten zu einem Serverfehler; jetzt erscheint die normale Meldung „muss eine ganze Zahl sein“

## 0.3.3 – Korrektur nach Praxisprüfung

- Rückfragen („endgültig löschen?“, Typwechsel) erschienen in der iOS-App nur mit „OK“ und ohne „Abbrechen“; jetzt eigene Rückfrage mit beiden Tasten

## 0.3.2 – Korrektur nach Praxisprüfung

- Startseite und Admin-Seite blieben beim ersten Aufruf in der iOS-Companion-App leer (erst nach Berührung sichtbar); erstes Zeichnen wird jetzt erzwungen

## 0.3.1 – Korrektur nach Praxisprüfung

- Startseite war im dunklen Home-Assistant-Design weiß auf weiß (Text unsichtbar); jetzt fester heller Hintergrund mit gut sichtbarer Taste „Admin-Bereich“, ebenso für die Admin-Seite

## 0.3.0 – in Prüfung (Modul 03: Rohstoff- & Zutatenverwaltung)

- Rohstoffverwaltung unter `/admin`: anlegen, bearbeiten, archivieren, wiederherstellen, löschen (nur wenn unbenutzt), Suche, CSV-Export
- Rohstoffnummer: nächste freie Nummer wird vorgeschlagen, bis zur ersten Verwendung änderbar; keine doppelten Namen (ohne Beachtung von Groß-/Kleinschreibung), Hinweis auf ähnliche Namen
- Optionaler Kurzname, der überall an der Station angezeigt wird (z. B. „Margarine“)
- Toleranz ist Pflichtfeld (g oder %); bei der Verwiegung gilt mindestens 1 g, 0 = Handzugabe
- Typwechsel Standard ↔ Mehl mit Warnung und Bestätigung, wenn Rezepte betroffen sind
- PIN-Schutz für alle ändernden Aufrufe, vorgezogen aus Modul 12: Probebetrieb mit PIN 1234 und rotem Hinweisbalken, nur Hash gespeichert, Sperre 5 Minuten nach 5 Fehlversuchen, Sitzungsdauer über Option `admin_timeout_minutes`
- Befund B6 aus Modul 02 behoben: eigene Datenbankverbindung je Anfrage
- Zurückgestellt (keine BÄKO-Anbindung): Allergene, Nährwerte, Zutatenliste, Lieferanten, Erstbefüllung und CSV-Import (Modul 05)

## 0.2.0 – freigegeben am 14.11.2026 (Modul 02: Datenbank & Datenmodell)

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
