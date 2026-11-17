# Modul 05 – Rezeptverwaltung (Schritt B: Konzept)

Status: **Konzept am 15.11.2026 von Michael freigegeben** (Konzeptfragen K05-1 bis K05-7, Abschnitt 13). **Teil C1 (0.5.0) am 15.11.2026 umgesetzt, Praxisprüfung am 16.11.2026 bestanden**, Ergänzungen C1-E1 bis C1-E3 am 17.11.2026 von Michael bestätigt. **Teil C2 (0.5.1) am 15.11.2026 auf dem Zweig `modul05-c2` umgesetzt** (vorgezogen vor der Praxisprüfung C1, Entscheidung Michael), am 17.11.2026 in `main` zusammengeführt, Praxisprüfung C2 am 17.11.2026 bestanden (Verbesserungen KC2-1 bis KC2-6). **Teil C3 (0.5.2) am 17.11.2026 umgesetzt** mit den Korrekturen KC2-1 bis KC2-6 und Migration `0004_recipe_note.sql` (interne Notiz); **Ergänzung C3-E1 Sammelaktionen (0.5.3)** am 17.11.2026; Praxisprüfung C3 läuft (Import der echten Vorlage ohne Fehler). Umsetzungshinweise und Abweichungen in Abschnitt 16.
Grundlage: Code-Stand `main` 807a198 (Add-on `rezeptbuch` 0.3.4), docs/datenmodell.md, docs/rohstoffe.md, docs/bedienkonzept.md, docs/importvorlage-rezepte.md, Entscheidungen M05-1 bis M05-15 und M05-13b vom 15.11.2026 (PROJEKTSTATUS Abschnitt 3).
Zielversion: Add-on `rezeptbuch` **0.5.x** (Umsetzung in drei Teilen, Abschnitt 12).

## 1. Umfang

**Enthalten**
- Rezepte anlegen, bearbeiten, kopieren, sperren/freischalten, archivieren, wiederherstellen, löschen (nur nie verwendete).
- Rezeptkopf: Nummer, Name, Gruppe, Knetzeit langsam/schnell, Hinweistext mit Anzeige „zu Beginn“/„am Ende“.
- Rezeptschritte und Rezeptzeilen (Rohstoff oder Unterrezept, Menge in ganzen Gramm, 0 g = Handzugabe nach Bedarf, Toleranz je Zeile überschreibbar, Prüfmarkierung „*“).
- Stückgewichte und Chargengrößen je Rezept.
- Versionen nach K4, Anzeige alter Versionen „old (n)“ (nur ansehen, M05-8).
- Rezeptgruppen (M05-9).
- Summen in der Übersicht: Gesamtgewicht und Summe Mehl (M05-10).
- Lese-Schnittstelle für die Stationen (Vorwahl in Modul 09/10).
- **Rohstoff-CSV-Import** (Erstbefüllung, aus Modul 03 aufgeschoben, M03-1/M03-8) mit **Überschreiben vorhandener Rohstoffe nach Warnhinweis** (K05-2). Bearbeiten vieler Rohstoffe: CSV-Export (Modul 03) → Excel → Re-Import.
- **Rezeptimport aus der Importvorlage** (.xlsx, M05-11, M05-12).
- **Export der Rezepte** als .xlsx im Format der Importvorlage (M05-15, K05-1). Kein Druck.
- **Änderungen am freigegebenen Modul 03** (M05-13b, M05-14): Sperre B2 für Namen und Kurznamen, Bedeutung „0 g / 0 %“, Filter „Toleranz 0 %“.

**Nicht enthalten**
- Skalierung, Rundung, Anteil am Gesamtgewicht, Bäckerprozent, „Mehl gesamt“ für die Vorwahl (Modul 06).
- Vorwahl, Rezeptübersicht und Wiegeansicht an der Station (Modul 09/10).
- Produktionsliste und Aufträge (Modul 09).
- Gestaltung der Seiten (Modul 10).
- Druck (M05-15).
- Zurückholen alter Versionen (M05-8).

## 2. Architektur

Gleiche Schichten wie in Modul 03 (docs/rohstoffe.md Abschnitt 2):

```
Browser (Seiten /admin/…)  ──fetch──►  router (FastAPI, nur HTTP)
                                          │
                               auth.require_admin (PIN-Sitzung, Modul 03)
                                          │
                          service (Regeln, Transaktion, change_log)
                                          │
                          db (sqlite3, eine Verbindung je Anfrage)
```

- Fachregeln liegen nur im **service**. Der Import (`imports/`) ruft dieselben Service-Funktionen auf wie die Seite; es gibt keine zweite Regelprüfung.
- Der Rohstoff-Import nutzt die Regeln aus `raw_materials.service` mit Quelle `import` (umgesetzt über die Funktionen `create_in_tx` usw., Abschnitt 16).
- Alle Schreibvorgänge laufen in einer Transaktion mit `BEGIN IMMEDIATE` (wie Modul 03).
- **Import „alles oder nichts“:** Der ganze Import läuft in **einer** Transaktion. Der Probelauf führt exakt dieselben Schritte aus und rollt am Ende zurück. Damit meldet der Probelauf genau die Fehler, die der echte Import hätte.

## 3. Datenbank – Migration `0003_recipe.sql`

`0001` und `0002` bleiben unverändert. Neu:

| Änderung | Inhalt | Grund |
|---|---|---|
| Spalte `recipe.revision` | INTEGER NOT NULL DEFAULT 0, wird bei jedem Speichern um 1 erhöht | Schutz vor gleichzeitigem Bearbeiten an zwei Geräten (R05-17) |
| Trigger `trg_recipe_number_locked` | lehnt Änderung von `recipe.number` ab, sobald das Rezept in `production_order` oder als Unterrezept in `recipe_item` vorkommt | M05-4, Schutz auch auf Datenbankebene (wie `trg_raw_material_number_locked`) |
| Index `idx_recipe_version_recipe` | auf `recipe_version (recipe_id)` | Versionsliste |

Sonst keine Schemaänderung. Insbesondere:
- Rohstoffe bekommen **keine** Prüfmarkierung; „Toleranz 0 %“ wird über den Wert selbst gefunden (M05-13b).
- `change_log.action` reicht aus: Sperren/Freischalten = `update`, Kopie = `create` (mit Angabe der Vorlage in `new_values`), Import = `create` bzw. beim Überschreiben von Rohstoffen `update`/`archive`/`restore`, jeweils mit Quelle `import`.

Ablauf wie bisher: Sicherungskopie vor der Migration, Rückrollen bei Fehler.

## 4. Fachregeln

### Rezept und Version

| Nr. | Regel |
|---|---|
| R05-1 | **Nummer** (M05-4): Vorschlag = höchste vorhandene Nummer + 1 (archivierte zählen mit). Von Hand änderbar, ganze Zahl > 0, eindeutig. Nach der ersten Verwendung (Auftrag oder als Unterrezept) gesperrt; Meldung „Rezeptnummer ist bereits verwendet und kann nicht mehr geändert werden“. |
| R05-2 | **Name** (M05-3): Pflicht, höchstens 100 Zeichen, Leerzeichen am Rand entfernt, doppelte zusammengezogen. Eindeutig unter den nicht archivierten Rezepten ohne Rücksicht auf Groß-/Kleinschreibung (Python `casefold()`, wie R03-2). Verglichen wird der Name der aktuellen Version. |
| R05-3 | **Sperre B2** (M05-14): Rezeptname, Gruppenname, Schrittname und die Bezeichnungen von Stückgewichten und Chargengrößen dürfen nicht mit `=`, `+`, `-` oder `@` beginnen (nach Entfernen der Leerzeichen am Rand). Meldung „Name darf nicht mit =, +, - oder @ beginnen“. Gilt beim Anlegen, Umbenennen und Import; vorhandene Namen bleiben unberührt. Der **Hinweistext** ist frei (er darf z. B. mit „- mit Mohn bestreuen“ beginnen); beim Export wird jede Textzelle ausdrücklich als Text geschrieben, nie als Formel. |
| R05-4 | **Gruppe:** optional. Archivierte Rezepte behalten ihre Gruppe. |
| R05-5 | **Knetzeit:** zwei ganze Zahlen ≥ 0 in Minuten, je einzeln leer erlaubt. |
| R05-6 | **Hinweistext:** optional, höchstens 2 000 Zeichen; Anzeige `start` oder `end`, Vorgabe `end` (K3). |
| R05-7 | **Status bei Neuanlage:** ein neues Rezept startet **gesperrt** (K05-4), ebenso Kopien (M05-7) und importierte Rezepte (M05-12). |

