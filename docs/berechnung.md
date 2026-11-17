# Modul 06 – Rezeptberechnung & Skalierung (Schritt B: Konzept)

Status: **Konzept am 17.11.2026 von Michael freigegeben** (Konzeptfragen K06-1 bis K06-4 entschieden, Abschnitt 13). **Teil C1 (0.6.0) am 17.11.2026 umgesetzt** auf dem Zweig `modul06` (Präzisierungen der Umsetzung in Abschnitt 16).
Grundlage: Entscheidungen M06-1 bis M06-7 vom 17.11.2026 (Schritt A, PROJEKTSTATUS Abschnitt 3), M02-1 bis M02-16, M03-4, M05-10, M05-13b, R05-27; docs/datenmodell.md, docs/rezepte.md, docs/bedienkonzept.md; Freigabebericht Modul 02 (B2, B4); Code-Stand `main` b918aad (Add-on `rezeptbuch` 0.5.3).
Zielversion: Add-on `rezeptbuch` **0.6.x**, Umsetzung in zwei Teilen (Abschnitt 12).
Besonderheit: Modul 06 wird **parallel zum Abschluss von Modul 05** begonnen (Entscheidung Michael 17.11.2026). Modul 05 ist noch nicht freigegeben, deshalb ändert Teil C1 nichts an Modul 05 (Abschnitt 12).

## 1. Zweck und Umfang

Modul 06 ist die **einzige Stelle**, an der Mengen gerechnet werden (Master-Prompt Regel 5). Es macht aus dem gespeicherten Grundrezept und der Auswahl der Vorwahl das Arbeitsrezept: Sollmenge, Toleranz und Aufteilung in ganze Gebinde + Rest je Zeile, dazu Anteile, Bäckerprozente und Hinweise.

**Enthalten**
- Skalierung nach allen Bezugsgrößen aus M02-1: Gesamtteig, Stückzahlen je Stückgewicht, Chargengröße, Leitrohstoff (g, kg oder Liter), „Mehl gesamt“.
- Rundungsregel (M06-1), Toleranz in Gramm mit Mindesttoleranz 1 g (M03-4, M06-5).
- Aufteilung der Sollmenge in ganze Gebinde/Stück + Rest (M02-2c, M02-2d).
- Unterrezepte über beliebig viele Ebenen (Mehl, Mengen, Anzeige eingeklappt).
- Anteil am Gesamtgewicht und Bäckerprozent, bezogen auf das Mehl inklusive Unterrezepten (M06-2, M06-6).
- Hinweis „ergibt n Stück“ je Stückgewicht (M06-3).
- Plausibilitätsprüfungen, Prüfung der Auftragsfelder (Befund B4) und der Chargenzeilen (Befund B2).
- Lese-Schnittstelle (REST) für Vorwahl und Rezeptübersicht der Stationen (Modul 09/10).
- Eine schlichte **Prüfseite „Berechnung“** im Admin-Bereich (K06-3).

**Nicht enthalten**
- Aufträge anlegen, Produktionsliste, Version fixieren, Chargen anlegen, Wiegen (Modul 09). Modul 06 liefert dafür die Rechenfunktionen.
- Höchstlast der Waage (30 kg) – Prüfung im Wiegeablauf (Modul 09), Anzeige in Modul 10 (M06-7).
- Gestaltung der Stationsseiten (Modul 10).
- Volumeneinheiten in Rezepten, Dichte (M02-2, Abweichung PROJEKTSTATUS Abschnitt 4).

## 2. Architektur

```
Station / Prüfseite ──fetch──►  calculation/router.py  (FastAPI, nur HTTP, ohne PIN)
                                        │
                                calculation/service.py  (lädt Daten, prüft Bezugsgröße, B4)
                                        │
                ┌───────────────────────┴───────────────────────┐
     calculation/loader.py                              calculation/engine.py
     (liest Rezeptversion, Unterrezepte,                (reine Rechnung, ohne Datenbank,
      Rohstoffe aus der DB → Datenobjekte)               exakte Brüche, Rundung, Toleranz)
```

- **`engine.py` kennt keine Datenbank.** Es bekommt einen Rezeptbaum als Datenobjekte und gibt das Ergebnis zurück. Dadurch sind alle Rechenregeln ohne Datenbank testbar, und Modul 09 nutzt beim Anlegen der Chargen genau dieselbe Rechnung.
- **Exakt rechnen, nur am Ende runden:** Gerechnet wird mit Python `fractions.Fraction` (Brüche, keine Kommazahlen), gerundet wird nur einmal je Zeile. So entstehen keine Fehler wie 312,000000001 → 313 g.
- Lesen über eine Verbindung je Anfrage (`deps.py`, B6), keine Schreibvorgänge außer dem Trigger aus Migration 0005 (Abschnitt 3).
- Die vorhandene Hilfsfunktion `units.kg_to_grams` wird für kg- und Liter-Eingaben genutzt (1 l = 1 000 g, M02-1e).

