# Strichcode, Inventur und Wareneingang – gemeinsames Konzept (Schritt B)

Status: **Konzept erstellt am 21.11.2026, 23:45** (Auftrag Michael 23:31: „Loslegen ohne weitere Tests“). **K03-51 bis K03-62 am 22.11.2026 im Sprachchat entschieden (eingetragen 07:55), dazu neu M03-25 Lagerorte und M03-26 Hilfs- und Betriebsstoffe.** **H-A bis H-F am 22.11. (Sprachchat, eingetragen 08:05) entschieden; Widerspruchsprüfung Abschnitt 14c; Abläufe und Vorschläge Abschnitt 14d.** **F-1, F-2, O-1 bis O-7 am 22.11. entschieden; Konzept freigegeben von Michael 22.11.2026, 08:09.** Teil S1 umgesetzt in 0.10.21 (Abschnitt 16), Teil I1 in 0.10.35 (Abschnitt 17).
Betrifft: Modul 03 (Bestand, Rohstoffverwaltung), Modul 02 (Migrationen), Modul 10 (Startseite, Touch-Grundsätze), Modul 12 (PIN-Regeln zur Kenntnis).
Grundlage, entschieden: M03-24 (Strichcode per Kamera, Schnellwahl; Scan-Modi 21:08 „Alle 5“, 1 = 1 Gebinde; 23:31 Gebinde beim ersten Scan abfragen und speichern), VC03-e (Wunsch Inventur mit Inventurwert, 13:20), `docs/wareneingang.md` (freigegeben 13:30, Teile W1/W2), VC03-b/VC03-d (Bestand, Schnellerfassung), M03-13 (Zugang ohne PIN, Inventur mit PIN), M11-2/M11-3 (keine Namen, keine Rohstoff-Lose), Kameratest 0.10.17–0.10.20.

## 1. Ziel und Umfang

Ein **Scanner** in der App (iPhone-App, Tablet), der einen Strichcode einem Rohstoff zuordnet und je nach **Modus** bucht oder anzeigt. Derselbe Scanner dient der **Inventur** (zählen) und dem **Wareneingang** (abhaken).

**Enthalten:** Scan-Seite mit sieben Modi; Code ↔ Rohstoff (einmal zuordnen); Gebinde am Rohstoff; Abgang von Hand (neu); Lagerorte (M03-25); Hilfs- und Betriebsstoffe (M03-26); Inventur mit Stichtag, Zählliste, Abschluss und Inventurwert-Export; Scan-Abhaken im Liefertag (W1); Migrationen; Tests.
**Nicht enthalten:** Etiketten drucken; Rohstoff-Lose, Charge und MHD – auch nicht anzeigen (K03-62); DataMatrix/PDF417/Aztec (Absturz am Tablet, 0.10.20); eigenes https-Zertifikat (Michael bei Bedarf).

## 2. Die Modi (M03-24, „Alle 5“)

| Modus | Ein Scan bewirkt | Bucht |
|---|---|---|
| **Info** | Karte: Name, Bestand, Meldewert, Preis, Gebinde, Lagerorte, Allergene (Pass), letzte 5 Buchungen | nichts |
| **+1 Zugang (Dauerscan)** | +1 Gebinde, Zähler „+3 Sack Weizenmehl 550 = 75 kg“, neuer Bestand | Zugang |
| **−1 Abgang (Dauerscan)** | −1 Gebinde mit **einem Grund je Serie** (Bruch, Verderb, Eigenverbrauch, Handelsware, Sonstiges, K03-54) | Abgang (neu) |
| **Bestand setzen** | Ziffernblock „Bestand Weizenmehl: _ Sack / kg“ | Inventur (Einzelbuchung) |
| **Inventur zählen** | +1 Gebinde in der Zählliste der offenen Inventur (Abschnitt 5) | erst beim Abschluss |
| **Wareneingang abhaken** | +1 Gebinde an der passenden Zeile der Lieferung (Abschnitt 6) | beim „Buchen“ der Lieferung |
| **Code zuordnen** | Code an einen Rohstoff hängen oder umhängen | nichts |

- **Unbekannter Code** in jedem Modus: Scan pausiert, Fenster „Code … unbekannt“ → Rohstoff suchen (wie Schnellerfassung) → **Gebinde abfragen** („Ein Gebinde dieses Rohstoffs ist: [25] kg, Bezeichnung [Sack]“, am Rohstoff gespeichert) → speichern → weiter im Modus.
- **Bekannter Code ohne Gebinde** in +1/−1/Zählen/Abhaken: Gebinde wird einmal abgefragt (Michael 23:31).
- **„1“ ist immer ein Gebinde**, umgerechnet in Gramm über die Gebindegröße am Rohstoff (21:08, K03-51). Bei Hilfs- und Betriebsstoffen ist „1“ eine Verpackungseinheit (M03-26).
- **Beim Öffnen wählt man immer zuerst den Modus**, erst dann startet die Kamera (K03-55). Der Modus bleibt bis zum Wechsel stehen.

## 3. Scannen im Betrieb

```
 ┌───────────────────────────────┐   ┌──────────── Modus (bleibt stehen) ───────────┐
 │        Kamerabild             │   │ [Info] [+1 Zugang] [−1 Abgang] [Bestand]     │
 │     ┌───────────────┐         │   │ [Inventur zählen] [Wareneingang] [Zuordnen]  │
 │     │  Zielrahmen   │         │   └──────────────────────────────────────────────┘
 │     └───────────────┘         │   Letzter Scan (groß):  Weizenmehl 550
 └───────────────────────────────┘                          +3 Sack = 75 kg · Bestand 312 kg
                                    [ ↶ Rückgängig ]   (ganz breit, letzter Scan)
```