### Zeilen und Schritte

| Nr. | Regel |
|---|---|
| R05-8 | **Rohstoffzeile:** Rohstoff aus dem Stamm. **Archivierte Rohstoffe sind für neue Zeilen nicht wählbar** (R03-9); eine bestehende Zeile mit inzwischen archiviertem Rohstoff bleibt erhalten und wird mit dem Hinweis „Rohstoff archiviert“ angezeigt. Menge ganze Gramm ≥ 0; **0 g = Handzugabe nach Bedarf** (M02-15). |
| R05-9 | **Unterrezeptzeile:** Rezept aus dem Bestand, nicht archiviert; gesperrte Rezepte sind erlaubt (M05-5). Menge ganze Gramm > 0. In der Liste farblich abgesetzt (Bedienkonzept). |
| R05-10 | **Keine Kreise:** Ein Rezept darf sich weder direkt noch über Umwege als Unterrezept enthalten. Geprüft wird beim Speichern über die aktuellen Versionen aller Rezepte; Meldung mit dem Weg, z. B. „Kreis: Hauptteig → Vorteig → Hauptteig“. Die Datenbank prüft zusätzlich den direkten Fall. |
| R05-11 | **Toleranz je Zeile:** leer = Toleranz des Rohstoffs. Sonst Einheit g oder % und Wert, Prüfung wie R03-5 (g ganze Zahl ≥ 0, % auf Zehntel, höchstens 100,0 %). **Nur 0 g ist Sollhandzugabe; 0 % wird gewogen** (bei der Verwiegung mindestens ±1 g, M03-4, M05-13b). Bei Unterrezeptzeilen gibt es keine Toleranz (das Unterrezept ist ein eigener Auftrag, R3). |
| R05-12 | **Reihenfolge:** Positionen werden beim Speichern lückenlos 1, 2, 3 … neu vergeben, in der Reihenfolge der Liste (Zeilen einfügen, verschieben, löschen). |
| R05-13 | **Schritte:** Nummer 1, 2, 3 … in Listenreihenfolge, Name Pflicht (höchstens 60 Zeichen, B2). Eine Zeile gehört zu keinem oder genau einem Schritt. Ein Schritt, dem noch Zeilen zugeordnet sind, kann nicht gelöscht werden (Meldung). |
| R05-14 | **Prüfmarkierung „*“** (M02-16, M05-12): wird angezeigt (Zeile und Rezeptliste mit Anzahl). Sie verschwindet, wenn Menge oder Rohstoff/Unterrezept der Zeile geändert werden oder die Zeile mit der Taste „geprüft“ bestätigt wird. Siehe K05-5. |

### Speichern und Versionen (K4, M05-2)

| Nr. | Regel |
|---|---|
| R05-15 | **Ein Speichervorgang** umfasst Kopf, Schritte und Zeilen. Die Seite schickt immer das ganze Rezept. |
| R05-16 | **Versionsentscheidung:** Ändert sich am Inhalt der Version nichts (Name, Knetzeit, Hinweis, Schritte, Zeilen), wird keine Version angelegt. Ändert sich etwas und die aktuelle Version ist **schon gewogen** (`frozen_at` gesetzt), entsteht **automatisch eine neue Version** mit der Meldung „Neue Version angelegt, da bereits produziert“. Ist sie **noch nicht gewogen**, antwortet der Server mit `version_choice_required`; die Seite fragt „Neue Version / Überschreiben / Abbrechen“ und schickt die Wahl mit (`version_mode: new` oder `overwrite`). Felder des Rezepts selbst (Nummer, Gruppe) erzeugen nie eine Version. |
| R05-17 | **Gleichzeitiges Bearbeiten:** Die Seite schickt beim Speichern die `revision` mit, die sie geladen hat. Weicht sie ab, lehnt der Server ab: „Rezept wurde inzwischen an einem anderen Gerät geändert – bitte neu laden“. |
| R05-18 | **Alte Versionen:** Liste mit „old (n)“, Datum und Kennzeichen „produziert“; Ansicht nur lesend (M05-8). Alte Versionen erscheinen nicht in der Vorwahl (M02-4b). |
| R05-19 | **Leeres Rezept:** Speichern ohne Zeilen ist erlaubt (Entwurf), Freischalten nicht (R05-21). |

### Stückgewichte und Chargengrößen (M02-12, M02-1c, M05-2)

| Nr. | Regel |
|---|---|
| R05-20 | Gehören zum Rezept, nicht zur Version, und werden **ohne Versionsfrage** gespeichert (eigene Taste). Bezeichnung Pflicht, höchstens 30 Zeichen, eindeutig je Rezept (Stückgewichte), B2. Gewicht bzw. Wert ganze Zahl > 0. Chargengröße „Stückzahl“ verweist auf ein Stückgewicht desselben Rezepts. **Löschen eines Stückgewichts, auf das eine Chargengröße verweist,** löscht diese Chargengröße mit (Datenbank `CASCADE`); deshalb vorher Rückfrage mit den betroffenen Chargengrößen. Bestehende Aufträge behalten ihre Kopie der Stückgewichte (`order_piece`). |

### Status, Archiv, Kopie, Löschen

| Nr. | Regel |
|---|---|
| R05-21 | **Freischalten (öffentlich):** nur mit mindestens einer Zeile. Enthält die aktuelle Version Zeilen mit „*“ oder Rohstoffe mit Toleranz 0 %, kommt eine Warnung mit Liste und Bestätigung (K05-3). **Sperren** geht jederzeit. |
| R05-22 | **Archivieren** (M05-6): nicht möglich, solange das Rezept in der aktuellen Version eines nicht archivierten Rezepts als Unterrezept steckt; Meldung „wird in n Rezepten als Unterrezept verwendet“ mit Liste. Archivierte Rezepte erscheinen weder in der Vorwahl noch in der Auswahl für Unterrezepte. |
| R05-23 | **Wiederherstellen:** nur, wenn kein nicht archiviertes Rezept denselben Namen hat (wie R03-10). Status bleibt wie vor dem Archivieren. |
| R05-24 | **Kopieren** (M05-7): aktuelle Version mit Schritten und Zeilen (inkl. „*“), Stückgewichte und Chargengrößen; nächste freie Nummer; Name „Kopie von <Name>“ (bei Namensgleichheit „Kopie 2 von …“); gesperrt; keine Gruppe geändert. |
| R05-25 | **Löschen:** nur, wenn nie verwendet (kein Auftrag, nie als Unterrezept in irgendeiner Version). Sonst Meldung „wird verwendet – bitte archivieren“. Löscht Versionen, Schritte, Zeilen, Stückgewichte und Chargengrößen mit (Datenbank `CASCADE`). |

### Gruppen (M05-9)

| Nr. | Regel |
|---|---|
| R05-26 | Name Pflicht, höchstens 60 Zeichen, eindeutig ohne Rücksicht auf Groß-/Kleinschreibung, B2. Reihenfolge per Liste. Löschen nur, wenn kein Rezept (auch kein archiviertes) die Gruppe nutzt. |

### Summen und Protokoll

| Nr. | Regel |
|---|---|
| R05-27 | **Summen** (M05-10): Gesamtgewicht = Summe aller Zeilen der Version (Unterrezepte mit ihrer Menge). Summe Mehl = Summe der Rohstoffzeilen vom Typ Mehl **dieses** Rezepts; Mehl innerhalb von Unterrezepten (z. B. Vorteig) zählt hier nicht mit – das rechnet Modul 06 für Bäckerprozent und „Mehl gesamt“ (Hinweis an Modul 06). |
| R05-28 | **Protokoll:** jede Änderung in `change_log` (`entity = recipe` bzw. `recipe_group`; Aktionen `create`, `update`, `new_version`, `archive`, `restore`, `delete`; Quelle `admin` oder `import`; alte und neue Werte als JSON). |

## 5. Änderungen an Modul 03 (M05-13b, M05-14)

Abgestimmt mit Michael am 15.11.2026 (Master-Prompt Regel 9 und 14). Abwärtskompatibel: keine Schemaänderung, vorhandene Daten bleiben gültig. **Umgesetzt in 0.5.0.**