## 3. Datenbank – Migration `0005_batch_item_version.sql`

Ein Trigger und eine neue Spalte, keine neue Tabelle:

| Änderung | Inhalt | Grund |
|---|---|---|
| Spalte `production_order.basis_item_position` | INTEGER, leer erlaubt; nur bei `basis_type = raw_material` gesetzt, wenn der Leitrohstoff **je Zeile** gewählt wurde (leer = „gesamt“). Prüfregel per Trigger: nur zusammen mit `raw_material` | K06-1; ohne die Spalte könnte ein Auftrag nicht speichern, welche Zeile gemeint war |
| Trigger `trg_batch_item_version` | lehnt beim Anlegen und Ändern einer Chargenzeile ab, wenn `recipe_item_id` gesetzt ist und die Rezeptzeile zu einer anderen Version gehört als `batch.recipe_version_id` | Befund **B2** aus dem Freigabebericht Modul 02, zweite Sicherung neben der Prüfung im Code |

Ablauf wie bisher: Sicherungskopie vor der Migration, Rückrollen bei Fehler. Es gibt bisher keine Chargen in der Datenbank, der Trigger trifft also keine vorhandenen Daten.

## 4. Rechenregeln

### 4.1 Grundgrößen eines Rezepts

Für eine Rezeptversion (bei Unterrezepten jeweils deren aktuelle bzw. fixierte Version) gilt, exakt als Bruch gerechnet:

| Größe | Berechnung |
|---|---|
| **Gesamtgewicht G** | Summe aller Zeilen (Unterrezepte mit ihrer Menge), wie R05-27 |
| **Mehl M** | Summe der Rohstoffzeilen vom Typ Mehl **plus** für jede Unterrezeptzeile: Menge × (Mehl des Unterrezepts ÷ Gesamtgewicht des Unterrezepts), über alle Ebenen (M06-2) |
| **Menge eines Rohstoffs R(x)** | wie Mehl, aber für einen bestimmten Rohstoff x (für den Leitrohstoff, K06-1) |

Beispiel: Hauptteig mit 3 000 g Vorteig (Vorteig: 1 500 g Mehl, 1 500 g Wasser, also halb Mehl) und 7 000 g Mehl im Hauptteig → M = 7 000 + 3 000 × 1 500 ÷ 3 000 = **8 500 g**.

Mengenänderungen im Auftrag (`order_item_override`, Bedienkonzept Abschnitt 3) ersetzen die Grundrezept-Menge der Zeile **vor** der Rechnung. Gespeichert werden sie in Modul 09; Modul 06 nimmt sie als Eingabe entgegen.

### 4.2 Faktor je Bezugsgröße

Alle Werte gelten **je Teig**; die Anzahl Teige (`dough_count`) vervielfacht nur die Chargen, nicht die Mengen.

| Bezugsgröße (`basis_type`) | Eingabe | Faktor f |
|---|---|---|
| `total` Gesamtteig | g oder kg | Ziel ÷ G |
| `pieces` Stückzahlen | Anzahl je Stückgewicht des Rezepts | (Σ Anzahl × Stückgewicht) ÷ G |
| `batch_size` Chargengröße | Chargengröße des Rezepts | Gewicht ÷ G bzw. (Stückzahl × Stückgewicht) ÷ G |
| `raw_material` Leitrohstoff **gesamt** | Rohstoff, g, kg oder l (1 l = 1 000 g) | Ziel ÷ R(x) (Summe aller Zeilen inkl. Unterrezepten, K06-1) |
| `raw_material` Leitrohstoff **je Zeile** | Rezeptzeile (Position), g, kg oder l | Ziel ÷ Menge dieser Zeile (K06-1) |
| `flour_total` Mehl gesamt | g oder kg | Ziel ÷ M |

**Auswahl des Leitrohstoffs (K06-1):** Jeder Rohstoff erscheint einmal als **„gesamt“** (Summe aller Zeilen inklusive Unterrezepten) und darunter je Rezeptzeile des Hauptrezepts, in der er vorkommt (z. B. „Wasser gesamt 6 000 g“, darunter „Wasser – Vorteig 1 500 g“ und „Wasser – Hauptteig 4 500 g“). Kommt er nur in einer Zeile vor, gibt es nur einen Eintrag. Zeilen innerhalb von Unterrezepten sind einzeln nicht wählbar; sie zählen über „gesamt“ mit.

Cremes, Füllungen und Beläge brauchen keine eigene Bezugsgröße; ein Blech wird als Chargengröße angelegt (M06-4). „Mehl gesamt“ wird nur angeboten, wenn M > 0.

### 4.3 Rundung (M06-1)