- **Erkennung:** Tablet mit dem Leser des Geräts (BarcodeDetector), iPhone mit ZXing **aus dem Add-on** (nicht mehr aus dem Netz). Nur EAN-13/-8, UPC-A/-E, Code 128, Code 39, ITF, QR (0.10.20).
- **Dauerscan ohne Doppelzählung:** Derselbe Code zählt erst wieder, wenn er **mindestens 0,8 s aus dem Bild** war (Sack weg, nächster Sack hin). Zehn gleiche Säcke hintereinander gehen damit ohne Warten. Ersetzt die starre 3-s-Sperre aus 0.10.20.
- **Signal bei Treffer:** grünes Aufleuchten, kurzer Ton und Vibration (K03-56). Vibration geht nur am Tablet (Android), am iPhone im Browser nicht. Keine Kameraleuchte.
- **Rückgängig:** nimmt den letzten Scan zurück (Gegenbuchung, Vermerk „Rückgängig“), mehrfach, nur Scans dieses Geräts der letzten 10 Minuten.
- **GS1-Codes** (z. B. Code 128 mit (01) GTIN plus Zusatzfeldern): Schlüssel ist nur die **GTIN**; Charge und MHD werden **weggelassen**, weder angezeigt noch gespeichert (K03-62). EAN-13, UPC und GTIN-14 werden auf eine gemeinsame 14-stellige Form gebracht, damit derselbe Artikel nicht zweimal angelegt wird.
- **https:** Live-Kamera nur über https (Nabu Casa). Im eigenen WLAN über http bleibt am iPhone der Foto-Weg; das Tablet braucht die https-Adresse (Kameratest 18:41/19:15).
- **Erreichbar:** Kachel „Scannen“ auf der Startseite (Tablet, neben Stationen und Wareneingang), Rohstoffverwaltung → Bestand → „Scannen“, Inventur → „Mit Kamera zählen“, Liefertag → „Mit Kamera abhaken“.

## 4. Gebinde am Rohstoff (Michael 23:31, K03-51 entschieden 22.11.)

- Das Scan-Gebinde ist das **vorhandene Feld „Gebindegröße“ am Rohstoff** (`unit_size_g`/`unit_label`). Ist es leer, fragt der erste Scan einmal Größe und Bezeichnung ab („25 kg, Sack“) und speichert sie dort.
- **Gewollte Folge (Michael):** Das Feld steuert auch das Verwiegen. Bei 30 kg Mehl sagt die Station „1 × Sack zugeben, Rest 5 kg wiegen“ (M02-2c).
- Je Rohstoff gibt es **ein** Gebinde. Wird dasselbe Mehl in 10-kg- und 25-kg-Säcken gekauft, sind das zwei Rohstoffe (passt zu M04-7, ein Rohstoff = ein Artikel).
- Codes hängen am Rohstoff (Tabelle `raw_material_barcode`, ohne eigenes Gebinde); mehrere Codes je Rohstoff sind möglich.

## 4a. Lagerorte (M03-25, Michael 22.11.)

- **Liste der Lagerorte** (z. B. Mehllager, Kühlhaus, Backstube), gepflegt im Unterreiter Bestand. Jeder Ort kann einen **eigenen Code** bekommen (z. B. ausgedruckter QR-Code am Regal).
- Am Rohstoff: **Lagerort 1** und optional **Lagerort 2**, jeweils mit optionaler eigener Beschriftung (z. B. „Anbruch“). Auswahl aus der Liste oder per Scan des Ort-Codes.
- **Der Bestand bleibt eine Summe je Rohstoff**, nicht nach Ort aufgeteilt. Der Lagerort dient zum Finden und zum Ordnen der Inventur.
- Rohstoffliste und Zählliste lassen sich nach Lagerort filtern und sortieren.

## 4b. Hilfs- und Betriebsstoffe (M03-26, Michael 22.11.)

- Eigene **Art „Hilfs- und Betriebsstoff“** im selben Stamm (neben Mehl und Standard), z. B. Verpackung, Reinigungsmittel – Vorlage: die 77 sonstigen Artikel aus der Kundeninventur (M04-28).
- **Gezählt in Verpackungseinheiten**, die Bezeichnung legt man am Artikel fest („Karton“, „Kanister“). Keine Gramm. Ein Scan = eine Verpackungseinheit.
- Haben **Bestand, Meldemenge, Strichcode, Lagerort(e), Preis und Abgang mit Grund** wie Rohstoffe.
- Zählen beim **Inventurwert mit, mit eigener Zwischensumme** im Export.
- Erscheinen **nie in Rezepten, an der Waage oder im Planer**.

## 5. Inventur (VC03-e)

**Ablauf:**
1. **Inventur anlegen** (PIN): Stichtag, Bezeichnung („Jahresinventur 2026“), Umfang: alle bestandsgeführten / alle aktiven Rohstoffe, Hilfs- und Betriebsstoffe einschließlich. Höchstens **eine offene Inventur**.
2. **Zählliste drucken** (optional): **nach Lagerort sortiert**, Nr., Name, Gebinde, leere Spalte „gezählt“. **Ohne Preise und ohne Buchbestand** (blind zählen). Ein Rohstoff mit zwei Lagerorten steht an beiden Orten.
3. **Zählen** (ohne PIN, K03-59): erst **Lagerort wählen oder scannen**, dann per Scan (+1 Gebinde) oder per Ziffernblock in kg/Gebinde zählen; liegt an einem Ort nichts, **„0“ eintippen**. Einträge je Rohstoff werden über alle Orte addiert. Jeder Eintrag ist einzeln löschbar, solange die Inventur offen ist.
   - **Filter „noch nicht gezählt“** (je Ort und gesamt). Ein Rohstoff gilt erst als gezählt, wenn an **allen seinen Lagerorten** gezählt wurde.
