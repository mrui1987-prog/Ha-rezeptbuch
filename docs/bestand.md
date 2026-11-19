# Ergänzung VC03-b – Rohstoffbestand und Meldewert (Konzept)

Status: **Wunsch Michael 19.11.2026, 18:05; M03-9 bis M03-14 entschieden 18:07/18:08; K03-9 bis K03-17 im Sprachchat entschieden (bis 18:22, mit Änderungen); Konzept am 19.11.2026, 18:22 von Michael freigegeben („Ich gebe es frei“). Umgesetzt als 0.10.7 auf Zweig `bestand` (Hinweise Abschnitt 7).**
Betrifft: Modul 03 (freigegeben, Ergänzung wie VC03-a), Modul 02 (Migration 0008), Modul 09 (Abzug, Start-Rückfrage, Abbruch), Modul 10 (Rezeptübersicht, „Zugang buchen“ an der Station), Modul 11 (Verbrauchsbilanz VC11-a kann das Buchungsprotokoll nutzen), Modul 05 („Rohstoff austauschen“).

## 1. Ziel

Jeder Rohstoff kann einen **aktuellen Bestand** und einen **Meldewert** haben. Beim Verwiegen wird abgezogen, damit Bediener und Chef sehen, wie viel noch da ist. Fehlendes oder knappes Material zeigt die **Rezeptübersicht vor dem Start**; in der Rohstofftabelle lassen sich die Rohstoffe am oder unter dem Meldewert anzeigen.

## 2. Regeln

| Nr. | Regel |
|---|---|
| B1 | **Einheit (K03-9):** Bestand und Meldewert werden in **kg mit bis zu 3 Nachkommastellen** eingegeben und angezeigt, gespeichert in ganzen Gramm. Bei Gebinde-Rohstoffen zusätzlich ungefähr in Stück („≈ 12 Ei“). |
| B2 | **Bestandsführung an/aus (K03-10):** Bestand leer = keine Bestandsführung (kein Abzug, keine Markierung). Die erste Buchung („Zugang“ oder „Bestand setzen“) schaltet sie ein. **Beenden:** „Bestand setzen“ mit leerem Feld (mit PIN, protokolliert). 0 heißt „nichts mehr da“, die Führung bleibt an. Meldewert leer = keine gelbe Markierung. |
| B3 | **Negativ erlaubt (M03-14).** Negativer Bestand wird rot angezeigt. |
| B4 | **Abzug bei jeder Quittung (M03-10, K03-12)**, in derselben Transaktion: gewogen = Ist (mit Teilmengen die Gesamtmenge); Gebinde = Einheiten × Größe + Rest; Sollhandzugabe = Soll. **Nichts** bei Handzugabe nach Bedarf, übergangenen Zutaten, Unterrezept-Zeilen (deren Zutaten zieht die Unterrezept-Charge ab) und im Handbetrieb. |
| B5 | **Abbruch (M03-10, K03-13):** Wurde schon abgezogen, fragt der Abbruch „Gewogenes (n Zutaten, x kg) vom Bestand abgezogen lassen?“. **Ja** = bleibt, **Nein** = Rückbuchung je Zutat (Art `reversal`, protokolliert). |
| B6 | **Rezeptübersicht vor dem Start (K03-14, geändert durch Michael, ersetzt den Hinweis beim Wiegen aus M03-12):** Zeile **orange** hinterlegt mit „(Bestand reicht nicht)“, wenn der Bestand kleiner als der Bedarf ist; **gelb** mit „(Meldewert)“, wenn der Bestand nach Abzug den Meldewert erreicht oder unterschreitet (≤). Bedarf = Summe der Zutatenmengen dieses Rohstoffs im Teig. Beim Bestätigen (Start) kommt bei orangen Zeilen die Rückfrage **„Folgende Zutaten werden über den Bestand hinaus ins Minus gebucht: …“** mit **OK** und **Abbrechen**. **Beim Wiegen selbst kein Hinweis.** |
| B7 | **Pflege (M03-11, M03-13):** „Zugang buchen“ (+ Menge, Notiz) **ohne PIN, auch an der Station**; „Bestand setzen“ (Inventur, auch leer) und Meldewert **mit PIN**. Jede Buchung ins Protokoll `stock_movement`. |
| B8 | **Rohstofftabelle (K03-15, geändert):** Spalten **Bestand** und **Meldewert**, Filter **„am/unter Meldewert“** (nur aktive Rohstoffe mit Bestandsführung und Meldewert), je Rohstoff **Buchungsverlauf**. **CSV-Export** mit Bestand und Meldewert. **CSV-Import auch mit Bestand** (Michael): Wert wird als Inventur gebucht, wenn er sich ändert; **leere Zelle beendet die Führung** wie das Feld; fehlt die Spalte, bleibt der Bestand unverändert (wie beim Preis). Meldewert ebenso (leer = löschen, Spalte fehlt = bleibt). |
| B9 | **Archivieren und „Rohstoff austauschen“ (K03-16, ergänzt):** Rückfrage **„Bestand auf Null setzen?“** (nur bei Bestandsführung); Ja = Inventur auf 0. Sonst bleibt der Bestand stehen. Beim Austauschen geht nichts automatisch auf den neuen Rohstoff über. Archivierte erscheinen nicht im Filter. |

