# Änderungen

## 0.5.10 – Modul 05, Korrektur (in Entwicklung)

- **Export → Re-Import mit archivierten Rohstoffen:** Ein vorhandenes Rezept, dessen aktuelle Version einen inzwischen archivierten Rohstoff schon verwendet, darf ihn beim Import behalten (wie beim Speichern im Formular). Vorher meldete der Import „Der Rohstoff … ist archiviert“. Neue Rezepte und neu hinzukommende Zeilen mit archivierten Rohstoffen bleiben ein Fehler

## 0.5.9 – Modul 05, Ergänzungen C3-E9, C3-E10 (in Entwicklung)

- **Rohstoff austauschen** (C3-E9, Taste über der Rezeptliste): alten und neuen Rohstoff mit Faktor wählen, dazu bis zu zwei Zusatzzutaten mit Faktor auf die alte Menge (direkt unter der getauschten Zeile, im selben Schritt). Angezeigt werden alle Rezepte, deren aktuelle Version den Rohstoff enthält, mit „alt → neu“; einzelne lassen sich abwählen. Jedes geänderte Rezept bekommt eine neue Version, Status und eigene Zeilentoleranz bleiben. Wahlweise „*“ an geänderten Zeilen und Archivieren des alten Rohstoffs, wenn er nirgends mehr vorkommt
- **Alte Versionen ansehen** (C3-E10): neben jeder Menge kursiv die Menge der aktuellen Version (gelb = abweichend, „entfällt“), neue Zeilen der aktuellen Version am Ende; am Handy unter der Menge

## 0.5.8 – Modul 05, Ergänzungen C3-E7, C3-E8, C3-E11 (in Entwicklung)

- **Umrechnung im Blatt „Rohstoffe“** (C3-E7, ersetzt das Blatt „Umrechnung“): Spalten „Umrechnung Einheit“ und „Gramm je Einheit“ beim Rohstoff, z. B. Eier: Stück, 65 – in der Rezeptzeile reicht dann „20“ „Stück“ „Eier“. Für ml gilt der Wert auch für l (× 1 000) und umgekehrt. Der Wert wird nicht gespeichert, er dient nur dem Import
- **Jede umgerechnete Zeile bekommt „*“** zum Prüfen; der Probelauf zeigt alle Umrechnungen vorab in einem eigenen Fenster („Weiter“), danach den Bericht
- Eine Zeile im Blatt „Rohstoffe“ nur mit Name und Umrechnung ändert einen vorhandenen Rohstoff nicht
- Ein Blatt „Umrechnung“ aus älteren Vorlagen wird übergangsweise weiter gelesen (Hinweis „veraltet“). Mustervorlage und Export enthalten es nicht mehr
- Hinweis zu LibreOffice („als .xlsx speichern“) in Mustervorlage, Export und Doku
- **Sammelaktion „Wiederherstellen“** für archivierte Rezepte (C3-E8), gleiche Regeln wie beim einzelnen Rezept
- **Musterdaten der Mustervorlage werden beim Import übersprungen** (C3-E11, erkannt am Namen); Hinweis im Bericht, Datei nur mit Musterdaten = „nichts zu importieren“. Zum Ausprobieren: Haken „Musterdaten der Mustervorlage mit importieren“

## 0.5.7 – Modul 05, Ergänzung C3-E5 (in Entwicklung)

- **Import vorhandener Rezepte erzeugt neue Versionen** (Wunsch Michael, ersetzt „vorhandene Nummer/Name = Fehler“): Ein Rezept der Datei, dessen Nummer (sonst Name) schon vorhanden ist, bekommt nach Bestätigung eine **neue Version**; die bisherige wird zur alten Version „old (n)“. Gleicher Inhalt = unverändert, keine Bestätigung nötig. Nummer, Gruppe und interne Notiz bleiben, wenn sie in der Datei leer sind; Stückgewichte und Chargengrößen werden über die Bezeichnung fortgeführt. Enthält die neue Version „*“, wird das Rezept gesperrt. Archivierte Rezepte und widersprüchliche Nummer/Name-Paare bleiben Fehler
- Bericht und Rückfrage nennen die Rezepte mit „Version n → neu n+1“

## 0.5.6 – Modul 05, Ergänzung C3-E4 (in Entwicklung)

- **Suche in der Rezeptliste mit Operatoren:** `R:Sonnenblumen` sucht unter den Rohstoffnamen, `K:Sonnenbl` unter den Kurznamen (jeweils in der aktuellen Version, Teiltreffer, ohne Groß-/Kleinschreibung). Ohne Operator wird wie bisher im Rezeptnamen gesucht (die Nummer geht weiter mit, ist aber nicht mehr im Hinweistext)

## 0.5.5 – Modul 05, Ergänzung C3-E3 (in Entwicklung)