| Änderung | Wo |
|---|---|
| **B2:** Rohstoffname und Kurzname dürfen beim Anlegen und Umbenennen nicht mit `=`, `+`, `-` oder `@` beginnen. Unveränderte vorhandene Namen werden beim Speichern anderer Felder nicht beanstandet. | `raw_materials/models.py` |
| **0 g / 0 %:** Hinweistext unter dem Toleranzfeld: „0 g = Handzugabe (nur quittieren, nicht wiegen). 0 % wird gewogen; bei der Verwiegung nie enger als 1 g.“ Anzeige in der Liste „0 g (Handzugabe)“ bleibt, „0 %“ ohne diesen Zusatz. | `admin.html`, Kommentar in `models.py` |
| **Filter „Toleranz 0 %“** in der Rohstoffliste; API `GET /raw-materials?zero_percent=true`. | `service.py`, `router.py`, `admin.html` |
| Doku: R03-5 in docs/rohstoffe.md, Abschnitt 4.1 in docs/datenmodell.md („Toleranz 0 g bedeutet Sollhandzugabe“). | Doku |

## 6. Importe

Beide Importe: nur im Admin-Bereich (PIN), Datei wird als Rohdaten im Anfragekörper geschickt (keine zusätzliche Bibliothek für Formular-Uploads), höchstens 5 MB, höchstens 5 000 Zeilen je Blatt. Ablauf immer **Probelauf → Bericht → Import**. Beim Import schickt die Seite dieselbe Datei erneut; der Server prüft alles noch einmal. Bericht: Anzahl neu/überschrieben/unverändert, **Änderungen** an vorhandenen Rohstoffen mit „alt → neu“ je Feld (K05-2d), **Fehler** (Blatt, Zeile, Spalte, Meldung – Import nicht möglich), **Hinweise** (Import möglich): Rohstoffe mit 0 %, Zeilen mit „*“, ähnliche Rohstoffnamen (R03-3), Typwechsel Mehl ↔ Standard bei verwendeten Rohstoffen (M03-5). **Werden Rohstoffe überschrieben, startet der Import erst nach der Bestätigung „n Rohstoffe werden überschrieben“** (`confirm_overwrite: true`).

### 6.1 Rohstoff-CSV-Import (M03-8, M05-13) – umgesetzt in 0.5.0

- Format wie der Export (docs/rohstoffe.md Abschnitt 6): Semikolon, UTF-8 (mit oder ohne BOM), Kopfzeile Pflicht, Prozent mit Komma.
- Werte in beiden Schreibweisen: Typ `Standard`/`standard`, `Mehl`/`flour`; Einheit `g`, `%`/`percent`; archiviert `ja`/`nein`/`1`/`0`.
- **Zuordnung (K05-2a):** über die Nummer; Zeile ohne Nummer über den Namen (ohne Groß-/Kleinschreibung); passt keiner, wird der Rohstoff **neu angelegt** (leere Nummer → nächste freie Nummer).
- **Vorhandener Rohstoff wird überschrieben (K05-2):** Name, Kurzname, Typ, Toleranz, Toleranzeinheit, Gebindegröße und -bezeichnung aus der Datei. **Leere Toleranz bleibt unverändert** (K05-2b); leerer Kurzname bzw. leeres Gebinde werden geleert. Nummer und Herkunft ändern sich nie.
- **Spalte „archiviert“ (K05-2c):** ja → archivieren, nein → wiederherstellen (Namensprüfung R03-10). Rohstoffe, die nicht in der Datei stehen, bleiben unverändert.
- **Neuer Rohstoff:** Toleranz leer → **0 %** (M05-13), Hinweis im Bericht. Herkunft immer „eigen“ (R03-8).
- „Herkunft“ und „geändert am“ werden nicht ausgewertet.
- Alle Regeln aus Modul 03 gelten (Name eindeutig unter den aktiven Rohstoffen nach dem Import, auch innerhalb der Datei; B2; Gebinde nur mit Bezeichnung; Typwechsel M03-5 im Bericht hervorgehoben und mit der Import-Bestätigung bestätigt).
- Präzisierungen der Umsetzung siehe Abschnitt 16.

### 6.2 Rezeptimport aus der Importvorlage (M05-11, M05-12)

Gelesen werden die Blätter **Rohstoffe, Rezepte, Rezeptzeilen, Stückgewichte, Chargengrößen** (Spalten wie in docs/importvorlage-rezepte.md). Die Umrechnung steht seit 0.5.8 im Blatt Rohstoffe (Spalten „Umrechnung Einheit“, „Gramm je Einheit“, C3-E7); ein altes Blatt Umrechnung wird übergangsweise gelesen. Anleitung und Prüfliste werden nicht gelesen. Spalten „(nicht importieren)“, „Bemerkung“ und „(Formel)“ werden ignoriert.

| Schritt | Verhalten |
|---|---|
| 1 Rohstoffe | **genau wie der CSV-Import (6.1):** Zuordnung über Nummer, sonst Name; vorhandene Rohstoffe werden **überschrieben** (Warnhinweis und Bestätigung), leere Toleranz bleibt unverändert, neue Rohstoffe mit 0 % bei leerer Toleranz (K05-2, M05-13). Schreibweisen `standard`/`flour`, `own`, `0`/`1` der Vorlage werden verstanden. |
| 2 Rezepte | je Import-ID ein Rezept; **vorhandenes Rezept (Nummer, sonst Name) → neue Version nach Bestätigung** (seit 0.5.7, C3-E5; ursprünglich Fehler nach M05-11). Musterrezepte der Mustervorlage werden übersprungen (0.5.8, C3-E11). Gruppe: vorhandene wird verwendet, neue wird angelegt (M05-9). Status **gesperrt** (M05-12). Hinweis „Beginn/Ende“ → `start`/`end`. |
| 3 Rezeptzeilen | Rohstoff über „Zutat (bereinigt)“ → Rohstoff aus Schritt 1 (Name, ohne Groß-/Kleinschreibung). Unterrezept über „Unterrezept Import-ID“, nur innerhalb der Datei. **Menge g rechnet der Import selbst** aus „Menge Original“ × Faktor (g = 1, kg = 1 000, sonst Umrechnung des Rohstoffs aus dem Blatt Rohstoffe, ml ↔ l automatisch; übergangsweise altes Blatt „Umrechnung“ nach „Einheit + Zutat“), kaufmännisch auf ganze Gramm gerundet (K05-6). Leere Menge Original → 0 g Handzugabe. Fehlender Faktor (z. B. „Maß“ ohne Wert) → Fehler. „Prüfen“ = „*“ → Prüfmarkierung; **jede umgerechnete Zeile bekommt „*“** (C3-E7). Toleranz optional (g/percent). Schritte in Reihenfolge des ersten Auftretens je Rezept. Kreisprüfung (R05-10) über die ganze Datei. |
| 4 Stückgewichte | je Import-ID; Bezeichnung eindeutig je Rezept. |
| 5 Chargengrößen | Art „Gewicht“: Wert = Zahl in der Zelle, sonst Gesamtgewicht des Rezepts; Art „Stück“: Wert Pflicht, Stückgewicht über die Bezeichnung desselben Rezepts. |

Grund für K05-6: Die Formeln der Vorlage enthalten nur dann einen gespeicherten Wert, wenn die Datei zuletzt mit Excel gespeichert wurde. Rechnet der Import selbst, ist er davon unabhängig. Im Bericht steht bei Abweichung zum gespeicherten Formelwert ein Hinweis.

Hinweis zur Vorlage: Das Blatt „Anleitung“ nennt die Toleranz noch „Pflicht“. Nach M05-13 darf sie leer bleiben (→ 0 %). Die Vorlage wird angepasst, sobald Michael sie mit der geprüften Prüfliste zurückgibt.

### 6.3 Export (M05-15, K05-1)

**.xlsx-Datei** im Format der Importvorlage: Blätter Rezepte, Rezeptzeilen, Stückgewichte, Chargengrößen, Rohstoffe (nur verwendete) mit den Importspalten, Menge g als Zahl (Menge Original = Menge g, Einheit g, Faktor 1), aktuelle Versionen, auf Wunsch mit archivierten Rezepten. Import-ID = „R“ + Rezeptnummer. Die Datei kann in eine leere Datenbank wieder importiert werden. Alle Textzellen werden als Text geschrieben (keine Formeln, B2). Kein Druck.

## 7. Schnittstellen (REST `/api/v1`)

Lesen (ohne PIN, die Stationen brauchen das in Modul 09/10):

| Methode | Pfad | Inhalt |
|---|---|---|
| GET | `/recipes?search=&group_id=&include_locked=false&include_archived=false` | Liste: Nummer, Name, Gruppe, gesperrt, archiviert, Versionsnummer, Gesamtgewicht, Zeilen, Anzahl „*“. Vorgabe = was die Vorwahl zeigt (öffentlich, nicht archiviert). |
| GET | `/recipes/{id}` | (ohne interne Notiz) aktuelle Version mit Kopf, Schritten, Zeilen (je Rohstoffzeile `station_name`, Name, Nummer, Typ, wirksame Toleranz, Gebinde, archiviert; je Unterrezept Nummer, Name, gesperrt), Stückgewichte, Chargengrößen, Summen, `revision`, Versionsliste |
| GET | `/recipes/{id}/versions/{version_no}` | alte Version, nur lesen |
| GET | `/recipe-groups` | Gruppen in Reihenfolge |

