# Konzept Produktionsplaner mit Verkaufsartikeln (Modul 10, Teil von C2)

Stand: 21.11.2026, 07:20 (Claude) – **Konzept am 21.11.2026, 00:21 von Michael freigegeben („gebe ich frei“).** K10-P5 bis K10-P14 entschieden (Sprachchat bis 16:22), K10-P15 bis K10-P22 (Textchat 20.11.2026, 23:11–23:31), K10-P21 präzisiert und K10-P23 (21.11.2026, 00:03/00:07). **Teil P-A umgesetzt als 0.10.16 (Zweig `planer-pa`, Abschnitt 16); H1 und H2 am 07:08 nachgezogen (Michael).**
Grundlage: docs/modulstatus-10.md Abschnitt 6 (M10-18 bis M10-23, K10-P1 bis K10-P23), docs/berechnung.md 17 (Bedarf, Obergrenze, Teige, `plan_doughs`, Bezugsart „kombiniert“), docs/datenmodell.md 4.2/4.3, docs/bestand.md (Bestand am Rohstoff).

## 1. Zweck

Wer plant (an der Station oder im Admin), trägt pro Tag ein, was verkauft werden soll (Artikel aus der Kasse, in Stück / halben / ganzen) und **in welchem Auftrag** (1, 2, 3 …) der Artikel mitproduziert wird. **„Jetzt planen“** zerlegt alle Artikel über ihre Stückliste in Rezepte und Rohstoffe, **zählt gleiche Rezepte je Tag und Auftragsnummer zusammen**, zeigt je Rezept die Aufträge mit Summe, lässt Aufträge **per Klick zusammenfassen** (auch über Tage), schlägt die Teige nach der aktiven Chargengröße vor und legt nach Wahl die **Aufträge in der Produktionsliste** an. Ein **Zuschlag** (Abwiegeverlust) kann je Auftrag eingeplant werden; die Obergrenze gilt einschließlich Zuschlag, ein Überschuss wird als **Übertrag** zum eigenen Auftrag. Rohstoffe aus Stücklisten erscheinen als Bedarfsliste; bestandsgeführte werden am Produktionstag abgebucht. Für Halbfabrikate gibt es keinen Bestand – was im Kühlhaus steht, entscheidet Michael (M10-20).

## 2. Begriffe

| Begriff | Bedeutung |
|---|---|
| **Artikel** | Verkaufsartikel aus der Vectron (Nummer = Kassennummer, K10-P1) |
| **Ganzes** | ein ganzer Kuchen / eine ganze Torte; „Stück je Ganzes“ am Artikel (K10-P2) |
| **Stückliste** | Zeilen eines Artikels: **Rezept** oder **Rohstoff** mit Menge; gilt für **1 Stück** bzw. bei „Stück je Ganzes“ für **1 Ganzes** |
| **Auftragsnummer** | 1, 2, 3 … je Planzeile: in welchem Durchgang der Artikel mitproduziert wird (K10-P15). Nicht „Charge“ – Charge = ein Teig mit Chargennummer (M11-1) |
| **Teil** | Bedarf eines Rezepts für **einen Tag und eine Auftragsnummer** |
| **Auftrag** | ein Teil oder mehrere zusammengefasste Teile → ein `production_order`, den die Automatik nach der Obergrenze in Teige (Chargen) aufteilt |
| **Rang** | Platz eines Auftrags in der Reihenfolge eines Rezepts und Produktionstags (Auftrag 1 vor 2, K10-P18); ein Übertrag schiebt die folgenden Aufträge um einen Rang nach hinten (K10-P23) |
| **Übertrag** | der Teil eines Auftrags, der durch den Zuschlag über die Obergrenze käme; wird ein eigener Auftrag direkt dahinter (K10-P23) |
| **Plan** | Eingaben eines Tages (Artikel × Menge × Auftragsnummer) |
| **Planlauf** | ein „Jetzt planen“ über einen oder mehrere Tage, mit Vorschau und angelegten Aufträgen |

## 3. Datenmodell (Migration 0010 für P-A und P-B, Abschnitt 16 H1)

**`sales_article`** – Verkaufsartikel

| Spalte | Typ | Regeln | Bedeutung |
|---|---|---|---|
| id | INTEGER | PK | |
| register_no | INTEGER | NN, U | Vectron-Nummer |
| name | TEXT | NN | Name aus der Kasse (beim Import aktualisiert) |
| register_group | INTEGER | | Warengruppe (WG) aus der Kasse |
| pieces_per_whole | INTEGER | > 0 oder leer | „Stück je Ganzes“ (K10-P2), Vorgabe WG 12 = 12, WG 13 = 14 |
| plan_enabled | INTEGER | NN, 0/1, Vorgabe 1 | 0 = „nicht planen“ (K10-P3) |
| in_register | INTEGER | NN, 0/1, Vorgabe 1 | 0 = „nicht mehr in der Kasse“ (nie gelöscht, K10-P1) |
| last_order_no | INTEGER | NN, ≥ 1, Vorgabe 1 | zuletzt eingestellte Auftragsnummer (K10-P15) |
| note | TEXT | | freie Bemerkung |
| created_at, updated_at | TEXT | NN | |

**`sales_article_line`** – Stückliste