## 3. Daten (K03-11) – Migration 0008

- `raw_material.stock_g` INTEGER, leer erlaubt, negativ erlaubt; `raw_material.stock_alert_g` INTEGER ≥ 0, leer erlaubt.
- Neue Tabelle `stock_movement`: `id`, `raw_material_id`, `kind` (`receipt` Zugang, `inventory` Bestand setzen, `consumption` Abzug, `reversal` Rückbuchung), `delta_g` (± g, bei Inventur Differenz), `stock_after_g` (leer = Führung beendet), `batch_id`, `batch_item_id`, `station_id`, `source`, `note`, `created_at`.
- Modul 04 nimmt dann die nächste freie Nummer (0009).

## 4. Schnittstellen

- Lesen ohne PIN: `stock_g`, `stock_alert_g`, `stock_status` in `/api/v1/raw-materials`, Filter `?below_alert=true`; `GET /api/v1/raw-materials/{id}/stock/movements`.
- `POST /api/v1/raw-materials/{id}/stock/receipt {amount_kg, note?, station?}` ohne PIN.
- `POST /api/v1/admin/raw-materials/{id}/stock/inventory {stock_kg|null, note?}` und Meldewert (`stock_alert_kg`) über das bestehende Anlegen/Ändern, beides mit PIN.
- Archivieren / Austauschen: Parameter `stock_zero`.
- Modul 09: Abzug bei den Quittungen; `start` liefert ohne `confirm_stock` eine Rückfrage `stock_short` mit der Liste; `cancel` liefert ohne `stock_keep` eine Rückfrage `stock_question`; `GET /api/v1/orders/{id}/stock` für die Rezeptübersicht (Abschnitt 7).

## 5. Umsetzung (K03-17)

- **Teil C (Server, Rohstoffseite, CSV, Abzug, Rückfragen, Prüfseite Ablauf):** nächste freie Version (0.10.7), Zweig `bestand`.
- **Modul 10 (mit C2, Rezeptübersicht):** orange/gelbe Zeilen, Start-Rückfrage, Bestand lesen und „Zugang buchen“ an der Station.

## 6. Änderungen

| Datum | Änderung |
|---|---|
| 19.11.2026, 18:10 | Entwurf mit M03-9 bis M03-14 und K03-9 bis K03-17 (offen). |
| 19.11.2026, 18:22 | Sprachchat: K03-9 bis K03-13, K03-17 wie vorgeschlagen; Beenden der Führung über leeres „Bestand setzen“; **K03-14 geändert** (Markierung orange/gelb in der Rezeptübersicht, Rückfrage beim Start mit Abbrechen, kein Hinweis beim Wiegen); **K03-15 geändert** (CSV-Import mit Bestand als Inventur, leere Zelle beendet die Führung); **K03-16 ergänzt** (Rückfrage „Bestand auf Null setzen?“ beim Archivieren und Austauschen). **Konzept freigegeben.** |
| 19.11.2026, 18:50 | Umsetzung 0.10.7 auf Zweig `bestand`; Hinweise Claude in Abschnitt 7. |

## 7. Umsetzung 0.10.7 – Hinweise Claude

Im Rahmen des freigegebenen Konzepts; bei Einwand ändern:

- **Rezeptübersicht:** `GET /api/v1/orders/{id}/stock?dough_index=` liefert je Rohstoff Bedarf, Bestand, Meldewert und `stock_status` (`short` = orange, `alert` = gelb). Ohne `dough_index` gilt der ganze Auftrag; schon gestartete Teige zählen nicht mehr (ihr Gewogenes ist bereits abgezogen). Vor dem ersten Start rechnet die Übersicht mit der aktuellen Rezeptversion (Rechenweg aus Modul 06, nur gelesen, unverändert).
- **Start-Rückfrage** gilt für den Teig, der gestartet wird. „Abbrechen“ macht alles rückgängig, auch das Fixieren der Rezeptversion.
- Der **Stand der Charge** enthält keinen Bestandsstatus (beim Wiegen kein Hinweis, B6); die Station holt ihn für die Übersicht über den Endpunkt oben.
- **Archivieren:** Body `{"stock_zero": true}` (ohne Body wie bisher, Bestand bleibt). **Rohstoff austauschen:** Vorschau liefert `old_stock_g`, Ausführung nimmt `stock_zero`, Antwort `stock_zeroed`.
- **CSV-Import:** Eine ältere Exportdatei setzt den Bestand auf ihren alten Stand zurück (wie entschieden, Hinweis in DOCS.md).
- **Prüfseite Ablauf:** Rückfragen „ins Minus“ beim Start und „abgezogen lassen?“ (mit „Nein, zurückbuchen“) beim Abbruch.
- **Löschen** eines nie verwendeten Rohstoffs löscht auch seine Buchungen (nur Zugänge/Inventuren möglich).