Ändern (mit PIN-Sitzung, `X-Rezeptbuch-Session`):

| Methode | Pfad | Inhalt |
|---|---|---|
| GET | `/admin/recipes/next-number` | Nummernvorschlag |
| POST | `/admin/recipes` | anlegen (Kopf, Schritte, Zeilen) → Version 1, gesperrt |
| PUT | `/admin/recipes/{id}` | speichern (R05-15 bis R05-17), Felder `revision`, `version_mode` |
| PUT | `/admin/recipes/{id}/piece-weights` | ganze Liste; `confirm_delete_batch_sizes` bei R05-20 |
| PUT | `/admin/recipes/{id}/batch-sizes` | ganze Liste |
| POST | `/admin/recipes/{id}/unlock`, `/lock` | freischalten (mit `confirm` bei Warnung, R05-21), sperren |
| POST | `/admin/recipes/{id}/archive`, `/restore`, `/copy` | R05-22 bis R05-24 |
| DELETE | `/admin/recipes/{id}` | R05-25 |
| POST, PATCH, DELETE | `/admin/recipe-groups`, `/admin/recipe-groups/{id}` | Gruppen; `PUT /admin/recipe-groups/order` für die Reihenfolge |
| POST | `/admin/import/raw-materials?mode=check` bzw. `mode=run&confirm_overwrite=true` | CSV-Import (6.1) – **umgesetzt in 0.5.0** |
| GET | `/admin/recipes/{id}` | wie `/recipes/{id}`, zusätzlich `internal_note` (0.5.2, KC2-2) |
| POST | `/admin/recipes/bulk` | Sammelaktion `{action: unlock\|lock\|archive\|restore\|delete, ids, mode: check\|run, confirm}` (0.5.3, C3-E1; `restore` seit 0.5.8, C3-E8); Export der Auswahl über `export.xlsx?ids=1,2,3` |
| POST | `/admin/import/recipes?mode=check` bzw. `mode=run&confirm_overwrite=true`, optional `include_samples=true` | Vorlagen-Import (6.2) – **umgesetzt in 0.5.2**; Bericht seit 0.5.8 mit `conversions`, `nothing_to_import`, `counts.samples_*` |
| GET | `/admin/recipes/template.xlsx` | Mustervorlage (0.5.4, C3-E2) |
| GET | `/admin/recipes/export.xlsx?include_archived=false` | Export (6.3, K05-1) |

Fehlerantworten wie Modul 03 (`detail`, `field`, `code`): 400 ungültig, 401 nicht angemeldet, 404 nicht gefunden, 409 Konflikt (Name/Nummer, Kreis, Archivieren als Unterrezept, Löschen verwendet, `version_choice_required`, `changed_elsewhere`, `confirmation_required`, `overwrite_confirmation_required`), 413 Datei zu groß, 423 PIN gesperrt, 503 Datenbank nicht bereit.

## 8. Seiten (schlicht, M05-1)

- Neue in sich geschlossene Seite `app/web/static/recipes.html` unter `/admin/rezepte`; die Rohstoffseite bleibt unverändert unter `/admin/rohstoffe`. Oben eine Reiterleiste „Rohstoffe | Rezepte | Gruppen | Import/Export“. Die Sitzung wird wie bisher im `sessionStorage` gehalten, ein Wechsel der Seite verlangt keine neue PIN.
- **Rezeptliste:** Suche (Nummer/Name), Filter Gruppe, Haken „gesperrte“ und „archivierte zeigen“, Kennzeichen „*“ mit Anzahl.
- **Rezept bearbeiten:** Kopf; Schritte; Zeilentabelle mit Auswahl Rohstoff/Unterrezept (Suche nach Nummer oder Name), Menge, Toleranz, Schritt, Tasten „hoch/runter/einfügen/löschen“, „geprüft“ bei „*“; Summen; Taste „Speichern“ mit Versionsrückfrage; Bereich Stückgewichte/Chargengrößen mit eigener Taste; Versionsliste mit Ansicht.
- **Tasten:** Freischalten/Sperren, Kopieren, Archivieren/Wiederherstellen, Löschen.
- **Import/Export:** Datei wählen → Probelauf → Bericht → „Importieren“; Export-Taste.
- Ausgelegt für Tablet/PC (breite Tabelle), am iPhone bedienbar. Übernommen aus der Praxisprüfung Modul 03: eigene Rückfrage-Fenster statt `confirm()`, erstes Zeichnen erzwungen, fester heller Hintergrund, Daten nur als Text einfügen.

## 9. Verzeichnisstruktur (neu in 0.5.x)

```
rezeptbuch/
├── requirements.txt         + openpyxl (Lesen/Schreiben .xlsx)
└── app/
    ├── recipes/             models.py (Eingabeprüfung), service.py (Regeln, Versionen, Kreisprüfung),
    │                        groups.py (Gruppen), router.py
    ├── imports/             raw_materials_csv.py, recipe_template.py (Lesen der Vorlage),
    │                        report.py (Bericht), router.py
    ├── exports/             recipe_template.py (Export), router.py
    ├── text_rules.py        gemeinsame Sperre B2 (Rezepte, Gruppen, Rohstoffe)
    ├── raw_materials/       angepasst: models.py, service.py, router.py (Abschnitt 5)
    ├── web/                 router.py (+ /admin/rezepte), static/recipes.html, static/admin.html (angepasst)
    └── db/migrations/0003_recipe.sql
rezeptbuch/tests/  test_migration_0003.py, test_recipe_service.py, test_recipe_versions.py,
                   test_recipe_groups.py, test_import_raw_materials.py, test_import_recipes.py,
                   test_export_recipes.py, test_recipe_api.py, test_text_rules.py (+ Anpassung Rohstofftests)
```

`openpyxl` ist reines Python und lokal vorhanden; die Import-/Exporttests laufen daher auch lokal. Die API-Tests laufen wie bisher nur im GitHub-Testlauf (FastAPI lokal nicht installierbar).

Stand 0.5.0 (Teil C1): `text_rules.py`, `imports/` (`raw_materials_csv.py`, `report.py`, `router.py`), `0003_recipe.sql`, Anpassungen in `raw_materials/` und `admin.html`; Tests `test_migration_0003.py`, `test_text_rules.py`, `test_import_raw_materials.py`, `test_import_api.py` (API, nur GitHub-Testlauf) und Ergänzungen in `test_raw_material_service.py`. `openpyxl` kommt erst mit Teil C3 in `requirements.txt`.

## 10. Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| Eingabe ungültig | 400 mit Feld und Grund; bei Zeilen mit Positionsangabe („Zeile 7: Menge fehlt“) |
| Gewogene Version soll geändert werden | wird nie überschrieben, automatisch neue Version (R05-16); Datenbank-Trigger als zweite Sicherung |
| Zwei Geräte speichern dasselbe Rezept | `revision` weicht ab → 409 `changed_elsewhere`, nichts gespeichert |
| Kreis bei Unterrezepten | 409 mit Weg |
| Importdatei beschädigt oder kein .xlsx/.csv | 400 „Datei kann nicht gelesen werden“ |
| Importdatei zu groß | 413 |
| Fehler im Import | ganzer Import zurückgerollt, nichts gespeichert, Bericht mit allen gefundenen Fehlern |
| Datenbank nicht bereit / gesperrt | 503 (wie Modul 03) |

## 11. Tests

