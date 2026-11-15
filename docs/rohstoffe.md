# Modul 03 – Rohstoff- & Zutatenverwaltung (Schritt B: Konzept)

Status: **Modul 03 am 15.11.2026 von Michael freigegeben (Add-on 0.3.4); Konzept am 14.11.2026 freigegeben, Praxisprüfung in Home Assistant am 15.11.2026 bestanden; Abweichungen und Korrekturen siehe Abschnitt 14**
Grundlage: Code-Stand `main` 43df855 (Add-on `rezeptbuch` 0.2.0), docs/datenmodell.md, docs/bedienkonzept.md, Entscheidungen M03-1 bis M03-8 und K03-1 bis K03-4 (PROJEKTSTATUS Abschnitt 3).
Zielversion: Add-on `rezeptbuch` **0.3.0** (aktueller Stand nach Korrekturen: **0.3.4**).

## 1. Umfang

**Enthalten**
- Rohstoffstamm mit Grunddaten (`raw_material`) plus **Kurzname** (M03-3b).
- Anlegen, Bearbeiten, Suchen, Archivieren, Wiederherstellen, Löschen (nur nie verwendete).
- Prüfregeln: eindeutiger Name, Nummernvergabe, Toleranz, Gebinde, Typwechsel mit Warnung.
- Änderungsprotokoll in `change_log`.
- PIN-Schutz mit echter Abfrage, **Probebetrieb-PIN 1234** (M03-7).
- CSV-Export der Rohstoffe (M03-8).
- Eine schlichte Seite mit PIN-Eingabe und Rohstoffliste (M03-6).
- **Befund B6 aus Modul 02:** eigene Datenbankverbindung je Anfrage statt einer gemeinsamen Verbindung (K03-1, vorgezogen aus Modul 05).

**Nicht enthalten**
- Zurückgestellt bis BÄKO-Anbindung: Allergene, Nährwerte, Zutatenverzeichnis, Lieferanten/Artikelnummern, Herkunft „BÄKO“ mit Importdatum.
- Erstbefüllung und CSV-Import (M03-1, aufgeschoben zu Modul 05).
- PIN ändern, Ende des Probebetriebs (Modul 12).
- Gestaltung der Oberfläche (Modul 10), Anzeige an der Station (Modul 09/10).

## 2. Architektur

Alles im Add-on `rezeptbuch`, strikt getrennt in Schichten:

```
Browser (Seite /admin)  ──fetch──►  router (FastAPI, nur HTTP)
                                       │
                            auth.require_admin (PIN-Sitzung)
                                       │
                                    service (Regeln, Transaktion, change_log)
                                       │
                                    db (sqlite3, Modul 02; Verbindung je Anfrage)
```

- Die Regeln liegen nur im **service**. Router und Seite enthalten keine Fachlogik, damit Modul 05 (Rezeptimport) und Modul 04 (BÄKO-Import) dieselben Funktionen nutzen. Service und `auth` kennen kein FastAPI und sind deshalb ohne Webserver testbar.
- **Datenbankverbindung (B6, K03-1):** Beim Start wird die Datenbank wie bisher einmal geöffnet, geprüft und migriert (`init_database`). Danach öffnet jede Anfrage über die Abhängigkeit `get_db` (`app/deps.py`) eine **eigene Verbindung** mit `connect()` und schließt sie am Ende. SQLite (WAL-Modus, 5 s Wartezeit) regelt die Reihenfolge. Der Modul-02-Code (`app/db/`) bleibt unverändert.

## 3. Datenbank – Migration `0002_raw_material.sql`

`0001_initial.sql` bleibt unverändert (ausgeliefert). Neu:

| Änderung | Inhalt | Grund |
|---|---|---|
| Spalte `raw_material.display_name` | TEXT, leer erlaubt, sonst nicht nur Leerzeichen | Kurzname (M03-3b), muss nicht eindeutig sein |
| Trigger `trg_raw_material_number_locked` | lehnt Änderung von `number` ab, sobald der Rohstoff in `recipe_item`, `production_order` (Leitrohstoff) oder `batch_item` vorkommt | M03-2, Schutz auch auf Datenbankebene |
| Index `idx_raw_material_name` | auf `name` | schnelle Suche |