4. **Abschluss** (PIN), Vorschau zeigt je Rohstoff: gezählt, Buchbestand, Differenz, Wert.
   - **Zählzeitpunkt zählt:** Jeder Zähleintrag merkt sich den Buchbestand im Moment der Zählung. Wird nach dem Zählen noch verwogen oder geliefert, rechnet der Abschluss diese Bewegungen dazu. Neuer Bestand = gezählt + Bewegungen seit der Zählung. So darf die Backstube während der Inventur weiterarbeiten.
   - **Ungezählte Rohstoffe:** Liste wie K03-36, vorgewählt „**unverändert**“, einzeln auf „**auf 0**“ umschaltbar (K03-57).
   - Gebucht wird je Rohstoff eine **Inventur-Buchung** mit Vermerk „Inventur <Stichtag>“ (eine Transaktion).
5. **Inventurwert:** je Rohstoff gezählte kg × **gültiger Preis je kg beim Abschluss** (Hilfs- und Betriebsstoffe: Einheiten × Preis je Einheit, H-B) (aktive Bezugsquelle, M04-14). Preis und Wert werden in der Inventur **gespeichert** und ändern sich später nicht (K03-58).
6. **Export** (.xlsx): Blatt „Inventur“ (Stichtag, Nr., Name, Menge kg bzw. Verpackungseinheiten, Gebinde, Preis, Wert €; Zwischensummen Rohstoffe und Hilfs- und Betriebsstoffe, Gesamtsumme), Blatt „ohne Preis“ (Rohstoffe ohne Preis, Wert fehlt, mit Hinweis in der Summe). Abgeschlossene Inventuren bleiben im Archiv und sind unveränderlich.

## 6. Wareneingang mit Scan (Ergänzung zu `docs/wareneingang.md`, W1)

- Liefertag-Seite bekommt die Taste **„Mit Kamera abhaken“** (K03-60).
- Mit Kamera starten die Zeilen bei **0** und zählen je Scan **ein Gebinde** hoch („3 von 16 Sack“). Ohne Kamera bleibt es wie entschieden (vorgehakt, Menge änderbar).
- Gramm je Scan = Gebinde am Rohstoff. Anzeige zusätzlich in Belegeinheit über „g je Mengeneinheit“ der Bezugsquelle (K03-19).
- Ein Scan zählt sofort eins („3 von 16 Sack“); bei 10 erwarteten Säcken also zehnmal scannen.
- **Unbekannter Code:** großes Fenster „Code unbekannt – welcher Rohstoff aus dieser Lieferung?“ mit den Rohstoffen der Lieferung als **große Tasten**. Ein Tipp: Code gespeichert, Zeile springt auf 1.
- Im selben Fenster Taste **„Nicht in der Lieferung“** (z. B. telefonisch nachbestellt): Suche im ganzen Stamm, der Rohstoff kommt als **zusätzliche Zeile „nicht erwartet“** in die Lieferung und wird mitgebucht.
- **Bekannter Code, aber nicht in der Lieferung:** Rückfrage **„Zusätzlich aufnehmen?“** → zusätzliche Zeile „nicht erwartet“; dort auch **„Ersatz für …“** mit Rückfrage zur Gebindegröße (H-D).
- Gebucht wird weiter nur mit „n Positionen buchen“ (W3, eine Transaktion).

## 7. Abgang von Hand (neu)

- Neue Buchungsart **Abgang** (`loss`) mit **Grund**: Bruch, Verderb, Eigenverbrauch, Handelsware, Sonstiges (+ Freitext) (K03-54).
- Per Scan (−1 Gebinde) oder in der Schnellerfassung als dritter Schalter „Abgang“ neben Zugang/Gesamtbestand (VC03-d).
- Im Bestandsverlauf eigener Filter „Abgang“. Für die spätere Verbrauchsbilanz (VC11-a) als eigener Posten sichtbar.

## 8. Datenmodell

**`raw_material_barcode`**: id, raw_material_id (FK), code (14-stellig normiert bzw. Text bei Code 128/39/QR, **eindeutig**), format, created_at, updated_at. Das Gebinde steht am Rohstoff (K03-51). Umhängen ändert raw_material_id.

**`storage_location`**: id, name (eindeutig), code (optional, eindeutig, auch gegen Rohstoff-Codes), sort, archived. **`raw_material`** bekommt `location1_id`, `location1_label`, `location2_id`, `location2_label` und für die neue Art `type = 'aid'` (Hilfs- und Betriebsstoff) die Zähleinheit (Hinweis Claude H-B).

**`stocktake`**: id, name, stichtag, scope (`stocked`/`active`), status (`open`/`closed`/`cancelled`), created_at, closed_at, total_value_cents, missing_price_count, note.
**`stocktake_count`**: id, stocktake_id, raw_material_id, location_id, qty (g bzw. Verpackungseinheiten), book_at_count, source (`scan`/`hand`), created_at.
**`stocktake_line`** (beim Abschluss): stocktake_id, raw_material_id, counted (leer = nicht gezählt), action (`set`/`unchanged`/`zero`), book_before, stock_after, price_cents (je kg bzw. Verpackungseinheit), value_cents, stock_movement_id.

**`stock_movement`** (Neuaufbau wie 0010): neue Arten **`loss`** (Abgang) und **`return`** (Rückgabe, W2), neue Spalten `reason` (Abgangsgrund), `stocktake_id`, `receiving_line_id` (W1); Quelle `scan` für Scan-Buchungen.

