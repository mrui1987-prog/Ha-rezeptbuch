# Modul 04 – PDF-Import Kennzeichnungspass, Händler und Bezugsquellen (Schritt B: Konzept)

Status: **Konzept erstellt am 19.11.2026, 11:15 (M04-19), K04-1 bis K04-11 am 19.11.2026, 11:14 entschieden, Konzept am 19.11.2026, 11:32 freigegeben (M04-21).** Teil C1 umgesetzt als 0.10.14 (in `main`).
**Teil C2 überarbeitet am 21.11.2026, 00:55 (Auftrag Michael 00:40) wegen M04-23: Die Leser laufen im eigenen Add-on 3 `rezeptbuch_leser`; Add-on 1 ruft es auf und macht Zuordnung, Probelauf und Speichern. Geändert: Abschnitte 2, 6, 8, 10, 11, 12, neu 15 (Add-on 3 und JSON-Vertrag) und 16 (Fragen K04-12 bis K04-18, **am 21.11.2026, 08:01 wie vorgeschlagen entschieden**, M04-26). Die Überarbeitung als Ganzes ist noch nicht freigegeben.** Abschnitte 1, 3, 4, 5, 7, 9 und 13 unverändert.
Grundlage: Entscheidungen M04-1 bis M04-24 (docs/modulstatus-04.md), docs/datenmodell.md, docs/rohstoffe.md (Abschnitt 15 Preis je kg), docs/rezepte.md 6.1, docs/bestand.md 8 (BÄKO-Belege, VC03-c), Leser Kennzeichnungspass (Schema 2, freigegeben 18.11.2026, 13:39).

**Leitlinie Michael (21.11.2026, 00:40):** Wenn sich noch etwas ändert, dann eher an der Datenbank, in die eingespielt wird, als an den PDFs. Darum ist der Vertrag zwischen Leser und Add-on 1 (Abschnitt 15) so gebaut, dass er die PDFs vollständig und unverfälscht beschreibt und **keine Datenbankbegriffe** enthält. Die Übersetzung in Tabellen macht allein Add-on 1 und kann sich ändern, ohne dass der Leser angefasst wird.

## 1. Umfang

**Enthalten**
- Pass-Daten am Rohstoff: Herkunftsangaben, Allergene, Nährwerte, Zutaten, Plausibilitätshinweise (M04-1 bis M04-4, M04-17).
- PDF-Import: hochladen (bis 50 PDFs), Probelauf mit Bericht, Zuordnung, Bestätigung, Speichern in einem Schritt (M04-8, M04-10, M04-16).
- Händlerliste, Reiter „Bezugsquellen“ am Rohstoff, genau eine aktive Bezugsquelle (M04-5).
- Preis je Bezugsquelle, aktive Bezugsquelle bestimmt den Rohstoffpreis (M04-14).
- Massenpflege „als aktive Bezugsquelle setzen“ mit Vorschau (M04-6).
- Anpassung CSV-Export/-Import und Lese-API an Bezugsquellen und Herkunft „datenlink“ (M04-14, M04-18).
- Migration (jetzt 0009, M04-11/K04-5), Tests, Doku.

**Nicht enthalten**
- Anbindung über die datenlink-API (wartet auf Application-Token, M04-12).
- Allergene oder Nährwerte **je Rezept** berechnen (Rezeptkennzeichnung) – später als eigener Vorschlag.
- Kennzeichnung von Hand pflegen (siehe K04-9).
- Anzeige an der Station (Modul 09/10), Gestaltung der Seiten (Modul 10).
- Preisverlauf, Kosten je Rezept (unverändert R03-15).
- Buchen aus BÄKO-Belegen (VC03-c, Modul 03). **Der Belegleser selbst liegt aber in Add-on 3** (M04-23) und nutzt denselben Vertrag (Abschnitt 15.4).

## 2. Architektur (geändert 21.11.2026 wegen M04-23)

Add-on 1 wie Modul 03: Seite → Router → **service** → Datenbank. Alle Schreibwege (Seite, CSV-Import, PDF-Import, Massenpflege) laufen über die Service-Funktionen in einer Transaktion (`*_in_tx`, wie seit 0.5.0).

```
 Admin-Seite (Add-on 1)
   │  PDF hochladen
   ▼
 Add-on 1 rezeptbuch ── POST PDF ──►  Add-on 3 rezeptbuch_leser
   │  Probelauf, Zuordnung,    ◄── JSON ──  (liest nur; keine Datenbank,
   │  Bericht, Speichern                       kein Netz nach außen)
   ▼
 Datenbank /data/rezeptbuch.db (nur Add-on 1)
```

**Add-on 3 `rezeptbuch_leser`** (M04-23): PDF rein, JSON raus. Enthält den Kennzeichnungspass-Leser (aus `tools/kennzeichnungspass/` übernommen, unverändert) und den BÄKO-Belegleser (VC03-c). Schreibt nie in die Datenbank, kennt keine Rohstoffe, speichert keine PDFs. Einzelheiten Abschnitt 15.

**Neue bzw. erweiterte Pakete in Add-on 1** (Namen vorläufig):

```
app/readers/        Aufruf von Add-on 3 (HTTP), Prüfung des JSON-Vertrags (format_version)
app/labelpass/      Umwandlung Schema 2 → Speicherform, Vergleich alt → neu
app/imports/        labelpass_import.py (Probelauf, Bericht, Import)
app/raw_materials/  label.py (Pass-Daten lesen/schreiben)
```

**Kein `pdfplumber` in Add-on 1.** Damit bleibt das Bau-Risiko auf Add-on 3 begrenzt, und ein Fehler im Leser stoppt nie einen laufenden Teig.

