# Modul 06 – Rezeptberechnung & Skalierung (Schritt B: Konzept)

Status: **Konzept am 17.11.2026 von Michael freigegeben** (Konzeptfragen K06-1 bis K06-4 entschieden, Abschnitt 13). **Teil C1 (0.6.0) am 17.11.2026 umgesetzt**, seit 18.11.2026 in `main` (Präzisierungen der Umsetzung in Abschnitt 16). **Teil C2 (0.6.1) am 18.11.2026 umgesetzt** auf dem Zweig `modul06` (Präzisierungen in Abschnitt 18). **Teil C3 (0.6.2) am 18.11.2026 umgesetzt** auf dem Zweig `modul06` (Präzisierungen in Abschnitt 19). **Konzeptergänzung vom 18.11.2026 (Abschnitt 17: Kombinieren, Faktor, Obergrenze, Aufteilung, Zusammenfassung, Sitzungsprüfung)**: Konzeptfragen K06-5 bis K06-12 am 18.11.2026, 11:13 entschieden (Abschnitt 17.12, K06-6 abweichend); **Ergänzung am 18.11.2026, 12:42 von Michael freigegeben**.
Grundlage: Entscheidungen M06-1 bis M06-7 vom 17.11.2026 (Schritt A, PROJEKTSTATUS Abschnitt 3), M02-1 bis M02-16, M03-4, M05-10, M05-13b, R05-27; docs/datenmodell.md, docs/rezepte.md, docs/bedienkonzept.md; Freigabebericht Modul 02 (B2, B4); Code-Stand `main` b918aad (Add-on `rezeptbuch` 0.5.3). Für Abschnitt 17 zusätzlich: V06-1, V06-2, Sitzungsprüfung (18.11.2026, 10:19), Klärungen (10:27), VC06-a bis VC06-f (10:44), Code-Stand `main` 4c3406c (0.6.0).
Zielversion: Add-on `rezeptbuch` **0.6.x**, Umsetzung in drei Teilen (Abschnitt 12).
Besonderheit: Modul 06 wird **parallel zum Abschluss von Modul 05** begonnen (Entscheidung Michael 17.11.2026). Modul 05 ist noch nicht freigegeben, deshalb ändert Teil C1 nichts an Modul 05 (Abschnitt 12). *(Stand 18.11.2026: Modul 05 freigegeben, 0.6.0 in `main`.)*

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
- **Ergänzung 18.11.2026 (Abschnitt 17):** Kombinieren von Bezugsarten (V06-1), Bezugsart „Faktor × Grundrezept“ (VC06-e), Obergrenze und automatische Aufteilung in mehrere Teige (V06-2, Klärungen 10:27, VC06-d), Ansicht „Zusammenfassung“ (VC06-f), Sitzungsprüfung der Admin-Seiten (VC06-c).

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

Weitere Datenbankänderungen aus der Konzeptergänzung: Migration `0006` (Abschnitt 17.9, Teil C3).

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

Alle Werte gelten **je Teig**; die Anzahl Teige (`dough_count`) vervielfacht nur die Chargen, nicht die Mengen. *(Ab Teil C3 ersetzt durch Abschnitt 17: Die Bezugsangaben ergeben den Gesamtbedarf des Auftrags, der bei Bedarf auf mehrere, auch unterschiedlich große Teige aufgeteilt wird; jeder Teig hat eine eigene Sollgröße.)*

| Bezugsgröße (`basis_type`) | Eingabe | Faktor f |
|---|---|---|
| `total` Gesamtteig | g oder kg | Ziel ÷ G |
| `pieces` Stückzahlen | Anzahl je Stückgewicht des Rezepts | (Σ Anzahl × Stückgewicht) ÷ G |
| `batch_size` Chargengröße | Chargengröße des Rezepts | Gewicht ÷ G bzw. (Stückzahl × Stückgewicht) ÷ G |
| `raw_material` Leitrohstoff **gesamt** | Rohstoff, g, kg oder l (1 l = 1 000 g) | Ziel ÷ R(x) (Summe aller Zeilen inkl. Unterrezepten, K06-1) |
| `raw_material` Leitrohstoff **je Zeile** | Rezeptzeile (Position), g, kg oder l | Ziel ÷ Menge dieser Zeile (K06-1) |
| `flour_total` Mehl gesamt | g oder kg | Ziel ÷ M |
| `factor` Faktor × Grundrezept *(neu, Abschnitt 17.3)* | Faktor, z. B. 1,5 | Faktor (Teig = Faktor × G) |

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
| R06-18 | Angezeigt bei den Bezugsgrößen Gesamtteig, Leitrohstoff, Mehl gesamt und Chargengröße „Gewicht“. Bei Stückzahlen ist die Anzahl schon bekannt. Der Bediener kann danach selbst auf die ganze Stückzahl umstellen; es wird nichts automatisch abgerundet (M06-3). *(Ergänzung für Kombination und Faktor: Abschnitt 17.2, R06-23.)* |

### 4.8 Anzeige von Unterrezepten (M06-6)

In der Rezeptübersicht erscheint ein Unterrezept als **eine Zeile** (z. B. „Vorteig 3 000 g“, farblich abgesetzt) und ist **eingeklappt**. Durch Antippen klappt es auf und zeigt seine Zutaten mit Mengen darunter, auch über weitere Ebenen. Die Schnittstelle liefert dafür den ganzen Baum; das Ein- und Ausklappen macht die Seite (Prüfseite in Modul 06, Stationsseite in Modul 10). Zusätzlich gibt es die Ansicht „Zusammenfassung“ (Abschnitt 17.8).

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

Weitere Prüfungen für Kombinieren, Faktor und Aufteilen: P06-11 bis P06-18 (Abschnitt 17.10).

**Hinweise** (Berechnung läuft, Hinweis wird angezeigt):

| Nr. | Fall |
|---|---|
| H06-1 | Zeilen mit Prüfmarkierung „*“ |
| H06-2 | Archivierter Rohstoff oder archiviertes Unterrezept im Rezept |
| H06-3 | Rohstoff mit Toleranz 0 % (wird mit ±1 g gewogen) |
| H06-4 | Aufrundung erhöht eine Zeile um mehr als 5 % (z. B. sehr kleine Teige mit Salz/Hefe) |
| H06-6 | Leitrohstoff „gesamt“: Summe nach Aufrundung liegt über der eingegebenen Menge (z. B. „Quark: 7 502 g statt 7 500 g“) |
| H06-5 | Rezept ist gesperrt oder archiviert (Prüfseite rechnet trotzdem; die Vorwahl zeigt solche Rezepte ohnehin nicht) |

Weitere Hinweise H06-7 bis H06-10: Abschnitt 17.10.

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

Erweiterung für Aufträge mit mehreren Teigen und für die Zusammenfassung: Abschnitt 17.11.

## 7. Schnittstellen

### 7.1 REST `/api/v1` (Lesen, ohne PIN – die Stationen brauchen das)