- **Neue Filter in der Rezeptliste:** „öffentliche zeigen“ (Haken vorausgewählt, zum Ausblenden der öffentlichen Rezepte), „nie verwogen“ (noch nie in einem Auftrag oder einer Charge verwendet – solange es keine Wiegedaten gibt, trifft das auf alle Rezepte zu) und „enthält Unterrezepte“ (aktuelle Version). Lese-API: `include_public`, `never_weighed`, `has_sub_recipes`

## 0.5.4 – Modul 05, Ergänzung C3-E2 (in Entwicklung)

- **Mustervorlage herunterladen** (Reiter „Import/Export“): .xlsx mit Anleitung und allen Blättern der Importvorlage, gefüllt mit einem Musterrezept „Schwarzwälder Kirschtorte (Muster)“ (Unterrezept Schoko-Biskuit, Stück/ml über „Umrechnung“, „*“, Handzugabe, Zeilentoleranz, Stückgewicht, Chargengrößen) und Musterrohstoffen („Muster …“, damit echte Rohstoffe nicht überschrieben werden). Die gelben Musterzeilen vor dem echten Import löschen
- Hinweis „Bitte einen Rohstoff wählen“ beim Speichern erscheint jetzt als Fenster in der Mitte (wie Speichern/Löschen), nicht nur oben

## 0.5.3 – Modul 05, Ergänzung C3-E1 (in Entwicklung)

- **Sammelaktionen in der Rezeptliste:** Haken je Rezept und „alle auswählen“; sobald etwas angehakt ist, erscheint eine Leiste mit **Freischalten, Sperren, Archivieren, Löschen, Exportieren** und „Auswahl aufheben“
- Vor jeder Aktion eine Vorschau: was ausgeführt wird, was übersprungen wird (mit Grund, z. B. „ohne Zeilen“, „als Unterrezept verwendet“, „wird verwendet – bitte archivieren“) und beim Freischalten alle offenen „*“ und Toleranzen 0 % in einer Liste; eine Bestätigung für alle
- Es gelten dieselben Regeln wie beim einzelnen Rezept; nicht erlaubte Rezepte werden übersprungen, die übrigen ausgeführt. Haupt- und Unterrezept können gemeinsam archiviert oder gelöscht werden
- „Exportieren“ erzeugt die .xlsx-Datei nur mit den ausgewählten Rezepten und ihren Unterrezepten

## 0.5.2 – Modul 05, Teil C3 (in Entwicklung)

- **Rezeptimport aus der Importvorlage (.xlsx)** im neuen Reiter „Import/Export“: Blätter Rohstoffe, Rezepte, Rezeptzeilen, Stückgewichte, Chargengrößen und Umrechnung; erst Probelauf mit Bericht, dann Import; alles oder nichts
- Rohstoffe aus der Vorlage wie beim CSV-Import (vorhandene werden nach Bestätigung überschrieben, neue ohne Toleranz erhalten 0 %)
- Rezeptnummer oder Rezeptname schon vorhanden = Fehler; fehlende Gruppen werden angelegt; importierte Rezepte starten **gesperrt**, Zeilen mit „*“ behalten die Prüfmarkierung
- Menge g rechnet der Import selbst (Menge Original × Faktor aus g/kg/Blatt „Umrechnung“, kaufmännisch gerundet); leere Menge = 0 g Handzugabe; fehlender Faktor = Fehler; Abweichung zum Formelwert der Datei als Hinweis
- Unterrezepte innerhalb der Datei (werden zuerst angelegt), Kreise werden mit Weg gemeldet
- **Export der Rezepte als .xlsx** im Format der Vorlage (aktuelle Versionen, verwendete Rohstoffe, auf Wunsch mit archivierten Rezepten); wieder importierbar in eine leere Datenbank; Texte werden nie als Formel geschrieben
- **Interne Notiz** je Rezept (nur Admin-Bereich, nie an der Station; Ändern ohne neue Version; in Kopie, Export und Import enthalten); Datenbank-Migration `0004_recipe_note.sql`
- Rezeptseite nach der Praxisprüfung C2: Beschriftung „Kurzname“ statt „Station“; Hinweis-Anzeige „am Anfang und am Ende“ / „nur am Ende“ mit Erklärung zum leeren Hinweis; Taste „Zutaten speichern“; Stückgewichte/Chargengrößen mit deutlichem Warnhinweis bei ungespeicherten Änderungen und Rückfrage „Beides speichern / Nur Zutaten speichern“ (Änderungen gehen nicht mehr still verloren); Rückfrage zu betroffenen Chargengrößen schon beim Löschen eines Stückgewichts; Haken „mit archivierten Rohstoffen“ in der Rezeptliste; Konflikt zweier Geräte als Fenster mit „Neu laden“
- Neue Bibliothek `openpyxl`

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
