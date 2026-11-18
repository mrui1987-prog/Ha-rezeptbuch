# Modul 03 – Rohstoff- & Zutatenverwaltung (Schritt B: Konzept)

Status: **Modul 03 am 15.11.2026 von Michael freigegeben (Add-on 0.3.4); Konzept am 14.11.2026 freigegeben, Praxisprüfung in Home Assistant am 15.11.2026 bestanden; Abweichungen und Korrekturen siehe Abschnitt 14.** **Ergänzung VC03-a „Preis je kg“ (Abschnitt 15) am 18.11.2026 geschrieben; K03-5 bis K03-8 am 18.11.2026, 13:13 entschieden; Ergänzung am 18.11.2026, 14:44 von Michael freigegeben; umgesetzt mit Modul 06 Teil C3 (0.6.2) am 18.11.2026 (Präzisierungen in 15.12), Praxisprüfung zusammen mit C3 offen.**
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
- **Ergänzung (VC03-a, 18.11.2026):** Preis je kg am Rohstoff, siehe Abschnitt 15.

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

Regeln zum Preis je kg (R03-13 bis R03-17): Abschnitt 15.3.

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

**CSV-Export:** Semikolon als Trenner, UTF-8 mit BOM (öffnet direkt richtig in Excel), Prozent mit Komma (2,5). Spalten: Nummer; Name; Kurzname; Typ; Toleranz; Toleranzeinheit; Gebindegröße g; Gebindebezeichnung; Herkunft; archiviert; geändert am. Dasselbe Format dient später für den Import (Modul 05). **Ab 0.6.2 zwei weitere Spalten am Ende** (Abschnitt 15.5).

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

Auswirkungen der Ergänzung VC03-a: Abschnitt 15.10.

## 12. Konzeptfragen – entschieden am 14.11.2026

| Nr. | Entscheidung |
|---|---|
| K03-1 | **Befund B6 wird jetzt in Modul 03 erledigt:** eigene Datenbankverbindung je Anfrage. Entfällt in Modul 05. |
| K03-2 | **Sitzungsdauer über die vorhandene Add-on-Option `admin_timeout_minutes`** (Standard 5 min). |
| K03-3 | **Toleranzfeld ist beim Anlegen leer** und muss ausgefüllt werden (Pflichtfeld, keine Vorbelegung des Werts). |
| K03-4 | **Kurzname überall an der Station** (Vorwahl, Rezeptübersicht, Wiegeansicht); voller Name im Admin-Bereich, Export und Chargenprotokoll. |

Konzeptfragen zur Ergänzung VC03-a (K03-5 bis K03-8, entschieden 18.11.2026): Abschnitt 15.11.

## 13. Änderungen

| Datum | Änderung |
|---|---|
| 14.11.2026 | Konzept erstellt (Schritt B). |
| 14.11.2026 | K03-1 bis K03-4 entschieden und eingearbeitet. |
| 14.11.2026 | Konzept von Michael freigegeben; Schritt C umgesetzt, Abschnitte 5 bis 10 an den Code angepasst (siehe Abschnitt 14). |
| 15.11.2026 | Praxisprüfung in Home Assistant (iPhone), Korrekturen 0.3.1 bis 0.3.4, Abschnitt 14 ergänzt. |
| 18.11.2026, 12:44 | **Abschnitt 15 „Ergänzung VC03-a – Preis je kg“ geschrieben** (Auftrag Michael „ergänze Konzept Rohstoffe“); Hinweise in Abschnitt 1, 4, 6, 11, 12. Keine bestehende Regel geändert. |
| 18.11.2026, 13:13 | **K03-5 bis K03-8 entschieden** und eingearbeitet (R03-13, 15.4, 15.6, 15.7, 15.9, 15.11); **K03-8 abweichend vom Vorschlag: runden statt Fehler.** Freigabe der Ergänzung offen. |
| 18.11.2026, 14:44 | **Ergänzung VC03-a (Abschnitt 15) von Michael freigegeben** (Freigabe zum Programmieren); Umsetzung mit Modul 06 Teil C3 (0.6.2). Inhalt unverändert. |
| 18.11.2026 | **VC03-a umgesetzt mit Modul 06 Teil C3 (0.6.2)**, Präzisierungen in 15.12. Keine Regel geändert. |

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

## 15. Ergänzung VC03-a – Preis je kg (18.11.2026, freigegeben 14:44)

Grundlage: Entscheidung VC03-a vom 18.11.2026, 10:51 (docs/modulstatus-03.md): **nur das Preisfeld**, **Euro netto je kg, 2 Nachkommastellen, leer erlaubt**, **„Preis geändert am“ automatisch**, **kein Preisverlauf**, **überall sichtbar (auch ohne PIN)**, **Rohstoffseite, CSV-Export und CSV-Import**, **Umsetzung mit Modul 06 Teil C3 (0.6.2) in Migration 0006** (docs/berechnung.md 17.9). Konzeptfragen K03-5 bis K03-8 am 18.11.2026, 13:13 entschieden (15.11). Änderung am freigegebenen Modul 03 wie M05-14. Vorbild: Optidos „Kosten / kg“.