| Methode | Pfad | Inhalt |
|---|---|---|
| GET | `/recipes/{id}/basis-options` | Was die Vorwahl anbieten darf: Stückgewichte, Chargengrößen, „Mehl gesamt“ ja/nein mit Mehl im Grundrezept, mögliche Leitrohstoffe (je Rohstoff mit Menge > 0 ein Eintrag „gesamt“ inkl. Unterrezepten und darunter die einzelnen Zeilen des Hauptrezepts, jeweils mit Grundrezept-Menge, K06-1), Grundrezept-Gesamtgewicht |
| POST | `/calculation` | Berechnung nach Abschnitt 4. Eingabe: `recipe_id`, optional `version_no` (Vorgabe: aktuelle Version), `basis_type`, `value`, `input_unit`, `pieces: [{piece_weight_id, count}]`, `batch_size_id`, `raw_material_id`, `item_position` (nur Leitrohstoff je Zeile), `overrides: [{position, amount_g}]`. Antwort: `CalcResult` (Abschnitt 6) |

POST statt GET, weil die Eingabe Listen enthält; die Anfrage ändert nichts. Fehlerantworten wie bisher (`detail`, `field`, `code`): 400 Eingabe ungültig (P06-1 bis P06-10), 404 Rezept/Version nicht gefunden, 503 Datenbank nicht bereit.

Erweiterungen (Kombinieren, Faktor, Obergrenze, Teige, Zusammenfassung): Abschnitt 17.11; die bisherigen Felder bleiben gültig (abwärtskompatibel).

### 7.2 Python-Funktionen für Modul 09

| Funktion | Zweck |
|---|---|
| `calculate(conn, request) -> CalcResult` | dieselbe Rechnung wie die REST-Schnittstelle |
| `validate_basis(conn, recipe_id, basis…) -> None` | Prüfung der Auftragsfelder (B4), wirft Fehler mit Feld |
| `build_batch_items(conn, order_id, version_id) -> list[dict]` | Werte für `batch_item` (target_g, tolerance_g, units_target, rest_target_g, Kopien von Nummer/Name/Gebinde) nur aus der fixierten Version (B2) |
| `tolerance_g(target_g, unit, value) -> int` | Toleranzregel R06-7/R06-8, auch für die Wiegeanzeige |

Neue bzw. erweiterte Funktionen für Teil C3: Abschnitt 17.11.

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
- Erweiterungen (Zusammenfassung, Kombinieren, Faktor, Teige): Abschnitt 17.8 und 17.7.

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

Neu in 0.6.1/0.6.2: Abschnitt 17.13.

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
- Tests zur Konzeptergänzung: Abschnitt 17.13.

## 12. Umsetzung in drei Teilen

| Teil | Inhalt | Version | Ändert Modul 05? |
|---|---|---|---|
| **C1** | `calculation/` komplett, Migration 0005 (B2), `liters_to_grams`, Prüfseite `/admin/berechnung` mit Reiter | 0.6.0 | **nein** (nur ein neuer Reiter-Eintrag in der Reiterleiste, siehe unten) |
| **C2** | Prozentspalten und „Mehl gesamt (mit Unterrezepten)“ in der Admin-Rezeptansicht und der Lese-API (Abschnitt 7.3); **Sitzungsprüfung** beim Öffnen und Reiterwechsel (Abschnitt 17.14, VC06-c); Ansicht **„Zusammenfassung“** (Abschnitt 17.8, Vorschlag K06-10) | 0.6.1 | ja, nach Freigabe Modul 05 und Abstimmung |
| **C3** | Kombinieren (V06-1), Faktor (VC06-e), Obergrenze und Aufteilung in Teige (V06-2, Klärungen 10:27, VC06-d), Migration `0006` (Abschnitt 17.9), Erweiterung von Schnittstelle, `validate_basis`, `build_batch_items` und Prüfseite (VC06-a/b) | 0.6.2 | ja (Haken „aktiv (Obergrenze)“ in der Rezeptbearbeitung), nach Abstimmung |

**Parallelbetrieb mit Modul 05:** Solange Modul 05 nicht freigegeben ist und eventuell noch Korrekturen 0.5.x bekommt, wird Modul 06 auf einem eigenen Zweig **`modul06`** entwickelt (wie `modul05-c2`). `main` bleibt bei Modul 05. Nach der Freigabe von Modul 05 wird `modul06` auf den neuesten Stand gebracht, zusammengeführt (0.6.0), getestet und praktisch geprüft. Der Reiter „Berechnung“ ist der einzige Berührungspunkt mit den Modul-05-Seiten (ein Eintrag in der Reiterleiste von `recipes.html`/`admin.html`). *(Erledigt 18.11.2026.)*

Jeder Teil mit Push, GitHub-Testlauf und Praxisprüfung durch Michael; Freigabe Modul 06 nach **C3** mit Freigabebericht (geändert durch VC06-a/b, 18.11.2026).

## 13. Konzeptfragen – entschieden am 17.11.2026

| Nr. | Frage | Vorschlag |
|---|---|---|
| ~~K06-1~~ | **Entschieden 17.11.2026 (Michael):** Leitrohstoff zur Auswahl **einmal „gesamt“** (Summe inkl. Unterrezepten) **und darunter je Rezeptzeile**. Gerundet wird wie überall **auf**, keine Ausnahme für den Leitrohstoff. Eingearbeitet in 4.2, R06-4, P06-4, H06-6, Abschnitt 3 und 7. | – |
| ~~K06-2~~ | **Entschieden 17.11.2026 (Michael):** wie bereits in M02-2d entschieden – Prozent von der **ganzen Sollmenge**, diese Toleranz gilt für den gewogenen Rest (30 000 g Mehl, 2 % → ±600 g auf 5 000 g Rest). | – |
| ~~K06-3~~ | **Entschieden 17.11.2026 (Michael):** Prüfseite „Berechnung“ wird angelegt (Abschnitt 8). | – |
| ~~K06-4~~ | **Entschieden 17.11.2026 (Michael):** Prozentspalten in der Admin-Rezeptansicht als Teil C2 erst **nach der Freigabe von Modul 05**; Teil C1 auf dem Zweig `modul06`. | – |

Konzeptfragen der Ergänzung (K06-5 bis K06-12): Abschnitt 17.12.

## 14. Auswirkungen auf andere Module

| Modul | Auswirkung |
|---|---|
| 02 | Migration 0005 (Trigger B2, Spalte `production_order.basis_item_position` für K06-1); Befunde B2/B4 damit erledigt. **Teil C3: Migration 0006** (Abschnitt 17.9: Haken Obergrenze, Bezugsarten `factor`/`combined`, Chargengrößen im Auftrag, Obergrenze und Teilungsart am Auftrag, Sollgröße je Teig, Unterrezept-Auftrag je Teig) – Abstimmung vor Umsetzung |
| 03 | Teil C2: Sitzungsprüfung auf der Rohstoffseite (VC06-c) |
| 05 | Teil C2: zusätzliche Felder in der Lese-API und Spalten auf `/admin/rezepte` (abwärtskompatibel, nach Freigabe 05); Reiter „Berechnung“; Sitzungsprüfung auf der Rezeptseite. **Teil C3: Haken „aktiv (Obergrenze)“ bei den Chargengrößen** in der Rezeptbearbeitung, Import/Export/Kopie übernehmen den Haken |
| 09 | nutzt `calculate`, `validate_basis`, `build_batch_items`, `tolerance_g`; legt Unterrezept-Aufträge mit Bezugsgröße „Gesamtteig“ = gerundete Zeilenmenge an (R06-5); prüft die Höchstlast der Waage (M06-7). **Neu:** legt Aufträge mit kombinierten Bezugsangaben und mehreren, auch unterschiedlich großen Teigen an (`plan_doughs`, Abschnitt 17.11), Unterrezept-Aufträge je Teig oder für alle (Abschnitt 17.6) |
| 10 | zeigt die Rezeptübersicht mit eingeklappten Unterrezepten, Prozenten, Stückhinweis; Anzeige Höchstlast (M06-7). **Neu:** Ansicht „Zusammenfassung“; Bedienablauf Abschnitt 17.7 (Kombination, Faktor, Teilungsart, Anzahl Teige, Rückfragen, Obergrenze nur für den Auftrag) |
| 11 | übernimmt die Sollwerte unverändert aus `batch_item`; Chargen eines Auftrags können unterschiedlich groß sein |
| 12 | Sitzungsprüfung beim Öffnen/Reiterwechsel kommt mit Teil C2 (zur Kenntnis) |
| 14 | Referenzrezepte aus Abschnitt 11 dienen auch der Gesamtprüfung |