**Migrationen** (K03-61, entschieden): je Teil die nächste freie Nummer, voraussichtlich S1 → 0011, I1 → 0012, W1 → 0013. Damit ändert sich die in `docs/wareneingang.md` 6 genannte Nummer 0011 auf „nächste freie“. Der Neuaufbau von `stock_movement` und `raw_material` (neue Art, Lagerorte) erfolgt einmal in S1.

## 9. Regeln

| Nr. | Regel |
|---|---|
| S1 | Ein Code gehört zu genau einem Rohstoff (eindeutig); ein Rohstoff darf mehrere Codes haben. |
| S2 | Gebucht wird nur bei bekanntem Code mit Gebinde; sonst erst Zuordnen/Gebinde (pausiert, nichts geraten). |
| S3 | Dauerscan bucht **je Scan sofort** (wie Schnellerfassung VC03-d E) mit Rückgängig (K03-52). |
| S4 | PIN (K03-53): Info, +1 Zugang, −1 Abgang, Inventur zählen, Wareneingang abhaken, erstes Zuordnen ohne PIN; Bestand setzen, Umhängen eines Codes, Inventur anlegen/abschließen mit PIN (M03-13). |
| S5 | Rohstoff ohne Bestandsführung: +1 fragt „Bestand ab jetzt führen (ab 0)?“ (wie VC03-d F); −1 nicht möglich. |
| S8 | Hilfs- und Betriebsstoffe: in Rezepten, Planer und an der Station nicht auswählbar; Toleranz entfällt. |
| S6 | Archivierte Rohstoffe: Code wird erkannt, Hinweis „archiviert“, keine Buchung. |
| S7 | Inventur: während sie offen ist, laufen Verwiegen, Zugang und Abgang normal weiter (Abschnitt 5, Zählzeitpunkt). |

## 10. Schnittstellen (REST `/api/v1`, Add-on 1)

| Methode | Pfad | PIN | Inhalt |
|---|---|---|---|
| GET | `/barcodes/{code}` | nein | Rohstoff mit Bestand/Gebinde oder `unknown` |
| POST | `/barcodes` | nein (erstes Zuordnen) | Code an Rohstoff; Gebinde am Rohstoff, wenn leer |
| PATCH | `/barcodes/{code}` | ja | umhängen |
| GET/POST | `/admin/storage-locations` | ja | Lagerorte pflegen |
| POST | `/raw-materials/{id}/stock/receipt` | nein | vorhanden; `source=scan`, `packs` |
| POST | `/raw-materials/{id}/stock/loss` | nein | Abgang mit Grund |
| POST | `/stock/movements/{id}/undo` | nein | Rückgängig (eigenes Gerät, 10 min) |
| POST | `/admin/stocktakes`, `…/{id}/close`, `…/{id}/cancel` | ja | Inventur anlegen, abschließen, verwerfen |
| GET/POST/DELETE | `/stocktakes/open/counts` | nein | Zählen |
| GET | `/admin/stocktakes/{id}`, `…/{id}.xlsx`, `…/{id}/countlist.pdf` | ja | Vorschau, Export, Zählliste |

## 11. Tests

- Code-Normierung (EAN-13 ↔ GTIN-14, UPC-A, GS1-128 mit Zusatzfeldern → nur GTIN), Eindeutigkeit, Umhängen nur mit PIN.
- +1/−1 mit Gebinde, ohne Gebinde gesperrt, ohne Bestandsführung, archiviert; Rückgängig nur 10 min/eigenes Gerät.
- Abgang mit Grund, Filter im Verlauf, Schnellerfassung.
- Inventur: mehrfach zählen und addieren, Zählzeitpunkt mit Verwiegen dazwischen, ungezählt unverändert/auf 0, Wert mit gespeichertem Preis, ohne Preis, nur eine offene, Export.
- Liefertag mit Scan: Start bei 0, Gebinde je Scan, unbekannter Code mit Rohstoffen der Lieferung, „Nicht in der Lieferung“, „Zusätzlich aufnehmen?“.
- Migrationen auf befüllter Datenbank (Bestandsverlauf bleibt).
- Oberfläche: Zähllogik „0,8 s aus dem Bild“ als JS-Test mit nachgestellten Treffern.

## 12. Umsetzung in Teilen

| Teil | Inhalt | Praxisprüfung (Michael) |
|---|---|---|
| **S1 Scanner** | Migration (Codes, Lagerorte, Art Hilfs- und Betriebsstoff, `stock_movement` neu), ZXing im Add-on, Scan-Seite mit Info, +1, −1, Bestand setzen, Zuordnen; Abgang in der Schnellerfassung; Lagerorte am Rohstoff; Kachel „Scannen“ | 3 echte Rohstoffe zuordnen, 5 Säcke +1, einer −1 „Bruch“, Rückgängig, Bestand setzen, iPhone und Tablet |
| **I1 Inventur** | Migration, Inventur anlegen/zählen/abschließen, Zählliste, Export mit Wert | Probeinventur mit 10 Rohstoffen, Verwiegen zwischendurch, Export prüfen |
| **W1 Wareneingang** | wie `docs/wareneingang.md` 11, plus Scan-Abhaken (Abschnitt 6) | wie dort, plus eine Lieferung per Kamera |
| W2 | unverändert | unverändert |

Reihenfolge (entschieden, K03-61): **S1 → I1 → W1 → W2**. I1 vor W1, damit die Jahresinventur zum 31.12. schon mit dem System gemacht werden kann. W1 bleibt vor C2-I (K03-47). Versionen: nächste freie 0.10.x je Teil. Die Prüfseite `/kameratest` entfällt mit S1 (Hinweis Claude).

## 13. Auswirkungen