**`tools/kennzeichnungspass/`** wird zu einem kleinen Aufruf des Leser-Codes aus Add-on 3 (Prüfwerkzeug am PC bleibt nutzbar, keine zweite Fassung).

## 3. Datenmodell (Migration 0009, in C1 schon angelegt)

Grundsatz: Die Rohstofftabelle bleibt schlank, Pass-Daten und Bezugsquellen kommen in eigene Tabellen. Zahlen exakt als ganze Zahlen (wie Gramm, Zehntelprozent, Cent).

### 3.1 Änderung `raw_material`

| Änderung | Inhalt |
|---|---|
| `source` | erlaubte Werte **`own` / `datenlink`** (statt `own` / `baeko`, M04-4, M04-18). Vorhandene Rohstoffe bleiben `own`. |
| `datenlink_id` | TEXT, leer erlaubt. **Eindeutig unter den nicht archivierten Rohstoffen** (Teilindex `WHERE archived = 0 AND datenlink_id IS NOT NULL`, M04-16). Archivierte behalten ihre ID. |
| `price_cents_per_kg`, `price_changed_at` | bleiben, Bedeutung ab jetzt: **gültiger Preis des Rohstoffs** (Abschnitt 5). |

Die Änderung der CHECK-Regel bei `source` verlangt in SQLite einen Neuaufbau der Tabelle (Schalter `-- migration: foreign_keys=off` wie in 0006, Trigger und Indizes von `raw_material` werden neu angelegt, `PRAGMA foreign_key_check` am Ende).

### 3.2 Neue Tabellen

**`raw_material_label`** – Pass-Angaben, höchstens eine Zeile je Rohstoff (ein Rohstoff = ein Pass, M04-7)

| Spalte | Typ | Bedeutung |
|---|---|---|
| raw_material_id | INTEGER | PK, FK → raw_material |
| data_source | TEXT | `datenlink` / `gdsn` (Datenquelle laut Pass) |
| manufacturer_name, manufacturer_city, manufacturer_country | TEXT | Datengeber (Hersteller) |
| product_no | TEXT | Produktnummer des Datengebers, **als Text** |
| gtin | TEXT | leer erlaubt |
| product_name | TEXT | Bezeichnung aus dem Pass, nur Info (M04-9) |
| valid_from | TEXT | „Gültig ab“, Datum (M04-15) |
| ingredients_state | TEXT | `text` / `none` („keine Angabe“, M04-17) |
| ingredients_text | TEXT | Zutatenliste als ein Text (M04-3, M04-17) |
| allergens_contained_state, allergens_cross_state | TEXT | je Spalte `known` / `none` („keine Angabe“, M04-1) |
| nutrition_basis | TEXT | `100g` / `100ml` |
| nutrition_preparation | TEXT | `unprepared` / `prepared` |
| plausibility | TEXT (JSON) | Hinweise des Lesers (M04-1) |
| file_name, file_sha256 | TEXT | hochgeladene Datei (K04-6) |
| imported_at | TEXT | Zeitpunkt des letzten Imports |

**`allergen`** – feste Liste (26 Zeilen wie im Pass: 14 Hauptallergene, Getreidesorten unter Gluten, Nusssorten unter Schalenfrüchte), von der Migration befüllt

| Spalte | Typ | Bedeutung |
|---|---|---|
| code | TEXT | PK, z. B. `gluten`, `weizen`, `haselnuss` |
| name | TEXT | Anzeige |
| parent_code | TEXT | FK → allergen, leer bei Hauptallergen |
| sort_order | INTEGER | Reihenfolge wie im Pass |

**`raw_material_allergen`** – angekreuzte Allergene

| Spalte | Typ | Bedeutung |
|---|---|---|
| raw_material_id | INTEGER | FK |
| kind | TEXT | `contained` / `cross` |
| allergen_code | TEXT | FK → allergen |
| parent_not_marked | INTEGER 0/1 | Unterallergen angekreuzt, Oberbegriff nicht (M04-1) |

PK (raw_material_id, kind, allergen_code). **Drei Zustände (M04-1):** Spalte `none` = „keine Angabe“ (nie als „nicht enthalten“ anzeigen); Spalte `known` + Zeile vorhanden = enthalten; Spalte `known` + keine Zeile = nicht enthalten.

**`raw_material_nutrient`** – Nährwerte je 100 g/ml

| Spalte | Typ | Bedeutung |
|---|---|---|
| raw_material_id | INTEGER | FK |
| nutrient_code | TEXT | `energy_kj`, `energy_kcal`, `fat`, `saturates`, `carbohydrate`, `sugars`, `fibre`, `protein`, `salt` |
| state | TEXT | `value` / `none` („keine Angabe“) |
| value_milli | INTEGER | Wert × 1000 (61,0 g → 61000; 2629 kJ → 2629000), leer bei `none` |
| less_than | INTEGER 0/1 | „kleiner als“ (Salz < 0,01 g) |

**`dealer`** – Händlerliste (M04-5)

| Spalte | Typ | Bedeutung |
|---|---|---|
| id | INTEGER | PK |
| name | TEXT | NN; eindeutig ohne Groß-/Kleinschreibung (Prüfung im service wie R03-2), Sperre B2 (`=`, `+`, `-`, `@`) |
| archived | INTEGER 0/1 | archiviert statt gelöscht |
| created_at, updated_at | TEXT | |

**`raw_material_source`** – Bezugsquellen