## 15. Änderungen

| Datum | Änderung |
|---|---|
| 17.11.2026 | Konzept erstellt (Schritt B), Konzeptfragen K06-1 bis K06-4. |
| 17.11.2026 | K06-4 entschieden (wie vorgeschlagen); **Konzept von Michael freigegeben** (Freigabe zum Programmieren). |
| 17.11.2026 | K06-2 (ganze Sollmenge, wie M02-2d) und K06-3 (Prüfseite anlegen) entschieden. |
| 17.11.2026 | K06-1 entschieden: Leitrohstoff „gesamt“ und je Zeile, Aufrunden ohne Ausnahme; neue Spalte `basis_item_position` in Migration 0005, Hinweis H06-6. |
| 17.11.2026 | Teil C1 (0.6.0) umgesetzt auf dem Zweig `modul06`; Präzisierungen in Abschnitt 16. |
| 18.11.2026 | Teil C2 (0.6.1) umgesetzt auf dem Zweig `modul06`; Präzisierungen in Abschnitt 18. |
| 18.11.2026, 14:54 | **„Mehl gesamt“ in ganzen Gramm, kaufmännisch gerundet** (Michael; Ergänzung zur Entscheidung 13:41, Vorschlag „aufrunden“ nicht übernommen). |
| 18.11.2026 | Teil C3 (0.6.2) umgesetzt auf dem Zweig `modul06`; Präzisierungen in Abschnitt 19. |
| 18.11.2026, 12:42 | **Konzeptergänzung Abschnitt 17 von Michael freigegeben** (Freigabe zum Programmieren); weiter mit Teil C2 (0.6.1). |
| 18.11.2026, 11:13 | K06-5 bis K06-12 entschieden (Michael); K06-6 abweichend: aktive Obergrenze im Auftrag nur senkbar. Eingearbeitet in R06-31, P06-17, 17.12; Hinweise „Vorschlag“ entfernt. Freigabe der Ergänzung offen. |
| 18.11.2026, 10:50 | **Konzeptergänzung Abschnitt 17** geschrieben (V06-1, V06-2, Sitzungsprüfung, Klärungen 10:27, VC06-a bis VC06-f); Hinweise in Abschnitt 1, 3, 4.2, 4.7, 4.8, 5–9, 11, 12 (drei Teile, Freigabe nach C3), 13, 14 ergänzt. Konzeptfragen K06-5 bis K06-12 offen, Freigabe durch Michael offen. |

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

## 17. Konzeptergänzung vom 18.11.2026 – Kombinieren, Faktor, Obergrenze, Aufteilung, Zusammenfassung

Status: **geschrieben am 18.11.2026, 10:50; Konzeptfragen K06-5 bis K06-12 am 18.11.2026, 11:13 entschieden (K06-6 abweichend vom Vorschlag) und eingearbeitet; am 18.11.2026, 12:42 von Michael freigegeben (Freigabe zum Programmieren).** Grundlage sind ausschließlich die Entscheidungen V06-1, V06-2 und Sitzungsprüfung (10:19), die Klärungen (10:27) und VC06-a bis VC06-f (10:44), vollständig in docs/modulstatus-06.md. Was das Konzept darüber hinaus festlegen musste, steht als **Konzeptfrage K06-5 bis K06-12** in Abschnitt 17.12 (entschieden 18.11.2026, 11:13).

### 17.1 Begriffe

| Begriff | Bedeutung |
|---|---|
| **Bezugsangabe** | eine Eingabe der Vorwahl: Gesamtteig, Stückzahl je Stückgewicht, Chargengröße × Anzahl, Faktor, Mehl gesamt oder Leitrohstoff |
| **Gesamtbedarf B** | Summe aller Bezugsangaben eines Auftrags in Gramm (ganzer Teig inkl. Vorteig/Unterrezept) |
| **Obergrenze L** | größter erlaubter Teig in Gramm: aktive Chargengröße des Rezepts oder Obergrenze nur für den Auftrag |
| **Teig** | ein getrennt gewogener Teig des Auftrags = eine Charge (`batch`, M02-10); jeder Teig hat seine **Sollgröße T** |
| **Teilungsart** | „voll auffüllen“ oder „gleichmäßig“ (V06-2, VC06-d) |

### 17.2 Bezugsarten kombinieren (V06-1)

| Nr. | Regel |
|---|---|
| R06-19 | **Kombinierbar** sind: Gesamtteig (g/kg), Stückzahlen je Stückgewicht (mehrere), Chargengrößen (mehrere, **dieselbe auch mehrmals**, eingegeben als Anzahl, z. B. 2 × „Großer Teig“) und **Faktor × Grundrezept** (VC06-e). Je Art höchstens ein Gesamtteig und ein Faktor; Stückgewichte und Chargengrößen je einmal mit Anzahl. |
| R06-20 | **Nur allein** wählbar sind „Mehl gesamt“ und Leitrohstoff (V06-1). |
| R06-21 | Jede Angabe wird exakt (Bruch) in Gramm umgerechnet: Gesamtteig = Eingabe; Stückzahl = Anzahl × Stückgewicht; Chargengröße „Gewicht“ = Anzahl × Wert; Chargengröße „Stück“ = Anzahl × Stückzahl × Stückgewicht; Faktor = Faktor × G (G nach Mengenänderungen, 4.1). **B = Summe aller Angaben.** |
| R06-22 | B wird **auf ganze Gramm aufgerundet** (nur beim Faktor kann B einen Bruchteil haben; K06-8). Danach wird wie „Gesamtteig = B“ gerechnet bzw. aufgeteilt (17.4). Eine einzelne Angabe ergibt genau dasselbe Ergebnis wie bisher. |
| R06-23 | **Stückhinweis** (R06-17): angezeigt, sobald die Kombination nicht nur aus Stückzahlen besteht; bei mehreren Teigen je Teig und für den ganzen Auftrag. Bei reinen Stückzahlen entfällt er wie bisher. |

Beispiel (Brötchenteig, G = 10 000 g): Gesamtteig 5 kg + 100 × Stück 65 g + 2 × „Großer Teig“ 12 kg + Faktor 0,5 → B = 5 000 + 6 500 + 24 000 + 5 000 = **40 500 g**.

### 17.3 Bezugsart „Faktor × Grundrezept“ (VC06-e)