| Modul | Auswirkung |
|---|---|
| 02 | Migrationen für S1, I1, W1 (nächste freie Nummern) |
| 03 | Scan-Seite, Codes am Rohstoff (Reiter „Codes“), Abgang, Inventur im Unterreiter Bestand |
| 04 | keine; Bezugsquellen-Faktor „g je ME“ wird beim Abhaken mitgenutzt |
| 09 | Gebinde-Aufteilung beim Verwiegen gilt für jeden Rohstoff, dessen Gebinde per Scan gesetzt wird (gewollt, K03-51); keine Codeänderung |
| 05/06 | Hilfs- und Betriebsstoffe aus der Rohstoffauswahl im Rezept ausblenden |
| 10 | Kachel „Scannen“ auf der Startseite, Touch-Grundsätze aus `docs/wareneingang.md` 8 gelten auch hier |
| 11 | Abgang als eigener Posten in der Verbrauchsbilanz (VC11-a) |
| 12 | zur Kenntnis: PIN-Regeln S4 |
| 13 | Inventur-Exporte sind Teil der Datenbank, keine eigene Ablage |

## 14. Fragen – entschieden (Michael, Sprachchat 22.11.2026, eingetragen 07:55)

| Nr. | Entscheidung |
|---|---|
| K03-51 | **Gebinde im vorhandenen Feld am Rohstoff** (abweichend vom Vorschlag „am Code“); die Waage teilt damit in „Sack + Rest“ – gewollt. |
| K03-52 | Jeder Scan bucht **sofort**, mit Rückgängig (sicher bei Absturz). |
| K03-53 | PIN wie Regel S4. |
| K03-54 | Abgangsgründe: Bruch, Verderb, Eigenverbrauch, **Handelsware**, Sonstiges (+ Freitext). |
| K03-55 | **Geändert:** Beim Öffnen immer zuerst den Modus wählen, dann startet die Kamera. |
| K03-56 | Aufleuchten, Ton und Vibration (wo möglich); **keine Kameraleuchte**. |
| K03-57 | Ungezählte vorgestellt „unverändert“, einzeln „auf 0“; **dazu Filter „noch nicht gezählt“**. |
| K03-58 | Preis beim Abschluss festschreiben; Export .xlsx mit Blatt „ohne Preis“. |
| K03-59 | Zählen ohne PIN; Anlegen und Abschließen mit PIN. |
| K03-60 | Wie vorgeschlagen, **ergänzt** um Fenster mit Lieferungs-Rohstoffen als große Tasten, Taste „Nicht in der Lieferung“ und Rückfrage „Zusätzlich aufnehmen?“ (Abschnitt 6). |
| K03-61 | S1 → I1 → W1 → W2, je Teil nächste freie Migration. |
| K03-62 | **Geändert:** nur GTIN; Charge und MHD **weglassen** (auch nicht anzeigen). |
| M03-25 | **Neu:** Lagerorte mit optionalem Code, je Rohstoff Lagerort 1 und optional 2 mit Beschriftung; Bestand bleibt Summe; Inventur nach Ort (Abschnitt 4a). |
| M03-26 | **Neu:** Hilfs- und Betriebsstoffe als eigene Art, in Verpackungseinheiten, mit Bestand, Meldemenge, Code, Lagerort, Preis, Abgang, eigener Zwischensumme im Inventurwert (Abschnitt 4b). |

## 14b. Weitere Entscheidungen (Michael, Sprachchat 22.11.2026, eingetragen 08:05)

| Nr. | Entscheidung |
|---|---|
| H-A | **Fünfte Taste „Hilfs- und Betriebsstoff“** bei unbekannten Belegzeilen. „Sonstige Artikel“ nur noch für Dinge ohne Bestand (z. B. Strecke). Die Frage kommt nur bei Artikelnummern, die noch keinem Eintrag zugeordnet sind; ab der zweiten Rechnung automatisch. **Ändert K03-27** (docs/wareneingang.md nachgezogen). |
| H-B | Preis bei Hilfs- und Betriebsstoffen **je Verpackungseinheit**; aus der Rechnung Netto ÷ Anzahl Einheiten. |
| H-C | Neue Lagerorte beim Zuordnen eintippen, danach fest in der Liste; kein freies Textfeld je Rohstoff. |
| H-D | „Ersatz für …“ auch beim Abhaken per Kamera, **mit Rückfrage „Gleiche Gebindegröße wie bisher (z. B. 25 kg Sack)?“** – wenn nicht, Größe nur für diese Lieferung eintragen, gebucht wird umgerechnet; der Rohstoff bleibt unverändert. Gilt sinngemäß für Verpackungseinheiten. |
| H-E | Importvorlage aus der BÄKO-Inventurliste mit Spalten **Art** und **Lagerort**; die 77 sonstigen Artikel kommen als Hilfs- und Betriebsstoffe herein. |
| H-F | Gebinde wie bisher auf der Rohstoffseite (PIN) änderbar; der Scanner fragt nur bei leerem Feld. |

## 14c. Widerspruchsprüfung (Claude, 22.11.2026, 08:05)