| Nr. | Regel |
|---|---|
| R06-1 | Jede Zeile: exakte Menge = Grundrezept-Menge × f, dann **auf das nächste ganze Gramm aufrunden** (312,1 g → 313 g; genau 312 g bleibt 312 g). |
| R06-2 | **0 g bleibt 0 g** (Handzugabe nach Bedarf, M02-15). Eine Zeile mit Menge > 0 ergibt nie 0 g (Aufrunden ergibt mindestens 1 g). |
| R06-3 | Die Summe der gerundeten Zeilen darf über dem Ziel liegen. Angezeigt werden **Ziel** und **Summe nach Rundung**. |
| R06-4 | **Leitrohstoff** (K06-1, entschieden): Auch die Zeilen des Leitrohstoffs werden wie alle Zeilen **aufgerundet**, keine Ausnahme. Bei „je Zeile“ ergibt die gewählte Zeile genau die eingegebene Menge. Bei „gesamt“ mit mehreren Zeilen kann die Summe durch das Aufrunden wenige Gramm über der eingegebenen Menge liegen; die Übersicht zeigt dann den Hinweis H06-6. |
| R06-5 | **Unterrezepte:** Die Unterrezeptzeile wird wie jede Zeile aufgerundet. Das Unterrezept wird dann mit dieser gerundeten Menge als Gesamtteig gerechnet (genau so wird später der verknüpfte Unterrezept-Auftrag angelegt, R3). Angezeigt wird also immer, was tatsächlich gewogen wird. Durch die zweite Rundung kann das Unterrezept wenige Gramm mehr ergeben als seine Zeile. |

### 4.4 Toleranz (M03-4, M06-5)

| Nr. | Regel |
|---|---|
| R06-6 | Wirksame Toleranz = Toleranz der Zeile, sonst des Rohstoffs (R1, R05-11). |
| R06-7 | **Gramm:** Wert unverändert. **0 g = Sollhandzugabe** (nur quittieren, nicht wiegen, M05-13b). |
| R06-8 | **Prozent:** Sollmenge × Prozent, **auf ganze Gramm abgerundet, mindestens 1 g** (2 % von 312 g = 6,24 g → 6 g; 2 % von 30 g = 0,6 g → 1 g). **0 % wird gewogen mit ±1 g.** |
| R06-9 | Bei Gebinde/Stück gilt die **ganze Toleranz für den gewogenen Rest** (M02-2d). Grundlage der Prozentrechnung ist die **ganze Sollmenge der Zeile** (K06-2, entschieden: wie M02-2d). |
| R06-10 | Zeilen mit 0 g Menge (Handzugabe nach Bedarf) haben keine Toleranz; Unterrezeptzeilen haben keine Toleranz (R05-11). |

### 4.5 Gebinde und Stück (M02-2c, M02-2d)

| Nr. | Regel |
|---|---|
| R06-11 | Hat der Rohstoff eine Gebinde-/Stückgröße: ganze Einheiten = Sollmenge ÷ Größe, **abgerundet**; Rest = Sollmenge − Einheiten × Größe. Beispiele: 580 g Eier, Ei 55 g → **10 Eier + 30 g wiegen**; 30 000 g Mehl, Sack 25 000 g → **1 Sack + 5 000 g wiegen**. |
| R06-12 | Kein Runden auf ganze Stück (M02-2d). Ist der Rest 0 g, wird nur quittiert. Die Einheiten werden immer von Hand quittiert (Modul 09). |

### 4.6 Anteil und Bäckerprozent (M05-10, M06-6)

| Nr. | Regel |
|---|---|
| R06-13 | **Anteil** = Zeilenmenge ÷ Gesamtgewicht × 100, angezeigt mit einer Nachkommastelle (kaufmännisch gerundet). |
| R06-14 | **Bäckerprozent** = Zeilenmenge ÷ Mehl (inklusive Unterrezepten) × 100, eine Nachkommastelle. Ohne Mehl im Rezept wird keine Bäckerprozent-Spalte gezeigt. |
| R06-15 | Prozente werden aus dem **Grundrezept** gerechnet, nicht aus den gerundeten Mengen; sie ändern sich durch die Skalierung also nicht. |
| R06-16 | Ausgeklappte Zeilen eines Unterrezepts zeigen ihre Prozente **bezogen auf den Hauptteig** (z. B. Mehl im Vorteig 17,6 % Bäckerprozent), damit sich die Mehlzeilen aller Ebenen zu 100 % addieren. |

### 4.7 Hinweis Stückzahl (M06-3)

