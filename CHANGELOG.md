# Änderungen

## 0.5.1 – Modul 05, Teil C2 (in Entwicklung, Zweig `modul05-c2`)

- **Rezeptverwaltung** unter `/admin/rezepte` (Reiter „Rohstoffe | Rezepte | Gruppen“): Rezepte anlegen, bearbeiten, kopieren, sperren/freischalten, archivieren, wiederherstellen und löschen (nur nie verwendete)
- Rezeptkopf mit Nummer (Vorschlag, bis zur ersten Verwendung änderbar), Name (eindeutig), Gruppe, Knetzeit langsam + schnell und Hinweistext (Anzeige zu Beginn oder am Ende)
- Schritte und Zutatenzeilen: Rohstoff oder Unterrezept per Nummer oder Name, Menge in Gramm (0 g = Handzugabe), eigene Toleranz je Zeile (leer = Toleranz des Rohstoffs), Zeilen verschieben, einfügen, löschen; Prüfmarkierung „*“ mit Taste „geprüft“
- Unterrezepte ohne Kreise (Meldung mit dem Weg, z. B. „Hauptteig → Vorteig → Hauptteig“)
- **Versionen:** Wurde die Version schon produziert, entsteht beim Speichern automatisch eine neue; sonst Rückfrage „Neue Version / Überschreiben“. Alte Versionen als „old (n)“ nur zum Ansehen
- Schutz vor gleichzeitigem Bearbeiten an zwei Geräten („bitte neu laden“)
- Stückgewichte und Chargengrößen je Rezept (eigene Taste, ohne neue Version)
- Neue Rezepte und Kopien starten **gesperrt**; „Freischalten“ nur mit Zeilen, bei „*“ oder Toleranz 0 % mit Warnung und Bestätigung
- Rezeptgruppen anlegen, umbenennen, sortieren, löschen (nur leere)
- Lese-Schnittstelle für die Stationen: `GET /api/v1/recipes`, `/recipes/{id}`, `/recipes/{id}/versions/{n}`, `/recipe-groups`
- Sperre B2 auch für Rezept-, Gruppen- und Schrittnamen sowie Bezeichnungen von Stückgewichten und Chargengrößen

## 0.5.0 – Modul 05, Teil C1 (in Entwicklung)

- **Rohstoff-CSV-Import** im Admin-Bereich (Taste „CSV-Import“): Format wie der CSV-Export, erst Probelauf mit Bericht, dann Import; alles oder nichts
- Vorhandene Rohstoffe werden mit den Werten der Datei **überschrieben** (Zuordnung über die Nummer, ohne Nummer über den Namen); der Bericht zeigt je Feld „alt → neu“, der Import startet erst nach der Bestätigung „n Rohstoffe werden überschrieben“
- Neue Rohstoffe mit leerer Toleranz erhalten **0 %** (wird gewogen, mindestens ±1 g) und werden im Bericht aufgelistet; leere Toleranz bei vorhandenen Rohstoffen bleibt unverändert
- Spalte „archiviert“ archiviert bzw. stellt wieder her; Rohstoffe, die nicht in der Datei stehen, bleiben unverändert
- Dateien aus Excel („CSV UTF-8“ und „CSV (Trennzeichen-getrennt)“) werden gelesen, ebenso Zahlen wie „25.000“
- Rohstoffliste: Filter **„nur Toleranz 0 %“**; Hinweis unter dem Toleranzfeld: 0 g = Handzugabe, 0 % wird gewogen
- **Sperre B2:** Namen und Kurznamen, die mit `=`, `+`, `-` oder `@` beginnen, werden beim Anlegen, Umbenennen und Import abgelehnt (vorhandene Namen bleiben)
- Datenbank-Migration `0003_recipe.sql`: Bearbeitungsstand je Rezept, Sperre der Rezeptnummer nach der ersten Verwendung (Vorbereitung für Teil C2)

## 0.3.4 – Korrektur nach Freigabeprüfung

- Ziffern-Sonderzeichen (z. B. „²“) in Rohstoffnummer oder Gebindegröße führten zu einem Serverfehler; jetzt erscheint die normale Meldung „muss eine ganze Zahl sein“

## 0.3.3 – Korrektur nach Praxisprüfung

- Rückfragen („endgültig löschen?“, Typwechsel) erschienen in der iOS-App nur mit „OK“ und ohne „Abbrechen“; jetzt eigene Rückfrage mit beiden Tasten

## 0.3.2 – Korrektur nach Praxisprüfung

- Startseite und Admin-Seite blieben beim ersten Aufruf in der iOS-Companion-App leer (erst nach Berührung sichtbar); erstes Zeichnen wird jetzt erzwungen

## 0.3.1 – Korrektur nach Praxisprüfung

- Startseite war im dunklen Home-Assistant-Design weiß auf weiß (Text unsichtbar); jetzt fester heller Hintergrund mit gut sichtbarer Taste „Admin-Bereich“, ebenso für die Admin-Seite

## 0.3.0 – freigegeben am 15.11.2026 (Modul 03: Rohstoff- & Zutatenverwaltung; Korrekturen 0.3.1 bis 0.3.4)

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