| Spalte | Typ | Bedeutung |
|---|---|---|
| id | INTEGER | PK |
| raw_material_id | INTEGER | FK → raw_material |
| dealer_id | INTEGER | FK → dealer; **eindeutig zusammen mit raw_material_id** (ein Händler einmal je Rohstoff) |
| article_no | TEXT | Artikelnummer beim Händler, leer erlaubt |
| note | TEXT | Bemerkung, z. B. „nur im Winter“ |
| price_cents_per_kg | INTEGER | wie R03-13 (0 bis 999 999, leer erlaubt) |
| price_changed_at | TEXT | wie R03-14, je Bezugsquelle |
| is_active | INTEGER 0/1 | **höchstens eine aktive je Rohstoff** (Teilindex `WHERE is_active = 1`) |
| created_at, updated_at | TEXT | |

„Genau eine aktiv, sobald es Bezugsquellen gibt“ sichert der service (erste Bezugsquelle wird automatisch aktiv; die aktive kann nur entfernt werden, wenn eine andere aktiv gesetzt wird oder es die letzte ist). Die Datenbank sichert „höchstens eine“.

### 3.3 Protokoll

`change_log` wie bisher: `entity` = `raw_material` (Pass-Daten als Zusammenfassung alt/neu, Quelle `import`), `dealer`, `raw_material_source` (Quelle `admin` bzw. `import`).

## 4. Fachregeln

| Nr. | Regel |
|---|---|
| R04-1 | **Name nie überschrieben** (M04-9). Kurzname, Toleranz, Typ, Gebinde bleiben eigene Felder. |
| R04-2 | **Herkunft:** wird `datenlink`, sobald ein Pass zugeordnet ist; ohne Pass `own` (M04-18). Von Hand nicht änderbar. |
| R04-3 | **datenlink-ID** unter den aktiven Rohstoffen eindeutig (M04-16). Wiederherstellen eines archivierten Rohstoffs wird abgelehnt, wenn ein aktiver Rohstoff dieselbe ID hat (Meldung mit Hinweis auf diesen Rohstoff, wie R03-10). |
| R04-4 | **Herstellerwechsel:** Hat ein Rohstoff schon eine datenlink-ID, kann ihm kein Pass mit **anderer** ID zugeordnet werden. Der Bericht zeigt „anderer Hersteller/anderes Produkt – bitte neuen Rohstoff anlegen und ‚Rohstoff austauschen‘ nutzen“ (M04-7). |
| R04-5 | **Archivierter Rohstoff** mit passender ID wird aktualisiert und bleibt archiviert; Hinweis „Rohstoff ist archiviert“ (M04-16). |
| R04-6 | **Nie automatisch überschreiben** (M04-8): jede Änderung erscheint im Probelauf „alt → neu“ und wird erst nach Bestätigung gespeichert. **Neues Allergen** (in einer Spalte neu angekreuzt oder Spalte von „keine Angabe“ zu bekannt) wird deutlich markiert; **wegfallendes Allergen** ebenfalls. |
| R04-7 | **Älterer oder gleicher Pass:** Ist „Gültig ab“ älter als der gespeicherte Pass, Hinweis „älterer Pass als gespeichert“, Eintrag zunächst abgewählt. Gleicher Pass ohne Änderung → „unverändert“. |
| R04-8 | **Mehrere PDFs zum selben Produkt in einem Durchgang:** nur der jüngste Pass wird angeboten, die übrigen erscheinen als „älterer Pass, übersprungen“. |
| R04-9 | **Unlesbar oder unbekanntes Format** (mehr als 2 Seiten, Unterzutaten, kein Kennzeichnungspass): wird gemeldet und nicht übernommen, die übrigen PDFs laufen weiter (M04-10). Nichts wird geraten. **Seit 21.11.2026: maßgeblich ist der `status` aus Add-on 3 (Abschnitt 15.3); nur `ok` ist übernehmbar.** |
| R04-10 | **Bezugsquellen:** ein Händler je Rohstoff einmal; erste Bezugsquelle wird aktiv; genau eine aktiv, solange es welche gibt. Archivierte Händler erscheinen nicht in der Auswahl für neue Bezugsquellen; bestehende bleiben. |
| R04-11 | **Händler löschen** nur, wenn nie verwendet; sonst archivieren (wie R03-11). Umbenennen wirkt bei allen Rohstoffen. |
| R04-12 | **Haftungshinweis** auf dem Reiter „Kennzeichnung“: „Angaben des Datengebers, ohne Gewähr; ersetzt nicht die Prüfung durch den Betrieb“ (M04-1). |

## 5. Preis je Bezugsquelle (M04-14)

- **Gültiger Preis** = Preis der aktiven Bezugsquelle; ohne Bezugsquelle der Preis direkt am Rohstoff.
- Der service schreibt den gültigen Preis in `raw_material.price_cents_per_kg` (Spiegel). Vorteil: Lese-API, CSV-Export und spätere Berechnungen lesen weiter **ein Feld** (K04-4).
- Ohne Bezugsquelle wird der Preis wie bisher am Rohstoff eingegeben. Mit Bezugsquelle ist das Preisfeld am Rohstoff nur Anzeige („Preis der aktiven Bezugsquelle“); geändert wird an der Bezugsquelle.
- Wird die letzte Bezugsquelle entfernt, bleibt der zuletzt gültige Preis am Rohstoff stehen und ist wieder direkt änderbar.
- Werte, Rundung, Obergrenze, 0,00 € ≠ leer: R03-13 unverändert, je Bezugsquelle.

## 6. PDF-Import – Ablauf (geändert 21.11.2026)