| Nr. | Regel |
|---|---|
| R06-17 | Für jedes Stückgewicht des Rezepts: „ergibt n × <Bezeichnung>“ mit n = exaktes Teiggewicht ÷ Stückgewicht, **auf eine Nachkommastelle abgerundet** (12,48 → 12,4), damit nie mehr Stück versprochen werden als möglich. |
| R06-18 | Angezeigt bei den Bezugsgrößen Gesamtteig, Leitrohstoff, Mehl gesamt und Chargengröße „Gewicht“. Bei Stückzahlen ist die Anzahl schon bekannt. Der Bediener kann danach selbst auf die ganze Stückzahl umstellen; es wird nichts automatisch abgerundet (M06-3). |

### 4.8 Anzeige von Unterrezepten (M06-6)

In der Rezeptübersicht erscheint ein Unterrezept als **eine Zeile** (z. B. „Vorteig 3 000 g“, farblich abgesetzt) und ist **eingeklappt**. Durch Antippen klappt es auf und zeigt seine Zutaten mit Mengen darunter, auch über weitere Ebenen. Die Schnittstelle liefert dafür den ganzen Baum; das Ein- und Ausklappen macht die Seite (Prüfseite in Modul 06, Stationsseite in Modul 10).

## 5. Plausibilitätsprüfungen

**Fehler** (keine Berechnung, Meldung mit Feld):

| Nr. | Fall | Meldung (Beispiel) |
|---|---|---|
| P06-1 | Wert ≤ 0 oder keine ganze Zahl nach Umrechnung | „Bitte eine Menge größer als 0 eingeben“ |
| P06-2 | Teig größer als 1 000 000 g je Teig (Grenze wie Rezeptzeilen in Modul 05) | „Menge zu groß (höchstens 1 000 kg je Teig)“ |
| P06-3 | Rezept ohne wiegbare Menge (keine Zeilen oder nur 0 g) | „Rezept enthält keine Mengen“ |
| P06-4 | Leitrohstoff kommt im Rezept (inkl. Unterrezepten) nicht oder nur mit 0 g vor; bei „je Zeile“: Position fehlt, gehört nicht zu diesem Rohstoff oder hat 0 g | „Rohstoff kommt im Rezept nicht vor“ (B4) |
| P06-5 | „Mehl gesamt“ ohne Mehl im Rezept | „Rezept enthält kein Mehl“ |
| P06-6 | Chargengröße oder Stückgewicht gehört nicht zum Rezept | „Chargengröße gehört nicht zu diesem Rezept“ (B4) |
| P06-7 | Stückzahlen: keine Anzahl > 0, Anzahl keine ganze Zahl, höchstens 100 000 | „Bitte mindestens eine Stückzahl eingeben“ |
| P06-8 | Eingabeeinheit passt nicht zur Bezugsgröße (Liter nur beim Leitrohstoff, Stück nur bei Stückzahlen bzw. Chargengröße „Stück“) | „Liter nur beim Leitrohstoff möglich“ (B4) |
| P06-9 | Kreis bei Unterrezepten oder mehr als 10 Ebenen (sollte nach R05-10 nie vorkommen) | „Unterrezepte bilden einen Kreis: …“ |
| P06-10 | Mengenänderung für eine Position, die es in der Version nicht gibt | „Zeile n gibt es im Rezept nicht“ |

**Hinweise** (Berechnung läuft, Hinweis wird angezeigt):

| Nr. | Fall |
|---|---|
| H06-1 | Zeilen mit Prüfmarkierung „*“ |
| H06-2 | Archivierter Rohstoff oder archiviertes Unterrezept im Rezept |
| H06-3 | Rohstoff mit Toleranz 0 % (wird mit ±1 g gewogen) |
| H06-4 | Aufrundung erhöht eine Zeile um mehr als 5 % (z. B. sehr kleine Teige mit Salz/Hefe) |
| H06-6 | Leitrohstoff „gesamt“: Summe nach Aufrundung liegt über der eingegebenen Menge (z. B. „Quark: 7 502 g statt 7 500 g“) |
| H06-5 | Rezept ist gesperrt oder archiviert (Prüfseite rechnet trotzdem; die Vorwahl zeigt solche Rezepte ohnehin nicht) |

**Auftragsfelder (Befund B4):** Dieselben Prüfungen P06-1 bis P06-8 stellt Modul 06 als Funktion `validate_basis(...)` bereit. Modul 09 ruft sie beim Anlegen und Ändern eines Auftrags auf; zusätzlich wird geprüft, dass die Summe der Stückzahlen (`order_piece`) den gespeicherten `basis_value` ergibt. Eine Prüfung per Datenbank-Trigger ist dafür nicht sinnvoll (Summen über mehrere Tabellen).

**Chargenzeilen (Befund B2):** Die Funktion `build_batch_items(...)` erzeugt die Chargenzeilen nur aus der fixierten Version des Auftrags; der Trigger aus Migration 0005 sichert das zusätzlich ab.

## 6. Datenstrukturen (Ergebnis einer Berechnung)