| Nr. | Regel |
|---|---|
| R06-24 | Eingabe ist eine Zahl > 0 mit **höchstens zwei Nachkommastellen** (z. B. 1,5 · 0,75 · 2), Komma oder Punkt; gespeichert in **Hundertsteln** (150 = 1,5), wie Prozente in Zehnteln (K2). K06-7. |
| R06-25 | Allein gewählt: Teig = Faktor × G; die Zeilen werden mit genau diesem Faktor gerechnet und wie üblich je Zeile aufgerundet (R06-1). In Kombination: Beitrag Faktor × G zu B (R06-21). |
| R06-26 | Bereich 0,01 bis 100; der Teig darf wie jeder andere höchstens 1 000 kg je Teig ergeben (P06-2). |

### 17.4 Obergrenze (V06-2, Klärungen 10:27)

| Nr. | Regel |
|---|---|
| R06-27 | Die Obergrenze ist **die Chargengröße des Rezepts mit gesetztem Haken „aktiv (Obergrenze)“**. Je Rezept ist **höchstens eine** Chargengröße aktiv (V06-2 (1)). |
| R06-28 | Chargengröße „Gewicht“: L = Wert in Gramm. Chargengröße „Stück“: **L = Stückzahl × Stückgewicht in Gramm** (Klärung 4). |
| R06-29 | Chargengrößen **ohne Haken** sind **keine Obergrenze** und bleiben normal auswählbar (Klärung 3). |
| R06-30 | Die Grenze gilt für den **ganzen Teig inklusive Vorteig/Unterrezept** (V06-2 (2)), also für die Sollgröße T des Hauptteigs. |
| R06-31 | Ist **keine** Chargengröße aktiv (Rezept ohne Chargengröße oder ohne Haken), gibt es keine Obergrenze und keine automatische Aufteilung. Der Bediener **darf dann frei eine Obergrenze nur für diesen Auftrag** eingeben (g/kg); sie wird am Auftrag gespeichert, nicht im Rezept (V06-2 (7), K06-6). **Ist eine Chargengröße aktiv, darf der Bediener die Obergrenze für den Auftrag nur senken** (z. B. kleinerer Kessel), **nicht erhöhen** (K06-6). Gespeichert wird die wirksame Grenze mit Herkunft `order`. |
| R06-32 | Verglichen wird mit der **Sollgröße T** (ganze Gramm). Durch das Aufrunden der Zeilen (R06-3) kann die gewogene Summe eines Teigs wenige Gramm über L liegen; das ist zulässig, ohne Hinweis (K06-12). |
| R06-33 | Wählt der Bediener genau „1 × aktive Chargengröße“, ist B = L: **genau ein Teig in Maximalgröße** (V06-2 (1)). |

### 17.5 Aufteilung in Teige (V06-2, Klärung 1, VC06-d)

| Nr. | Regel |
|---|---|
| R06-34 | **Mindestanzahl** n_min = B ÷ L, **aufgerundet** auf eine ganze Zahl. Ist B ≤ L, gibt es einen Teig und nichts zu teilen. |
| R06-35 | Kombinierte Angaben, Gesamtteig, Stückzahlen, Chargengrößen, Faktor: **erst zusammenzählen, dann automatisch teilen** (V06-2 (3)), sobald B > L. |
| R06-36 | **Anzahl Teige:** Das System schlägt n_min vor; der Bediener darf **mehr** Teige wählen, **nicht weniger** (Klärung 1). Höchstens 50 Teige je Auftrag (P06-16). |
| R06-37 | **Teilungsart wählt immer der Bediener** (V06-2 (5)), auch bei mehr Teigen als nötig (VC06-d). Vorbelegung: „voll auffüllen“. |
| R06-38 | **Voll auffüllen:** Teige 1 bis n−1 bekommen T = L, der letzte T = B − (n−1) × L. Beispiel 32 000 g bei L = 20 000 g → **20 000 + 12 000 g**. |
| R06-39 | **Voll auffüllen mit leerem Teig:** Ergibt „voll auffüllen“ einen Teig mit 0 g oder weniger (nur möglich, wenn der Bediener mehr Teige als n_min wählt), ist diese Kombination **nicht wählbar**: Meldung „Voll auffüllen ergibt nur n_min Teige – für mehr Teige bitte ‚gleichmäßig‘ wählen“ (P06-15). Kein Teig mit 0 g. K06-5. |
| R06-40 | **Kleiner letzter Teig:** Ist bei „voll auffüllen“ der letzte Teig kleiner als **20 % von L**, erscheint Hinweis H06-7 („Letzter Teig nur 500 g – gleichmäßig teilen?“); der Bediener kann trotzdem fortfahren. K06-5. |
| R06-41 | **Gleichmäßig:** alle n Teige gleich groß, T = B ÷ n, **auf ganze Gramm aufgerundet** (V06-2 (6)); die Summe darf dadurch bis zu n−1 g über B liegen. Beispiel 32 000 g, n = 2 → **16 000 + 16 000 g**; n = 3 → 3 × 10 667 g = 32 001 g. Da L eine ganze Zahl ist und n ≥ n_min, ist T nie größer als L. |
| R06-42 | **Jeder Teig wird für sich gerechnet** wie „Gesamtteig = T“ mit allen Regeln aus Abschnitt 4 (Aufrunden je Zeile, Toleranz, Gebinde, Unterrezepte, Prozente, Hinweise). Gleich große Teige haben dieselben Zeilen. |
| R06-43 | Mengenänderungen im Auftrag (`order_item_override`) gelten für **alle** Teige des Auftrags gleich (sie ändern das Grundrezept vor der Rechnung, 4.1). |

Beispiel aus 17.2 (B = 40 500 g, L = 20 000 g): n_min = 3. Voll auffüllen → 20 000 + 20 000 + 500 g (Hinweis H06-7). Gleichmäßig → 3 × 13 500 g.

### 17.6 Vorteig/Unterrezept bei geteilten Teigen (Klärung 2)

| Nr. | Regel |
|---|---|
| R06-44 | Hat der Auftrag **mehr als einen Teig** und das Rezept Unterrezeptzeilen, fragt das System **je Unterrezeptzeile des Hauptrezepts**: „Vorteig je Teig oder einmal für alle?“ (Klärung 2; „je Unterrezeptzeile“ = K06-9). |
| R06-45 | **Je Teig:** Für jeden Teig entsteht ein eigener Unterrezept-Auftrag mit Gesamtteig = gerundete Zeilenmenge dieses Teigs (R06-5). Bei gleich großen Teigen sind sie gleich. |
| R06-46 | **Für alle:** Es entsteht **ein** Unterrezept-Auftrag mit Gesamtteig = **Summe der gerundeten Zeilenmengen aller Teige**. Jeder Hauptteig entnimmt beim Wiegen seine eigene Zeilenmenge (Unterrezeptzeile wird wie bisher abgehakt, R3). Das Unterrezept wird mit dieser Summe einmal gerechnet und aufgerundet (R06-5); es kann dadurch wenige Gramm mehr ergeben. |
| R06-47 | Unterrezepte **innerhalb** eines Unterrezepts folgen dessen Auftrag (keine weitere Rückfrage). |
| R06-48 | Ein Unterrezept-Auftrag „für alle“ wird **nicht automatisch geteilt**. Liegt er über der aktiven Obergrenze des Unterrezepts, erscheint Hinweis H06-9; der Bediener entscheidet (z. B. „je Teig“ wählen). K06-9. |
| R06-49 | Bei nur einem Teig gibt es keine Rückfrage; es bleibt bei einem Unterrezept-Auftrag wie bisher. |

### 17.7 Mehl gesamt und Leitrohstoff mit Obergrenze (V06-2 (8)) und Bedienablauf

**Mehl gesamt und Leitrohstoff** (nur allein, R06-20):