Ablauf wie in Modul 02: automatische Sicherungskopie vor der Migration, Rückrollen bei Fehler.

**Eindeutiger Name (M03-3):** Die Prüfung läuft im service mit Python `casefold()` und `trim`, innerhalb einer Schreibtransaktion (`BEGIN IMMEDIATE`). Grund: SQLite kann Groß- und Kleinschreibung nur bei A–Z vergleichen, nicht bei Ä/Ö/Ü. Die Regel gilt unter den **nicht archivierten** Rohstoffen.

## 4. Fachregeln

| Nr. | Regel |
|---|---|
| R03-1 | **Nummer:** Vorschlag = höchste vorhandene Nummer + 1 (auch archivierte zählen, damit keine Nummer doppelt vergeben wird). Von Hand änderbar, ganze Zahl > 0, eindeutig. Nach erster Verwendung gesperrt (Meldung „Nummer ist in Rezepten verwendet und kann nicht mehr geändert werden“). |
| R03-2 | **Name:** Pflicht, eindeutig ohne Rücksicht auf Groß-/Kleinschreibung und Leerzeichen am Rand. Doppelte Leerzeichen werden zusammengezogen. |
| R03-3 | **Ähnliche Namen:** Beim Anlegen zeigt das System Hinweise auf ähnliche Namen (z. B. „Marrgarine“ ↔ „Margarine“), sperrt aber nicht. Vergleich mit Python `difflib` (Schwelle 0,8, keine neue Bibliothek). |
| R03-4 | **Kurzname:** optional, frei wählbar, mehrfach erlaubt (z. B. drei Sorten mit „Margarine“). Leer = Name wird angezeigt. **An der Station überall der Kurzname** (Vorwahl, Rezeptübersicht, Wiegeansicht; K03-4). Admin-Bereich, Export und Chargenprotokoll zeigen immer den vollen Name. Die Anzeige an der Station setzen Modul 09/10 um; die API liefert dafür das Feld `station_name` (Kurzname, sonst Name). |
| R03-5 | **Toleranz:** Pflichtfeld. **Beim Anlegen ist das Feld leer** und muss ausgefüllt werden (K03-3); ohne Wert wird nicht gespeichert. `0` = Sollhandzugabe (nur quittieren). In Gramm ganze Zahl ≥ 0. In Prozent auf Zehntel genau, höchstens 100,0 %. Einheit vorbelegt mit Gramm (R1). Die **Mindesttoleranz 1 g** (M03-4) wirkt bei der Verwiegung und wird in Modul 06/09 umgesetzt; hier wird sie nur als Hinweis unter dem Eingabefeld angezeigt. |
| R03-6 | **Gebinde/Stück:** Größe in Gramm und Bezeichnung nur zusammen (z. B. 55 g „Ei“). |
| R03-7 | **Typwechsel Mehl ↔ Standard** (M03-5): erlaubt. Ist der Rohstoff in Rezepten verwendet, antwortet das System zuerst mit einer Warnung „betrifft n Rezepte – ‚Mehl gesamt‘ ändert sich dort“ (Code `type_change_confirmation_required`). Erst nach Bestätigung (`confirm_type_change: true`) wird gespeichert. Fixierte Versionen und Chargen bleiben unverändert. |
| R03-8 | **Herkunft:** Handanlage immer „eigen“. „BÄKO“ setzt nur der spätere Datenlink-Import (Modul 04). |
| R03-9 | **Archivieren:** jederzeit möglich. Archivierte Rohstoffe erscheinen nicht mehr in der Auswahl für neue Rezeptzeilen (Modul 05), bestehende Rezepte bleiben unverändert. |
| R03-10 | **Wiederherstellen:** nur, wenn kein aktiver Rohstoff denselben Namen hat (sonst Meldung mit Hinweis auf den gleichnamigen Rohstoff). |
| R03-11 | **Löschen:** nur, wenn nie verwendet. Sonst Meldung „wird in n Rezepten verwendet – bitte archivieren“. Die Datenbank sperrt das zusätzlich per Fremdschlüssel. |
| R03-12 | **Protokoll:** jede Änderung in `change_log` (Quelle `admin`, `entity = raw_material`, alte und neue Werte als JSON). |