1. **Hochladen** im Admin-Bereich (PIN), Reiter „Import/Export“ (seit R1 gemeinsam), Bereich „Kennzeichnungspässe (PDF)“: bis 50 PDFs, je Datei höchstens 5 MB. Die Seite schickt die Dateien einzeln an Add-on 1 (Rohdaten im Anfragekörper).
2. **Lesen:** Add-on 1 schickt das PDF unverändert an Add-on 3 (`POST /v1/lesen/kennzeichnungspass`, Abschnitt 15.2) und bekommt das JSON zurück. Prüft `format` und `format_version`; passt die Fassung nicht, wird die Datei als „Leser passt nicht zu dieser Version – Add-on 3 aktualisieren“ gemeldet. **Ist Add-on 3 nicht erreichbar**, meldet die Seite „Leser nicht erreichbar – Add-on ‚HA-Rezeptbuch Leser‘ starten“, nichts wird gespeichert, alles andere läuft weiter.
3. **Probelauf:** Add-on 1 legt das JSON zusammen mit dem PDF im **Probelauf-Speicher** ab (Arbeitsspeicher, an die PIN-Sitzung gebunden, verfällt nach 30 Minuten oder beim Neustart) und gibt den Bericht je Datei zurück.
4. **Bericht je Produkt:**
   - erkannt über datenlink-ID → „Rohstoff Nr. 12 Haselnüsse“ mit Änderungen „alt → neu“ (oder „unverändert“), Hinweise (archiviert, älterer Pass, neues/wegfallendes Allergen, Plausibilität, z. B. Sorten nur in der Zutatenliste);
   - **neu** → Auswahl: **zu vorhandenem Rohstoff** (Liste mit Namensvorschlägen wie R03-3; nur Rohstoffe ohne datenlink-ID) oder **neu anlegen** (Name vorbelegt mit der Bezeichnung aus dem Pass, änderbar; Regeln für Neuanlage K04-7);
   - **nicht lesbar** (`status` ≠ `ok`) → Grund aus `meldung` und `warnungen`, nicht wählbar.
   - Jeder Eintrag einzeln **abwählbar** (M04-10).
5. **Import:** Die Seite schickt die Probelauf-Kennung, die gewählten Einträge und die Zuordnungen. Add-on 1 prüft alles noch einmal gegen den **aktuellen** Datenbankstand und speichert **alles in einem Schritt** (eine Transaktion), das PDF unter `/data/kennzeichnungspaesse/` (K04-6). Hat sich seit dem Probelauf etwas geändert, wird nicht gespeichert, sondern ein neuer Bericht gezeigt. Add-on 3 wird beim Import **nicht** noch einmal gefragt (gespeichert wird, was im Bericht stand).
6. **Protokoll:** je Rohstoff ein `change_log`-Eintrag (Quelle `import`, mit Leser-Version aus dem JSON), im Add-on-Protokoll eine Zeile mit Zahl der übernommenen Pässe.

## 7. Seiten (schlicht, Gestaltung Modul 10)

- **Rohstoffliste:** neue Spalten „Herkunft“ (eigen/datenlink), „Pass ab“, „Händler (aktiv)“; Filter „ohne Pass“; Haken je Zeile für die **Massenpflege** (Händler wählen → „als aktive Bezugsquelle setzen“ → Vorschau mit Preisänderung je Rohstoff → Speichern, M04-6).
- **Rohstoff bearbeiten**, drei Reiter:
  - **Grunddaten** – wie heute; Preisfeld nur Anzeige, wenn eine Bezugsquelle aktiv ist.
  - **Kennzeichnung** – nur Anzeige: Herkunftsangaben, „Pass gültig ab …“, Allergene (zwei Spalten, „keine Angabe“ deutlich anders als „nein“), Nährwerte, Zutaten, Hinweise, Haftungshinweis, PDF öffnen (K04-6), Taste „Zuordnung lösen“ (K04-9).
  - **Bezugsquellen** – Liste mit Händler, Artikelnummer, Preis, Bemerkung, aktiv; hinzufügen, ändern, entfernen, aktiv setzen.
- **Händler:** seit R1 Unterreiter der Rohstoffverwaltung (anlegen, umbenennen, archivieren, löschen wenn nie verwendet).
- Keine Browser-Dialoge (`alert`/`confirm`), eigene Rückfragen wie seit 0.3.3.

## 8. Schnittstellen Add-on 1 (REST `/api/v1`)

Lesen ohne PIN (wie R03-16, K04-4):

| Methode | Pfad | Inhalt |
|---|---|---|
| GET | `/raw-materials`, `/raw-materials/{id}` | zusätzlich `source` (`own`/`datenlink`), `datenlink_id`, `label_valid_from`, `active_source` (`dealer_name`, `article_no`) oder `null`; `price_cents_per_kg` = gültiger Preis (Feldname unverändert) |
| GET | `/raw-materials/{id}/label` | Pass-Daten (Allergene mit drei Zuständen, Nährwerte, Zutaten, Hinweise) |
| GET | `/raw-materials/{id}/sources` | Bezugsquellen |
| GET | `/dealers` | Händlerliste |

Ändern mit PIN:

| Methode | Pfad | Inhalt |
|---|---|---|
| POST/PATCH/DELETE | `/admin/dealers…` | Händler pflegen, archivieren, wiederherstellen |
| POST/PATCH/DELETE | `/admin/raw-materials/{id}/sources…` | Bezugsquellen, `…/{sid}/activate` |
| POST | `/admin/raw-materials/bulk-active-source` | Massenpflege, mit `dry_run` (Vorschau) |
| POST | `/admin/imports/labelpass/preview` | eine PDF → Add-on 3 → Eintrag im Probelauf |
| POST | `/admin/imports/labelpass/commit` | gewählte Einträge speichern |
| DELETE | `/admin/raw-materials/{id}/label` | Zuordnung lösen (K04-9) |
| GET | `/admin/raw-materials/{id}/label.pdf` | gespeichertes PDF (K04-6) |
| GET | `/admin/readers/status` | Erreichbarkeit und Version von Add-on 3 (für die Seite, neu) |