| Nr. | Regel |
|---|---|
| R06-50 | Gerechnet wird wie bisher (4.2): Teiggewicht = f × G. Liegt es über einer Obergrenze (aktiv oder für den Auftrag eingegeben), fragt das System **„Nach Obergrenze teilen? Ja/Nein“**. |
| R06-51 | **Nein:** ein Teig wie bisher, Hinweis H06-8 („Teig liegt über der Obergrenze 20 000 g“). **Ja:** B = Teiggewicht aufgerundet auf ganze Gramm, Aufteilung nach 17.5 (Anzahl, Teilungsart, Rückfrage Vorteig wie dort), jeder Teig als Gesamtteig T gerechnet. |
| R06-52 | Nach dem Teilen ist die eingegebene Mehl- bzw. Leitrohstoff-Menge **die Summe über alle Teige**; durch das Aufrunden je Teig und Zeile kann sie wenige Gramm darüber liegen. Hinweis H06-6 gilt dann für den ganzen Auftrag (auch bei „je Zeile“). |

**Bedienablauf an der Station** (Gestaltung Modul 10, Anlegen Modul 09; hier nur die Reihenfolge, die die Rechnung vorgibt):

1. Rezept wählen → Bezugsangaben eingeben (kombinierbar nach R06-19, oder allein Mehl gesamt/Leitrohstoff).
2. Optional Obergrenze nur für den Auftrag: ohne aktive Chargengröße frei, mit aktiver Chargengröße nur kleiner (R06-31, K06-6).
3. B > L: Anzeige „Bedarf 40,5 kg – Obergrenze 20 kg – mindestens 3 Teige“; bei Mehl gesamt/Leitrohstoff vorher Rückfrage „teilen?“.
4. Anzahl Teige (Vorschlag n_min, nur erhöhbar) und Teilungsart wählen; Anzeige der Teiggrößen.
5. Bei Unterrezepten und mehr als einem Teig: Rückfrage „Vorteig je Teig oder für alle?“.
6. Rezeptübersicht je Teig (Zeilen oder Zusammenfassung), dann Auftrag anlegen.

Die Prüfseite (Abschnitt 8) bekommt dieselben Eingaben (ohne Anlegen) und zeigt die Teige als Reiter „Teig 1 · Teig 2 · …“ mit Ergebnis je Teig.

### 17.8 Ansicht „Zusammenfassung“ (VC06-f)

Umschalter in der Rezeptübersicht: **„Zeilen“** (wie bisher, Unterrezepte eingeklappt) / **„Zusammenfassung“**.

| Nr. | Regel |
|---|---|
| R06-53 | Jeder **Rohstoff erscheint einmal** mit der **Summe über alle Ebenen** (Hauptteig und alle Unterrezepte), z. B. „Wasser gesamt 6 000 g“. Unterrezepte selbst erscheinen nicht als Zeile. |
| R06-54 | Die Menge ist die **Summe der gerundeten Zeilenmengen** aller Ebenen, also genau das, was tatsächlich gewogen wird (passt zu R06-5). Mit Mauszeiger/Antippen der genaue Wert (K06-10). |
| R06-55 | **Anteil** und **Bäckerprozent** je Rohstoff aus dem **Grundrezept** (R06-15), bezogen auf den Hauptteig (wie R06-16); die Mehle ergeben zusammen 100,0 % Bäckerprozent (Rundungsabweichung von 0,1 möglich). |
| R06-56 | **Mischungsverhältnis der Mehle:** bei Rezepten mit Mehl eine Zeile „Mehlmischung“: jede Mehlsorte mit ihrem Anteil am Mehl gesamt in Prozent, eine Nachkommastelle, z. B. „Weizenmehl 550 70,6 % · Roggenmehl 1150 29,4 %“. Bei nur einer Mehlsorte „100 %“. |
| R06-57 | Reihenfolge nach dem **ersten Vorkommen** im Rezeptbaum (Hauptteig von oben, Unterrezept an der Stelle seiner Zeile). Handzugaben (0 g) erscheinen mit „nach Bedarf“. Keine Toleranz- und Gebindespalte (die gehören zum Wiegen je Zeile). |
| R06-58 | Bei mehreren Teigen zeigt die Zusammenfassung wahlweise **einen Teig** oder den **ganzen Auftrag** (Summe aller Teige; bei Unterrezept „für alle“ zählt dessen Auftrag einmal). K06-10. |

Grundlage im Bedienkonzept (Abschnitt Rezeptverwaltung, „Übersicht … wahlweise als Zusammenfassung mit Anteil am Gesamtgewicht und Bäckerprozent“); dort fehlte sie bisher in diesem Konzept.

### 17.9 Datenbank – Migration `0006` (Teil C3, Abstimmung Modul 02/05 vor Umsetzung)

Entschieden K06-11. Vorhandene Aufträge (bisher keine im Betrieb) und Werte bleiben gültig; Sicherungskopie und Rückrollen wie bei 0005.

| Änderung | Inhalt | Grund |
|---|---|---|
| Spalte `recipe_batch_size.is_limit` | INTEGER NN, 0/1, Vorgabe 0; eindeutiger Teilindex „höchstens eine je Rezept mit `is_limit = 1`“ | R06-27 (V06-2 (1)) |
| `production_order.basis_type` erweitert | neue Werte **`factor`** (Faktor allein) und **`combined`** (mehr als eine Bezugsangabe); `basis_value` = B in Gramm (aufgerundet, R06-22) | V06-1, VC06-e |
| Spalten `production_order.total_part_g`, `factor_hundredths` | Gesamtteig-Anteil bzw. Faktor (R06-24), leer erlaubt; nur bei `total`/`combined` bzw. `factor`/`combined` | Angaben speichern, B nachvollziehbar |
| neue Tabelle **`order_batch_size`** | `order_id`, `batch_size_id` (FK, leer erlaubt bei späterem Löschen), Kopien `label`, `kind`, `value`, `piece_weight_g`, dazu `batch_count` (> 0) | mehrere Chargengrößen, dieselbe mehrmals (V06-1), wie `order_piece` |
| `order_piece` | unverändert, auch bei `combined` genutzt | – |
| Spalten `production_order.limit_g`, `limit_source`, `split_mode` | genutzte Obergrenze in Gramm (Kopie), Herkunft `recipe`/`order`, Teilungsart `fill`/`even`; leer = keine Obergrenze/keine Teilung | V06-2 (5), (7) |
| neue Tabelle **`order_dough`** | `order_id`, `dough_index` (≥ 1, eindeutig je Auftrag), `target_g` (> 0); Anzahl Zeilen = `dough_count` | **Sollgröße je Teig** (bisher alle gleich) |
| Spalte `production_order.parent_dough_index` | bei Unterrezept-Aufträgen: Teig des Hauptauftrags; leer = „für alle“ | R06-45/R06-46 (Klärung 2) |

Dieselbe Migration enthält das Preisfeld am Rohstoff aus **VC03-a** (entschieden 18.11.2026, 10:51; Regeln in docs/rohstoffe.md, nicht Teil dieses Konzepts).

Trigger bzw. Prüfregeln: Spalten nur bei passender Bezugsart (wie 0005); `order_dough`-Anzahl = `dough_count` und jedes `target_g` ≤ `limit_g` prüft der Code (`validate_basis`), da Summen über Tabellen (wie Abschnitt 5). In Modul 05 kommen der Haken in der Rezeptbearbeitung sowie Übernahme bei Kopie, Export und Import dazu (Abstimmung).