### 15.1 Umfang

**Enthalten:** Feld „Preis je kg“ und „Preis geändert am“ am Rohstoff; Eingabe und Anzeige auf der Rohstoffseite; Lese- und Admin-Schnittstelle; CSV-Export und CSV-Import (docs/rezepte.md 6.1); Protokoll in `change_log`; Tests.

**Nicht enthalten:** Kosten je Rezept, je Teig oder je Stück (Rezeptkalkulation, später in Modul 06, eigener Vorschlag); Preisverlauf; Preis je Gebinde oder je Stück; Mehrwertsteuer; Anzeige an der Station (Modul 09/10 zeigen den Preis nicht an); Preise aus dem BÄKO-Datenlink (Modul 04); Importvorlage `.xlsx` und Rezept-Export `.xlsx` (K03-7).

### 15.2 Datenbank (Teil von Migration `0006`)

| Änderung | Inhalt | Grund |
|---|---|---|
| Spalte `raw_material.price_cents_per_kg` | INTEGER, leer erlaubt; CHECK `NULL` oder `0 ≤ Wert ≤ 999 999` (= 9 999,99 €) | Preis in **Cent je kg als ganze Zahl**: exakt, keine Rundungsfehler bei 2 Nachkommastellen (wie die exakte Rechnung in Modul 06) |
| Spalte `raw_material.price_changed_at` | TEXT (Zeitstempel im selben Format wie `updated_at`), leer erlaubt | „Preis geändert am“ (VC03-a (3)) |

Vorhandene Rohstoffe: beide Felder leer. Kein Trigger; die Regeln R03-14 setzt der service (alle Schreibwege – Seite, CSV-Import, später BÄKO-Import – laufen über `raw_materials.service`, Abschnitt 2). Sicherungskopie und Rückrollen wie bei jeder Migration.

### 15.3 Fachregeln

| Nr. | Regel |
|---|---|
| R03-13 | **Preis je kg:** optional, Euro **netto** je kg. Leer = kein Preis hinterlegt. **0,00 € ist erlaubt** und etwas anderes als leer (z. B. Wasser; K03-6). Keine negativen Werte. Obergrenze **9 999,99 €/kg** (Tippfehlerschutz, K03-6); darüber Fehler 400. **Mehr als 2 Nachkommastellen werden kaufmännisch auf 2 Stellen gerundet** (2,355 → 2,36; 2,354 → 2,35) **mit Hinweis** (K03-8); geprüft wird die Obergrenze nach dem Runden. Eingabe mit Komma oder Punkt („2,35“, „2.35“); Tausenderpunkt mit Komma („1.234,50“) wird verstanden; ein angehängtes „€“ und Leerzeichen werden ignoriert. |
| R03-14 | **Preis geändert am:** wird beim Speichern **automatisch** auf den aktuellen Zeitpunkt gesetzt, **wenn sich der gespeicherte Preis ändert** – auch beim Eintragen des ersten Preises und beim Leeren. Bleibt der Preis (nach dem Runden) gleich, z. B. Formular speichern ohne Preisänderung oder unveränderter CSV-Re-Import, bleibt auch das Datum. Von Hand nicht änderbar. |
| R03-15 | **Kein Preisverlauf:** Es gilt immer nur der aktuelle Preis. Alte Preise stehen nur im Änderungsprotokoll (R03-12). Rezeptversionen und Chargen speichern keinen Preis. |
| R03-16 | **Sichtbarkeit:** Preis und Datum stehen in der Lese-Schnittstelle **ohne PIN** und im Admin-Bereich (Entscheidung VC03-a (2)). Ändern nur mit PIN-Sitzung. |
| R03-17 | **Archiv, Typ, Gebinde unberührt:** Archivieren und Wiederherstellen behalten den Preis; Typwechsel und Gebinde haben keinen Einfluss. Der Preis bezieht sich **immer auf 1 kg**, auch bei Gebinde-Rohstoffen (z. B. Eier: Preis je Stück ÷ Stückgewicht × 1 000; Hinweis unter dem Feld). |

### 15.4 Schnittstellen