Fehler wie bisher mit deutscher Meldung, `field`, `code`. Schnittstelle von Add-on 3: Abschnitt 15.2.

## 9. CSV-Export und -Import

- **Export:** „Preis je kg €“ = gültiger Preis. „Herkunft“ zeigt „eigen“/„datenlink“. Neue Spalten am Ende: **„Händler (aktiv)“, „Artikelnummer (aktiv)“, „datenlink-ID“** (K04-3).
- **Import:** Preisspalte ändert den Preis der **aktiven Bezugsquelle**, ohne Bezugsquelle den Preis am Rohstoff (M04-14); Bericht nennt, wo der Preis geändert wurde („Bezugsquelle BÄKO“). Die neuen Spalten und „Herkunft“ werden **nicht ausgewertet** (K04-3). Alles Übrige wie docs/rezepte.md 6.1.

## 10. Tests (geändert 21.11.2026)

**Add-on 3** (eigene Tests im Ordner `rezeptbuch_leser/tests`):
- Leser-Tests wie bisher (reine Funktionen; echte Pässe nur mit `KENNZEICHNUNGSPASS_PDF_DIR`, nicht im Repo).
- HTTP: Gesundheit, falsche Methode/Pfad, leerer Körper, zu groß (> 10 MB), kein PDF, im Test erzeugtes PDF „kein Kennzeichnungspass“ → `falsches_dokument`, Antwort immer im Vertrag (Pflichtfelder, `format_version`).
- **Probebau des Docker-Images für amd64 und aarch64 im GitHub-Testlauf** (prüft `pdfplumber` auf Alpine).
- Belegleser: reine Funktionen mit im Test erzeugten Zeilen; echte Belege nur mit `BAEKO_BELEG_PDF_DIR` (Kundendaten, nicht im Repo), Summenprüfung als Selbstprüfung.

**Add-on 1:**
- Aufruf von Add-on 3 mit einem **Ersatz-Leser im Test** (keine PDFs, kein `pdfplumber`): erreichbar/nicht erreichbar/Zeitüberschreitung/falsche `format_version`/`status` ≠ `ok`.
- R04-1 bis R04-12 je Gut- und Schlechtfall: neu/zuordnen/unverändert/geändert, neues Allergen, „keine Angabe“, älterer Pass, doppelt im Durchgang, archiviert, Herstellerwechsel abgelehnt, unlesbar, 51 Dateien abgelehnt, Probelauf ändert nichts, Änderung zwischen Probelauf und Import, alles oder nichts, PDF-Ablage, Zuordnung lösen.
- Bestehende Tests laufen weiter.

## 11. Umsetzung in Teilen (K04-10, geändert 21.11.2026)

| Teil | Inhalt | Praxisprüfung (Michael) |
|---|---|---|
| C1 | Migration 0009, Händlerliste, Bezugsquellen, Preis je Bezugsquelle, Massenpflege, CSV/API-Anpassung – **umgesetzt 0.10.14** | (a)–(j) in docs/modulstatus-04.md |
| C2-L | **Add-on 3 `rezeptbuch_leser`**: Kennzeichnungspass-Leser + BÄKO-Belegleser, HTTP-Schnittstelle, Probebau | Add-on installieren und starten; Gesundheit im Protokoll; Test-Aufruf aus Add-on 1 (über die Seite aus C2-I) |
| C2-I | Add-on 1: Aufruf von Add-on 3, PDF-Import, Reiter „Kennzeichnung“, Zuordnung lösen, PDF-Ablage | 20–50 echte Pässe importieren, Zuordnung, erneuter Import „unverändert“, geänderter Pass, Abel+Schäfer-Hinweis, Add-on 3 gestoppt → saubere Meldung |

Reihenfolge: C2-L zuerst (Auftrag Michael 21.11.2026, 00:40: Leser jetzt bauen, Konzept wird danach gelesen). C2-I nach Freigabe dieses Konzepts. Versionen: Add-on 1 nächste freie 0.10.x beim Übernehmen; Add-on 3 eigene Reihe (K04-15). Code nur über Zweig, Tests, GitHub-Testlauf, dann `main` (Projektregel 6).

## 12. Auswirkungen auf andere Module (ergänzt 21.11.2026)

| Modul | Auswirkung |
|---|---|
| 01 | **drittes Add-on** (M04-23): docs/architektur.md (bisher „2 Add-ons“) und Repo-Aufbau nachziehen |
| 02 | Migration 0009 (in C1); C2 braucht keine weitere Migration |
| 03 | R03-8 und M03-2 ersetzt; Preis am Rohstoff = gültiger Preis (M04-14). **VC03-c nutzt den Belegleser aus Add-on 3** (K03-23); Zuordnung, erwarteter Zugang und Buchung bleiben in Add-on 1 |
| 05 | Rohstoff-CSV-Import: Preis an die aktive Bezugsquelle; „Rohstoff austauschen“ unverändert (M04-7) |
| 06 | keine Änderung |
| 08 | keine Änderung (Add-on 3 nutzt kein MQTT) |
| 09/10 | Kennzeichnung an der Station später möglich (Lese-API vorhanden); Gestaltung in Modul 10. **Ein Ausfall von Add-on 3 berührt den Wiegeablauf nicht** |
| 12 | zur Kenntnis: Kennzeichnung, Bezugsquellen und Händler ohne PIN lesbar (K04-4); Add-on 3 ist nur im internen Netz der Add-ons erreichbar (K04-13) |
| 13 | PDF-Ablage (K04-6) gehört zur Sicherung; Add-on 3 hat keine eigenen Daten |
| 14 | Probebau aarch64/amd64 bestätigt nur den Bau; Start auf der echten HA-Hardware gehört zur Inbetriebnahme |