### 17.10 Plausibilitätsprüfungen und Hinweise (neu)

**Fehler:**

| Nr. | Fall | Meldung (Beispiel) |
|---|---|---|
| P06-11 | „Mehl gesamt“ oder Leitrohstoff zusammen mit anderen Angaben | „Mehl gesamt und Leitrohstoff nur allein möglich“ |
| P06-12 | Faktor ≤ 0, über 100 oder mehr als zwei Nachkommastellen | „Bitte einen Faktor zwischen 0,01 und 100 eingeben“ |
| P06-13 | Anzahl einer Chargengröße keine ganze Zahl > 0 (höchstens 100) | „Bitte eine Anzahl größer als 0 eingeben“ |
| P06-14 | Anzahl Teige kleiner als n_min | „Mindestens 3 Teige nötig (Obergrenze 20 000 g)“ |
| P06-15 | „Voll auffüllen“ ergäbe einen leeren Teig (R06-39) | „Voll auffüllen ergibt nur 2 Teige – für mehr Teige bitte ‚gleichmäßig‘ wählen“ |
| P06-16 | mehr als 50 Teige | „Höchstens 50 Teige je Auftrag“ |
| P06-17 | Auftrags-Obergrenze ≤ 0, über 1 000 kg, keine ganzen Gramm oder **größer als die aktive Chargengröße** (K06-6) | „Obergrenze darf höchstens 20 000 g sein (Chargengröße ‚Großer Teig‘)“ |
| P06-18 | keine Bezugsangabe | „Bitte mindestens eine Angabe machen“ |

P06-2 (höchstens 1 000 kg) gilt **je Teig**; B darf darüber liegen, wenn geteilt wird.

**Hinweise:**

| Nr. | Fall |
|---|---|
| H06-7 | „Voll auffüllen“: letzter Teig kleiner als 20 % der Obergrenze (R06-40) |
| H06-8 | Teig liegt über der Obergrenze (Mehl gesamt/Leitrohstoff mit „Nein“, R06-51) |
| H06-9 | Unterrezept-Auftrag „für alle“ liegt über der Obergrenze des Unterrezepts (R06-48) |
| H06-10 | Gleichmäßig geteilt: Summe der Teige liegt durch Aufrunden über dem Bedarf (z. B. „32 001 g statt 32 000 g“) |

### 17.11 Schnittstellen und Funktionen (Erweiterung, abwärtskompatibel)

**`GET /recipes/{id}/basis-options`** zusätzlich: `limit: {batch_size_id, label, limit_g} | null` (aktive Chargengröße, R06-28), je Chargengröße `is_limit`, `factor_allowed: true`.

**`POST /calculation`** zusätzlich (alle bisherigen Felder bleiben gültig):

| Feld | Inhalt |
|---|---|
| `basis_type` | auch `factor` und `combined` |
| `total_part` | Gesamtteig-Anteil (Wert + `input_unit`) |
| `factor` | Faktor als Text („1,5“) |
| `batch_sizes: [{batch_size_id, count}]` | Chargengrößen mit Anzahl |
| `order_limit` | Obergrenze nur für den Auftrag (g/kg) |
| `split` | `true`/`false` – Antwort auf „teilen?“ (nur Mehl gesamt/Leitrohstoff) |
| `dough_count`, `split_mode` | gewählte Anzahl (Vorgabe n_min) und Teilungsart `fill`/`even` (Vorgabe `fill`) |
| `sub_modes: [{position, mode}]` | je Unterrezeptzeile `per_dough`/`all` (Vorgabe `per_dough`) |

Antwort zusätzlich: `demand: {exact, target_g, parts: [...]}` (B mit Einzelbeiträgen), `split: {limit_g, limit_source, min_count, count, mode, needs_question}`, `doughs: [{dough_index, target_g, result: CalcResult}]`, `order_totals` (Summe nach Rundung, Mehl, Stückhinweis für den ganzen Auftrag), `summary` und `flour_mix` je Teig und für den Auftrag (17.8), `sub_orders: [{position, mode, dough_index | null, target_g}]` (17.6). Bei einem Teig bleiben die bisherigen Felder auf oberster Ebene wie heute gefüllt; `doughs` enthält dann einen Eintrag.

**Python-Funktionen für Modul 09:**

| Funktion | Zweck |
|---|---|
| `plan_doughs(demand_g, limit_g, count, mode) -> list[int]` (`engine.py`) | Sollgrößen der Teige nach R06-34 bis R06-41, ohne Datenbank |
| `calculate(conn, request)` | wie oben, mit Teigen, Zusammenfassung und Unterrezept-Aufträgen |
| `validate_basis(conn, recipe_id, order)` | zusätzlich: P06-11 bis P06-18, `order_batch_size`, `order_dough` (Anzahl, Summe ≥ B, jedes `target_g` ≤ `limit_g`, passt zur Teilungsart), Felder nur bei passender Bezugsart |
| `build_batch_items(conn, order_id, version_id, dough_index)` | Chargenzeilen **je Teig** aus dessen `target_g` (`order_dough`); ohne `dough_index` wie bisher für Aufträge mit einem Teig |
| `sub_order_targets(conn, order_id)` | Gesamtteig je Unterrezept-Auftrag (je Teig oder für alle, R06-45/R06-46) |

### 17.12 Konzeptfragen der Ergänzung – entschieden am 18.11.2026, 11:13 (Michael)

| Nr. | Frage | Entscheidung |
|---|---|---|
| ~~K06-5~~ | Leerer oder sehr kleiner Teig bei „voll auffüllen“ (offen aus VC06-d) | **Wie vorgeschlagen:** Leerer Teig nicht wählbar (P06-15), kein Teig mit 0 g; letzter Teig unter **20 % von L** → nur Hinweis H06-7, Bediener darf fortfahren (R06-39, R06-40) |
| ~~K06-6~~ | Obergrenze nur für den Auftrag bei Rezepten mit Chargengrößen ohne Haken? Darf eine aktive Obergrenze im Auftrag geändert werden? | **Teils abweichend vom Vorschlag:** Ohne aktive Chargengröße (auch bei Chargengrößen ohne Haken) gibt der Bediener frei eine Obergrenze ein. **Mit aktiver Chargengröße darf er sie für den Auftrag senken, nicht erhöhen** (Vorschlag war: nicht änderbar). Eingearbeitet in R06-31, P06-17 |
| ~~K06-7~~ | Genauigkeit des Faktors | **Wie vorgeschlagen:** höchstens zwei Nachkommastellen, 0,01–100, gespeichert in Hundertsteln (R06-24, R06-26) |
| ~~K06-8~~ | Gesamtbedarf mit Bruchteil (nur beim Faktor) | **Wie vorgeschlagen:** B auf ganze Gramm aufrunden, bevor gerechnet oder geteilt wird (R06-22) |
| ~~K06-9~~ | Rückfrage Vorteig; Unterrezept „für alle“ über eigener Obergrenze | **Wie vorgeschlagen:** Rückfrage **je Unterrezeptzeile** des Hauptrezepts; „für alle“ wird nicht automatisch geteilt, nur Hinweis H06-9 (R06-44, R06-48) |
| ~~K06-10~~ | Zusammenfassung: Mengen, Umfang, Teil | **Wie vorgeschlagen:** Summe der **gerundeten** Mengen; je Teig oder ganzer Auftrag; Umsetzung **in Teil C2 (0.6.1)** (R06-54, R06-58) |
| ~~K06-11~~ | Datenmodell (Migration 0006) | **Wie vorgeschlagen:** Abschnitt 17.9 (Haken `is_limit`, `basis_type` `factor`/`combined`, `order_batch_size`, `order_dough`, Obergrenze/Teilungsart am Auftrag, `parent_dough_index`); gilt als Abstimmung mit Modul 02/05 |
| ~~K06-12~~ | Obergrenze und Aufrunden der Zeilen | **Wie vorgeschlagen:** Grenze gilt für die Sollgröße T; gewogene Summe darf wenige Gramm darüber liegen, ohne Hinweis (R06-32) |