- **Lesen (ohne PIN):** `GET /raw-materials` und `GET /raw-materials/{id}` liefern zusätzlich `price_cents_per_kg` (ganze Zahl oder `null`) und `price_changed_at` (Zeitstempel oder `null`). Die Seite formatiert als „2,35 €“.
- **Ändern (PIN):** `POST /admin/raw-materials` und `PATCH /admin/raw-materials/{id}` nehmen `price_per_kg` als **Text** in Euro an („2,35“, „2.35“, „1.234,50 €“; R03-13). Bei `PATCH`: Feld fehlt = unverändert, `null` oder leerer Text = Preis löschen. `price_changed_at` wird nicht angenommen (R03-14).
- **Gerundet (K03-8):** Die Antwort enthält dann zusätzlich `warnings: [{field: "price_per_kg", code: "price_rounded", detail: "Preis auf 2 Nachkommastellen gerundet: 2,355 → 2,36 €"}]`; gespeichert wird der gerundete Wert.
- Fehler wie bisher mit `field = price_per_kg` und Code `invalid_price` (kein Zahlwert, negativ, über 9 999,99 €).

### 15.5 CSV-Export

Zwei neue Spalten **am Ende** (die bisherigen Spalten behalten ihre Lage): **„Preis je kg €“** (Komma, genau 2 Nachkommastellen, ohne Tausenderpunkt und ohne €-Zeichen, z. B. „2,35“; leer ohne Preis) und **„Preis geändert am“** (Format wie „geändert am“; leer ohne Datum).

### 15.6 CSV-Import (docs/rezepte.md 6.1, Code in `app/imports/`)

- Spalte **„Preis je kg €“** optional; als Kopfzeile werden auch „Preis je kg“, „Preis €/kg“ und „Preis/kg“ erkannt (ohne Groß-/Kleinschreibung).
- **Spalte fehlt ganz:** Preis bei vorhandenen Rohstoffen unverändert (wie die übrigen Spalten, docs/rezepte.md 16, C1); ältere CSV-Dateien ohne Preisspalte lassen sich weiter importieren.
- **Leere Zelle:** Preis wird **gelöscht** (wie Kurzname und Gebinde; K03-5). So ergibt Export → Re-Import „unverändert“.
- Wert nach R03-13 (Excel-Schreibweisen „2,35“, „2.35“, „1.234,50“, „2,35 €“). **Mehr als 2 Nachkommastellen → gerundet, mit Hinweis im Bericht** (Zeile, „2,355 → 2,36“; Import möglich, K03-8). Kein Zahlwert, negativ oder über 9 999,99 € → Fehler mit Zeile und Spalte, Import nicht möglich.
- Änderungen erscheinen im Bericht als „alt → neu“ und zählen als Überschreiben (Bestätigung `confirm_overwrite` wie bisher). „Preis geändert am“ setzt der Import nach R03-14; die Spalte „Preis geändert am“ wird **nicht ausgewertet** (wie „geändert am“).
- Neue Rohstoffe übernehmen den Preis aus der Datei.

### 15.7 Seite (`admin.html`, schlicht)

- **Liste:** neue Spalte **„€/kg“** (leer, wenn kein Preis).
- **Formular:** Feld **„Preis je kg (€ netto)“**, beim Anlegen leer; darunter „geändert am …“ (nur Anzeige) und der Hinweis „bei Gebinde/Stück auf 1 kg umrechnen“.
- **Nach dem Speichern mit gerundetem Preis** zeigt die Seite den Hinweis aus der Antwort („Preis auf 2 Nachkommastellen gerundet: 2,355 → 2,36 €“) und den gespeicherten Wert (K03-8).
- Rückfragen weiter mit eigenem Fenster (keine Browser-Dialoge, 0.3.3). Gestaltung in Modul 10.

### 15.8 Dateien (voraussichtlich, Teil C3)

`app/db/migrations/0006_….sql` (gemeinsam mit Modul 06), `app/raw_materials/models.py` (Preis lesen, prüfen und runden), `service.py` (R03-14), `export.py`, `router.py`, `app/imports/raw_materials_csv.py`, `app/web/static/admin.html`; Doku `DOCS.md`, `CHANGELOG.md`, docs/rezepte.md 6.1 (Hinweis auf Preisspalte).

### 15.9 Tests

- Migration 0006: vorhandene Rohstoffe mit leerem Preis; CHECK lehnt negative Werte und Werte über 999 999 ab.
- R03-13: gültige Eingaben (2,35 · 2.35 · 1.234,50 · „2,35 €“ · 0 · 0,00 · 9 999,99) und ungültige (−1 · 10 000 · Text · „²“).
- K03-8 Runden: 2,355 → 2,36 und 2,354 → 2,35 mit Hinweis; 9 999,994 → 9 999,99 erlaubt; 9 999,995 → 10 000,00 → Fehler (Obergrenze nach dem Runden); Hinweis auch im Import-Bericht.
- R03-14: Datum beim ersten Preis, bei Änderung, beim Leeren gesetzt; bei unverändertem Preis (auch 2,349 → 2,35 bei gespeicherten 2,35), bei Änderung anderer Felder unverändert.
- R03-17: Archivieren/Wiederherstellen behält den Preis.
- API: Lesen ohne PIN liefert Preis und Datum; `PATCH` ohne Feld, mit `null`, mit Text, mit Rundung (`warnings`); Ändern ohne Sitzung 401.
- CSV-Export: Spalten am Ende, Format „2,35“, leer ohne Preis.
- CSV-Import: alte Datei ohne Preisspalte (Preis bleibt), leere Zelle löscht, Kopfzeilen-Varianten, Rundung mit Hinweis, Fehler mit Zeile/Spalte, Bericht „alt → neu“, Export → Re-Import „unverändert“ (Datum bleibt).
- `change_log` enthält alten und neuen Preis. Bestehende Tests laufen weiter.