## 13. Konzeptfragen – entschieden am 19.11.2026, 11:14 (Michael: „wie vorgeschlagen“)

Alle elf Fragen wie vorgeschlagen entschieden.

| Nr. | Frage | Entscheidung |
|---|---|---|
| K04-1 | **Bisheriger Preis**, wenn ein Rohstoff seine **erste** Bezugsquelle bekommt (von Hand oder über die Massenpflege) | **Übernehmen** als Preis dieser Bezugsquelle, Datum bleibt. Hat der Rohstoff schon Bezugsquellen, bekommt eine neu angelegte Bezugsquelle einen leeren Preis (wie M04-6). Präzisiert M04-6 „Preis zunächst leer“ nur für die erste Bezugsquelle. |
| K04-2 | **„Preis geändert am“** am Rohstoff beim Wechsel der aktiven Bezugsquelle | Wird gesetzt, **wenn sich der gültige Preis dadurch ändert** (sinngemäß R03-14); bei gleichem Preis bleibt es. Jede Bezugsquelle hat zusätzlich ihr eigenes Datum. |
| K04-3 | **CSV-Export** | Spalte „Preis je kg €“ = gültiger Preis; drei neue Spalten am Ende („Händler (aktiv)“, „Artikelnummer (aktiv)“, „datenlink-ID“), **nur zur Info**, der Import wertet sie nicht aus. |
| K04-4 | **Lese-API** | Feldname `price_cents_per_kg` bleibt und liefert den gültigen Preis; dazu `active_source`. Kennzeichnung, Bezugsquellen und Händler **ohne PIN lesbar** (wie Preise, R03-16). |
| K04-5 | **Migrationsnummer und Version** | Nächste freie Nummer bei der Umsetzung (geplant 0007; bekommt Modul 09 vorher eine Migration, dann 0008). Version: nächste freie Version von Add-on 1. Ändert M04-11 nur bei der Nummer. |
| K04-6 | **PDF aufbewahren?** | **Ja**, unter `/data/kennzeichnungspaesse/` (nur der zuletzt importierte Pass je Rohstoff, ca. 100 KB je Pass), am Reiter „Kennzeichnung“ zu öffnen, in der HA-Sicherung enthalten. Alternative: nur Dateiname und Prüfsumme. |
| K04-7 | **Neuanlage aus dem Pass:** Pflichtfeld Toleranz (R03-5) | Wie beim CSV-Import: **0 %** mit Hinweis im Bericht (Filter „0 %“ findet sie), Typ „Standard“, nächste freie Nummer. |
| K04-8 | **Neue Zutaten-/Allergen-Hinweise** des Lesers (Plausibilität) | Werden gespeichert und am Reiter „Kennzeichnung“ angezeigt (wie M04-1), **keine** Sperre beim Import. |
| K04-9 | **Kennzeichnung von Hand / Zuordnung lösen** | Keine Handpflege der Kennzeichnung im ersten Schritt (eigene Rohstoffe wie Wasser bleiben ohne Pass). Taste **„Zuordnung lösen“** mit PIN und Rückfrage: Pass-Daten werden entfernt, Herkunft wieder „eigen“, datenlink-ID frei, Eintrag im Protokoll (für falsche Zuordnung). |
| K04-10 | **Zwei Teile** C1 (Händler/Bezugsquellen/Preis) und C2 (PDF-Import) | **Ja**, je Teil Praxisprüfung; C1 ist unabhängig vom PDF-Leser und kann zuerst geprüft werden. **C2 seit 21.11.2026 in C2-L/C2-I geteilt (Abschnitt 11, Teil der offenen Überarbeitung).** |
| K04-11 | **Ein Händler mehrmals je Rohstoff** (z. B. zwei Artikelnummern bei BÄKO) | **Nein**, ein Händler einmal je Rohstoff; zweite Artikelnummer bei Bedarf in der Bemerkung. |

## 15. Add-on 3 `rezeptbuch_leser` (neu 21.11.2026, M04-23)

### 15.1 Aufbau

| Punkt | Festlegung (Fragen in 16, entschieden 21.11.2026, 08:01) |
|---|---|
| Slug / Name | `rezeptbuch_leser` / „HA-Rezeptbuch Leser“ |
| Grundbild | wie Add-on 1 und 2: `base-python:3.12-alpine3.20`, aarch64 und amd64 |
| Abhängigkeiten | nur `pdfplumber` (bringt `pdfminer.six`, `Pillow`, `pypdfium2` mit). **Kein FastAPI**: HTTP-Server aus der Python-Standardbibliothek (wenig Code, keine weitere Abhängigkeit) |
| Erreichbar | nur im internen Netz der Add-ons, Port **8100**, **kein Ingress, kein offener Port** am Host (K04-13) |
| Adresse aus Add-on 1 | Rechnername des Add-ons: `<Kennung der Add-on-Quelle>-rezeptbuch-leser` (bei Michael `ebca0349-rezeptbuch-leser`). Add-on 1 bildet ihn aus seinem eigenen Rechnernamen (`…-rezeptbuch` → `…-rezeptbuch-leser`); Option `reader_url` in Add-on 1 nur zum Überschreiben (K04-12) |
| Daten | keine. PDFs nur im Arbeitsspeicher bzw. kurz als Wegwerfdatei, danach gelöscht |
| Grenzen | höchstens **10 MB** je PDF, **20 Seiten** (Belege mit Übertrag; Pässe haben 2), **30 s** je Datei, eine Datei je Aufruf |
| Protokoll | eine Zeile je Aufruf: Leser, Status, Dauer, Prüfsumme (keine Inhalte, keine Namen) |
| Optionen | `log_level` |

