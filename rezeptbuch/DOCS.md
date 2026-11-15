# HA-Rezeptbuch

Rezeptverwaltung, Produktionsliste und Wiegeablauf für kleine Bäckereien.

**Stand 0.5.0:** Rohstoffverwaltung (Modul 03) mit CSV-Export und CSV-Import unter `/admin`. Rezeptverwaltung (Modul 05) ist in Arbeit. Die Oberfläche ist noch schlicht; die Gestaltung folgt in Modul 10.

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
| `/admin` | Rohstoffe (PIN); Rezepte und Aufträge folgen in späteren Modulen |

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

## Haftung

Die Software wird ohne Gewährleistung bereitgestellt (MIT-Lizenz). Rezeptmengen und Allergenangaben sind vom Betrieb zu prüfen.