```
CalcResult
├── recipe: number, name, version_no, station-taugliche Namen
├── basis: type, input_value, input_unit, target_g (exakt, je Teig), factor (Bruch als Text)
├── totals: target_g, rounded_sum_g, flour_g (exakt, inkl. Unterrezepte), knead_slow/fast
├── piece_hints: [{label, weight_g, count_tenths}]      z. B. 124 = 12,4 Stück
├── items: [CalcLine]                                   Reihenfolge = Position
├── warnings: [{code, text, position?}]
└── errors: []                                           (nur bei Fehlern, dann keine items)

CalcLine
├── position, step_no, step_name, recipe_item_id
├── kind: raw_material | sub_recipe | hand (0 g)
├── raw_material: id, number, name, station_name, type, archived
├── base_g (Grundrezept, nach Mengenänderung), exact_g (Text), target_g (gerundet)
├── tolerance: unit, value, tolerance_g, is_hand_ack (0 g Toleranz)
├── units: size_g, label, count, rest_g               (nur mit Gebinde/Stück)
├── share_tenths, baker_tenths                         z. B. 176 = 17,6 %
├── needs_review
└── sub: CalcResult des Unterrezepts                  (nur bei sub_recipe, eingeklappt angezeigt)
```

Prozente und Stückzahlen werden als ganze Zahlen in Zehnteln übertragen (wie die Toleranz, K2), damit keine Kommazahlen zwischen Server und Seite wandern.

## 7. Schnittstellen

### 7.1 REST `/api/v1` (Lesen, ohne PIN – die Stationen brauchen das)

| Methode | Pfad | Inhalt |
|---|---|---|
| GET | `/recipes/{id}/basis-options` | Was die Vorwahl anbieten darf: Stückgewichte, Chargengrößen, „Mehl gesamt“ ja/nein mit Mehl im Grundrezept, mögliche Leitrohstoffe (je Rohstoff mit Menge > 0 ein Eintrag „gesamt“ inkl. Unterrezepten und darunter die einzelnen Zeilen des Hauptrezepts, jeweils mit Grundrezept-Menge, K06-1), Grundrezept-Gesamtgewicht |
| POST | `/calculation` | Berechnung nach Abschnitt 4. Eingabe: `recipe_id`, optional `version_no` (Vorgabe: aktuelle Version), `basis_type`, `value`, `input_unit`, `pieces: [{piece_weight_id, count}]`, `batch_size_id`, `raw_material_id`, `item_position` (nur Leitrohstoff je Zeile), `overrides: [{position, amount_g}]`. Antwort: `CalcResult` (Abschnitt 6) |

POST statt GET, weil die Eingabe Listen enthält; die Anfrage ändert nichts. Fehlerantworten wie bisher (`detail`, `field`, `code`): 400 Eingabe ungültig (P06-1 bis P06-10), 404 Rezept/Version nicht gefunden, 503 Datenbank nicht bereit.

### 7.2 Python-Funktionen für Modul 09

| Funktion | Zweck |
|---|---|
| `calculate(conn, request) -> CalcResult` | dieselbe Rechnung wie die REST-Schnittstelle |
| `validate_basis(conn, recipe_id, basis…) -> None` | Prüfung der Auftragsfelder (B4), wirft Fehler mit Feld |
| `build_batch_items(conn, order_id, version_id) -> list[dict]` | Werte für `batch_item` (target_g, tolerance_g, units_target, rest_target_g, Kopien von Nummer/Name/Gebinde) nur aus der fixierten Version (B2) |
| `tolerance_g(target_g, unit, value) -> int` | Toleranzregel R06-7/R06-8, auch für die Wiegeanzeige |

### 7.3 Änderungen an Modul 05 (nur Teil C2, K06-4)

Erst nach der Freigabe von Modul 05 und nach Abstimmung (Master-Prompt Abschnitt 9):
- `GET /recipes/{id}` und `GET /admin/recipes/{id}` bekommen **zusätzlich** `sums.flour_total_g` (Mehl inklusive Unterrezepten) und je Zeile `share_tenths`/`baker_tenths`. Vorhandene Felder bleiben unverändert (`flour_g` = nur direkte Zeilen, R05-27), also abwärtskompatibel.
- Die Rezeptseite `/admin/rezepte` zeigt die Spalten **Anteil** und **Bäckerprozent** und die Summe „Mehl gesamt (mit Unterrezepten)“.

## 8. Prüfseite „Berechnung“ (K06-3)

Schlichte Seite `app/web/static/calc.html` unter `/admin/berechnung`, neuer Reiter „Berechnung“ in der Reiterleiste. Gestaltung wie die übrigen Admin-Seiten (M03-6), in Modul 10 nicht übernommen, sondern ersetzt durch die Stationsseiten.