### 15.2 Schnittstelle (HTTP, intern)

| Methode | Pfad | Inhalt |
|---|---|---|
| GET | `/v1/gesundheit` | `{"format":"rezeptbuch-leser","format_version":1,"addon_version":"…","leser":{"kennzeichnungspass":2,"baeko_beleg":1}}` (Leser mit Schema-Fassung) |
| POST | `/v1/lesen/kennzeichnungspass` | Körper = PDF (`application/pdf`), Kopfzeile `X-Dateiname` optional |
| POST | `/v1/lesen/baeko-beleg` | wie oben; Belegart (Auftragsbestätigung/Rechnung/Gutschrift) erkennt der Leser selbst |

HTTP-Status: 200 bei jedem gelesenen oder abgelehnten PDF (Ergebnis steht im JSON), 400 leerer Körper/kein PDF, 404 unbekannter Pfad, 413 zu groß. Add-on 1 wertet nur 200 inhaltlich aus.

### 15.3 JSON-Vertrag (Fassung 1)

```json
{
  "format": "rezeptbuch-leser",
  "format_version": 1,
  "addon_version": "0.1.0",
  "leser": "kennzeichnungspass",
  "leser_schema": 2,
  "datei": {"name": "…pdf", "bytes": 123456, "sha256": "…", "seiten": 2},
  "status": "ok",
  "meldung": null,
  "daten": { … },
  "warnungen": [],
  "plausibilitaet": []
}
```

| Feld | Bedeutung |
|---|---|
| `status` | **`ok`** = vollständig gelesen, keine Warnung → übernehmbar · **`unlesbar`** = Aufbau weicht ab oder Warnungen (M04-10, nichts geraten); `daten` kann Teilinhalt enthalten, **nur zur Anzeige** · **`falsches_dokument`** = kein Kennzeichnungspass bzw. kein BÄKO-Beleg · **`fehler`** = Leser abgestürzt/Zeitüberschreitung |
| `meldung` | ein deutscher Satz für den Bericht |
| `daten` | Kennzeichnungspass: **Schema 2 unverändert** (Kopf von `zwischenstruktur.py`); BÄKO-Beleg: 15.4 |
| `warnungen`, `plausibilitaet` | wie im Leser; `plausibilitaet` sperrt nie (K04-8) |

Regeln: Neue Felder darf Add-on 3 jederzeit **hinzufügen**; Add-on 1 ignoriert Unbekanntes. Wird ein Feld umbenannt, entfernt oder in der Bedeutung geändert, steigt `format_version` bzw. `leser_schema`. Add-on 1 nennt die Fassungen, die es versteht, und lehnt andere mit Meldung ab (Abschnitt 6, Schritt 2).

### 15.4 BÄKO-Belegleser (gebaut 21.11.2026, `leser_schema` 1; Grundlage docs/bestand.md 8.1–8.4)

Liefert den Beleg **so, wie er auf dem Papier steht**, ohne Rohstoffe und ohne Umrechnung in Gramm (beides Add-on 1, K03-19, M03-18). Name und Anschrift des Kunden werden **nicht** übernommen.
- Kopf: `belegart` (`auftragsbestaetigung` / `rechnung` / `gutschrift`), `haendler` (wie gedruckt, z. B. „BÄKO Saar-Pfalz eG“), `belegnummer` (AT…/RE…/GS…), `belegdatum` (AB: Auftragsdatum; ISO), `lieferdatum_voraussichtlich` (nur AB), `kundennummer` + `kundennummer_text`, `ausstelldatum_text`, `ihre_referenz` (CL…, Kopf), `versandart`.
- Je Position: `nr` (laufend), `pos` (AB/GS), `seite`, `warengruppe` (nur Rechnung), `artikelnummer` (Text), `anzahl_text` (Rechnung, z. B. „16 SCK a 25 KG“), `bezeichnung` + `bezeichnung_zeilen`, `gebinde_text` (AB/GS, z. B. „1 VE à 3 BT“), `gebinde_klammer` („(2 TR)“), `zusatztext` (Text nach dem Gebinde, z. B. Grundtext der Gutschrift), `bestellartikel` + `bestell_hinweis`, `menge_text` + `menge_tausendstel`, `mengeneinheit`, `preis_text` + `preis_zehntausendstel_euro`, `preiseinheit` (EIN/HDT/TSD), `netto_text` + `netto_cent`, `mwst_prozent`, `skonto` (`text`, `prozent_text`, `cent`; Rechnungen 2024) und `netto_nach_konditionen_cent`, `lieferung` (`art` Hauptorder/Ordersatz/Rücknahme/Strecke, `lieferschein`, `lieferdatum`, `zusatz`), `auftrag` (`referenz` CL…, `auftrag` AT…/RN…, `auftragsdatum`), `ext_belegnummer`, `lieferantenbeleg` (Strecke).
- `summen`: `netto_cent`, `mwst_cent`, `brutto_cent`, `belegsumme_cent`, `mwst_saetze` (je Satz netto/MwSt./brutto) und `gelesen_netto_cent` (Summe der gelesenen Positionen, nach Skonto). `warengruppen`: Rechnungsanlage bzw. Artikelgruppen der Gutschrift (Nummer, Name, Beträge). `zahlung_text` (z. B. „Abbuchung zum … abzgl. 2 % Skonto …“).
- **Prüfungen, jede Abweichung = Warnung = `unlesbar` (K03-31):** Summe der Positionen = Netto-Summe; je MwSt.-Satz; jeder Übertrag am Seitenende und oben auf der Folgeseite; je Warengruppe gegen die Rechnungsanlage; Summe nach Konditionen = Netto − Skonto; Belegsumme = Brutto; Belegnummer passt zur Belegart; jede Zeile mit Zahlen rechts muss zugeordnet sein; Spalte „Ihre Art.-Nr.“ gefüllt → unbekannter Aufbau.
- **Plausibilität (sperrt nicht):** Menge × Preis ≠ Netto (über Rundung hinaus); **im PDF übereinander gedruckte Bezeichnungszeilen** (bei der BÄKO gesehen: „M32“ über „grün“ bzw. über der nächsten Artikelzeile) werden nach der Reihenfolge im PDF getrennt, der Position zugeordnet und gemeldet; ein leicht versetzter Doppeldruck desselben Texts wird stillschweigend einmal genommen.
- Streckenlieferung (WG 1301) und Pfand werden gelesen wie jede Position; was damit geschieht, entscheidet Add-on 1 (K03-24, K03-30).
- **Geprüft an 6 echten Belegen** (AT1002852, RE1395402, RE1392522, RE1389186, RE1360935 mit Skonto je Position und Strecke, GS1008363): alle `ok`, 165 Positionen, Summen auf den Cent; Gegenprobe mit `pdftotext` 164/165 gleich (die fehlende ist eine überdruckte Zeile, die `pdftotext` verschluckt). Gescannte PDFs (Kundeninventur) → `falsches_dokument`.

