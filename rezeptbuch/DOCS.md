# HA-Rezeptbuch

Rezeptverwaltung, Produktionsliste und Wiegeablauf für kleine Bäckereien.

**Stand 0.5.1:** Rohstoffverwaltung (Modul 03) mit CSV-Export und CSV-Import unter `/admin`, Rezeptverwaltung (Modul 05) unter `/admin/rezepte`. Rezeptimport aus der Importvorlage und Export folgen in 0.5.2. Die Oberfläche ist noch schlicht; die Gestaltung folgt in Modul 10.

## Datenbank

- Datei: `/data/rezeptbuch.db` (wird vom Home-Assistant-Backup erfasst)
- Beim Start wird die Datenbank geprüft und bei Bedarf auf den neuesten Stand gebracht.
- Vor jeder solchen Aktualisierung entsteht eine Sicherungskopie in `/data/backups/` (die letzten 5 bleiben erhalten).
- Ist die Datenbank beschädigt oder neuer als das Add-on, startet das Rezeptbuch nicht im Produktionsbetrieb und meldet den Fehler im Add-on-Protokoll.

## Voraussetzungen

- Home Assistant OS oder Supervised (Add-ons)
- MQTT-Broker (Add-on „Mosquitto broker“)
- Add-on „HA-Rezeptbuch Waage“ für die Waagenanbindung

## Oberflächen

| Adresse | Zweck |
|---------|-------|
| `/admin` | Rohstoffe (PIN) |
| `/admin/rezepte` | Rezepte und Rezeptgruppen (PIN); Aufträge folgen in späteren Modulen |

Die Stationsadressen für die Tablets an den Waagen folgen in Modul 09/10 und sind in dieser Version noch nicht vorhanden.

Im Probebetrieb gilt die PIN **1234** (roter Hinweisbalken). Die PIN-Änderung folgt in Modul 12. Es wird nur ein Hash gespeichert. Nach 5 Fehlversuchen ist die Eingabe 5 Minuten gesperrt. Die Sitzungsdauer stellt die Add-on-Option `admin_timeout_minutes` ein (Standard 5 Minuten).

## Rohstoffe importieren (CSV)

Taste **„CSV-Import“** in der Rohstoffliste. Die Datei hat das Format des CSV-Exports (Semikolon, Kopfzeile `Nummer;Name;Kurzname;Typ;Toleranz;Toleranzeinheit;Gebindegröße g;Gebindebezeichnung;Herkunft;archiviert;geändert am`). Gelesen werden „CSV UTF-8“ und „CSV (Trennzeichen-getrennt)“ aus Excel.

- Zuerst läuft immer ein **Probelauf**; er zeigt neue, überschriebene und unveränderte Rohstoffe, Fehler und Hinweise. Gespeichert wird erst mit **„Importieren“**, und nur wenn die Datei keinen Fehler enthält (alles oder nichts).
- Zuordnung über die **Nummer**, ohne Nummer über den **Namen**; passt keiner, wird der Rohstoff neu angelegt.
- **Vorhandene Rohstoffe werden überschrieben** (Bestätigung nötig). Leere Toleranz bleibt unverändert, leerer Kurzname und leeres Gebinde werden geleert, leerer Typ bleibt. Nummer und Herkunft ändern sich nie. „Herkunft“ und „geändert am“ werden nicht ausgewertet.
- **Neue Rohstoffe ohne Toleranz erhalten 0 %.** 0 % wird gewogen (bei der Verwiegung mindestens ±1 g); nur **0 g** ist eine Handzugabe. Mit dem Filter „nur Toleranz 0 %“ lassen sich diese Rohstoffe später finden.
- Spalte **„archiviert“**: ja = archivieren, nein = wiederherstellen. Rohstoffe, die nicht in der Datei stehen, bleiben unverändert.
- Viele Rohstoffe bearbeiten: CSV-Export → in Excel ändern → als CSV speichern → CSV-Import.
- Namen und Kurznamen dürfen nicht mit `=`, `+`, `-` oder `@` beginnen (Schutz vor Excel-Formeln).
- Höchstens 5 MB und 5 000 Zeilen je Datei.

## Rezepte

Reiter **„Rezepte“** im Admin-Bereich.

- **Neues Rezept:** Nummer wird vorgeschlagen (änderbar, solange das Rezept nirgends verwendet wurde). Der Name muss unter den nicht archivierten Rezepten eindeutig sein. Neue Rezepte starten **gesperrt** und erscheinen erst nach **„Freischalten“** in der Vorwahl.
- **Zutaten:** Rohstoff oder Unterrezept über Nummer oder Name wählen, Menge in ganzen Gramm. **0 g = Handzugabe** (nur quittieren). Toleranz leer = Toleranz des Rohstoffs; 0 % wird gewogen (mindestens ±1 g). Archivierte Rohstoffe und Rezepte sind für neue Zeilen nicht wählbar. Ein Rezept darf sich nicht über Unterrezepte selbst enthalten.
- **Speichern und Versionen:** Wurde die aktuelle Version schon produziert, entsteht automatisch eine neue Version. Sonst fragt das Rezeptbuch „Neue Version“ oder „Überschreiben“. Nur die Bestätigung einer „*“-Zeile mit „geprüft“ überschreibt ohne Rückfrage. Alte Versionen stehen als „old (n)“ in der Versionsliste und können nur angesehen werden.
- Hat ein anderes Gerät das Rezept inzwischen gespeichert, wird nichts überschrieben: Meldung „bitte neu laden“.
- **Stückgewichte und Chargengrößen** gehören zum Rezept und haben eine eigene Taste (keine neue Version). Wird ein Stückgewicht gelöscht, fallen die zugehörigen Chargengrößen nach Rückfrage mit weg.
- **Sperren** blendet ein Rezept nur in der Vorwahl aus; als Unterrezept bleibt es nutzbar. **Archivieren** geht nicht, solange das Rezept als Unterrezept in einem aktiven Rezept steckt. Archivierte Rezepte können wiederhergestellt, aber nicht bearbeitet werden. **Löschen** nur, wenn das Rezept nie verwendet wurde.
- **Kopieren** übernimmt die aktuelle Version, Stückgewichte und Chargengrößen als „Kopie von …“ (gesperrt).
- Gesamtgewicht und Summe Mehl zeigen den gespeicherten Stand der direkten Zeilen; Anteile und Bäckerprozent folgen mit Modul 06.
- **Gruppen** im Reiter „Gruppen“: anlegen, umbenennen, Reihenfolge, löschen nur, wenn kein Rezept (auch kein archiviertes) darin ist.

## Haftung

Die Software wird ohne Gewährleistung bereitgestellt (MIT-Lizenz). Rezeptmengen und Allergenangaben sind vom Betrieb zu prüfen.