| Nr. | Fundstelle | Ergebnis |
|---|---|---|
| W-1 | `docs/wareneingang.md` 3 / 13 (K03-27: Verpackung als „Sonstige Artikel“ ohne Bestand) | **Nachgezogen** nach H-A (fünf Tasten, Ignorierliste nur für nicht zugeordnete Artikel). |
| W-2 | `docs/wareneingang.md` 6, 10, 11, 12 (Migration fest 0011) | **Nachgezogen:** „nächste freie Nummer“ (K03-61). |
| W-3 | `docs/wareneingang.md` 4 / K03-45 (± Gebinde-Tasten in Sack/kg) | **Nachgezogen:** bei Hilfs- und Betriebsstoffen zählen die Tasten in Verpackungseinheiten. |
| W-4 | Gebindegröße am Rohstoff ist auch die **Stückgröße** für Stück-Zutaten (Ei, Hefewürfel; Verwiegen „n × Stück“, Planer-Stückliste „Stück“) | **Offen, Frage F-1:** Bei solchen Rohstoffen ist das Liefergebinde (Karton mit 180 Eiern, Karton mit 42 Würfeln) nicht das Waagen-Gebinde. Mit nur einem Feld würde der Scanner das Verwiegen verfälschen. |
| W-5 | `docs/planer.md` (Stückliste Rezept/Rohstoff) ↔ Abschnitt 4b („nie im Planer“) | **Offen, Frage F-2:** Verpackung je Verkaufsartikel (Tüte, Tortenschachtel) wäre in der Stückliste sinnvoll, dann würde der Planer sie auch abbuchen. |
| W-6 | Rohstoff-CSV-Import und Sammelaktion „Typ setzen“ kennen nur Mehl/Standard; Toleranz ist Pflicht (K03-3) | Kein Widerspruch, **wird mit S1 erweitert:** dritte Art, Toleranz entfällt dort, Typwechsel von/zu Hilfs- und Betriebsstoff gesperrt, solange der Eintrag in einem Rezept steht. |
| W-7 | Bestand in Gramm (`stock_g`, K03-9) | Hilfs- und Betriebsstoffe führen den Bestand in Einheiten; Umsetzung über die Zähleinheit am Eintrag (S1), Rohstoffe unverändert. |
| W-8 | Zugang per Scan **und** spätere AB-Buchung bzw. „Rechnung ohne AB“ (K03-26) | **Doppelbuchung möglich** – Vorschlag O-1 in Abschnitt 14d. |

**Fragen (entschieden 22.11.2026, Sprachchat, eingetragen 08:28):** F-1 **ja** (Feld „Liefergebinde“), F-2 **nein** (Verpackung bucht der Laden selbst aus).
- **F-1 Liefergebinde ≠ Waagen-Gebinde:** Am Rohstoff ein **zweites, optionales Feld „Liefergebinde“** (z. B. „Karton = 180 Stück“). Ist es leer, gilt das Gebinde (Regelfall Mehl: Sack = Sack). Der Scanner zählt in Liefergebinden, die Waage bleibt beim Stück. Das ändert K03-51 nur für diese Sonderfälle.
- **F-2 Verpackung im Planer:** Hilfs- und Betriebsstoffe dürfen in der Stückliste eines Verkaufsartikels stehen (Menge in Stück), der Planer bucht sie mit ab; in Rezepten und an der Waage weiter nie.

## 14d. Abläufe Schritt für Schritt – Optimierungen (Wunsch Michael 07:58; entschieden 22.11.2026, Sprachchat)

| Nr. | Ablauf | Heute im Konzept | Vorschlag |
|---|---|---|---|
| O-1 | Ware kommt, jemand scannt +1, später wird die AB gebucht | zwei Zugänge → doppelter Bestand | +1 prüft offene Lieferungen: „Gehört zu Lieferung AT… (erwartet heute)?“ → **Ja** bucht auf die Lieferzeile statt frei. Die Rechnung ohne AB zeigt Scan-Zugänge der letzten 3 Tage desselben Artikels und hakt sie als „schon gebucht“ vor. |
| O-2 | −1 Abgang | Grund wird je Serie abgefragt | **Grund gleich in der Modus-Auswahl** wählen („−1 Bruch“, „−1 Verderb“ …), dann sofort scannen – ein Fenster weniger. |
| O-3 | Inventur, Ort wechseln | erst Ort wählen/scannen | Ort-Code **jederzeit scannbar**, wechselt den Ort im laufenden Zählen; Anzeige oben groß „Zählen: Mehllager“. |
| O-4 | Inventur, Ort fertig | jedes Leere einzeln „0“ tippen | Taste **„Ort fertig“**: listet die hier noch nicht gezählten Einträge, vorgewählt „0“, einzeln abwählbar. |
| O-5 | Bestand setzen / Inventur mit Anbruch | Menge in Gebinden oder kg | Eingabe **„3 Sack + 12,5 kg“** in einem Schritt (volle Gebinde + Rest). |
| O-6 | Modus wählen | jedes Mal neu (K03-55) | Kacheln groß, der zuletzt benutzte Modus **hervorgehoben, aber nicht vorgewählt**. |
| O-7 | Unbekannter Code ohne Lieferung | Suche im ganzen Stamm | Vorschläge zuerst aus dem gewählten Lagerort und aus Artikeln ohne Code. |

**Entscheidungen Michael (Sprachchat 22.11.2026):**
- **O-1 geändert:** „Nichts fällt bei +1 vom Himmel“ – **kein +1 ohne Beleg**: Zugang per Scan nur zu einer **Lieferung** (W1) oder einem **Einkauf** (z. B. Metro, ohne PIN anlegbar), sonst nur als **Korrektur mit PIN**. Der Abgleich Rechnung ↔ Scan-Zugänge entfällt damit.
- **O-2 bis O-7: ja.** Zusätzlich **Fußleiste** in der Inventur mit aktuellem Lagerort und „noch zu zählen: n“; Tipp öffnet den Filter „noch nicht gezählt“ (für I1).
- Rechnung vs. Lieferung: erklärt und so angenommen („Das passt“).
- **Freigabe des Konzepts: 22.11.2026, 08:09** („Ich gebe das Konzept frei. Beginn.“), mit Auftrag: nach grünem Testlauf nach main und in HA einspielen.

## 15. Änderungen