### 15.10 Auswirkungen auf andere Module

| Modul | Auswirkung |
|---|---|
| 02 | zwei Spalten in Migration 0006 (docs/berechnung.md 17.9) |
| 05 | Rohstoff-CSV-Import (`app/imports/`) liest die Preisspalte (vom freigegebenen Modul 05, abgedeckt durch VC03-a „CSV-Import“); Importvorlage und Rezept-Export unverändert (K03-7) |
| 06 | keine Rechnung mit dem Preis in Teil C3; Rezeptkalkulation (Kosten je Rezept/Stück) später als eigener Vorschlag |
| 04 | BÄKO-Preise ins selbe Feld, sofern der Datenlink sie liefert; Vorrang Handpreis/BÄKO-Preis dort klären; Rundung nach R03-13 |
| 09/10 | keine Anzeige des Preises an der Station; Gestaltung der Seite in Modul 10 |
| 12 | zur Kenntnis: Preise ohne PIN lesbar (R03-16) |
| 13 | Preise sind Teil der Datenbanksicherung und des CSV-Exports |

### 15.11 Konzeptfragen – entschieden am 18.11.2026, 13:13 (Michael)

| Nr. | Frage | Entscheidung |
|---|---|---|
| K03-5 | Leere Preiszelle im CSV-Import | **Preis löschen** (wie Kurzname/Gebinde; Export → Re-Import bleibt „unverändert“; jede Löschung steht im Bericht „alt → neu“). Fehlt die Spalte ganz, bleibt der Preis. Wie vorgeschlagen. |
| K03-6 | Obergrenze und 0 € | **0 bis 9 999,99 €/kg; 0,00 € erlaubt** (verschieden von leer). Wie vorgeschlagen. |
| K03-7 | Preis auch in Importvorlage `.xlsx` und Rezept-Export `.xlsx` | **Nein, nur CSV** (wie VC03-a); bei Bedarf später als eigene Ergänzung. Wie vorgeschlagen. |
| K03-8 | Mehr als 2 Nachkommastellen | **Auf 2 Stellen runden (kaufmännisch), mit Hinweis** an der Seite und im Import-Bericht. **Abweichend vom Vorschlag** („Fehler“). |

**Ergänzung am 18.11.2026, 14:44 von Michael freigegeben.** Umgesetzt mit Modul 06 Teil C3 (0.6.2); Praxisprüfung der Preisfunktion zusammen mit C3.

### 15.12 Präzisierungen der Umsetzung (0.6.2)

Keine Abweichung von einer Entscheidung.

1. **Tausenderpunkt nur zusammen mit Komma:** „1.234,50“ = 1 234,50 €. Ein Punkt ohne Komma ist der Dezimalpunkt: „1.234“ = 1,234 € → gerundet 1,23 € mit Hinweis (R03-13 „2.35“ = 2,35 €). „1,234.50“ ist ungültig.
2. **Schnittstelle:** `price_per_kg` nimmt neben Text auch Zahlen an. Das Formular der Rohstoffseite schickt den Preis bei jedem Speichern mit; unverändert bleibt das Datum (R03-14).
3. **Kopfzeilen nur im CSV:** Die Preisspalten kennt nur der CSV-Import (`CSV_HEADERS`); die Importvorlage `.xlsx` nutzt die bisherige Kopfzeilen-Tabelle und meldet eine Preisspalte als „wird nicht ausgewertet“ (K03-7). Im Bericht heißt das Feld „Preis je kg“ („2,35 €“, „(leer)“), Fehler nennen die Spalte „Preis je kg €“.
4. **Seite:** Hinweis zum gerundeten Preis erscheint nach dem Speichern über der Liste, mit dem Rohstoffnamen; „Preis geändert am“ in Ortszeit („18.11.2026 14:55“).
5. **Tests:** `test_raw_material_price.py` (62), `test_migration_0006.py` (Preisspalten), API-Tests in `test_raw_material_api.py` (nur GitHub), Kopfzeile in `test_raw_material_service.py` angepasst.