## 5. PIN-Schutz (M03-7)

| Punkt | Festlegung |
|---|---|
| Speicherung | `setting.pin_hash`: PBKDF2-SHA256 (200 000 Durchläufe, Salz, Python-Standardbibliothek). Die PIN selbst wird nie gespeichert. |
| Probebetrieb | Fehlt beim Start ein PIN-Hash, legt der Server den Hash von **1234** an und setzt `setting.pin_is_default = 1`. Solange das gilt, zeigt die Seite einen roten Balken **„Probebetrieb – PIN 1234“**. Erst Modul 12 (PIN ändern) beendet den Probebetrieb. |
| Anmeldung | `POST /api/v1/admin/login` mit PIN → zufälliges Sitzungszeichen (nur im Arbeitsspeicher, nach Neustart neu anmelden). Die Seite schickt es bei jedem Aufruf im Kopf `X-Rezeptbuch-Session` mit. Kein Cookie, weil der Pfad hinter HA-Ingress wechselt. |
| Schutz | Alle ändernden Aufrufe und der Export unter `/api/v1/admin/...` prüfen die Sitzung (zentrale Funktion `require_admin`). Ohne gültige Sitzung: 401. |
| Sitzungsdauer | Vorhandene Add-on-Option **`admin_timeout_minutes`** (Standard 5 min, einstellbar 1–60; K03-2). Jede gültige Anfrage verlängert die Sitzung. |
| Sperre | Nach **5 Fehlversuchen** 5 Minuten gesperrt (Antwort 423). Die Sperre gilt für alle Geräte, da es keine Benutzer gibt. |
| Abmelden | `POST /api/v1/admin/logout`, außerdem automatisch nach Ablauf. |
| Zusätzlicher Schutz | Zugriff weiterhin nur über HA-Ingress mit HA-Anmeldung. |

## 6. Schnittstellen (REST `/api/v1`)

Lesen (ohne PIN, die Stationen brauchen das später):

| Methode | Pfad | Inhalt |
|---|---|---|
| GET | `/raw-materials?search=&include_archived=false` | Liste (einfaches Array), Suche in Nummer, Name, Kurzname; jedes Element mit `station_name` |
| GET | `/raw-materials/{id}` | ein Rohstoff mit Verwendungszahl |
| GET | `/system/info` | Version, `pin_is_default` (für den Probebetrieb-Balken), `admin_timeout_minutes` |

Ändern (mit PIN-Sitzung):

| Methode | Pfad | Inhalt |
|---|---|---|
| POST | `/admin/login`, `/admin/logout` | Sitzung |
| GET | `/admin/raw-materials/next-number` | Nummernvorschlag |
| GET | `/admin/raw-materials/similar?name=` | ähnliche Namen |
| POST | `/admin/raw-materials` | anlegen |
| PATCH | `/admin/raw-materials/{id}` | bearbeiten; Typwechsel bei Verwendung nur mit `confirm_type_change: true` |
| POST | `/admin/raw-materials/{id}/archive`, `/restore` | archivieren, wiederherstellen |
| DELETE | `/admin/raw-materials/{id}` | löschen, nur wenn nie verwendet |
| GET | `/admin/raw-materials/export.csv` | CSV-Export |

Fehlerantworten (immer mit deutscher Meldung im Feld `detail`, dazu `field` und `code`): 400 ungültige Eingabe, 401 nicht angemeldet, 404 nicht gefunden, 409 Konflikt (Name doppelt, Nummer vergeben oder gesperrt, Löschen verwendet, Typwechsel ohne Bestätigung), 423 PIN gesperrt, 503 Datenbank nicht bereit oder gesperrt.

**CSV-Export:** Semikolon als Trenner, UTF-8 mit BOM (öffnet direkt richtig in Excel), Prozent mit Komma (2,5). Spalten: Nummer; Name; Kurzname; Typ; Toleranz; Toleranzeinheit; Gebindegröße g; Gebindebezeichnung; Herkunft; archiviert; geändert am. Dasselbe Format dient später für den Import (Modul 05).

## 7. Seite (schlicht, ohne Gestaltung)