### 17.13 Umsetzung, Dateien und Tests

**Teil C2 (0.6.1):** Prozentspalten und „Mehl gesamt (mit Unterrezepten)“ (Abschnitt 7.3), Sitzungsprüfung (17.14), Zusammenfassung und Mehlmischung (17.8, K06-10) in `engine.py`, Lese-API und Prüfseite.

**Teil C3 (0.6.2):** `engine.py` (Kombinieren, Faktor, `plan_doughs`, Unterrezept-Aufträge), `models.py` (neue Felder, P06-11 bis P06-18), `service.py`, `router.py`, `calc.html` (Kombination, Faktor, Teige als Reiter), Migration `0006_order_doughs.sql`, Haken in der Rezeptbearbeitung (Modul 05, nach Abstimmung).

**Neue Tests:** `test_calc_combine.py` (R06-19 bis R06-26: jede Kombination, dieselbe Chargengröße mehrmals, Faktor mit Bruchteil, einzelne Angabe = bisheriges Ergebnis), `test_calc_split.py` (R06-27 bis R06-52: n_min, nur erhöhbar, voll auffüllen inkl. leerer/kleiner Teig, gleichmäßig aufgerundet, Stück-Chargengröße als Grenze, ohne Haken keine Grenze, Auftrags-Obergrenze, Mehl gesamt/Leitrohstoff mit Ja/Nein, Vorteig je Teig/für alle, Beispiele 32 000 g und 40 500 g von Hand nachgerechnet), `test_calc_summary.py` (R06-53 bis R06-58: Summe über Ebenen, Mehle 100 %, Mehlmischung), `test_migration_0006.py` (Haken höchstens einmal je Rezept, Prüfregeln, Migration mit Daten), API-Tests für die neuen Felder; bestehende Tests laufen unverändert weiter.

### 17.14 Sitzungsprüfung der Admin-Seiten (beauftragt 10:19, Einordnung VC06-c)

- Beim **Öffnen** der Seiten Rohstoffe, Rezepte und Berechnung und bei jedem **Reiterwechsel** fragt die Seite den Server, ob die Sitzung noch gilt; ist sie abgelaufen, kommt **sofort die PIN-Eingabe** und danach die Rückkehr zur gewählten Seite (`?next=…`, wie Präzisierung 16.12).
- Dafür eine schlanke Schnittstelle **`GET /api/v1/admin/session`** (204 = gültig, 401 = abgelaufen), die die Sitzung nicht verlängert; sie ersetzt den Behelf über `recipes/next-number` (16.12).
- Ungespeicherte Änderungen: Die bestehende Rückfrage beim Reiterwechsel (Prüfpunkt C1 (l)) kommt **vor** der Sitzungsprüfung; bei abgelaufener Sitzung gehen ungespeicherte Eingaben verloren wie bisher bei ändernden Aktionen (der Server lehnt ohnehin mit 401 ab).
- Auf dem iPhone keine Browser-Dialoge (`alert`/`confirm`), wie aus der Praxisprüfung Modul 03 bekannt.
- Die serverseitige Prüfung jeder ändernden Anfrage bleibt unverändert (Modul 03/12).

## 18. Präzisierungen der Umsetzung (Teil C2, 0.6.1)

Festlegungen, die das Konzept offen ließ. Keine Abweichung von einer Entscheidung.

1. **Prozente in der Lese-API** (Abschnitt 7.3) werden mit dem Rechenkern aus dem Rezeptbaum der jeweiligen Version gerechnet (`recipes/service.py`, `_add_percentages`), auch für alte Versionen (`/recipes/{id}/versions/{n}`). Lässt sich der Baum nicht rechnen (z. B. leeres Unterrezept), sind `flour_total_g`, `share_tenths` und `baker_tenths` leer (`null`); die Rezeptansicht funktioniert weiter. Ohne Mehl ist `baker_tenths` leer, `flour_total_g` = 0.
2. **Rezeptseite:** Die Spalten „Anteil %“ und „Bäcker %“ zeigen den **gespeicherten Stand**. Eine Zeile, deren Rohstoff/Unterrezept oder Menge im Editor geändert wurde, und neue Zeilen zeigen „–“ bis zum Speichern (keine Rechnung in der Seite, Master-Prompt Regel 5). Handzugaben (0 g) zeigen 0,0.
3. **Zusammenfassung:** im Ergebnis von `calculate` als `summary` (Rohstoff, `target_g` = Summe der gerundeten Mengen, `exact_g`, `hand_only`, `has_hand`, `share_tenths`, `baker_tenths`) und `flour_mix` (`flour_tenths` je Mehlsorte). Ein Rohstoff, der gewogen **und** als Handzugabe vorkommt, erscheint einmal mit seiner Menge und dem Zusatz „+ nach Bedarf“. Die Ansicht „ganzer Auftrag“ (R06-58) folgt mit den Teigen in Teil C3; bis dahin gilt die Zusammenfassung für den einen Teig.
4. **Sitzungsprüfung:** `GET /api/v1/admin/session` antwortet 204 oder 401 und verlängert die Sitzung nicht (`AdminSessions.is_valid`). Geprüft wird beim Öffnen der Seiten Rohstoffe, Rezepte und Berechnung, bei jedem Reiter (auch Rezepte/Gruppen/Import-Export innerhalb der Rezeptseite) und bei der Rückkehr per „Zurück“ (Seite aus dem Zwischenspeicher). Bei Ablauf geht es nach der Anmeldung **zum gewählten Reiter** weiter. Ohne Verbindung wird nicht abgemeldet. Die Prüfseite nutzt dafür nicht mehr `admin/recipes/next-number` (16.12).
5. **Tests:** neu `test_calc_summary.py` (9); ergänzt `test_recipe_service.py` (Prozente, alte Version), `test_auth.py` (Prüfung ohne Verlängerung), `test_calc_api.py` (Zusammenfassung, Prozente in beiden Lese-Schnittstellen, Sitzungsprüfung; nur GitHub-Testlauf). Oberflächen lokal mit Ersatzserver in Chrome geprüft (Rechner und iPhone-Größe): Prozentspalten, Zusammenfassung, Ablauf beim Öffnen und beim Reiterwechsel mit Rückkehr zum gewählten Reiter.

## 19. Präzisierungen der Umsetzung (Teil C3, 0.6.2)

Festlegungen, die das Konzept offen ließ. Keine Abweichung von einer Entscheidung.