| Datum | Änderung |
|---|---|
| 21.11.2026, 23:45 | Konzept erstellt (Auftrag Michael 23:31). K03-51 bis K03-62 offen. Liegt im Projektwissen; ins Repo mit der Umsetzung. |
| 22.11.2026, 07:55 | K03-51 bis K03-62 entschieden (Sprachchat), M03-25 Lagerorte und M03-26 Hilfs- und Betriebsstoffe neu; Abschnitte 2–14 angepasst, neue offene Punkte H-A bis H-F. Freigabe offen. |
| 22.11.2026, 08:28 | F-1 ja, F-2 nein, O-1 geändert (kein +1 ohne Beleg), O-2 bis O-7 ja + Fußleiste; **Freigabe 08:09**; Teil S1 umgesetzt (0.10.21, Abschnitt 16); Konzept ins Repo. |
| 27.11.2026 | Teil I1 umgesetzt (0.10.35, Migration 0014); Hinweise Claude in Abschnitt 17. |
| 22.11.2026, 08:05 | H-A bis H-F entschieden (Sprachchat), H-D mit Gebinde-Rückfrage; Widerspruchsprüfung 14c (W-1 bis W-3 in docs/wareneingang.md nachgezogen, F-1/F-2 offen); Abläufe und Vorschläge O-1 bis O-7 (Wunsch Michael 07:58). Freigabe offen. |

## 16. Umsetzung Teil S1 (0.10.21, 22.11.2026)

**Umgesetzt:** Migration 0011 (`storage_location`, `raw_material_barcode`, `purchase`; Neuaufbau `raw_material` mit Art `aid`, Liefergebinde, Lagerort 1/2; Neuaufbau `stock_movement` mit `loss`, `return`, `correction`, `undo` und Spalten `reason`, `purchase_id`, `device_id`, `undo_of_id`, `stocktake_id`, `receiving_line_id`). Scan-Seite `/scannen` mit Info, +1 Einkauf, +1 Korrektur (PIN), −1 je Grund (O-2), Bestand setzen (PIN, O-5), Code zuordnen/umhängen (PIN); Rückgängig 10 min eigenes Gerät; 0,8-s-Regel; Signal; unbekannter Code mit Suche (ohne Code zuerst, O-7) und Gebinde-Abfrage; zuletzt benutzter Modus umrandet (O-6). Rohstoffseite: Liefergebinde, Lagerorte (neuer Ort direkt eintippbar, H-C), Art Hilfs- und Betriebsstoff, Codes mit „entfernen“. Unterreiter Bestand: Lagerorte pflegen, Schnellerfassung „Abgang“ mit Grund, Verlauf mit Grund/Einkauf. `/kameratest` entfällt. Tests: `test_scanner.py`, `test_scanner_api.py`, `test_scan_gate.py`.

**Abweichungen (Hinweis Claude – zur Kenntnis):**
- **ZXing kommt weiter aus dem Netz** (unpkg), nicht aus dem Add-on: in der Arbeitsumgebung ist kein Paket-Download möglich. Betrifft nur das iPhone (Tablet nutzt den eingebauten Leser). Nachziehen, sobald Paket-Download geht.
- **Schnittstelle Nachschlagen:** `GET /barcodes/lookup?code=…` statt `/barcodes/{code}` (Codes können Schrägstriche enthalten). Umhängen: `POST /admin/barcodes/reassign`. Korrektur: `POST /admin/raw-materials/{id}/scan/correction`; Scan-Zugang/-Abgang: `POST /raw-materials/{id}/scan/receipt|loss`; Einkäufe `GET/POST /purchases`.
- **Hilfs- und Betriebsstoffe intern:** 1 Verpackungseinheit = 1000 im Feld `stock_g` (wie 1 kg), Preis „je kg“ = Preis je Einheit. Scan-Seite zeigt Einheiten; Rohstoffseite und Schnellerfassung zeigen die Zahl noch mit „kg“-Beschriftung (Anzeige folgt mit I1). Sammelaktion „Typ setzen“ bietet die Art nicht an (Wechsel nur einzeln, gesperrt solange in Rezept/Auftrag/Verkaufsartikel).
- **Info-Karte ohne Allergene** (Pass) – folgt bei Bedarf.
- **„Zugang buchen“ von Hand** (Rohstoffseite, Schnellerfassung, Station) bleibt wie bisher ohne Beleg; die Regel „kein +1 ohne Beleg“ gilt in S1 nur am Scanner. **Vorschlag Claude – offen:** so lassen oder auch dort einen Beleg verlangen?
- Inventur zählen und Wareneingang abhaken kommen mit I1 bzw. W1.

**Praxisprüfung (Michael):** 3 echte Rohstoffe zuordnen, 5 Säcke +1 Einkauf, einer −1 Bruch, Rückgängig, Bestand setzen „3 Sack + 12,5 kg“; iPhone (https) und Tablet.

## 17. Umsetzung Teil I1 Inventur (0.10.35, 27.11.2026)