Eine einzige, in sich geschlossene HTML-Datei (`app/web/static/admin.html`, Stil und Skript eingebettet), erreichbar unter `/admin`, `/admin/login` und `/admin/rohstoffe`. Die Adresse der Schnittstelle bestimmt die Seite aus ihrer eigenen Adresse (HA-Ingress-sicher, keine weiteren Dateiadressen).

- **PIN-Ansicht:** PIN-Feld mit Ziffernblock, roter Probebetrieb-Balken, Meldung bei falscher PIN oder Sperre.
- **Rohstoffliste:** Tabelle mit Suche, Haken „archivierte zeigen“, Formular Anlegen/Bearbeiten (Toleranz leer bis zur Eingabe, Nummernvorschlag, Hinweis auf ähnliche Namen), Tasten Archivieren/Wiederherstellen/Löschen, CSV-Export, Abmelden. Bei abgelaufener Sitzung (401) springt die Seite zurück zur PIN-Eingabe.

Alle Daten werden nur als Text eingefügt (kein `innerHTML` mit Daten). Gestaltung in Modul 10.

## 8. Verzeichnisstruktur (neu in 0.3.0)

```
rezeptbuch/app/
├── main.py        angepasst: Router, Fehlerbehandlung, Sitzungen, Probebetrieb-PIN
├── errors.py      Fehlerklassen mit HTTP-Status und deutscher Meldung
├── settings.py    Add-on-Optionen (admin_timeout_minutes)
├── deps.py        get_db: eine Verbindung je Anfrage (B6)
├── auth/          pin.py, sessions.py, dependencies.py (require_admin), router.py
├── raw_materials/ models.py (Eingabeprüfung), service.py (Regeln), export.py (CSV), router.py
├── web/           router.py, static/admin.html
└── db/migrations/0002_raw_material.sql
rezeptbuch/tests/  test_auth.py, test_raw_material_service.py, test_raw_material_api.py, test_migration_0002.py (test_db_migrate.py angepasst)
```

## 9. Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| Eingabe ungültig | 400, Feld und Grund werden genannt |
| Zwei Geräte speichern gleichzeitig | eigene Verbindung je Anfrage, Schreibtransaktion `BEGIN IMMEDIATE`; die zweite wartet bis 5 s (Modul 02), danach 503 |
| Datenbank nicht bereit | alle Rohstoff-Aufrufe 503 |
| Migration 0002 scheitert | Rückrollen, Sicherung bleibt, Add-on startet im Fehlermodus (Health 503) |
| Sitzung abgelaufen | 401, Seite springt zur PIN-Eingabe |

## 10. Tests

- Migration 0002 auf leerer und auf befüllter Datenbank.
- Jede Regel R03-1 bis R03-12 mit Gut- und Schlechtfall (u. a. Groß-/Kleinschreibung, Umlaute, Nummer nach Verwendung, Löschen verwendet, Wiederherstellen bei Namensgleichheit, Typwechsel mit und ohne Bestätigung, Anlegen ohne Toleranz abgelehnt).
- PIN: richtige/falsche PIN, Sperre nach 5 Fehlversuchen, Ablauf der Sitzung, Probebetrieb-Kennzeichen, kein Klartext in der Datenbank.
- API: alle Endpunkte mit und ohne Sitzung, CSV-Inhalt, Seite, 503 ohne Datenbank (laufen nur im GitHub-Testlauf, da FastAPI lokal nicht installierbar war).
- Verbindung je Anfrage (B6): gleichzeitige Schreibzugriffe aus 6 Threads ohne Fehler (30 eindeutige Nummern, von 5 gleichnamigen Anlagen gelingt genau eine).
- Bestehende Tests laufen weiter. Lokal: 173 bestanden, 2 übersprungen.

## 11. Auswirkungen auf andere Module

| Modul | Auswirkung |
|---|---|
| 05 | nutzt `raw_materials.service` für die Zutatenauswahl und den späteren Import; CSV-Format liegt fest; **B6 entfällt dort** (in Modul 03 erledigt) |
| 06/09 | Mindesttoleranz 1 g umsetzen; Kurzname (`station_name`) überall an der Station anzeigen |
| 10 | gestaltet die Seite aus Abschnitt 7 neu, Schnittstellen bleiben |
| 12 | baut auf `auth` auf: PIN ändern, Probebetrieb beenden, weitere Admin-Bereiche schützen |
| 04 | ergänzt später BÄKO-Felder per weiterer Migration und setzt Herkunft „BÄKO“ |