| Spalte | Typ | Regeln | Bedeutung |
|---|---|---|---|
| id | INTEGER | PK | |
| article_id | INTEGER | NN, FK → sales_article | |
| position | INTEGER | NN, U mit article_id | Reihenfolge |
| kind | TEXT | NN, `recipe` / `raw` | Zeilenart (M10-19; keine Artikel aus Artikeln) |
| recipe_id | INTEGER | FK → recipe, Pflicht bei `recipe` | Rezept (nicht Version; beim Wiegen gilt die aktuelle Version) |
| piece_weight_id | INTEGER | FK → recipe_piece_weight, nur bei `recipe` | wahlweise Stückgewicht statt Gramm (K10-P6) |
| raw_material_id | INTEGER | FK → raw_material, Pflicht bei `raw` | Rohstoff |
| amount_g | INTEGER | > 0 | Menge in Gramm je Stück/Ganzes (Standard) |
| amount_pieces | INTEGER | > 0 | wahlweise Stück (nur `raw`, M10-19) |

Prüfregel: genau eine Mengenangabe – `amount_g`, **oder** `piece_weight_id` (Rezept), **oder** `amount_pieces` (Rohstoff). Stückgewicht muss zum Rezept gehören.

**Neue Felder am Rezept** (nicht an der Version, Planungseigenschaften; Pflege in der Rezeptbearbeitung, Export/Import mit je einer Spalte am Ende – Abstimmung Modul 05 über dieses Konzept):
- `recipe.preproduce` – INTEGER NN 0/1, Vorgabe 0: „darf vorproduziert werden“. Wirkung **nur** Schild „vorproduzierbar“ in der Vorschau und Startwert **Aufrunden** (K10-P17); zusammengefasst wird nie automatisch.
- `recipe.weigh_surcharge_tenths` – INTEGER ≥ 0 oder leer: **Abwiegezuschlag** in Zehntelprozent (12 = 1,2 %), Vorgabe für die Plus-Taste (K10-P21).

**`sales_plan`** – Plan eines Tages: `id`, `plan_date` (NN, U), `note`, `updated_at`.

**`sales_plan_line`** – `plan_id` (NN, FK), `article_id` (NN, FK), `order_no` (NN, ≥ 1), `pieces`, `halves`, `wholes` (je ≥ 0, mindestens eine > 0), U (plan_id, article_id, order_no). Derselbe Artikel darf am selben Tag in mehreren Aufträgen stehen.

**`plan_run`** – Planlauf: `id`, `created_at`, `dates` (Text, Liste der Tage), `status` `preview`/`done`, `mode` `replace`/`delta` (K10-P10, leer beim ersten Lauf), `choices` (Text/JSON: Zusammenfassungen, Wahl, Zuschläge, Überträge, Produktionstag je Auftrag – damit die Vorschau beim Zurückkommen gleich bleibt).
**`plan_run_order`** – `run_id`, `order_id` (FK → production_order).

**`order_article_source`** – woraus ein Planer-Auftrag besteht (Ausklappen in der Vorschau, Knopf „Artikel“ an der Station, K10-P20/K10-P22): `id`, `order_id` (NN, FK → production_order), `article_id` (FK, leer erlaubt), Kopien `article_name`, `register_no`, `plan_date`, `order_no`, `quantity_text` (z. B. „20 Stück + 2 ganze“), `amount_g` (Anteil am Bedarf). Bei einem Übertrag zeigt die Liste die Artikel des Ursprungsauftrags mit Vermerk „Übertrag aus Auftrag x“.

**Zuschlag am Auftrag (nur zur Anzeige):** `production_order.surcharge_tenths` bzw. `production_order.surcharge_g` (je Teig), leer = kein Zuschlag. Der Zuschlag steckt bereits in der Teigmenge (Abschnitt 9) – **keine Änderung an `validate_basis`/`build_batch_items` in Modul 06/09**; die Station zeigt nur „+1,2 % Abwiegezuschlag“ an. Dazu `production_order.carryover_of_order_id` (FK, leer): Übertrag aus diesem Auftrag (K10-P23).

**`plan_stock_booking`** – Abbuchung bestandsgeführter Rohstoffe eines Produktionstags (K10-P12): `id`, `production_date` (NN), `raw_material_id` (NN, FK), `amount_g` (NN, > 0), `stock_movement_id` (FK), `booked_at`, `reversed_at`. Buchung in `stock_movement` mit neuen Buchungsarten **„Planer“** (Abgang) / **„Planer zurück“** (Zugang) – Abstimmung Modul 03.

**Einstellung** `planner_in_preselection` (0/1, Vorgabe 1) in `setting`: Planer in der Vorwahl der Stationen anzeigen (K10-P5).

Stücklisten und Pläne werden in `change_log` protokolliert wie Rezepte.

## 4. Import der Vectron-Artikelliste (K10-P1)