- Migration 0003 auf leerer und befüllter Datenbank; Nummernsperre per Trigger.
- Jede Regel R05-1 bis R05-28 mit Gut- und Schlechtfall, u. a.: Name doppelt (Umlaute, Groß-/Kleinschreibung), B2 für alle betroffenen Felder, archivierter Rohstoff in neuer Zeile, Kreis über drei Rezepte, 0 g / 0 %, Versionsentscheidung (unverändert, gewogen, nicht gewogen mit „neu“ und „überschreiben“, fehlende Wahl), `revision`-Konflikt, Löschen eines Stückgewichts mit Chargengröße, Archivieren eines verwendeten Unterrezepts, Wiederherstellen bei Namensgleichheit, Kopie mit Namenszusatz, Löschen verwendet/nie verwendet, Freischalten leer und mit Warnung.
- Modul-03-Anpassungen: B2 bei Name und Kurzname, unveränderter alter Name bleibt speicherbar, Filter 0 %.
- Rohstoff-CSV-Import: beide Schreibweisen, BOM mit/ohne; neu mit Toleranz leer → 0 %; **Überschreiben** über Nummer und über Namen, leere Toleranz bleibt, leerer Kurzname wird geleert, archiviert ja/nein, nicht enthaltene Rohstoffe unverändert, Import ohne `confirm_overwrite` abgelehnt, Bericht „alt → neu“, Typwechsel hervorgehoben; Name doppelt in der Datei; Export → Re-Import ohne Änderung meldet „unverändert“; Probelauf ändert nichts.
- Vorlagen-Import mit einer Testvorlage **ohne Betriebsdaten** (im Test erzeugt): Rohstoffe verwenden/anlegen, Faktor fehlt, „*“, Unterrezept und Kreis, Chargengröße Gewicht/Stück, alles-oder-nichts, Probelauf = Import.
- Export → Import in leere Datenbank ergibt dieselben Rezepte; Text mit `=` wird als Text geschrieben.
- API: alle Endpunkte mit und ohne Sitzung, Lese-Endpunkte ohne PIN.
- Bestehende Tests laufen weiter.

## 12. Umsetzung in drei Teilen (K05-7)

| Teil | Inhalt | Version | Praxisprüfung durch Michael | Stand |
|---|---|---|---|---|
| C1 | Anpassungen Modul 03 (Abschnitt 5), Rohstoff-CSV-Import (6.1), Migration 0003, `text_rules.py` | 0.5.0 | Rohstoffe aus dem Blatt „Rohstoffe“ der Vorlage als CSV importieren, exportieren, in Excel ändern und wieder importieren (Überschreiben mit Warnhinweis) | umgesetzt 15.11.2026, Praxisprüfung offen |
| C2 | Rezeptpflege, Gruppen, Versionen, Lese-API, Seite `/admin/rezepte` | 0.5.1 | Rezept anlegen, Versionen, Kopie, Archiv | umgesetzt 15.11.2026 auf Zweig `modul05-c2`, Praxisprüfung nach Zusammenführung |
| C3 | Vorlagen-Import (6.2), Export (6.3), Korrekturen KC2-1 bis KC2-6, Migration 0004 | 0.5.2 | Import der geprüften Vorlage, danach Prüfung „*“ und Freischalten; Export; KC2-Punkte | umgesetzt 17.11.2026, Praxisprüfung offen |

Jeder Teil mit eigenem Push und GitHub-Testlauf. Freigabe von Modul 05 nach C3 mit Freigabebericht wie bei Modul 03. C3 braucht die von Michael geprüfte Importvorlage nur für die Praxisprüfung, nicht für die Programmierung.

## 13. Konzeptfragen – entschieden am 15.11.2026

| Nr. | Entscheidung |
|---|---|
| K05-1 | **Export als .xlsx** mit denselben Blättern wie die Importvorlage, wieder importierbar (ändert M05-15 „CSV“). |
| K05-2 | **Rohstoffe werden beim Import immer überschrieben**, nach Warnhinweis und Bestätigung (Vorgabe Michael, ändert M05-11 für Rohstoffe). Bearbeiten: Export → Excel → Re-Import. Für Rezepte galt zunächst „vorhandene Nummer = Fehler“, seit 0.5.7 erzeugt der Import für vorhandene Rezepte nach Bestätigung eine neue Version (C3-E5). |
| K05-2a | Zuordnung über die Nummer, ohne Nummer über den Namen, sonst neu anlegen. |
| K05-2b | Leere Toleranz bei vorhandenem Rohstoff bleibt unverändert (0 % nur bei neuen); andere leere Felder werden geleert. |
| K05-2c | Spalte „archiviert“ wird übernommen; nicht enthaltene Rohstoffe bleiben unverändert. |
| K05-2d | Probelauf mit „alt → neu“ je Feld, Typwechsel hervorgehoben, Import erst nach Bestätigung; gilt für CSV-Import und Blatt „Rohstoffe“ der Vorlage. |
| K05-3 | **Freischalten** mit offenen „*“ oder Rohstoffen mit 0 %: Warnung mit Liste und Bestätigung, keine Sperre; ohne Zeilen kein Freischalten. |
| K05-4 | **Neu angelegte Rezepte starten gesperrt**; Freischalten über die Taste „Freischalten“ im Admin-Bereich. |
| K05-5 | **„geprüft“ bei „*“:** nur „*“ bestätigt und Version nicht gewogen → überschreiben ohne Rückfrage; sonst K4. |
| K05-6 | **Import rechnet Menge g selbst** (Menge Original × Faktor); Formelspalten werden nicht gelesen. |
| K05-7 | **Umsetzung in drei Teilen** C1 0.5.0, C2 0.5.1, C3 0.5.2 (Abschnitt 12). |

## 14. Auswirkungen auf andere Module

| Modul | Auswirkung |
|---|---|
| 03 | Änderungen aus Abschnitt 5 (abgestimmt, M05-13b, M05-14) |
| 06 | liest Rezeptversion, Zeilen, Unterrezepte, Typ Mehl; rechnet Anteil, Bäckerprozent, „Mehl gesamt“ **inklusive Mehl in Unterrezepten** (R05-27) und Mindesttoleranz 1 g; ergänzt die Prozentspalten in der Rezeptübersicht |
| 09/10 | Vorwahl über `GET /recipes` (öffentlich, nicht archiviert), `station_name` je Zeile; 0 % wird gewogen, 0 g ist Handzugabe (M05-13b) |
| 10 | gestaltet `/admin/rezepte` neu, Schnittstellen bleiben |
| 13 | `.xlsx`-Export kann als zusätzliche lesbare Sicherung der Rezepte dienen (kein Ersatz für die Datenbanksicherung) |
| 04 | unverändert; der Vorlagen-Import setzt Herkunft immer „eigen“ |

## 15. Änderungen

| Datum | Änderung |
|---|---|
| 15.11.2026 | Konzept erstellt (Schritt B). |
| 15.11.2026 | Konzeptfragen K05-1 bis K05-7 entschieden und eingearbeitet: Export als .xlsx, Rohstoffe beim Import überschreiben (K05-2 mit 2a–2d, Abschnitt 6.1/6.2, Schnittstellen, Tests), übrige wie vorgeschlagen. |
| 15.11.2026 | Konzept von Michael freigegeben. Teil C1 (0.5.0) umgesetzt; Umsetzungshinweise in Abschnitt 16. |
| 15.11.2026 | Teil C2 (0.5.1) auf Zweig `modul05-c2` umgesetzt; Umsetzungshinweise in Abschnitt 16. |
| 17.11.2026 | Ergänzung C3-E1 (0.5.3): Sammelaktionen in der Rezeptliste (Abschnitt 16). |
| 17.11.2026 | Ergänzung C3-E5 (0.5.7): Import vorhandener Rezepte (Nummer, sonst Name) erzeugt nach Bestätigung eine neue Version, die bisherige wird „old (n)“; gleicher Inhalt = unverändert; archivierte = Fehler. |
| 17.11.2026 | Ergänzung C3-E4 (0.5.6): Suche mit Operatoren `R:` (Rohstoff) und `K:` (Kurzname) in der Rezeptliste. |
| 17.11.2026 | Ergänzung C3-E3 (0.5.5): Filter „öffentliche zeigen“, „nie verwogen“, „enthält Unterrezepte“ in der Rezeptliste (`GET /recipes?include_public=&never_weighed=&has_sub_recipes=`). |
| 17.11.2026 | Ergänzung C3-E2 (0.5.4): Mustervorlage `GET /admin/recipes/template.xlsx` (Musterrezept Schwarzwälder Kirschtorte, Musterrohstoffe mit Präfix „Muster“); Hinweisfenster statt Meldung oben bei fehlendem Rohstoff. |
| 17.11.2026 | Teil C3 (0.5.2) umgesetzt: Vorlagen-Import, Export, KC2-1 bis KC2-6, interne Notiz (Migration 0004); Umsetzungshinweise in Abschnitt 16. |
| 18.11.2026 | Ergänzungen C3-E7, C3-E8, C3-E11 (0.5.8): Umrechnung im Blatt Rohstoffe mit automatischem „*“ und Übersicht vorab, Blatt Umrechnung veraltet; Sammelaktion Wiederherstellen; Musterdaten beim Import übersprungen (Abschnitt 16). |

## 16. Umsetzung und Abweichungen

### Teil C1 (0.5.0, 15.11.2026)