1. **Migration 0006 baut `production_order` neu auf**, weil SQLite die CHECK-Regel von `basis_type` nicht ändern kann (Vorgehen der SQLite-Dokumentation: neue Tabelle, Daten kopieren, alte löschen, umbenennen; Indizes und alle Trigger aus 0001/0005 unverändert neu). Dafür kennt `migrate.py` den Schalter **`-- migration: foreign_keys=off`** in der ersten Zeile einer Migration: Fremdschlüssel aus, Prüfung `PRAGMA foreign_key_check` weiter vor dem COMMIT, danach wieder ein (auch nach einem Fehler). Beim Umbenennen gilt kurz `legacy_alter_table`, damit Trigger anderer Tabellen (z. B. `batch`), die `production_order` beim Namen nennen, nicht stören. Vorhandene Werte bleiben unverändert (Test mit Aufträgen, Stückzahlen, Mengenänderungen, Charge und Chargenzeile).
2. **Prüfregeln in der Datenbank** (zusätzlich zum Code): `total_part_g` nur bei `total`/`combined`, `factor_hundredths` nur bei `factor`/`combined` und Pflicht bei `factor`, `limit_g` und `limit_source` nur gemeinsam, `split_mode` nur mit Obergrenze, `parent_dough_index` nur bei Unterrezept-Aufträgen; `order_batch_size` mit Kopie des Stückgewichts nur bei Art „Stück“; `order_dough.target_g` 1 bis 1 000 000 g. `order_batch_size` und `order_dough` sind bei abgeschlossenen Aufträgen gesperrt (Trigger wie `order_piece`). Höchstens ein Haken `is_limit` je Rezept über einen eindeutigen Teilindex.
3. **Faktor allein** (R06-25): Die Zeilen werden mit genau dem Faktor gerechnet; `basis_value` ist der Bedarf B = Faktor × G auf ganze Gramm aufgerundet (R06-22). Wird geteilt, rechnet jeder Teig wie „Gesamtteig = T“. **Kombiniert mit einem Teig:** wie „Gesamtteig = B“.
4. **Antwort von `POST /calculation`:** Auf oberster Ebene stehen die Werte von **Teig 1** (bei einem Teig genau wie bisher); `basis.type` ist die gewählte Bezugsart, bei „kombiniert“ mit `target_g` = B. Jeder Teig steht mit seinem Ergebnis unter `doughs`. `warnings` enthält die Hinweise des Auftrags und aller Teige ohne Doppelungen. Hinweis-Codes: `last_dough_small` (H06-7), `over_limit` (H06-8), `sub_over_limit` (H06-9), `even_rounded` (H06-10), `basis_rounded` (H06-6, nach dem Teilen für den ganzen Auftrag). Zusammenfassung des ganzen Auftrags: `order_summary`/`order_flour_mix`; ein Unterrezept „für alle“ wird dafür einmal mit der Summe gerechnet.
5. **Mehrere Teige nur mit Obergrenze** (Fehler `dough_count_without_limit`). Mit Obergrenze darf der Bediener auch dann mehr Teige wählen, wenn der Bedarf darunter liegt (VC06-d).
6. **Mehl gesamt/Leitrohstoff:** ohne Antwort (`split` leer) und bei „Nein“ ein Teig mit Hinweis H06-8, dazu `split.needs_question`. Mehr Teige gibt es dort nur mit „Ja“ (Fehler `split_required`).
7. **Vorteig-Rückfrage:** ohne Antwort gilt „je Teig“. Bei einem Teig gibt es genau einen Unterrezept-Auftrag (`mode` „all“, `dough_index` leer = wie bisher).
8. **Anfrage:** `total_part` und `order_limit` als Zahl (Gramm) oder `{value, input_unit}` mit g/kg; Stückzahlen und Chargengrößen mit Anzahl 0 werden in der Kombination weggelassen; mehrere Angaben ohne `basis_type` „combined“ sind ein Fehler (`combine_required`), mit „Mehl gesamt“/Leitrohstoff `sole_basis` (P06-11).
9. **`validate_basis`** gibt das Rechenergebnis zurück (Teige, Unterrezept-Aufträge für Modul 09). Neu geprüft: Felder passend zur Bezugsart, Bedarf = `basis_value` bei „kombiniert“/„Faktor“, `limit_source` „recipe“ nur mit der aktiven Chargengröße, mit aktiver Chargengröße ist eine Obergrenze Pflicht (`limit_missing`), Anzahl und Sollgrößen der Teige (`doughs`) gleich der Aufteilung. `basis_value` höchstens 1 000 kg bei Gesamtteig, Mehl gesamt und Leitrohstoff (Eingabe, P06-2); bei Stückzahlen, Faktor und kombiniert darf der Bedarf darüber liegen, wenn geteilt wird.
10. **`build_batch_items(conn, order_id, version_id, dough_index)`:** Bei mehreren Teigen ist `dough_index` Pflicht und die Sollgröße kommt aus `order_dough`; bei einem Teig gilt die Bezugsart des Auftrags (Faktor genau). **`sub_order_targets(conn, order_id, sub_modes)`** bekommt die Antwort „je Teig/für alle“ als Eingabe (sie steht danach in `parent_dough_index` der angelegten Unterrezept-Aufträge) und rechnet mit der fixierten Version, sonst der aktuellen.
11. **Haken in der Rezeptbearbeitung:** Fehlt `is_limit` in der Anfrage (ältere Seite oder Importdatei ohne Spalte), bleibt der bisherige Haken. Beim Speichern werden zuerst alle Haken entfernt, dann gesetzt (Umsetzen in einem Schritt). Importvorlage/Export: Spalte **„Obergrenze (ja = aktiv)“** im Blatt Chargengrößen, gültig sind ja/x/1/aktiv, leer/nein; die Musterdatei hat die Spalte und eine Erklärzeile. Kopie übernimmt den Haken.
12. **„Mehl gesamt“ in ganzen Gramm, kaufmännisch** (entschieden 18.11.2026, 13:41 und 14:54): Die „576,742 g“ standen auf der Prüfseite (Rezeptinfo und „Mehl gesamt“); dort jetzt ganze Gramm, der genaue Wert erscheint beim Darüberfahren. Die Rezeptseite zeigte schon seit 0.6.1 `flour_total_g` (kaufmännisch gerundet). Bäckerprozente rechnen weiter mit dem genauen Wert.
13. **Prüfseite:** Bezugsarten „Faktor“ und „Kombiniert“ (Anzahl je Chargengröße), Feld „Obergrenze nur für diesen Auftrag“ mit Anzeige der aktiven Chargengröße, Rückfrage „teilen?“, Anzahl Teige und Teilungsart, Auswahl „je Teig / einmal für alle“ je Unterrezept, Teige als Reiter, Zusammenfassung „dieser Teig / ganzer Auftrag“, Liste der Unterrezept-Aufträge. Ein Fehler bei Anzahl/Teilungsart (z. B. weniger Teige als nötig) lässt das letzte Ergebnis stehen und setzt die Auswahl zurück.
14. **Tests:** neu `test_migration_0006.py` (16), `test_calc_split.py` (31, ohne Datenbank, Beispiele 32 000 g und 40 500 g von Hand nachgerechnet), `test_calc_combine.py` (46, mit Datenbank), `test_raw_material_price.py` (62, VC03-a); ergänzt `test_db_migrate.py` (Schalter), `test_export_recipes.py` (Haken im Export/Re-Import), `test_raw_material_service.py` (Kopfzeile), API-Tests `test_calc_api.py`, `test_raw_material_api.py` (nur GitHub). Prüfseite und Rezeptseite lokal mit Ersatzserver in Chrome geprüft (Rechner und iPhone-Größe).