- Rezept wählen (Suche nach Nummer/Name, auch gesperrte).
- Bezugsgröße wählen: Gesamtteig (g/kg) · Stückzahlen je Stückgewicht · Chargengröße (Tasten) · Mehl gesamt · Leitrohstoff („gesamt“ oder je Zeile, + g/kg/l).
- Ergebnis: Tabelle mit Position, Kurzname, Menge, Toleranz ±, Gebinde („10 Eier + 30 g“), Anteil, Bäckerprozent; Unterrezepte eingeklappt mit ▸, Antippen klappt auf; darunter Ziel, Summe nach Rundung, Mehl gesamt, Knetzeit, „ergibt n Stück“, Hinweise.
- Nur lesen, speichert nichts. Liegt im Admin-Bereich (PIN), damit sie nicht an den Stationen auftaucht; die Schnittstelle selbst braucht keine PIN.
- Zweck: Michael kann jede Rechnung an echten Rezepten nachprüfen (Praxisprüfung Modul 06, Vergleich mit den Excel-Werten).

## 9. Verzeichnisstruktur (neu in 0.6.x)

```
rezeptbuch/
└── app/
    ├── calculation/
    │   ├── __init__.py
    │   ├── models.py      Eingabeprüfung der Anfrage
    │   ├── engine.py      reine Rechnung: Mehl, Faktor, Rundung, Toleranz, Gebinde, Prozente, Stückhinweis
    │   ├── loader.py      Rezeptbaum aus der Datenbank lesen (Version, Zeilen, Unterrezepte, Rohstoffe)
    │   ├── service.py     calculate, validate_basis, build_batch_items, basis_options
    │   └── router.py      /api/v1/recipes/{id}/basis-options, /api/v1/calculation
    ├── units.py           + liters_to_grams (1 l = 1 000 g)
    ├── web/static/calc.html, web/router.py (+ /admin/berechnung)
    └── db/migrations/0005_batch_item_version.sql
rezeptbuch/tests/
    test_calc_engine.py    Rechenregeln ohne Datenbank
    test_calc_service.py   mit Datenbank: Unterrezepte, B4, build_batch_items
    test_migration_0005.py Trigger B2
    test_calc_api.py       Schnittstelle (nur GitHub-Testlauf)
```

## 10. Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| Eingabe ungültig (P06-1 bis P06-10) | 400 mit Feld und Meldung, keine Teilergebnisse |
| Rezept oder Version fehlt | 404 |
| Kreis/zu tiefe Verschachtelung | 400 mit Weg; Rechnung bricht ab, statt endlos zu laufen |
| Rohstoff eines Rezepts zwischenzeitlich archiviert | Rechnung läuft, Hinweis H06-2 |
| Chargenzeile mit Zeile einer anderen Version | Code lehnt ab; Trigger als zweite Sicherung (B2) |
| Datenbank nicht bereit | 503 (wie Modul 03/05) |

## 11. Tests

- **Rechenregeln (ohne Datenbank):** jede Bezugsgröße; Aufrunden (312,1 → 313, 312,0 → 312, sehr kleine Werte → 1 g); 0 g bleibt 0; Leitrohstoff „gesamt“ über mehrere Zeilen und Unterrezepte sowie „je Zeile“ (genau die eingegebene Menge), Hinweis H06-6 (K06-1); Prozent-Toleranz abgerundet und mindestens 1 g; 0 % → ±1 g; 0 g Toleranz → Handquittung; Gebinde (Eier 580/55, Sack 30 000/25 000, Rest 0); Mehl über zwei Ebenen Unterrezept; Bäckerprozente der Mehlzeilen aller Ebenen ergeben 100,0 %; Stückhinweis abgerundet; Mengenänderung vor der Rechnung; keine Gleitkommafehler (Brüche).
- **Referenzrezepte:** 2–3 echte Rezepte aus der Importvorlage mit von Hand nachgerechneten Sollwerten (Brötchenteig mit Stückgewichten, ein Brot mit Vorteig, Käsekuchen mit Quark als Leitrohstoff). Die Testdaten werden im Test erzeugt, keine Betriebsdaten im Repo (Abschnitt 7 PROJEKTSTATUS).
- **Mit Datenbank:** Unterrezept mit eigener aktueller Version; B4 (Chargengröße eines anderen Rezepts, Leitrohstoff nicht im Rezept, Liter bei Gesamtteig, Stückzahl-Summe); `build_batch_items` nur aus fixierter Version; Trigger B2 auf neuer und befüllter Datenbank.
- **API:** beide Endpunkte, Fehlerfälle, ohne PIN erreichbar.
- Bestehende Tests laufen unverändert weiter.

## 12. Umsetzung in zwei Teilen