**Präzisierungen beim Rohstoff-CSV-Import** (im Rahmen von K05-2, keine neue Regel):
- **Fehlt eine Spalte ganz**, bleibt das Feld bei vorhandenen Rohstoffen unverändert. Pflicht ist nur die Spalte „Name“.
- **Leerer Typ, leere Toleranzeinheit, leeres „archiviert“** lassen bei vorhandenen Rohstoffen den bisherigen Wert stehen (sonst würde ein leerer Typ still zu „Standard“). Bei neuen Rohstoffen gilt Standard, g bzw. nicht archiviert. Leerer Kurzname und leeres Gebinde werden wie entschieden geleert.
- **Toleranzeinheit geändert, Toleranz leer** → Fehler „bitte auch den Toleranzwert angeben“ (wie in Modul 03).
- **Zuordnung über den Namen** findet zuerst einen aktiven Rohstoff, sonst einen eindeutigen archivierten (der dann mit „archiviert = nein“ wiederhergestellt werden kann); bei mehreren gleichnamigen archivierten Rohstoffen Fehler „bitte die Nummer angeben“.
- **Archivieren und Umbenennen in einer Zeile:** erst archivieren, dann ändern (keine Namensprüfung gegen aktive Rohstoffe). **Wiederherstellen:** erst ändern, dann wiederherstellen (Namensprüfung mit dem neuen Namen).
- **Doppelte Nummern oder Namen innerhalb der Datei** werden vorab als Fehler gemeldet (Zeile und erste Fundstelle).
- **Antworten:** Probelauf immer 200 mit Bericht. Import mit Fehlern: 400 `import_failed`; ohne Bestätigung bei Überschreiben: 409 `overwrite_confirmation_required`; beide mit dem Bericht im Feld `report`. Nur neue Rohstoffe brauchen keine Bestätigung.
- Fehler in einer Zeile verwerfen nur diese Zeile (Savepoint), damit der Bericht alle Fehler zeigt; gespeichert wird trotzdem nur ohne jeden Fehler.

**Ergänzungen C1-E1 bis C1-E3** (betreffen nur das Lesen der Datei; am 17.11.2026 von Michael bestätigt, in der Praxisprüfung C1 geprüft):
- Speichert Excel die Datei als „CSV (Trennzeichen-getrennt)“, ist sie nicht UTF-8, sondern Windows-1252. Der Import liest diese Dateien ebenfalls und zeigt einen Hinweis „bitte Umlaute prüfen“. Ohne diese Ergänzung müsste beim Speichern immer „CSV UTF-8“ gewählt werden.
- Trennzeichen wird an der Kopfzeile erkannt (Semikolon, sonst Tabulator oder Komma).
- Ganze Zahlen in Excel-Schreibweise werden verstanden: „25.000“ → 25 000, „55,0“ → 55 (Nummer, Gebindegröße).

**Technik:**
- `raw_materials/service.py` hat die Regeln jetzt in Funktionen für eine bereits offene Transaktion (`create_in_tx`, `update_in_tx`, `archive_in_tx`, `restore_in_tx`). Die bisherigen Funktionen (`create_raw_material` usw.) rufen diese auf und verhalten sich unverändert; der Import nutzt dieselben Funktionen in seiner einen Transaktion. Keine Änderung an Modul 02 (`transaction` bleibt).
- Der CSV-Import sitzt in Teil C1 auf der Rohstoffseite (Taste „CSV-Import“). Die Reiterleiste mit „Import/Export“ folgt mit der Rezeptseite in Teil C2.
- Der Index `idx_recipe_version_recipe` deckt sich teilweise mit dem vorhandenen Index aus `UNIQUE (recipe_id, version_no)`; er wurde wie im Konzept angelegt und ist unschädlich.
- `openpyxl` wird für C1 nicht gebraucht und kommt mit Teil C3 in `requirements.txt`.

**Bekannte Grenze:** Zwei aktive Rohstoffe können ihre Namen nicht in einem Import tauschen (A → B und B → A): Die zweite Zeile meldet „gibt es schon“. Abhilfe: zuerst einen Zwischennamen importieren.

### Teil C2 (0.5.1, 15.11.2026, Zweig `modul05-c2`)

**Vorgehen:** Auf Wunsch von Michael vor der Praxisprüfung von C1 begonnen, auf einem eigenen Zweig. `main` bleibt bei 0.5.0, bis die Praxisprüfung C1 bestanden ist; Korrekturen aus dieser Prüfung kommen auf `main` und werden in den Zweig übernommen. Danach Zusammenführung, GitHub-Testlauf und Praxisprüfung C2.

**Neue Dateien:** `app/recipes/` (`models.py` Eingabeprüfung, `service.py` Regeln/Versionen/Kreisprüfung, `groups.py` Gruppen, `router.py`), `app/web/static/recipes.html` (Seite `/admin/rezepte` mit Reitern Rohstoffe, Rezepte, Gruppen); Tests `test_recipe_service.py`, `test_recipe_versions.py`, `test_recipe_groups.py`, `test_recipe_api.py` (API, nur GitHub-Testlauf). Geändert: `main.py`, `web/router.py`, `admin.html` (Reiter „Rezepte“, Rückkehr nach der Anmeldung über `?next=rezepte`). **Keine Migration**, `0003_recipe.sql` aus C1 reicht. Der Dateiname `groups.py` liegt wie im Konzept in `app/recipes/`.

**Präzisierungen der Umsetzung** (im Rahmen der Regeln, keine neue Regel):
- **Archivierte Rezepte sind nicht bearbeitbar** (409 `archived`, „bitte zuerst wiederherstellen“). Sperren/Freischalten bleibt möglich.
- **Bearbeitungsstand (`revision`):** steigt bei jedem Speichern mit Änderung und beim Speichern von Stückgewichten oder Chargengrößen (diese Aufrufe nehmen `revision` optional entgegen). Sperren, Freischalten, Archivieren und Wiederherstellen ändern ihn nicht. Der Konflikt „an einem anderen Gerät geändert“ wird **vor** der Versionsfrage geprüft.
- **Zeilen mit inzwischen archiviertem Rohstoff oder Unterrezept** bleiben beim Speichern erlaubt, wenn derselbe Rohstoff bzw. dasselbe Rezept schon in der aktuellen Version steht (R05-8).
- **Prüfmarkierung „*“:** Die Seite schickt je Zeile die ID aus der aktuellen Version mit. „*“ bleibt nur, wenn die Zeile mit gleichem Rohstoff/Unterrezept und gleicher Menge erhalten ist und die Seite es nicht mit „geprüft“ entfernt hat. Die Seite kann „*“ nie setzen; neue Zeilen erhalten es nur beim Import (Teil C3). Werden ausschließlich „*“ bestätigt, wird ohne Rückfrage überschrieben; ist die Version produziert, entsteht eine neue (K05-5).
- **Freischalten-Warnung 0 %** (K05-3) berücksichtigt die wirksame Toleranz der Zeile, also auch eine eigene Zeilentoleranz von 0 %.
- **Leere Nummer** beim Speichern = unverändert; Feld `group_id` fehlt = unverändert, `null` = keine Gruppe.
- **Stückgewichte und Chargengrößen** werden an Ort und Stelle geändert und behalten ihre ID (Verweise aus Aufträgen bleiben gültig). Chargengrößen können ihr Stückgewicht über die ID oder die Bezeichnung angeben (`piece_weight_label`); so speichert die Seite beide Listen nacheinander mit einer Taste.
- **Summen** zeigt die Seite als „gespeicherter Stand“ vom Server, nicht live beim Tippen (Berechnung nur an einer Stelle).
- **Versionsliste:** aktuelle Version „aktuell“, ältere „old (n)“; die Einzelansicht liefert `display_name` „<Name> old (n)“.
- **Kopie:** Ein langer Name wird nach „Kopie von “ auf 100 Zeichen gekürzt.
- **Grenzen:** höchstens 50 Schritte und 300 Zeilen je Rezept, Menge und Stückgewicht höchstens 1 000 000 g, Knetzeit höchstens 999 min, Chargengröße „Stückzahl“ höchstens 100 000.
- Der Reiter „Import/Export“ folgt mit Teil C3; der Rohstoff-CSV-Import bleibt auf der Rohstoffseite.