## 12. Konzeptfragen – entschieden am 14.11.2026

| Nr. | Entscheidung |
|---|---|
| K03-1 | **Befund B6 wird jetzt in Modul 03 erledigt:** eigene Datenbankverbindung je Anfrage. Entfällt in Modul 05. |
| K03-2 | **Sitzungsdauer über die vorhandene Add-on-Option `admin_timeout_minutes`** (Standard 5 min). |
| K03-3 | **Toleranzfeld ist beim Anlegen leer** und muss ausgefüllt werden (Pflichtfeld, keine Vorbelegung des Werts). |
| K03-4 | **Kurzname überall an der Station** (Vorwahl, Rezeptübersicht, Wiegeansicht); voller Name im Admin-Bereich, Export und Chargenprotokoll. |

## 13. Änderungen

| Datum | Änderung |
|---|---|
| 14.11.2026 | Konzept erstellt (Schritt B). |
| 14.11.2026 | K03-1 bis K03-4 entschieden und eingearbeitet. |
| 14.11.2026 | Konzept von Michael freigegeben; Schritt C umgesetzt, Abschnitte 5 bis 10 an den Code angepasst (siehe Abschnitt 14). |
| 15.11.2026 | Praxisprüfung in Home Assistant (iPhone), Korrekturen 0.3.1 bis 0.3.4, Abschnitt 14 ergänzt. |

## 14. Abweichungen der Umsetzung vom freigegebenen Konzept

- **Eine Seite statt zwei:** `admin.html` enthält PIN-Ansicht und Rohstoffliste; keine getrennten Dateien `login.html`, `rohstoffe.html`, `app.js`, `app.css`. Grund: keine weiteren Adressen, die hinter HA-Ingress wechseln könnten. Die Adressen `/admin/login` und `/admin/rohstoffe` liefern dieselbe Seite.
- **Zusätzliche Module** `errors.py`, `settings.py`, `deps.py`.
- **Antwort der Liste** ist ein einfaches Array; Prozent-Toleranz wird als Dezimalzahl (z. B. 2,5) angezeigt.
- **Testdatei `test_db_per_request.py`** entfällt; der Nachweis zur Verbindung je Anfrage steht in `test_raw_material_service.py` (parallele Threads) und im API-Test „503 ohne Datenbank“.
- **Tests mit FastAPI/httpx** (`test_raw_material_api.py`, `test_main.py`) laufen nur im GitHub-Testlauf (lokal ohne Netzwerk nicht installierbar). Stand 0.3.3: 209 Tests bestanden. Die Seite wurde am 15.11.2026 auf dem iPhone in der Companion-App geprüft.

### Korrekturen nach der Praxisprüfung (15.11.2026)

| Version | Korrektur |
|---|---|
| 0.3.1 | Startseite und Admin-Seite im dunklen HA-Design lesbar (fester heller Hintergrund). |
| 0.3.2 | Start- und Admin-Seite blieben beim ersten Aufruf in der iOS-Companion-App leer; erstes Zeichnen wird erzwungen. |
| 0.3.3 | Rückfragen („endgültig löschen?“, Typwechsel) mit eigener Abfrage inkl. „Abbrechen“ statt `confirm()` (zeigte in der iOS-App nur „OK“). |
| 0.3.4 | Ziffern-Sonderzeichen (z. B. „²“) in Nummer/Gebindegröße ergaben HTTP 500; jetzt Fehler 400 mit deutscher Meldung (nur ASCII-Ziffern 0–9 gelten als Zahl). |

### Bewusste Entscheidungen aus dem Freigabebericht

- **B2 (CSV-Formeln):** Namen, die mit `=`, `+`, `-` oder `@` beginnen, werden in Modul 05 (Rezeptverwaltung) gesperrt. Für Rohstoffe wird dies dort mit entschieden.
- **B3 (sehr große Toleranz):** keine zusätzliche Warnung (Entscheidung Michael, 15.11.2026).