| Teil | Inhalt | Version | Ändert Modul 05? |
|---|---|---|---|
| **C1** | `calculation/` komplett, Migration 0005 (B2), `liters_to_grams`, Prüfseite `/admin/berechnung` mit Reiter | 0.6.0 | **nein** (nur ein neuer Reiter-Eintrag in der Reiterleiste, siehe unten) |
| **C2** | Prozentspalten und „Mehl gesamt (mit Unterrezepten)“ in der Admin-Rezeptansicht und der Lese-API (Abschnitt 7.3) | 0.6.1 | ja, nach Freigabe Modul 05 und Abstimmung |

**Parallelbetrieb mit Modul 05:** Solange Modul 05 nicht freigegeben ist und eventuell noch Korrekturen 0.5.x bekommt, wird Modul 06 auf einem eigenen Zweig **`modul06`** entwickelt (wie `modul05-c2`). `main` bleibt bei Modul 05. Nach der Freigabe von Modul 05 wird `modul06` auf den neuesten Stand gebracht, zusammengeführt (0.6.0), getestet und praktisch geprüft. Der Reiter „Berechnung“ ist der einzige Berührungspunkt mit den Modul-05-Seiten (ein Eintrag in der Reiterleiste von `recipes.html`/`admin.html`).

Jeder Teil mit Push, GitHub-Testlauf und Praxisprüfung durch Michael; Freigabe Modul 06 nach C2 mit Freigabebericht.

## 13. Konzeptfragen – entschieden am 17.11.2026

| Nr. | Frage | Vorschlag |
|---|---|---|
| ~~K06-1~~ | **Entschieden 17.11.2026 (Michael):** Leitrohstoff zur Auswahl **einmal „gesamt“** (Summe inkl. Unterrezepten) **und darunter je Rezeptzeile**. Gerundet wird wie überall **auf**, keine Ausnahme für den Leitrohstoff. Eingearbeitet in 4.2, R06-4, P06-4, H06-6, Abschnitt 3 und 7. | – |
| ~~K06-2~~ | **Entschieden 17.11.2026 (Michael):** wie bereits in M02-2d entschieden – Prozent von der **ganzen Sollmenge**, diese Toleranz gilt für den gewogenen Rest (30 000 g Mehl, 2 % → ±600 g auf 5 000 g Rest). | – |
| ~~K06-3~~ | **Entschieden 17.11.2026 (Michael):** Prüfseite „Berechnung“ wird angelegt (Abschnitt 8). | – |
| ~~K06-4~~ | **Entschieden 17.11.2026 (Michael):** Prozentspalten in der Admin-Rezeptansicht als Teil C2 erst **nach der Freigabe von Modul 05**; Teil C1 auf dem Zweig `modul06`. | – |

## 14. Auswirkungen auf andere Module

| Modul | Auswirkung |
|---|---|
| 02 | Migration 0005 (Trigger B2, Spalte `production_order.basis_item_position` für K06-1); Befunde B2/B4 damit erledigt |
| 05 | Teil C2: zusätzliche Felder in der Lese-API und Spalten auf `/admin/rezepte` (abwärtskompatibel, nach Freigabe 05); Reiter „Berechnung“ |
| 09 | nutzt `calculate`, `validate_basis`, `build_batch_items`, `tolerance_g`; legt Unterrezept-Aufträge mit Bezugsgröße „Gesamtteig“ = gerundete Zeilenmenge an (R06-5); prüft die Höchstlast der Waage (M06-7) |
| 10 | zeigt die Rezeptübersicht mit eingeklappten Unterrezepten, Prozenten, Stückhinweis; Anzeige Höchstlast (M06-7) |
| 11 | übernimmt die Sollwerte unverändert aus `batch_item` |
| 14 | Referenzrezepte aus Abschnitt 11 dienen auch der Gesamtprüfung |

## 15. Änderungen

| Datum | Änderung |
|---|---|
| 17.11.2026 | Konzept erstellt (Schritt B), Konzeptfragen K06-1 bis K06-4. |
| 17.11.2026 | K06-4 entschieden (wie vorgeschlagen); **Konzept von Michael freigegeben** (Freigabe zum Programmieren). |
| 17.11.2026 | K06-2 (ganze Sollmenge, wie M02-2d) und K06-3 (Prüfseite anlegen) entschieden. |
| 17.11.2026 | K06-1 entschieden: Leitrohstoff „gesamt“ und je Zeile, Aufrunden ohne Ausnahme; neue Spalte `basis_item_position` in Migration 0005, Hinweis H06-6. |
| 17.11.2026 | Teil C1 (0.6.0) umgesetzt auf dem Zweig `modul06`; Präzisierungen in Abschnitt 16. |

## 16. Präzisierungen der Umsetzung (Teil C1, 0.6.0)

Festlegungen, die das Konzept offen ließ oder die bei der Umsetzung genauer wurden. Keine Abweichung von einer Entscheidung.