**Tests:** GitHub-Testlauf erfolgreich (Run 43739927541, Commit 64cd606): **424 Tests bestanden** (rezeptbuch 417, rezeptbuch_waage 7), 1 Warnung aus Fremdbibliothek. Der erste Lauf (Commit 562bb71) scheiterte nur am C1-Test, der die Version fest auf 0.5.0 prüfte; er vergleicht jetzt mit `config.yaml`. Lokal 353 bestanden, 4 übersprungen (API-Tests ohne FastAPI); neu 106 Fachtests (Service 72, Versionen 28, Gruppen 6) und 25 API-Tests (`test_recipe_api.py`). Zusätzlich lokaler Oberflächentest der Seite in Chrome (Testserver nur für die Prüfung, nicht im Repo): Anmeldung mit Rückkehr, Gruppe mit B2, Rezept anlegen, Versionsfrage, Stückgewichte/Chargengrößen, Freischalten mit 0-%-Warnung, alte Version ansehen, Kopie, „geprüft“, Unterrezept, Konflikt zweier Geräte, Archivieren als Unterrezept gesperrt; Darstellung am Handy (390 px) geprüft.

### Teil C3 (0.5.2, 17.11.2026)

**Neue Dateien:** `app/imports/recipe_template.py` (Vorlagen-Import), `app/exports/` (`recipe_template.py`, `router.py`), Migration `app/db/migrations/0004_recipe_note.sql`; Tests `test_import_recipes.py`, `test_export_recipes.py`, `test_import_export_api.py` (API, nur GitHub-Testlauf), Hilfsdatei `tests/template_factory.py` (erzeugt Testvorlagen mit den Spalten der echten Vorlage, ohne Betriebsdaten). `openpyxl` in `requirements.txt`. Geändert: `recipes/service.py` und `models.py` (interne Notiz, Filter, Stückgewichte/Chargengrößen zusätzlich als Funktionen für eine offene Transaktion `set_piece_weights_in_tx`, `set_batch_sizes_in_tx` – Verhalten der bisherigen Funktionen unverändert), `recipes/router.py`, `imports/report.py` und `router.py`, `main.py` (Export-Router vor dem Rezept-Router), `recipes.html`; Migrationstests auf Stand 4.

**Interne Notiz (KC2-2, Entscheidung Michael 17.11.2026):** Spalte `recipe.internal_note` (höchstens 2 000 Zeichen) per Migration `0004` (`ADD COLUMN`). Gehört zum Rezept, nicht zur Version: Ändern erzeugt nie eine neue Version, wird als `update` protokolliert und erhöht den Bearbeitungsstand. Fehlt das Feld beim Speichern, bleibt die Notiz unverändert. Kopie, Export und Vorlagen-Import (Spalte „Notiz intern“, optional) übernehmen sie. Die Lese-Schnittstelle der Stationen `GET /recipes/{id}` liefert sie **nicht**; die Admin-Seite lädt über `GET /admin/recipes/{id}`.

**Vorlagen-Import – Präzisierungen der Umsetzung** (im Rahmen von 6.2):
- Spalten werden an der Überschrift erkannt, ein Zusatz in Klammern zählt nicht („Rezeptnummer (Vorschlag)“ = „Rezeptnummer“, „Toleranz (Pflicht)“ = „Toleranz“). Spalten mit „(Formel)“ oder „(nicht importieren)“ sowie Bemerkungen werden nicht gelesen; unbekannte Spalten erscheinen als Hinweis. Pflicht sind die Blätter „Rezepte“ und „Rezeptzeilen“; die übrigen sind optional.
- Fußnoten unter den Tabellen (nur erste Zelle mit einem Satz gefüllt, wie in der Vorlage) werden mit Hinweis übersprungen.
- Die Datei wird zweimal geöffnet: mit gespeicherten Werten und mit Formeln. So wird erkannt, ob „Wert“ einer Chargengröße eine Formel ist (dann = Gesamtgewicht, wie leer), und der gespeicherte Wert von „Menge g (Formel)“ dient nur dem Vergleich (Hinweis bei Abweichung, K05-6).
- Einheit leer = g. Schlüssel der Umrechnung „Einheit Zutat“ ohne Groß-/Kleinschreibung. Mengen auch als Text mit Komma („0,75“). Rundung kaufmännisch (2,5 → 3).
- Zeilenart leer = Rohstoff, bei nur „Unterrezept Import-ID“ = Unterrezept. Werte „Rohstoff/Unterrezept“, „Beginn/Ende“ (auch „am Anfang und am Ende“/„nur am Ende“), „Gewicht/Stück“, Toleranzeinheit „g/percent/%“; „Prüfen“ = „*“ (auch x/ja/1).
- Zutaten werden über den **Namen** dem Rohstoffstamm nach Schritt 1 zugeordnet (aktive Rohstoffe, ohne Groß-/Kleinschreibung); ein Rohstoff muss daher nicht im Blatt „Rohstoffe“ stehen, wenn er schon in der Datenbank ist. Archivierter Rohstoff = Fehler.
- Zeilen werden nach „Position“ sortiert (ohne Position in Blattreihenfolge). Toleranzeinheit ohne Wert = Fehler.
- Leere Rezeptnummern erhalten fortlaufend Nummern nach der höchsten vorhandenen **bzw. in der Datei genannten** Nummer (kein Zusammenstoß mit später in der Datei genannten Nummern).
- Doppelte Import-ID, Nummer oder Name innerhalb der Datei werden vorab gemeldet. Unterrezepte werden zuerst angelegt; ein Rezept, dessen Unterrezept Fehler hat, wird mit Meldung nicht angelegt. Fehler der Service-Schicht werden Blatt und Zeile zugeordnet (z. B. Toleranz über 100 % → Blatt Rezeptzeilen, Zeile n).
- Eine Formel in einer Eingabespalte (z. B. Rezeptname) wird mit ihrem gespeicherten Wert gelesen.
- Schutz: höchstens 5 MB, entpackt höchstens 100 MB, 5 000 Zeilen je Blatt; `.xlsb` wird mit Hinweis „als .xlsx speichern“ abgelehnt.
- Antworten wie beim CSV-Import (Probelauf 200; Import mit Fehlern 400 `import_failed`; Überschreiben ohne Bestätigung 409 `overwrite_confirmation_required`; jeweils mit Bericht). Der Bericht enthält zusätzlich die neuen Rezepte (Nummer, Name, Zeilen, Gesamtgewicht, Anzahl „*“) und neuen Gruppen.

**Export – Präzisierungen:** Blatt „Info“ vorne, danach Rezepte, Rezeptzeilen, Stückgewichte, Chargengrößen, Rohstoffe (nur in den exportierten Versionen verwendete, mit Nummer), leere Umrechnung. Archivierte Unterrezepte exportierter Rezepte kommen immer mit. Rezepte-Blatt mit Status und Version „(nicht importieren)“. Eigene Zeilentoleranzen werden mitgegeben, die Toleranz des Rohstoffs nicht. Dateiname `rezepte_JJJJ-MM-TT.xlsx`. Ein Re-Import in dieselbe Datenbank meldet erwartungsgemäß „Nummer schon vergeben“ (M05-11).

**Korrekturen KC2-1 bis KC2-6** (Seite `recipes.html`): „Kurzname: …“ statt „Station: …“; Auswahl „am Anfang und am Ende“ (`start`) / „nur am Ende“ (`end`) mit Satz „Ist der Hinweistext leer, erscheint an der Waage kein Hinweis.“; Taste „Zutaten speichern“ mit Erläuterung; Kasten Stückgewichte/Chargengrößen bei ungespeicherten Änderungen farbig umrandet mit Warnzeile, „Zutaten speichern“ fragt dann „Beides speichern / Nur Zutaten speichern“, ungespeicherte Stückgewichte bleiben nach dem Speichern der Zutaten stehen (bisher stillschweigend verworfen); Rückfrage beim Klick auf ✕ eines Stückgewichts mit den betroffenen Chargengrößen (Rückfrage des Servers beim Speichern bleibt); Haken „mit archivierten Rohstoffen“ (API `GET /recipes?archived_raw_materials=true`, Listenfeld `archived_raw_material_count`, Spalte „Hinweis“); Konflikt „bitte neu laden“ als Fenster mit „Neu laden“ (auch beim Speichern der Stückgewichte).

**Tests:** lokal 411 bestanden, 5 übersprungen (API-Tests ohne FastAPI); neu 45 Import-, 7 Export- und 6 Servicetests, 9 API-Tests (nur GitHub-Testlauf). Zusätzlich lokaler Oberflächentest in Chrome mit einem Prüfserver (nur für die Prüfung, nicht im Repo): Probelauf und Import einer Testvorlage, Export-Download, Filter „mit archivierten Rohstoffen“, Kurzname-Hinweis, interne Notiz, KC2-4-Rückfrage, KC2-3 „Beides speichern“ mit Server-Sicherung, KC2-6-Fenster mit „Neu laden“, Handy-Ansicht (390 px).