Zahlen als Ganzzahlen, damit nichts gerundet wird; die gedruckten Texte stehen daneben, damit der Bericht genau zeigt, was auf dem Beleg steht.

## 16. Fragen zur Überarbeitung – entschieden am 21.11.2026, 08:01 (Michael: „Alle okay“, M04-26)

Alle sieben Fragen wie vorgeschlagen entschieden.

| Nr. | Frage | Entscheidung |
|---|---|---|
| K04-12 | Wie findet Add-on 1 das Add-on 3? | Rechnername aus dem eigenen ableiten (15.1), Option `reader_url` nur zum Überschreiben. Keine Supervisor-Rechte nötig. |
| K04-13 | Schutz von Add-on 3 | Kein offener Port, kein Ingress; nur andere Add-ons im internen Netz erreichen es. Kein eigenes Kennwort, weil es nur liest, nichts speichert und nichts zurückgibt, was nicht im hochgeladenen PDF steht. |
| K04-14 | Add-on 3 nicht gestartet | PDF-Import und (später) Beleg-Import zeigen eine Meldung, alles andere läuft. Add-on 1 hängt nicht von Add-on 3 ab (kein `services`-Eintrag). |
| K04-15 | Version Add-on 3 | Eigene Reihe ab **0.1.0** wie Add-on 2 (die Versionsregel 0.10.x vom 19.11.2026, 17:02 gilt für Add-on 1). Jede Änderung an einem Leser hebt die Version von Add-on 3; Add-on 1 bleibt unberührt. |
| K04-16 | Wo liegt der Leser-Code? | In `rezeptbuch_leser/app/leser/`. `tools/kennzeichnungspass/` ruft ihn nur noch auf (eine Fassung). |
| K04-17 | Pass-Leser-Code beim Umzug | **Unverändert** übernommen (freigegeben 18.11.2026); nur ein Mantel drumherum (Status, Vertrag, Wegwerfdatei). |
| K04-18 | Echte Belege für Tests | Wie die Pässe: nicht im Repo (Kundendaten); Selbstprüfung mit Summen nur lokal bzw. in Claudes Arbeitsumgebung. |

## 14. Änderungen

| Datum | Änderung |
|---|---|
| 19.11.2026, 11:15 | Konzept erstellt (Schritt B, M04-19). Fragen K04-1 bis K04-11 offen. Liegt nur im Projektwissen; ins Repo mit der Umsetzung. |
| 19.11.2026, 11:14 (eingetragen 11:25) | **K04-1 bis K04-11 wie vorgeschlagen entschieden** (Michael). Inhalt unverändert. |
| 19.11.2026, 11:32 | **Konzept freigegeben** (Michael: „Ich gebe es frei“, M04-21). Umsetzung nach Freigabe Modul 06. |
| 21.11.2026, 08:01 | **K04-12 bis K04-18 wie vorgeschlagen entschieden** (Michael: „Alle okay“, M04-26). Freigabe der Überarbeitung und Übernahme von Add-on 3 in `main` weiter offen (Michael 08:01: „Nur K04-12–18“). |
| 21.11.2026, 07:45 | **Abschnitt 15.4 nach dem Bau des Beleglesers auf die tatsächlichen Felder gebracht** (Michael hat 6 echte Belege + Kundeninventur geliefert, 07:12). Freigabe weiter offen. |
| 21.11.2026, 00:55 | **Teil C2 überarbeitet** (Auftrag Michael 00:40, wegen M04-23): Leser in Add-on 3, JSON-Vertrag, Ablauf mit Aufruf von Add-on 3, Tests, Teile C2-L/C2-I, Auswirkungen; Abschnitte 15 und 16 neu (K04-12 bis K04-18 offen). **Freigabe der Überarbeitung offen.** Jetzt auch im Repo (Zweig von Add-on 3). |