**Umgesetzt:** Migration **0014** (`stocktake`, `stocktake_count`, `stocktake_line`; höchstens eine offene Inventur per Index; Index auf `stock_movement.stocktake_id`). Neues Fachmodul `app/stocktake/`.
- **Anlegen** (PIN) im Unterreiter Bestand, Panel „Inventur“: Bezeichnung, Stichtag, Umfang (alle bestandsgeführten / alle aktiven; Hilfs- und Betriebsstoffe immer dabei).
- **Zählen** (ohne PIN, blind) auf der Scan-Seite, Modus **„Inventur zählen“** (auch direkt über „Zählen (Scan-Seite)“ im Panel, `scannen?modus=inventur`): erst Lagerort wählen oder Ort-Code scannen; Ort-Code jederzeit scannbar (O-3), Anzeige „Zählen: Mehllager“; Scan = +1 Gebinde (Liefergebinde, F-1; bei Hilfs- und Betriebsstoffen +1 Verpackungseinheit); Tippen auf „Menge“ = „3 Sack + 12,5 kg“ (O-5) oder „0“; „Einträge“ zeigt und löscht einzelne Einträge; Rückgängig löscht den letzten eigenen Eintrag; **„Ort fertig“** (O-4) mit vorgewählter „0“ je ungezähltem Eintrag; Filter „nur noch nicht gezählte“; **Fußleiste** mit Ort und „noch zu zählen: n“, Tipp zeigt alle noch nicht gezählten über alle Orte.
- **Zählliste drucken** (PIN): nach Lagerort, Nr., Name, Gebinde, leere Spalte „gezählt“, ohne Preise und Buchbestand; Rohstoff mit zwei Orten steht an beiden, „ohne Lagerort“ am Ende.
- **Vorschau und Abschluss** (PIN): je Rohstoff gezählt, Buchbestand, Bewegungen seit der Zählung, neuer Bestand, Differenz, Preis, Wert; ungezählte „unverändert“ (vorgewählt) oder einzeln „auf 0“ (Tasten für alle); Abschluss bucht in einer Transaktion je Rohstoff `inventory` mit Vermerk „Inventur TT.MM.JJJJ“, Quelle `stocktake`, `stocktake_id`; Preis und Wert werden in `stocktake_line` festgeschrieben (mit Nr., Name, Art, Gebinde zum Abschluss).
- **Verwerfen** (PIN): bucht nichts.
- **Archiv** mit „Ansehen“ und **Excel** (.xlsx): Blatt „Inventur“ (Kopf mit Bezeichnung, Stichtag, Abschlusszeit; Nr., Name, Menge, Einheit, Gebinde, Preis, je, Wert, Hinweis; Zwischensummen Rohstoffe und Hilfs- und Betriebsstoffe, Gesamtsumme mit Hinweis auf fehlende Preise), Blatt „ohne Preis“.
- **Anzeige Hilfs- und Betriebsstoffe** (nachgezogen aus Abschnitt 16): Rohstoffliste, Rohstoffseite (Bestand, Verlauf), Schnellerfassung, Meldeliste und Sammelaktion „Bestand auf 0“ zeigen Verpackungseinheiten („12 Karton“) statt kg.
- Schnittstellen: `GET /api/v1/stocktakes/open`, `POST /api/v1/stocktakes/open/counts`, `DELETE /api/v1/stocktakes/open/counts/{id}`, `POST /api/v1/stocktakes/open/location-done` (ohne PIN); `GET/POST /api/v1/admin/stocktakes`, `GET …/{id}` (Vorschau, `?zero_ids=`), `POST …/{id}/close` (`confirm`, `zero_ids`), `POST …/{id}/cancel`, `GET …/{id}/countlist`, `GET …/{id}.xlsx` (PIN).
- Tests: `test_stocktake.py`, `test_stocktake_api.py`.

**Hinweise Claude – im Rahmen des Konzepts, bei Einwand ändern:**
- **Migration 0014** statt 0012: W1 (0012) und B1/W2a (0013) kamen vor I1 (K03-61 „nächste freie“).
- **Zählliste als Druck aus der Seite** statt `countlist.pdf`: im Add-on gibt es keine PDF-Bibliothek; „Zählliste drucken“ öffnet den Druckdialog des Geräts (dort auch „Als PDF sichern“). Der Server liefert die Liste als JSON (`…/countlist`).
- **Zählzeitpunkt bei mehreren Einträgen:** Bezug für „Bewegungen seit der Zählung“ ist der **letzte** Zähleintrag des Rohstoffs (Buchbestand in diesem Moment). Bewegungen lassen sich keinem Lagerort zuordnen; wer einen Rohstoff an zwei Orten zählt, sollte das zügig hintereinander tun. Begann die Bestandsführung erst nach der Zählung, zählt der ganze Buchbestand als Bewegung; wurde sie nach der Zählung beendet, keine.
- **Inventurwert ungezählter Rohstoffe „unverändert“:** bewertet mit dem **Buchbestand** (Hinweis im Export „nicht gezählt – Buchbestand“), damit der Wert vollständig ist; „auf 0“ = 0 €. Negative Bestände zählen 0 €.
- **Gezählt außerhalb des Umfangs:** Wird bei „alle bestandsgeführten“ ein Rohstoff ohne Bestandsführung gezählt, kommt er mit in die Inventur, und der Abschluss schaltet seine Bestandsführung ein. Der Umfang wird nicht beim Anlegen eingefroren, sondern beim Zählen/Abschluss gelesen.
- **Gezählt ist gezählt:** Ein Rohstoff mit Einträgen wird beim Abschluss immer gesetzt, auch wenn noch nicht alle seine Orte gezählt sind (Vorschau zeigt „nicht an allen Orten“, Zähler „nicht an allen Orten n“).
- **Blind zählen:** Die Zählansicht (`/stocktakes/open`) liefert weder Buchbestand noch Preis; beides nur in der Vorschau mit PIN.
- Archivierte Rohstoffe sind nicht zählbar (S6).

**Praxisprüfung (Michael):** Probeinventur mit 10 Rohstoffen an 2–3 Lagerorten (einer mit Lagerort 2), Zählliste drucken, zählen per Kamera und von Hand („3 Sack + 12,5 kg“, „Ort fertig“), zwischendurch einen Teig verwiegen, Vorschau prüfen (Bewegungen seit Zählung), einen ungezählten „auf 0“, abschließen, Excel öffnen.