### Ergänzung C3-E1 (0.5.3, 17.11.2026) – Sammelaktionen

**Wunsch Michael (17.11.2026, während der Praxisprüfung C3):** Rezepte in der Liste über Haken einzeln oder mit „alle auswählen“ anwählen; sobald etwas ausgewählt ist, die Aktionen **Freischalten, Sperren, Archivieren, Löschen, Exportieren**. Freischalten aller gewählten Rezepte auf einmal mit einer gemeinsamen Warnliste („*“, 0 %) und einer Bestätigung.

**Umsetzung:** `app/recipes/bulk.py` (`bulk_action`), Endpunkt `POST /api/v1/admin/recipes/bulk`, Export mit `ids`. Die Statusfunktionen haben dafür Varianten für eine offene Transaktion (`unlock_in_tx`, `lock_in_tx`, `archive_in_tx`, `delete_in_tx`); die bisherigen Funktionen rufen diese auf und verhalten sich unverändert. Keine Migration.

**Präzisierungen** (keine neue Fachregel):
- Es gelten dieselben Regeln wie beim einzelnen Rezept (R05-21, R05-22, R05-25). Anders als beim Import gilt **nicht** „alles oder nichts“: nicht erlaubte Rezepte werden **übersprungen** und mit Grund gemeldet, die übrigen ausgeführt. Die Vorschau (gleiche Schritte in einer Transaktion, danach zurückgerollt) zeigt das vor der Bestätigung.
- Ausführen verlangt `confirm: true` (sonst 409 `confirmation_required`). Die Seite fragt immer einmal, beim Löschen mit „Endgültig löschen“.
- Archivieren und Löschen werden wiederholt, solange es vorangeht: Haupt- und Unterrezept lassen sich gemeinsam archivieren bzw. löschen, wenn beide gewählt sind.
- Bereits freigeschaltete bzw. gesperrte Rezepte erscheinen als „ohne Änderung“.
- „alle auswählen“ wählt die **angezeigten** Rezepte (Suche und Filter wirken). Ändert sich der Filter, bleiben nur sichtbare Rezepte gewählt.
- Export der Auswahl: gewählte Rezepte plus ihre Unterrezepte (auch archivierte), unabhängig vom Haken „archivierte“.
- Höchstens 1 000 Rezepte je Aktion. Jede Änderung steht wie bisher im `change_log`.
- Wiederherstellen war zunächst keine Sammelaktion; seit 0.5.8 vorhanden (C3-E8).

**Tests:** `test_recipe_bulk.py` (18), 5 API-Tests in `test_import_export_api.py` (nur GitHub). Oberflächentest in Chrome: Auswahl, „alle auswählen“, Vorschau mit Warnliste, Freischalten, Archivieren eines Unterrezepts übersprungen, Export der Auswahl mit Unterrezept, Löschen, Handy-Ansicht.

### Ergänzungen C3-E7, C3-E8, C3-E11 (0.5.8, 18.11.2026)

**C3-E7 Umrechnung im Blatt „Rohstoffe“** (Entscheidung Michael 17.11.2026, Variante A, ändert K05-6/6.2):
- Zwei Spalten im Blatt Rohstoffe: „Umrechnung Einheit“ und „Gramm je Einheit“ (Mustervorlage mit Kommentar „Nur ausfüllen, wenn Rezepte über Umrechnung importiert werden sollen“ und Beispiel). Erkannt an der Überschrift ohne Klammerzusatz. Der Wert wird **nicht gespeichert** (M02-2), keine Migration.
- Die Rezeptzeile findet den Faktor über den Rohstoff (Name, ohne Groß-/Kleinschreibung) und die Einheit. Ist er für „ml“ eingetragen, gilt × 1 000 für „l“ und umgekehrt (E7c).
- **Jede umgerechnete Zeile bekommt „*“** (die Spalte „Prüfen“ bleibt für von Hand gesetzte „*“). g/kg und leere Menge (Handzugabe) gelten nicht als Umrechnung.
- **E7b:** Eine Zeile im Blatt Rohstoffe, die außer Nummer bzw. Name nur die Umrechnung enthält, ändert einen **vorhandenen** Rohstoff nicht (zählt als „unverändert“, keine Bestätigung); gibt es den Rohstoff noch nicht, wird er wie bisher neu angelegt (Toleranz 0 %). Eine vollständige Zeile mit Umrechnung überschreibt wie bisher (K05-2).
- **E7a:** Ein altes Blatt „Umrechnung“ wird weiter gelesen; der Bericht meldet „veraltet“, sobald es Zeilen enthält. Bei beiden Angaben gilt das Blatt Rohstoffe. **ToDo Modul 14:** Unterstützung des alten Blatts entfernen.
- **E7d:** Der Bericht enthält die Umrechnungen gesondert (`conversions`: Rezept, Zeile, Zutat, Text „20 Stück × 65 g = 1 300 g“, Quelle). Die Seite zeigt sie nach dem Probelauf **vorab in einem eigenen Fenster** mit „Weiter“, danach den Bericht; im Bericht steht eine Zeile mit der Taste „Umrechnungen anzeigen“.
- Fehlermeldungen: Umrechnung fehlt → Blatt Rezeptzeilen, Spalte „Einheit Original“, mit Hinweis auf das Blatt Rohstoffe; Einheit ohne Wert, Wert ohne Einheit, Wert ≤ 0 oder kein Zahlwert → Blatt Rohstoffe mit Zeile und Spalte. Eine Umrechnung für g/kg wird mit Hinweis nicht verwendet.
- Mustervorlage und Export: Blatt „Umrechnung“ entfällt; Export hat leere Umrechnungsspalten im Blatt Rohstoffe. Die Kontrollformel „Faktor“ der Mustervorlage liest den Faktor aus dem Blatt Rohstoffe (gleiche Einheit). Info-Text des Exports an C3-E5 angepasst (vorhandene Rezepte → neue Version).
- **E7e:** Hinweis LibreOffice („als .xlsx speichern“) in Anleitung der Mustervorlage, Info-Blatt des Exports und DOCS.md. Kein `.ods`-Leser. ToDo Modul 14: eine mit LibreOffice gespeicherte Vorlage einmal importieren.

**C3-E8 Sammelaktion „Wiederherstellen“:** Aktion `restore` in `bulk.py`, Service-Funktion `restore_in_tx` (die bisherige `restore_recipe` ruft sie auf, Verhalten unverändert). Nicht archivierte Rezepte erscheinen als „ohne Änderung“; ein gleichnamiges aktives Rezept (M05-3) → übersprungen mit Grund. Die Taste erscheint nur, wenn mindestens ein archiviertes Rezept angehakt ist. Status gesperrt/öffentlich bleibt (R05-23).

**C3-E11 Musterdaten ignorieren** (Entscheidung Michael 18.11.2026, E11-1 bis E11-6 wie vorgeschlagen):
- Erkennung über die **feste Namensliste** `SAMPLE_RECIPE_NAMES` / `SAMPLE_RAW_NAMES` in `exports/sample_template.py` (2 Musterrezepte, 11 Musterrohstoffe; ohne Groß-/Kleinschreibung), nicht über die gelbe Füllung oder „Muster“ im Namen.
- Übersprungen werden die Musterrezepte samt ihren Zeilen, Stückgewichten und Chargengrößen (über die Import-ID) sowie die Musterrohstoffe. Verweist ein eigenes Rezept auf ein Musterrezept als Unterrezept → Fehler „ist ein Musterrezept“.
- Bericht: Hinweis „Musterdaten der Mustervorlage ignoriert: n Musterrezepte und m Musterrohstoffe“, Zähler `counts.samples_recipes`, `counts.samples_raw_materials`. Enthält die Datei nur Musterdaten: Hinweis „nichts zu importieren“, `nothing_to_import`, Taste „Importieren“ bleibt aus.
- Bereits importierte Musterrezepte werden nicht mehr angefasst (keine neue Version, E11-5).
- **Präzisierung (zur Kenntnis):** Damit die Mustervorlage weiter zum Ausprobieren taugt (C3-E2: „ohne Änderung importierbar“), gibt es den Haken **„Musterdaten der Mustervorlage mit importieren“** (`include_samples=true`, Standard aus).

**Tests:** neu 26 Import-Tests (Umrechnung, E7a/E7b/E7c, Fehler, Musterdaten), 4 Sammelaktions-Tests (Wiederherstellen), 3 Tests der Mustervorlage, 1 Export-Test; `test_amount_conversion_and_rounding` erwartet jetzt „*“ bei der Stück-Zeile.