1. **Eingabeprüfung ohne Pydantic** (`models.py`), wie in Modul 03 und 05: Fehler kommen als Status 400 mit deutschem Text, `field` und `code`. Pydantic hätte englische Meldungen mit Status 422 geliefert.
2. **Mengen müssen ganze Gramm ergeben** (P06-1): „7,5 kg“ = 7 500 g ist gültig, „7,5 g“ nicht. Erlaubt sind nur Ziffern mit höchstens einem Komma oder Punkt; Tausenderpunkte werden nicht erkannt. Höchstens 1 000 kg gelten für die Eingabe **und** für den daraus berechneten Teig (z. B. Leitrohstoff Salz).
3. **Eingabeeinheit:** ohne Angabe gilt `g` (Stückzahlen: `pcs`; Chargengröße: aus der Chargengröße). Bei der Chargengröße muss eine angegebene Einheit zur Art passen (`pcs` nur bei „Stück“).
4. **Leitrohstoff-Auswahl** (`basis-options`): Die einzelnen Zeilen werden nur aufgeführt, wenn der Rohstoff an mehr als einer Stelle vorkommt (mehrere Zeilen oder zusätzlich in einem Unterrezept). Reihenfolge nach dem ersten Vorkommen. Handzugaben (0 g) sind nicht wählbar.
5. **Ausgabe:** `totals.target_g` (kaufmännisch gerundet) mit `target_exact` (Text) und `target_is_exact`; `flour_g` mit `flour_exact`; `basis.factor` als Bruch („1/3“) und `factor_text` (vier Nachkommastellen). Die Liste `errors` gibt es nicht: Bei einem Fehler antwortet die Schnittstelle mit Status 400 statt mit einem Ergebnis.
6. **Hinweis-Codes:** `needs_review` (H06-1), `archived` (H06-2), `tolerance_zero_percent` (H06-3), `rounding_large` (H06-4), `recipe_locked`/`recipe_archived` (H06-5), `basis_rounded` (H06-6). Ein gesperrtes **Unter**rezept ist kein Hinweis (M05-5).
7. **Leeres Unterrezept** (nur 0-g-Zeilen) ist ein Fehler („Unterrezept … enthält keine Mengen“), da es sich nicht skalieren lässt.
8. **Mengenänderungen** (`overrides`) gelten nur für Zeilen des Hauptrezepts; eine Unterrezeptzeile braucht eine Menge > 0.
9. **Migration 0005:** je ein Trigger für Anlegen und Ändern (`trg_order_basis_item_position_insert/_update`, `trg_batch_item_version_insert/_update`) und zusätzlich die Prüfregel `basis_item_position >= 1`. Der Trigger B2 greift nur, wenn `recipe_item_id` gesetzt ist; hat die Charge noch keine Version, wird eine Chargenzeile mit Rezeptzeile abgelehnt.
10. **`validate_basis(conn, recipe_id, order)`** bekommt die Spalten des Auftrags als Wörterbuch (`basis_type`, `basis_value` in Gramm, `basis_input_unit`, `basis_raw_material_id`, `basis_item_position`, `batch_size_id`, dazu `pieces`, optional `recipe_version_id` und `overrides`). Geprüft wird zusätzlich, dass Leitrohstoff, Chargengröße und Stückzahlen nur bei ihrer Bezugsgröße angegeben sind und die Chargengröße den gespeicherten `basis_value` ergibt; danach läuft dieselbe Rechnung wie in der Vorwahl.
11. **`build_batch_items`** rechnet mit dem gespeicherten `basis_value` des Auftrags (nicht neu aus Stückgewichten, die sich inzwischen geändert haben könnten) und den Mengenänderungen aus `order_item_override`. Jede Zeile enthält die Spalten von `batch_item` und zusätzlich `kind`, `is_hand_ack`, `sub_recipe_id`, `station_name` (für Modul 09, nicht für die Tabelle). Handzugaben (0 g) werden als Rohstoffzeile mit 0 g und ohne Toleranz geliefert.
12. **Prüfseite:** Die Sitzung wird beim Öffnen über `GET /api/v1/admin/recipes/next-number` geprüft (ohne Sitzung → PIN-Eingabe, danach zurück zur Prüfseite über `?next=berechnung`). Dafür kennt `admin.html` jetzt neben `next=rezepte` auch `next=berechnung`. Auswahl auch alter Versionen; Bäckerprozent-Spalte nur bei Rezepten mit Mehl; Menge mit Mauszeiger zeigt den genauen Wert.
13. **Tests:** Migrationstests vergleichen den neuesten Stand mit der Zahl der ausgelieferten Migrationen statt mit einer festen Zahl (Empfehlung PROJEKTSTATUS Abschnitt 5). `test_calc_api.py` läuft nur im GitHub-Testlauf (FastAPI ist lokal nicht installiert); die Prüfseite wurde lokal mit einem Ersatzserver in Chromium geprüft (Rechner und iPhone-Ansicht).