1. Datei `.xlsx` (Export der Vectron, Aufbau wie `test.xlsx`, geprüft 20.11.2026, 14:18); Spalten **über die Überschrift**: „Nummer“, „Name“, „Warengruppe“. Übrige Spalten ignoriert (K10-P4).
2. Übersprungen: Zeilen ohne Nummer oder Namen, Zwischenüberschriften (Name beginnt mit „#“), Warengruppe 0.
3. Filter: **Vorgabe WG 1–14**; im Probelauf alle gefundenen Warengruppen mit Anzahl als Haken, zuwählbar.
4. **Probelauf**: „neu / Name geändert / unverändert / nicht mehr in der Kasse“ mit Anzahl; erst „Übernehmen“ schreibt.
5. Abgleich über `register_no`: neu → angelegt (mit `pieces_per_whole`-Vorgabe nach WG), Name geändert → übernommen, fehlend → `in_register = 0` (nie gelöscht); kommt er wieder, `in_register = 1`.
6. Doppelte Nummern in der Datei → Fehler, nichts übernommen. Gleiche Namen mit verschiedenen Nummern erlaubt, Hinweis im Probelauf.
7. Ort: Reiter **Import/Export** (seit R1 gemeinsam für Rezepte und Rohstoffe), Bereich „Verkaufsartikel“. **Export** der Artikel mit Stücklisten als `.xlsx`; **Import von Stücklisten später** (K10-P14). Erste Befüllung von Hand oder mit Claude aus einer Liste.

## 5. Artikelpflege (Admin, PIN)

- Nur im **Admin-Bereich mit PIN** (K10-P5): Liste mit Suche (Nummer/Name), Filter Warengruppe, „ohne Stückliste“, „nicht planen“, „nicht mehr in der Kasse“.
- Artikelseite: Name/Nummer/WG (nur lesen), „Stück je Ganzes“, „nicht planen“, Bemerkung, **Stückliste** (Rezept- oder Rohstoffsuche, Menge in g / Stückgewicht / Stück), darunter die **Summe in Gramm** je Stück bzw. Ganzes.
- **„Stückliste kopieren von …“**; Sammelaktionen „nicht planen“, „Stück je Ganzes“.
- Hinweis an der Zeile bei archiviertem Rezept/Rohstoff; der Artikel ist dann erst nach Korrektur planbar (R10-P8).
- Unterrezepte werden nicht aufgelöst (K10-P7): Wer eine Füllung über mehrere Artikel zusammenfassen will, trägt sie als **eigene Stücklistenzeile** ein (Kirschstreusel = Hefeteig 1 200 g + Kirschfüllung 1 500 g + Streusel 600 g).

## 6. Eingabe im Planer

**Zwei Zugänge (K10-P5):** an der Station über die **Vorwahl, ohne PIN** (Taste „Planer“, ausblendbar über den Admin-Schalter „Planer in der Vorwahl anzeigen“) und im **Admin-Bereich mit PIN** (eigener Reiter „Planer“, immer sichtbar).

**Ablauf:**
- Tag wählen (Vorgabe morgen). Liste aller planbaren Artikel (`plan_enabled = 1`, mit Stückliste), gruppiert nach Warengruppe, Suche.
- Je Artikel **Stück**; bei `pieces_per_whole` zusätzlich **halbe** und **ganze**; ohne zusätzlich **halbe** (Zopf, Kranz, K10-P2).
- Je Zeile **Auftragsnummer** (Tippfeld „Auftrag 1“, Tippen zählt hoch, Zahlenfeld für eine bestimmte Nummer). **Vorbelegt mit der zuletzt eingestellten Nummer des Artikels** (`last_order_no`, K10-P15); wird sie geändert, merkt sich der Artikel die neue.
- Derselbe Artikel kann mit „+ weiterer Auftrag“ ein zweites Mal mit anderer Auftragsnummer eingetragen werden.
- Speichern je Tag als `sales_plan`. **Öffnen und Nachtragen ändert keine Aufträge** – erst „Jetzt planen“ → „Aufträge anlegen“ (Abschnitt 9).
- **„Plan übernehmen von …“** (K10-P11): Vorgabe gleicher Wochentag der Vorwoche; Liste aller Artikel dieses Tages mit Mengen und Auftragsnummern, **alle vorgehakt, einzeln abwählbar, Mengen in der Liste änderbar**; „Übernehmen“ schreibt die gehakten Zeilen (vorhandene Zeilen desselben Artikels und derselben Auftragsnummer nach Rückfrage überschrieben).
- Artikel ohne Stückliste: grau, „Stückliste fehlt“, nicht eingebbar.

## 7. Rechenweg „Jetzt planen“

Es werden ein oder mehrere Tage mit Plan gewählt.

| Nr. | Regel |
|---|---|
| R10-P1 | **Menge je Planzeile:** mit `pieces_per_whole` = n: S = Stück + halbe × n/2 + ganze × n; **Anzahl Ganze = S ÷ n aufgerundet**; Stückliste × Anzahl Ganze. Ohne: Anzahl = Stück + halbe × 0,5. (Ungerades n: „halb“ = n/2 aufgerundet.) |
| R10-P2 | **Stücklistenzeile Rezept:** Gramm = Anzahl × `amount_g` bzw. × Stückgewicht; Zeilen mit Stückgewicht merken sich die Stückzahl je Stückgewicht (Stückhinweis „x Stück à y g“, K10-P6). |
| R10-P3 | **Teile bilden:** zusammenzählen **je Rezept, Tag und Auftragsnummer** über alle Artikel (K10-P15). Bruchteile erst in der Summe auf ganze Gramm aufrunden. |
| R10-P4 | **Zusammenfassen nur per Klick** (K10-P16): Teile eines Rezepts anhaken → „Ausgewählte zusammenfassen“ – auch über mehrere Tage und auch mit Überträgen. Nichts ist vorgehakt (K10-P17). „Trennen“ macht es rückgängig. **Produktionstag** eines zusammengefassten Auftrags = frühester Tag seiner Teile, änderbar (K10-P9). |
| R10-P5 | **Unterrezepte** in den Rezepten werden nicht aufgelöst (K10-P7). |
| R10-P6 | **Vorschlag Teige je Auftrag:** mit aktiver Chargengröße L (Haken „aktiv (Obergrenze)“, M10-21): Bedarf B, n = B ÷ L aufgerundet. Ohne aktive Chargengröße: ein Teig mit B (über 1 000 kg Fehler wie P06-2). |
| R10-P7 | **Wahl je Auftrag** (K10-P8/K10-P19) über **einen Tippknopf mit Wechselpfeil** `⇄`: jeder Tipp schaltet **Genau → Aufrunden → Abrunden → Streichen → Genau**. **Genau** = B (+ Zuschlag) gleichmäßig auf n Teige (`even`) · **Aufrunden** = n × L, volle Teige · **Abrunden** = (n − 1) × L, Rest aus Vorrat (bei n = 1 wie Streichen) · **Streichen** = kein Auftrag. **Von Hand:** Tipp auf die Grammzahl öffnet das Zahlenfeld; danach zeigt der Knopf „Von Hand“, der nächste Tipp springt auf Genau. Ohne aktive Chargengröße wechselt der Knopf nur Genau ↔ Streichen. **Startwert Genau, bei vorproduzierbaren Rezepten Aufrunden** (K10-P17). Der Knopf zeigt das Ergebnis mit an, z. B. `⇄ Genau · 2 × 3 947 g (+1,2 %)`. |
| R10-P8 | **Fehler, die das Anlegen sperren:** archiviertes Rezept/Rohstoff in einer Stückliste, Rezept gesperrt oder ohne Version, Bedarf 0. Angezeigt mit Sprung zum Artikel (nur im Admin). |
| R10-P9 | **Rohstoffzeilen:** Summe je Rohstoff und Produktionstag in Gramm; `amount_pieces` über das Stück-/Gebindegewicht des Rohstoffs umgerechnet (fehlt es: nur Stückzahl, kein Abbuchen). Abbuchen: Abschnitt 10. |
| R10-P10 | **Zuschlag** (K10-P21): Plus-Taste `+` je Auftrag, Eingabe **in % oder g**, vorbelegt mit dem Abwiegezuschlag des Rezepts (änderbar, leer = 0). Jeder Teig bekommt seinen Zuschlag (%: anteilig, g: je Teig in voller Höhe); die **Obergrenze gilt einschließlich Zuschlag** (Michael 00:03). Bei **Genau/Von Hand** wird B mit Zuschlag auf die n Teige verteilt; bei **Aufrunden/Abrunden** sind die Teige voll, der Zuschlag ist darin enthalten (Hinweis „Zuschlag im Aufrunden/Abrunden enthalten“). |
| R10-P11 | **Übertrag** (K10-P23): Passt B mit Zuschlag bei Genau/Von Hand nicht mehr in die n Teige (B + Zuschlag > n × L), bleibt der Auftrag bei **n vollen Teigen (n × L)**, und der **Rest wird ein eigener Auftrag „Übertrag“** direkt dahinter. Alle späteren Aufträge **desselben Rezepts am selben Produktionstag rücken einen Rang nach hinten** (aus Auftrag 2 wird Rang 3 usw.); die Auftragsnummern der Artikel im Plan bleiben unverändert. Hinweis in der Vorschau: „Durch den Zuschlag entsteht ein Übertrag von x g – Auftrag y rückt nach hinten“. Der Übertrag hat einen eigenen Tippknopf (z. B. Streichen, wenn noch Vorrat da ist) und lässt sich mit dem folgenden Auftrag **zusammenfassen** (R10-P4). |

**Beispiel (Zahlen ausgedacht):** Freitag: Croissant in Auftrag 1, Kirschstreusel (20 Stück + 2 ganze, n = 12 → 4 Kuchen) und 60 Kirsch-Nusstaschen (je 30 g Füllung) in Auftrag 2. Stückliste je Kuchen: Hefeteig 1 200 g, Kirschfüllung 1 500 g, Streusel 600 g. **Kirschfüllung Fr · Auftrag 2 = 4 × 1 500 + 60 × 30 = 7 800 g**; aktive Chargengröße 5 000 g → n = 2. Knopf: Genau 2 × 3 900 g · Aufrunden 2 × 5 000 g · Abrunden 1 × 5 000 g (2 800 g aus Vorrat) · Streichen. Mit Zuschlag 1,2 % bei Genau: 7 894 g → 2 × 3 947 g (passt). **Übertrag:** Hefeteig Fr · Auftrag 1 = 9 950 g, Zuschlag 1,2 % → 10 070 g > 2 × 5 000 g → Auftrag 1 = 2 × 5 000 g, **Übertrag 70 g** als eigener Auftrag direkt dahinter, der bisherige Hefeteig-Auftrag 2 rückt auf Rang 3; Übertrag und Auftrag 2 lassen sich zusammenfassen (oder den Übertrag streichen).

## 8. Vorschau

Je Produktionstag, je Rezept ein Block:

```
Kirschfüllung                    🏷 vorproduzierbar
 ☐ ▸ Fr · Auftrag 2   7 800 g   ⇄ Aufrunden · 2 × 5 000 g   +
 ☐ ▸ Sa · Auftrag 1   5 400 g   ⇄ Aufrunden · 2 × 5 000 g   +
     Summe           13 200 g
     [ Ausgewählte zusammenfassen ]

Hefeteig
 ☐ ▸ Fr · Auftrag 1   9 950 g   ⇄ Genau · 2 × 5 000 g (+1,2 %)   +
 ☐ ▸ Fr · Übertrag      70 g   ⇄ Genau · 1 × 70 g               ⚠ Übertrag
 ☐ ▸ Fr · Auftrag 2   4 800 g   ⇄ Genau · 1 × 4 858 g (+1,2 %)   +
     Summe           14 820 g
```

- **Summe** je Rezept immer sichtbar (K10-P20).
- **Ausklappen** (▸) je Auftrag zeigt, **aus welchen Artikeln** er besteht (Artikel, Menge, Anteil in g); bei zusammengefassten Aufträgen zusätzlich Tag und Auftragsnummer jedes Teils; beim Übertrag die Artikel des Ursprungsauftrags (K10-P20, K10-P23).
- Schild **„vorproduzierbar“** bei Rezepten mit `preproduce` (K10-P17).
- Gibt es für Tag/Rezept/Auftragsnummer schon Aufträge aus früheren Läufen: „schon angelegt: x g (offen / in Arbeit / fertig)“.
- Reihenfolge nach Rang: Auftrag 1 vor Auftrag 2; ein zusammengefasster Auftrag steht an der Stelle seines frühesten Teils; ein Übertrag direkt hinter seinem Ursprung (K10-P18, K10-P23).
- Darunter **Rohstoffbedarf** mit Bestand und orangem Hinweis „Bestand reicht nicht“ (docs/bestand.md).
- Planlauf als `plan_run` (`preview`) gespeichert; Wahl, Zusammenfassungen, Zuschläge und Überträge bleiben beim Zurückkommen erhalten.

## 9. Aufträge anlegen

„Aufträge anlegen“ erzeugt je Auftrag (nicht gestrichen) einen `production_order`:

- `planned_date` = Produktionstag; `list_position` am Ende der Produktionsliste des Tages, **in der Reihenfolge der Ränge** (K10-P18/K10-P23), danach in der Produktionsliste änderbar. Kennzeichen „Planer“, beim Übertrag zusätzlich „Übertrag“.
- **Bezugsart:** nur Stückgewichte → `pieces` (`order_piece`); gemischt → `combined` (`order_piece` + `total_part_g`); nur Gramm → `total`. Bei „Aufrunden“/„Von Hand“ und bei einem **Zuschlag** wird die Differenz als `total_part_g` ergänzt (`combined`). Bei „Abrunden“ ohne Stückgewichte `total` = (n − 1) × L (docs/berechnung.md 17).
- Obergrenze: `limit_source = recipe`, Teilungsart `even` bei Genau/Von Hand, `fill` bei Aufrunden/Abrunden; `dough_count` und `order_dough` aus `plan_doughs`. **Der Zuschlag steckt in der Teigmenge**, die Obergrenze wird von `validate_basis` unverändert geprüft – **keine Änderung an Modul 06/09** (Michael 00:03).
- `surcharge_tenths`/`surcharge_g` und `carryover_of_order_id` nur zur Anzeige.
- Herkunft je Auftrag in `order_article_source` (Artikel, Tag, Auftragsnummer, Menge, Anteil).
- Geprüft wird jeder Auftrag mit `validate_basis`; ein Fehler bricht **alle** Anlagen des Laufs ab (eine Transaktion).
- `plan_run_order` vermerkt die angelegten Aufträge, `plan_run.status = done`.

**Erneut planen (K10-P10):** Gibt es schon Aufträge aus früheren Läufen (gleiches Rezept, Tag, Auftragsnummer), fragt der Planer beim Anlegen:
- **„Ersetzen“** – offene Aufträge aus früheren Läufen werden gelöscht und neu angelegt; gestartete/fertige bleiben und werden vom neuen Bedarf abgezogen.
- **„Nur Unterschied dazu“** – alles bleibt stehen; nur der **Mehrbedarf** wird als zusätzlicher Auftrag angelegt. Weniger Bedarf löscht nichts, nur Hinweis „weniger als bereits angelegt (−x g)“.
- „Zurück“ (nichts angelegt).

## 10. Rohstoffe abbuchen (K10-P12)

- **Bestandsgeführte** Rohstoffe aus Stücklisten werden **am Produktionstag** abgebucht, nicht beim Anlegen.
- Taste **„Rohstoffe für heute abbuchen“** im Planer (Station und Admin) mit Bestätigungsfenster (Rohstoff / Menge / Bestand danach); einmal je Tag und Rohstoff (`plan_stock_booking`, Buchungsart „Planer“); erneutes Drücken bucht nur den seitdem dazugekommenen Unterschied.
- Nicht bestandsgeführte Rohstoffe nur in der Bedarfsliste.
- **Ändern nach dem Abbuchen**: Rückfrage **„Zurückbuchen? Ja / Nein“** (Buchungsart „Planer zurück“).
- Rezeptzutaten weiterhin **nur beim Wiegen** abgezogen (VC03-b).

## 11. Chargen-Taste an der Station (K10-P22, erweitert M10-11)

Die Taste „Chargen“ zeigt die heutigen Chargen der Station; jede Charge hat **zwei getrennte Knöpfe**:
- **„Zutaten“** klappt die Chargenzeilen auf: Zutat, **Soll / Ist**, Abweichung, manuell quittiert, weggelassen.
- **„Artikel“** klappt auf, aus welchen Artikeln der Auftrag stammt (`order_article_source`). Die Artikel hängen am **Auftrag**, nicht am einzelnen Teig: Wurde ein Auftrag in mehrere Teige geteilt, zeigen alle Chargen dieselbe Liste mit dem Hinweis **„Auftrag in n Teigen“**. Aufträge ohne Planer: Knopf grau.
- Gehört zu Modul 10 (Station); die volle Chargensuche/-ansicht im Admin bleibt Modul 11 (dort dieselben Angaben).

## 12. Ort und Oberfläche

- **Station:** Taste „Planer“ in der Vorwahl (ausblendbar), Tablet-Bedienung (große Felder, Tippknöpfe, Zahlenfeld).
- **Admin (PIN):** Reiter **„Planer“** mit Unterreitern **Planen** und **Artikel**, immer sichtbar, handytauglich; gestaltet wie R1.
- Ergebnis in der **Produktionsliste** an den Stationen (Modul 10 C2).
- Keine Browser-Dialoge; Rückfragefenster auf Tastenhöhe im Admin (M10-17), mittig an der Station.

## 13. API (Entwurf; P-A umgesetzt wie in Abschnitt 16)

| Methode | Pfad | PIN | Zweck |
|---|---|---|---|
| GET | `/api/v1/articles…` | nein | Artikel und Stückliste lesen |
| POST/PUT/DELETE | `/api/v1/articles…` | ja | Artikel und Stückliste pflegen |
| POST | `/api/v1/articles/import` (`dry_run`) | ja | Vectron-Import mit Probelauf |
| GET/PUT | `/api/v1/plans/{date}` | nein | Plan eines Tages (mit Auftragsnummern) |
| POST | `/api/v1/plans/copy` | nein | Plan übernehmen von … |
| POST | `/api/v1/plan-runs` | nein | „Jetzt planen“: Vorschau rechnen (`dates`) |
| PUT | `/api/v1/plan-runs/{id}` | nein | Wahl, Zusammenfassungen, Zuschläge, Produktionstag speichern |
| POST | `/api/v1/plan-runs/{id}/commit` (`mode` replace/delta) | nein | Aufträge anlegen |
| POST | `/api/v1/plans/{date}/stock-booking` | nein | Rohstoffe abbuchen / zurückbuchen |
| GET | `/api/v1/orders/{id}/articles` | nein | Artikel eines Auftrags (Chargen-Taste) |
| GET/PUT | `/api/v1/settings/planner` | ja (Schreiben) | Schalter „Planer in der Vorwahl“ |

Hinweis für Modul 12: Planen, Anlegen und Abbuchen bewusst **ohne PIN** (wie „Zugang buchen“, M03-13). Rechenkern `plan_demand(conn, dates, choices)` ohne Oberfläche (testbar), nutzt `plan_doughs` und `validate_basis`.

## 14. Teile, Tests

**Teile (K10-P13):** **P-A** Artikel, Import, Stückliste, Export, Felder `recipe.preproduce` und `recipe.weigh_surcharge_tenths`, Admin-Reiter „Planer“ mit „Artikel“ (Migration) · **P-B** Plan-Eingabe mit Auftragsnummern (Station und Admin), „Plan übernehmen“, „Jetzt planen“, Vorschau (Summe, Ausklappen, Zusammenfassen, Tippknopf, Zuschlag, Übertrag), Aufträge anlegen (Ersetzen/Unterschied, `order_article_source`), Rohstoffe abbuchen, Schalter, Chargen-Taste mit „Zutaten“/„Artikel“. Jeweils eigener Zweig, Versionsnummer nach der Versionsregel. Die Taste „Planer“ in der Vorwahl kommt mit dem restlichen C2-Teil (Vorwahl); bis dahin erreichbar über den Admin-Reiter und eine eigene Stationsseite.

Tests: Import (Filter, Überschriften, Abgleich, doppelte Nummer), Prüfregeln Stückliste, R10-P1 (ganz/halb/Stück, ungerades n), Teile je Rezept/Tag/Auftragsnummer, Zusammenfassen/Trennen über Tage, Aufträge und Überträge, letzte Auftragsnummer am Artikel, Tippknopf-Reihenfolge mit/ohne aktive Chargengröße und Von Hand, Startwert bei `preproduce`, Zuschlag % und g (Obergrenze einschließlich Zuschlag, Genau verteilt, Aufrunden/Abrunden enthalten), Übertrag (Rang-Verschiebung, Zusammenfassen mit dem folgenden Auftrag, Streichen), Bezugsart pieces/combined/total, Transaktion bei Fehler, Ersetzen/Nur Unterschied, Plan übernehmen, Abbuchen/Zurückbuchen, Artikel je Auftrag bei geteilten Teigen, Beispiel aus Abschnitt 7 von Hand nachgerechnet.

## 15. Konzeptfragen – entschieden

| Nr. | Frage | Entscheidung |
|---|---|---|
| K10-P5 | Wo wird geplant? | **Geändert (Sprachchat):** an der Station über die Vorwahl ohne PIN; Admin-Schalter blendet ihn dort aus; eigener Admin-Reiter „Planer“, immer da. Artikel/Stücklisten nur mit PIN. |
| K10-P6 | Rezeptzeile mit Stückgewicht | Wie vorgeschlagen. |
| K10-P7 | Unterrezepte zusammenfassen? | Wie vorgeschlagen: nein, nur über eigene Stücklistenzeilen. |
| K10-P8 | Wahl je Rezept | Wie vorgeschlagen; **„Auffüllen“ umbenannt in „Aufrunden“** (20.11., 23:31), Bedienung über Tippknopf (K10-P19). |
| K10-P9 | Produktionstag bei „zusammen“ | Wie vorgeschlagen: frühester Tag der Teile, änderbar – gilt für per Klick zusammengefasste Aufträge (K10-P16). |
| K10-P10 | Erneut planen | **Geändert:** Wahl „Ersetzen“ / „Nur Unterschied dazu“. |
| K10-P11 | Plan übernehmen | **Ergänzt:** alle vorgehakt, abwählbar, Mengen änderbar. |
| K10-P12 | Rohstoffzeilen | **Geändert:** bestandsgeführte am Produktionstag abbuchen, Rückfrage „Zurückbuchen?“. |
| K10-P13 | Teile | Wie vorgeschlagen: P-A, P-B nach Freigabe. |
| K10-P14 | Stücklisten per Datei | Wie vorgeschlagen: Export jetzt, Import später. |
| K10-P15 | Auftragsnummer | **Michael 20.11., 23:11/23:14:** je Planzeile Auftrag 1, 2, 3 …; jeder Artikel **behält die zuletzt eingestellte Nummer**; gezählt je Rezept, Tag und Auftragsnummer. |
| K10-P16 | Zusammenfassen | **Michael 23:14:** **immer nur per Klick** („besser einmal zu viel geklickt als einmal geärgert“), auch über Tage. |
| K10-P17 | Haken „darf vorproduziert werden“ | **Michael 23:22/23:31 (Vorschlag A):** nur Schild „vorproduzierbar“ und Startwert Aufrunden; **ändert M10-22**. |
| K10-P18 | Reihenfolge | **Wie vorgeschlagen:** Auftrag 1 vor 2; zusammengefasster Auftrag an der Stelle des frühesten Teils. |
| K10-P19 | Wahl je Auftrag, Bedienung | **Michael 23:14–23:26:** Wahl **je Auftrag**; **ein Tippknopf mit Wechselpfeil** (Genau → Aufrunden → Abrunden → Streichen), Von Hand über die Grammzahl, Ergebnis im Knopf. |
| K10-P20 | Vorschau | **Michael 23:14/23:16:** Summe je Rezept immer; Auftrag ausklappbar mit den Artikeln. |
| K10-P21 | Zuschlag | **Michael 23:28/23:31, präzisiert 21.11., 00:03:** Plus-Taste je Auftrag, **g oder %**, jeder Teig bekommt seinen Zuschlag; **Vorgabe am Rezept optional**, im Planer schon eingetragen und änderbar. **Die Obergrenze gilt einschließlich Zuschlag** („über max darf es nicht gehen“); bei Aufrunden/Abrunden ist der Zuschlag in den vollen Teigen enthalten. Keine Änderung an Modul 06/09 nötig. |
| K10-P22 | Chargen-Taste an der Station | **Michael 23:16/23:19/23:31:** jede Charge mit getrennten Knöpfen **„Zutaten“** (Soll/Ist) und **„Artikel“**; bei geteilten Teigen dieselbe Artikelliste mit Hinweis „Auftrag in n Teigen“. |
| K10-P23 | Übertrag durch Zuschlag | **Michael 21.11., 00:03/00:07:** Würde der Zuschlag die Obergrenze überschreiten, entsteht ein **eigener Auftrag (Übertrag) direkt dahinter**; ein bereits vorhandener Auftrag 2 rückt auf Rang 3; mit **Hinweis**; der Benutzer kann Übertrag und folgenden Auftrag **zusammenfassen**. |

## 16. Umsetzung Teil P-A (0.10.16, 21.11.2026, 00:40)

Zweig `planer-pa` von `main` (abd664b), Commit cd0f581, Testlauf 44838127498 grün; lokal 1 029 Tests bestanden (API-Tests nur im GitHub-Lauf). Übernahme in `main` erst nach Freigabe Michael.

**Umfang:** Migration `0010_sales_articles.sql` (`sales_article`, `sales_article_line`, `recipe.preproduce`, `recipe.weigh_surcharge_tenths`); `app/articles/` (Dienst, Vectron-Import, Export, Schnittstelle); Seite `/admin/planer` (`planner.html`) mit Unterreitern Planen (Platzhalter) und Artikel; Reiter „Planer“ in allen Admin-Seiten; im Reiter Import/Export der Rezeptseite Bereiche „Verkaufsartikel importieren/exportieren“; Kasten „Planung“ in der Rezeptbearbeitung (`PUT /api/v1/admin/recipes/{id}/planning`, keine neue Version).

**Schnittstelle (umgesetzt):** ohne PIN `GET /api/v1/articles` (`q`, `group`, `status` active/missing/all, `without_lines`, `not_planned`), `GET /api/v1/articles/groups`, `GET /api/v1/articles/{id}`; mit PIN `POST /api/v1/admin/articles/import?mode=check|run&groups=1,2,…`, `GET /api/v1/admin/articles/export.xlsx`, `POST /api/v1/admin/articles/bulk` (`plan_disable`, `plan_enable`, `pieces_per_whole`), `PATCH /api/v1/admin/articles/{id}`, `PUT /api/v1/admin/articles/{id}/lines`, `POST /api/v1/admin/articles/{id}/copy-lines`.

**Hinweise Claude:**
- **H1 – entschieden 21.11.2026, 07:08 (Michael: „h1 und 2 ziehen wir jetzt noch nach“): eine Migration wie in Abschnitt 3.** Migration 0010 enthält jetzt auch `sales_plan`, `sales_plan_line`, `plan_run`, `plan_run_order`, `order_article_source` (zusätzlich Spalte `carryover` = Artikel des Ursprungsauftrags), `production_order.surcharge_tenths`/`surcharge_g`/`carryover_of_order_id`, `plan_stock_booking` und die Buchungsarten `planner` („Planer“) / `planner_return` („Planer zurück“) in `stock_movement` (Tabelle dafür neu aufgebaut, Inhalt unverändert, Test mit Aktualisierung von Stand 9). Einstellung `planner_in_preselection`: ohne Eintrag gilt 1. Werden beim Rechenkern (P-B) noch Spalten gebraucht, kommen sie mit der nächsten freien Nummer.
- **H2 – entschieden 07:08 (Michael), umgesetzt:** Rezept-Export, Vorlagen-Import und Mustervorlage mit den Spalten „Darf vorproduziert werden (ja/nein)“ und „Abwiegezuschlag % (z. B. 1,2; leer = keiner)“ am Ende des Blatts „Rezepte“. Leer oder Spalte fehlt = unverändert (neues Rezept: nein/kein Zuschlag); falsche Werte sind Fehler im Probelauf; eine Änderung erscheint als Hinweis, ohne neue Version.
- H3: Pfade weichen vom Entwurf (Abschnitt 13) ab: Pflege unter `/api/v1/admin/articles…` (wie die übrigen Admin-Schnittstellen), Import mit `mode=check|run` statt `dry_run` (wie der Rezeptimport).
- H4: Ein Stückgewicht, das in einer Stückliste steht, lässt sich in der Rezeptbearbeitung nicht löschen (Fehler `piece_weight_in_articles`).
- H5: Archivierte Rezepte/Rohstoffe dürfen in einer Stückliste stehen bleiben (Hinweis ⚠), aber nicht neu eingetragen werden.
- H6: Rohstoffzeile „Stück“ rechnet über die Gebindegröße des Rohstoffs; fehlt sie, zeigt die Summe „unvollständig“.
- H7: Die Oberfläche ist nur per Skriptprüfung und Seitentest geprüft, **nicht im Browser**.

**Prüfpunkte für Michael (Praxisprüfung P-A):**
(a) Reiter „Planer“ in Rohstoffe, Rezepte, Berechnung, Waagen, Ablauf; PIN-Abfrage bei abgelaufener Sitzung;
(b) Import/Export → Vectron-Artikelliste wählen → Probelauf: Zahlen, Warengruppen-Haken (1–14 vorgewählt), gleiche Namen, nicht mehr in der Kasse;
(c) Haken ändern → erneut Probelauf → Importieren; Kuchen WG 12 = 12, Torten WG 13 = 14 Stück je Ganzes;
(d) Planer → Artikel: Suche, Warengruppe, Status, „ohne Stückliste“, „nicht planen“;
(e) Sammelaktionen „nicht planen“, „wieder planen“, „Stück je Ganzes“ setzen/leeren;
(f) Artikel öffnen: Stück je Ganzes, planen, Bemerkung speichern;
(g) Stückliste: Rezept mit Gramm, Rezept mit Stückgewicht, Rohstoff mit Gramm und mit Stück; ↑↓ und ✕; Summe; speichern; Rückfrage beim Verlassen ohne Speichern;
(h) „Kopieren von Artikel-Nr.“;
(i) Rezept → Kasten „Planung“: Haken und „1,2“ speichern, falsche Werte (21, 1,25) werden abgelehnt;
(j) Stückgewicht löschen, das in einer Stückliste steht → Fehlermeldung; Export Verkaufsartikel öffnen (Blätter Artikel, Stückliste);
(k) Rezepte exportieren: am Ende des Blatts „Rezepte“ die Spalten „Darf vorproduziert werden“ und „Abwiegezuschlag %“; Wert ändern, Probelauf zeigt Hinweis „Planung … geändert“, Import übernimmt ohne neue Version; „vielleicht“ bzw. „1,25“ werden abgelehnt;
(l) Bestand → Verlauf: Filter „Art“ hat „Planer“ und „Planer zurück“; alte Buchungen nach dem Einspielen unverändert da.
