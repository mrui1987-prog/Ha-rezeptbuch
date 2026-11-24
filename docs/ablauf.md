# Modul 09 – Produktions- & Wiegeablauf (Schritt B: Konzept)

Status: **Konzept erstellt am 19.11.2026, 11:50. Konzeptfragen K09-1 bis K09-14 entschieden (11:47, Sprachchat, 11:53, 12:12, 12:17, 12:22); K09-10 geändert, K09-11 bis K09-14 neu, K09-13/K09-14 ergänzt 12:22 (Michael). **Konzept am 19.11.2026, 12:25 von Michael freigegeben („Ich gebe das Konzept frei“).**
Grundlage: Entscheidungen M09-1 bis M09-14 (docs/modulstatus-09.md, 19.11.2026, 08:24/11:06/11:34), docs/bedienkonzept.md (Abschnitte 1–5), docs/architektur.md (Abschnitt 5), docs/datenmodell.md (4.3), docs/berechnung.md (7.2, 16, 17, 19), docs/schnittstellen.md (Mittelsmann, Live-Kanal), docs/waage.md (Status, Befehle, Z07-1/Z07-2).
Zielversion: Add-on 1 `rezeptbuch` **0.9.0/0.9.1** (Zweig `modul09`). Add-on 2 unverändert.

## 1. Zweck und Umfang

Der ganze Ablauf **im Server**: Auftrag anlegen, Teig starten (Version fixieren, Charge und Sollwerte anlegen), Zutat für Zutat wiegen und quittieren, Tara, Pause und Übergabe zwischen den Stationen, Abbruch, Unterrezepte, Abschluss, Protokoll. Dazu eine schlichte **Prüfseite `/admin/ablauf`** (M09-2), mit der sich alles ohne Tablet-Oberfläche bedienen und prüfen lässt.

**Nicht enthalten:** Tablet-Oberfläche `/station/1|2` (Modul 10), Chargensuche/Auswertung/Druck (Modul 11), PIN-Änderung (Modul 12), Änderungen an der Berechnung (Modul 06) oder an Add-on 2.

## 2. Architektur

```
 Prüfseite /admin/ablauf (später Tablets, Modul 10)
        │ REST /api/v1/orders…, /api/v1/batches…     ▲ Live /api/v1/live (type batch, weigh)
        ▼                                             │
 ┌──────────────── app/production ────────────────────┴───┐
 │ orders.py   Aufträge anlegen/listen/löschen             │
 │ batches.py  Start, Zutat wählen, Quittieren, Pause …    │ ← Datenbank (Transaktionen)
 │ weigh.py    Wiegelogik je Station (rein, ohne DB/Netz): │
 │             Ist, Toleranz, Auto-Quittung, Tara, Höchstlast│
 │ runner.py   je Station: hört den Mittelsmann ab,         │ ← app/scales/hub.py (Modul 08)
 │             treibt weigh.py, 45-s-Wächter, Live-Meldung  │    current_state, Abo, send_command
 │ settings.py Einstellungen (Admin)                       │
 │ router.py   REST                                         │
 └─────────────────────────────────────────────────────────┘
        │ calculate / build_batch_items / sub_order_targets / plan_doughs (Modul 06)
```

- **Wahrheit liegt in der Datenbank** (Auftrag, Charge, Zutatenstand, Protokoll). Was nur beim Wiegen gebraucht wird (Fenster der letzten 2 s, Tara-Bezug, Tara läuft), hält `runner.py` je Station im Speicher; nach einem Neustart wird es beim „Weiter“ neu aufgebaut (K09-4).
- Waage nur über den **Mittelsmann** (M08-7). `weigh.py` bekommt die Zustände als Werte und eine Uhr – ohne Warten testbar.

## 3. Zustände

**Auftrag** (`production_order.status`): `open` → `in_progress` (erster Teig gestartet) → `done` (alle Teige fertig) · `cancelled` (Abbruch vor/bei der Produktion).

**Charge = ein Teig** (`batch.status`):

```
 open ──Start an Station X──▶ running (Besitzer X)
                               │  ▲
          Pause / 45 s offline │  │ Weiter an X oder Y (Y nur ohne „Fest an Waage“)
                               ▼  │
                             paused (frei)
 running ──Handwaage──▶ paused (Grund „Handwaage“, bleibt an der Station reserviert, K09-11)
 running ──alle Zutaten erledigt──▶ done (Abschlussanzeige) ──Behälter abgenommen──▶ Station frei (K09-10)
 running/paused ──Abbruch (bestätigt)──▶ cancelled
 Neustart des Add-ons: running → paused (Grund „Neustart“)
```

Mit der letzten Zutat ist die Charge `done`. Die Station bleibt belegt, bis der **Behälter abgenommen** wird (K09-10); der Hinweistext bleibt auf dem Tablet, bis jemand „OK“ drückt – das blockiert nichts.

**Zutat** (`batch_item`): offen (`ack_type` leer) → erledigt (`ack_type` gesetzt). Gebinde: erst `units_ack` (Ereignis), dann Rest; erledigt erst nach dem Rest.

## 4. Teig starten (M09-9, R2/K6, M09-10)

`POST /api/v1/orders/{id}/start {station, dough_index?}` in **einer** Transaktion:
1. Prüfen: Auftrag `open`/`in_progress`, Teig noch nicht gestartet, Station eingerichtet (M08-9), an der Station läuft keine andere Charge, „Fest an Waage“ passt.
2. **Erster Teig:** aktuelle Rezeptversion fixieren (`recipe_version_id`, `frozen_at`), Auftrag `in_progress`; **Unterrezept-Aufträge** aus `sub_order_targets` anlegen (`parent_order_id`, `parent_dough_index`, Menge = Gesamtteig, R06-5).
3. `batch` mit vorläufiger Chargennummer (K09-5), `status running`, Besitzer, `started_at`; `batch_item` aus `build_batch_items(…, dough_index)`, `sub_order_id` auf den passenden Unterrezept-Auftrag.
4. Rezepthinweis „zu Beginn“ (K3) wird mit der Antwort geliefert.
5. Tara-Aufnahme (Abschnitt 6.2): Die Software geht davon aus, dass der Behälter schon auf der Waage steht, und sendet **einmal `tare`**; das **Behältergewicht bleibt unbekannt** (K09-13). Danach erste offene Zutat. Wer das Behältergewicht braucht, nutzt freiwillig „Behälter wiegen“ (Abschnitt 6.2a).

## 5. Zutatenarten und Quittieren

| Art (aus `build_batch_items`) | Ablauf | `ack_type` / Ereignis |
|---|---|---|
| **Wiegen** (Rest > 0, Toleranz ≥ 1 g) | Ist gegen Soll, Auto-Quittung oder Taste | `auto_stable` / `manual_stable` / `manual_unstable` (K09-2); `weighed` |
| **Sollhandzugabe** (Toleranz 0 g, `is_hand_ack`) | nur quittieren, Ist = Soll | `hand`; `hand` |
| **Handzugabe nach Bedarf** (Soll 0 g) | nur quittieren, Ist leer | `hand`; `hand` |
| **Gebinde/Stück** (M09-6) | „10 × Ei“ von Hand quittieren, dann Rest wie „Wiegen“ (Rest 0 g → fertig; Rest < 1 g gibt es nicht, Ganzzahl) | Ereignis `units_ack` mit Anzahl; Ist = Einheiten × Größe + Rest |
| **Unterrezept** (M09-10) | eigener Auftrag; Zeile gesperrt, bis der Unterrezept-Teig fertig ist **oder** abgehakt wird | fertig gewogen: `sub_done` (K09-1), Ist = Ist-Summe der Unterrezept-Charge; abgehakt: `sub_checked`, Ist = Soll |
| **Übergehen** (M09-12) | nur mit Bestätigung (`confirm: true`) | `skipped`; `skipped`, Ist leer |

- Reihenfolge: nach jeder Quittung automatisch die **nächste offene** Zutat (Position); bei Übernahme nach Pause ist **jede offene** wählbar (`select`).
- **Quittieren nur in der Toleranz** (|Ist − Soll| ≤ Toleranz) und nur bei Waagenstatus `ok`. `invalid`/`error`/`offline` → kein Quittieren, Hinweis.
- Protokoll je Quittung: `weighing_event` mit Gewicht, Tara, `stable`, Station, Zeit; `batch_item.actual_g`, `station_id`, `acknowledged_at`.

## 6. Waage im Ablauf

### 6.1 Ist-Wert

`Ist = angezeigter Wert − Tara-Bezug` (Software, M09-5). Der Tara-Bezug ist der angezeigte Wert im Moment der letzten Tara (nach Tara an der Waage ~0).

### 6.2 Tara (M09-5, bestätigte Hinweise)

Nach jeder Quittung (und beim Start, beim „Weiter“, auf Tastendruck):
1. Software merkt den Bezug **sofort** (angezeigter Wert) – Ist ist damit 0.
2. Befehl `tare` an die Waage (Mittelsmann).
3. **Phase „Tara läuft“:** bis die Waage einen stabilen Wert bei ~0 meldet (|Wert| ≤ Wanderung), höchstens **3 s** (K09-3). Danach Bezug = dieser Wert. Erst jetzt wird die nächste Zutat freigegeben (sonst würde der Sprung der Anzeige als Ist erscheinen).
3a. **Tara ausgeführt, obwohl schon Last aufliegt (Befund B2, Michael 15:21):** Springt die Waage nach dem Befehl von brutto auf netto oder fällt die Anzeige gegenüber dem Höchstwert seit dem Befehl um das tarierte Gewicht, gilt die Tara als ausgeführt; Nullpunkt = 0 netto. Gleiches für eine verspätet ausgeführte Tara (Punkt 4).
4. Kommt die Bestätigung nicht (Befehl verworfen, Waage langsam): Software-Bezug bleibt, Hinweis „Tara an der Waage nicht bestätigt“, Ablauf geht weiter (Software maßgeblich). Springt die Anzeige später doch auf ~0, erkennt `weigh.py` den Sprung um genau den Bezug und führt den Bezug nach.
5. Jede Tara → Ereignis `tare_set` mit Bezug; die **Tara-Summe** (Behältergewicht, falls bekannt, + alle bisherigen Zutaten) wird mitgeführt.

### 6.2a Behälter wiegen (K09-13, freiwillig)

Taste **„Behälter wiegen“**, **jederzeit** während der Charge (geändert 12:22, Michael: „Vielleicht brauche ich einen anderen Behälter“):
1. Hinweis „Waage leeren“. Die Software wartet auf eine leere Waage: stabil bei ~0 (|Wert| ≤ 50 g) oder `-----` (tarierter Behälter abgenommen).
2. Befehl `tare`, **½ s Pause, `zero`, auf stabile Anzeige warten (höchstens 3 s), `zero` erneut** (geändert 19.11.2026, 17:14 und 23:02, Michael: die KERN verwirft `tare`/`zero` bei unruhiger Anzeige und piept trotzdem). Hinweis „Waage wird genullt – bitte warten“. Nach dem zweiten `zero` wartet die Software 2 s auf die Bestätigung (stabil, ohne Tara, Anzeige ≤ ±5 g) und sendet `zero` sonst erneut, **höchstens zweimal**. Bleibt die Null aus: Hinweis „Waage leer lassen und an der Waage Null drücken“; die Null von Hand wird erkannt. Tara auf leerer Waage löscht eine alte Tara, Null gleicht die Drift aus.
3. Hinweis „Behälter jetzt aufstellen“ mit Taste **„Ohne Behälter“**.
4. Wert stabil über 50 g → Software speichert ihn als **Behältergewicht** (`batch.container_g`) und sendet erneut `tare` (Phasen wie 6.2). „Ohne Behälter“ → `container_g = 0`, keine weitere Tara.
4a. **Geändert durch M09-19 (Michael 24.11.2026): nach dem Behälter nur `tare`, kein `zero` mit Last** – die KERN löscht bei `zero` die Tara und zeigt brutto 0, der Behälter wäre für die Waage „versteckt“ (modulstatus-07, Nachprüfung 0.7.6 (b)). Schritt `final_tare` („Waage wird tariert – bitte warten“): bestätigt, sobald die Waage netto ~0 zeigt; sonst bei ruhiger Anzeige bis zu zweimal neu senden, danach rechnet die Software selbst weiter. `zero` gibt es nur noch auf leerer Waage (Schritt 2). *Bisher (19.11., 22:38/23:02): ½ s nach der Tara `zero`, stabil abwarten, `zero` erneut.* **Piepen der KERN = Fehlermeldung**, wenn ein Befehl zu schnell nach dem vorigen kam (Korrektur Michael 24.11.2026).
5. Das Behältergewicht wird angezeigt und ist **von Hand änderbar**. Das ändert nur den gespeicherten Wert (Höchstlast, Protokoll), nicht das Wiegen.

Mitten in einer Zutat beginnt die Zutat im neuen Behälter **wieder bei 0**; das bisher Gewogene wird **nicht** als Teilmenge gezählt (geändert 19.11.2026, 16:18, Michael – Teilmengen nur bei „Behälter wechseln“, 6.2b). Die **Tara-Summe beginnt neu** beim neuen Behälter.

`container_g` leer = unbekannt (Normalfall). Bekanntes Gewicht zählt zur Tara-Summe (Höchstlast 6.4). Protokoll: Ereignis `container` mit Gewicht, Herkunft gewogen/von Hand/ohne Behälter in `note`.

*Hinweis Claude:* Ein schon tarierter Behälter, der noch auf der Waage steht, sieht für die Software wie eine leere Waage aus (Anzeige 0). Dann verwirft die Waage `zero` (über 50 g brutto), und das Aufstellen ergibt kein neues Gewicht. Der Hinweis „Waage leeren“ wird deshalb nie übersprungen.

### 6.2b Behälter wechseln (K09-14)

Für Mengen, die nicht auf einmal in den Behälter passen. Taste **„Behälter wechseln“**, während einer Zutat oder zwischen zwei Zutaten:
1. Die Software speichert die bisher gewogene Menge der aktuellen Zutat als **Teilmenge** (nur bei Status `ok` und stabil, sonst wartet sie). Die Zutat bleibt offen. Zwischen zwei Zutaten gibt es keine Teilmenge.
2. Hinweis „Behälter abnehmen und ausleeren“. Sobald die Waage das Abnehmen meldet (`-----`, Last kleiner als Tara), sendet die Software **`tare` und `zero` mit Pause und Wiederholung wie bei „Behälter wiegen“** (6.2a Schritt 2; geändert 12:22 und 17:14, Michael; `zero` bei `-----` erlaubt, Z07-2).
3. Hinweis „Leeren Behälter aufstellen“. Wert stabil über 50 g → Software merkt ihn als **Behältergewicht** (`container_g`) und sendet `tare` (Phasen wie 6.2).
4. Weiter mit dem Rest: **Ist = Summe der Teilmengen + aktuelle Anzeige − Tara-Bezug**, Rest = Soll − Teilmengen. Auto-Quittung und Toleranz gelten für die Gesamtmenge.
5. Nach dem Ausleeren beginnt die **Tara-Summe neu** beim leeren Behälter (Höchstlast 6.4, Lastprüfung K09-12).

Ist das Behältergewicht schon bekannt und weicht der neue Wert um mehr als `resume_check_g` (5 g) ab: Meldung „Anderer Behälter?“, weiter mit Bestätigung. Protokoll: je Teilmenge Ereignis `partial` (Gewicht, Station, `stable`), dazu `container`; `batch_item.actual_g` = Gesamtmenge.

*Grund für Tara + Null:* Ab der zweiten Zutat enthält die letzte Tara auch die schon gewogenen Zutaten. Der leere Behälter läge dann unter der Tara, die Waage zeigte `-----` statt 0. Nach Tara + Null steht die leere Waage sicher bei 0 brutto. **Praxisprüfung C2:** Wirkung von `tare` bei `-----` an der KERN (Modul 07: nach Abnehmen teils schon brutto, Tara auf leerer Waage bleibt brutto) – `zero` danach stellt in jedem Fall auf 0.

### 6.3 Auto-Quittung (M09-4)

Automatisch quittiert wird, wenn **durchgehend für die Einstellung „Zeit“ (2 s)**: Status `ok`, `stable` wahr, |Ist − Soll| ≤ Toleranz, **und** Höchst- minus Mindestwert im Zeitraum ≤ Einstellung „Wanderung“ (5 g). **Zusätzlich (Befund B1, Michael 19.11.2026, 14:58): Ist mindestens das halbe Soll (aufgerundet) und mindestens 1 g** – sonst würde eine Zutat mit Toleranz größer als das Soll schon bei 0 g quittiert; von Hand gilt die volle Toleranz. **Außerdem mindestens die „Mindestlast Autoquittierung“ (Einstellung `auto_ack_min_g`, Standard 70 g, 0 = aus; Michael 15:21)** – darunter nur von Hand. Ist-Wert = letzter Wert. Jeder Ausreißer (aus der Toleranz, nicht stabil, `invalid`) startet die Zeit neu. Fortschritt (0–100 %) geht über den Live-Kanal (Balken in Modul 10).

### 6.4 Höchstlast (M09-7)

`Gesamtlast = Tara-Summe + angezeigter Wert` (bei netto anzeigender Waage). Warnung, sobald Gesamtlast ≥ `capacity_g` − Einstellung „Vorwarnung“ (1000 g); **vor** einer Zutat zusätzlich, wenn Gesamtlast + Rest-Soll darüber läge. Nur Warnung, weiterwiegen. Überlast meldet die Waage als `-----` (`invalid`) → kein Wert, kein Quittieren.

### 6.5 Waagenausfall (M09-8)

`runner.py` prüft je Station: ist die Waage seit **45 s** `offline` (`offline_since` des Mittelsmanns), geht die laufende Charge auf `paused` (Grund „Waage getrennt“), Hinweis über den Live-Kanal. Rückkehr der Waage hebt die Pause nicht auf; „Weiter“ von Hand.

### 6.6 Abschluss und Nullstellen (K09-10, geändert 11:53)

Sind alle Zutaten erledigt: Charge `done`, Abschlussanzeige mit Rezepthinweis und Knetzeiten. **Das Abnehmen des Behälters schließt automatisch ab:** Erkennt die Software, dass die Last weg ist (Waage meldet nach dem letzten Tarieren `-----` oder die Gesamtlast liegt unter 50 g), sendet sie `zero` (bei `-----` erlaubt, Z07-2), speichert `finish_ack_at` und gibt die Station frei. Der **Hinweistext bleibt stehen, bis „OK“** gedrückt wird (nur Anzeige). Ohne Waage (offline) gibt es zusätzlich die Taste „Abschließen“.

## 7. Pause, Besitzer, Übergabe (M09-11, Bedienkonzept 4a)

- Nur die **Besitzer-Station** darf wiegen/quittieren; die andere sieht „in Arbeit an Waage X“.
- **Pause:** Charge `paused`, Besitzer leer (außer „Fest an Waage“: bleibt gebunden).
- **Weiter:** `UPDATE batch SET status='running', owner_station_id=? WHERE id=? AND status='paused' AND (fest IS NULL OR fest=?)` – zählt nur, wenn genau eine Zeile geändert wurde; die zweite Station bekommt „bereits an Waage X übernommen“. Danach **neue Tara an dieser Station** (K09-4), dann Auswahl der Zutat. **Seit M09-17 (23.11.2026):** an **derselben** Station mit bestandener Lastprüfung **keine neue Tara**, das Ist der angefangenen Zutat läuft weiter (Abschnitt 9). **Seit M09-18 (23.11.2026, 20:50):** eine **angefangene Zutat** (Teilmenge vorhanden oder Ist ≥ 5 g beim letzten gespeicherten Stand) wird **nicht an der anderen Station übernommen** – wie beim Stationswechsel im Normalbetrieb (M09-16); Meldung „Die Zutat ist an Waage X angefangen – bitte dort fertig wiegen und quittieren“ (`resume_started_elsewhere`).
- Eine Station hat höchstens eine laufende Charge.
- **Neustart des Add-ons:** beim Start werden alle `running` → `paused` (Grund „Neustart“).

## 8. Abbruch (M09-12)

`cancel {confirm: true}`: Charge `cancelled`, Gewogenes bleibt im Protokoll (Trigger sperren danach Änderungen). Sind alle Teige erledigt oder abgebrochen, wird der Auftrag `done` (mind. ein Teig fertig) bzw. `cancelled`. Ein offener Auftrag ohne gestarteten Teig kann gelöscht werden (mit Bestätigung, K09-6).

## 9. Handbetrieb (M09-13, Bedienkonzept 5) und Handwaage während der Verwiegung (K09-11, K09-12)

Je Station ohne laufende Charge: Anzeige netto mit derselben Tara-Logik (6.2) über `POST /api/v1/stations/{nr}/hand/tare`; Tara-Bezug nur im Speicher. Startet an der Station eine Charge, endet der Handbetrieb dort automatisch.

**Handwaage mitten in der Verwiegung (K09-11, Michael 11:53):** Taste „Handwaage“ an der laufenden Charge → Charge `paused` mit Grund `hand_scale`, **bleibt an dieser Station reserviert** (die andere Station sieht „pausiert – Handwaage an Waage X“ und kann nicht übernehmen). Die Waage läuft als normale Waage mit Tara; jemand kann zwischendurch etwas anderes abwiegen.

**Prüfung beim Zurückkehren (K09-12):** Beim Wechsel merkt sich die Software die **Gesamtlast** (Behälter + bisherige Zutaten). Bei „Weiter“ vergleicht sie die aktuelle Gesamtlast damit: Abweichung ≤ **5 g** (Einstellung `resume_check_g`) → weiter mit neuer Tara; größer → Meldung „Gewicht weicht um … g ab – richtiger Behälter?“, Weitermachen nur mit Bestätigung, die Abweichung wird protokolliert (Ereignis mit beiden Werten). Die Prüfung gilt auch für normale Pausen an derselben Station; bei Übernahme an der anderen Waage entfällt sie (andere Waage). **Geändert durch M09-17 (Michael 23.11.2026, 20:28):** Abweichung ≤ 5 g → **keine neue Tara**, das Ist läuft weiter. Gilt nach Handwaage, Pause, 45-s-Pause und Neustart des Add-ons: Der Stand der Waage (Gesamtlast, Tara-Bezug als Gesamtlast, Tara der Waage, Ist, Zeile, Station) steht dauerhaft in `batch.snap_*` (Migration 0013) – geschrieben beim Pausieren und im Hintergrund bei stabilen Werten (höchstens einmal je Sekunde, ab 2 g Änderung), gelöscht nach jeder Quittung, Tara von Hand und Behälter wiegen/wechseln. Größere Abweichung → Fenster mit **drei Tasten** (`resume_choice`): **„Schon in den Kessel gegeben“** (`poured`, nur wenn die Zutat angefangen war: das Ist beim Pausieren wird Teilmenge, neue Tara, Rest = Soll − Teilmengen), **„Behälter neu aufgestellt, nichts zugegeben“** (`new_container`, neue Tara, Ist beginnt bei 0; die alte Bestätigung `confirm_deviation` gilt als diese Wahl) und **„Abbrechen“** (bleibt pausiert). Protokoll: `resume_deviation` mit der Wahl, bei „Kessel“ zusätzlich `partial`; ohne neue Tara ein `tare_set` „Weiter ohne neue Tara“. **Tara/Null von Hand (Michael 23.11.2026, 21:36; seit M09-19, 24.11.2026, auch beim laufenden Wiegen – Tasten an der Waage ändern nie Ist oder Tara der Software, erkannt wird nur still im Protokoll):** Die Software beobachtet die Software die Waage weiter. Springt eine ruhige, tarierte Anzeige ohne Zwischenwert (höchstens 0,7 s zwischen zwei Beobachtungen, nicht in den 3 s nach einem eigenen Befehl) auf ~0, war das Tara oder Null von Hand: die Software verschiebt ihren Ausgleich (Gesamtlast − Anzeige) um den alten Wert, die Gesamtlast bleibt richtig. Netto danach = Tara von Hand, brutto danach = Null von Hand (versteckte Last). Ein Sprung von brutto auf netto (~0) gilt ebenfalls als Tara von Hand. Nach einem Neustart gilt der gespeicherte Ausgleich (`batch.snap_scale_tare_g` = Gesamtlast − Anzeige). **Zeigt die Waage beim „Weiter“ keinen gültigen Wert** (`-----`, unter 0 oder Überlast), wird „Weiter“ abgelehnt mit „Bitte den Behälter des Teigs wieder aufstellen“ (Befund Michael 19.11.2026, 22:38).

## 10. Einstellungen (M09-4, Admin mit PIN)

Tabelle `setting` (Modul 02), Lesen ohne PIN, Ändern mit PIN (`/api/v1/admin/production-settings`), Abschnitt auf der Prüfseite:

| Schlüssel | Standard | Bereich | Bedeutung |
|---|---|---|---|
| `auto_ack_seconds` | 2 | 1–10 s | Zeit für die Auto-Quittung (ersetzt 4 s aus R4) |
| `auto_ack_span_g` | 5 | 0–50 g | erlaubte Wanderung in dieser Zeit |
| `offline_pause_seconds` | 45 | 10–300 s | Waagenausfall bis Pause (R6) |
| `capacity_warn_g` | 1000 | 0–10 000 g | Vorwarnung vor der Höchstlast |
| `tare_confirm_seconds` | 3 | 1–10 s | Wartezeit auf die Tara-Bestätigung der Waage |
| `resume_check_g` | 5 | 0–100 g | erlaubte Abweichung der Gesamtlast beim „Weiter“ (K09-12) |
| `auto_ack_min_g` | 70 | 0–5 000 g | Mindestlast Autoquittierung (Michael 15:21, 0 = aus) |

## 11. Schnittstelle (REST, ohne PIN außer Einstellungen)

| Methode, Pfad | Zweck |
|---|---|
| `GET /api/v1/orders?date=` | Produktionsliste (offen, in Arbeit an Waage X, fertig) |
| `POST /api/v1/orders` | Auftrag anlegen (Bezugsangaben wie `validate_basis`, Teige, Unterrezept je Teig/für alle, „Fest an Waage“, Datum) |
| `GET /api/v1/orders/{id}` · `DELETE …` | Details (Zutaten aus der Berechnung) · löschen, nur `open`, `confirm: true` |
| `POST /api/v1/orders/{id}/start` | Teig starten `{station, dough_index?}` |
| `GET /api/v1/batches/{id}` | Stand der Charge mit Zutaten, aktuelle Zutat, Hinweise |
| `POST /api/v1/batches/{id}/select` | Zutat wählen (nach Übernahme) |
| `POST …/units` | ganze Einheiten quittieren |
| `POST …/ack` | von Hand quittieren (nur in Toleranz) |
| `POST …/hand` | Handzugabe quittieren |
| `POST …/skip` · `…/cancel` | übergehen / abbrechen, je `confirm: true` |
| `POST …/sub-check` | Unterrezept abhaken (Ist = Soll) |
| `POST …/tare` | Tara von Hand |
| `POST …/container {action: start\|none\|set, container_g?}` | Behälter wiegen, ohne Behälter, Gewicht von Hand ändern (K09-13) |
| `POST …/container-change` | Behälter wechseln, Teilmenge speichern (K09-14) |
| `POST …/pause` · `…/resume {station, resume_choice?}` | Pause / Weiter (Lastprüfung K09-12; ohne neue Tara bei bestandener Prüfung, sonst `resume_choice` `poured`/`new_container`, M09-17; Antwort `resume_mode` `keep`/`poured`/`new_container`/`tare`) |
| `POST …/hand-scale` | Handwaage während der Verwiegung (Pause, reserviert, K09-11) |
| `POST …/finish` | Abschließen von Hand (nur nötig ohne Waage; sonst schließt das Abnehmen ab) |
| `GET/PUT /api/v1/admin/production-settings` | Einstellungen (PUT mit PIN) |
| `POST /api/v1/stations/{nr}/hand/tare` | Handbetrieb |

Jede ändernde Anfrage nennt die **Station**; der Server prüft Besitzer und Status. Antworten liefern den neuen Stand der Charge.

**Live-Kanal** `/api/v1/live` (Modul 08) – neue Nachrichtentypen:
- `{"type":"weigh","station":1,"batch_id":…,"position":…,"actual_g":…,"target_g":…,"tolerance_g":…,"zone":"low|ok|high","auto_ack_progress":0–100,"taring":bool,"capacity_warning":bool,"hint":…}` bei jeder Änderung (höchstens ca. 10/s)
- `{"type":"batch","batch_id":…,"status":…,"owner_station":…,"current_position":…,"event":"acked|paused|resumed|finished|cancelled|…"}` bei jedem Schritt
- `{"type":"orders"}` wenn sich die Produktionsliste ändert (Tablet lädt neu)

## 12. Datenbank – Migration 0007 (K09-1)

Nötig, weil CHECK-Regeln nur per Neuaufbau änderbar sind (wie 0006, Schalter `foreign_keys=off`):
- `batch_item.ack_type` zusätzlich **`sub_done`** (Unterrezept gewogen) und **`manual_stable`** (von Hand, Waage stabil) (K09-1, K09-2).
- `batch`: neue Spalten `pause_reason` (`manual`, `scale_offline`, `restart`, `hand_scale`), `paused_at`, `pause_load_g` (Gesamtlast beim Pausieren, K09-12), `finish_ack_at` (Behälter abgenommen/abgeschlossen), `container_g` (Behältergewicht, leer = unbekannt, K09-13).
- `weighing_event.event_type` zusätzlich `resume_deviation` (Abweichung beim „Weiter“ bestätigt, `weight_g` = Abweichung) und `container` (Behältergewicht, K09-13) und `partial` (Teilmenge beim Behälterwechsel, K09-14).
- Startwerte der Einstellungen (Abschnitt 10) per `INSERT OR IGNORE`.
- Bisher gibt es keine Chargen im Betrieb (Tabellen leer) → Neuaufbau ohne Datenrisiko.
- **Nummer:** Modul 09 wird vor Modul 04 umgesetzt (04 erst nach Freigabe Modul 06) → Modul 09 bekommt **0007**, Modul 04 die nächste freie (0008; nach K04-5 ohnehin „nächste freie“).

## 13. Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| Zwei Stationen drücken gleichzeitig „Weiter“ | erste gewinnt (bedingtes UPDATE), zweite: 409 „bereits an Waage X übernommen“ |
| Quittieren außerhalb der Toleranz / Waage `invalid`/`offline` | 409 mit Grund, nichts gespeichert |
| Waage 45 s offline | Pause, Hinweis; Daten bleiben |
| Tara an der Waage nicht bestätigt | Hinweis, Software rechnet weiter (6.2) |
| Datenbank gesperrt | 503 „beschäftigt“ (wie bisher), Bedienung wiederholt |
| Neustart mitten im Wiegen | Charge `paused`, Zutat offen, beim „Weiter“ neue Tara |
| Rezept zwischen Anlegen und Start geändert | gilt noch (Version erst beim Start fixiert, R2) |
| Unterrezept-Zeile ohne fertigen Unterrezept-Teig | Quittieren gesperrt, „abhaken“ möglich |

## 14. Tests und Praxisprüfung

**Automatisch:** `weigh.py` mit Uhr-Attrappe (Auto-Quittung 2 s/5 g, Rücksetzen, Tara-Phasen inkl. ausbleibender Bestätigung und verspätetem Sprung, Höchstlast-Warnung, Gebinde); Ablauf mit Datenbank (Start fixiert Version, Unterrezept-Aufträge, alle Zutatenarten, Pause/Weiter mit Wettlauf, Fest an Waage, Neustart → paused, Abbruch, Abschluss, Auftrag fertig); 45-s-Pause; Migration 0007; REST und Live-Nachrichten; Einstellungen mit/ohne PIN. Bestehende Tests unverändert.

**Praxisprüfung (über HA, Handgriffe Michael):** Auftrag mit 2–3 Zutaten anlegen und starten, wiegen mit Auto-Quittung (Waage zeigt nach jeder Zutat 0), manuell quittieren, Gebinde, Handzugabe, Übergehen, Pause → Weiter (Waage 2 als Simulator für die Übergabe), Waveshare 45 s vom Strom → Pause, Höchstlast-Warnung mit Gewicht nahe 29 kg (oder kleiner Testwert für `capacity`), Abschluss mit Behälter abnehmen → Null, Einstellungen ändern.

## 15. Konzeptfragen (entschieden 19.11.2026; K09-1, K09-2, K09-4 bis K09-9 wie vorgeschlagen 11:53, Michael: „Damit passen dann auch alle anderen weiteren Punkte“)

| Nr. | Frage | Vorschlag |
|---|---|---|
| K09-1 | Unterrezept fertig gewogen: welche Quittierungsart? | Neue Art **`sub_done`** („Unterrezept gewogen“, Ist = Ist-Summe des Unterrezept-Teigs); `sub_checked` bleibt „abgehakt, nicht gewogen“. Mit **Migration 0007** (Modul 04 → 0008). |
| K09-2 | Von Hand quittiert, Waage aber stabil (vor Ablauf der 2 s) | Neue Art **`manual_stable`** („manuell (stabil)“), damit „manuell (nicht stabil)“ nur bei wirklich unruhiger Waage steht (Master-Prompt: manuelle Eingriffe eindeutig). |
| K09-3 | Tara-Bestätigung der Waage | **ENTSCHIEDEN 19.11.2026, 11:47 (Michael: „Ok“ nach Erklärung im Sprachchat):** Bis zu 3 s auf stabilen Wert ~0 warten, nächste Zutat erst danach; sonst Software-Tara mit Hinweis (Abschnitt 6.2). |
| K09-4 | Tara bei „Weiter“ | **Bei jedem „Weiter“ neu tarieren** (andere Station = andere Waage; nach Neustart ist der alte Bezug unbekannt). Der Behälter steht dabei auf der Waage. |
| K09-5 | Vorläufige Chargennummer | `JJJJMMTT-NNN` (Tageszähler, z. B. `20261120-003`), in Modul 11 ersetzbar. |
| K09-6 | Aufträge an der Station | Anlegen und Löschen (nur `open`, mit Bestätigung) **ohne PIN** wie die Vorwahl im Bedienkonzept; im Admin-Bereich dasselbe. |
| K09-7 | Einstellungen | Fünf Werte nach Abschnitt 10, alle im Admin änderbar (auch 45 s und Vorwarnung). |
| K09-8 | Umsetzung in Teilen | **C1 (0.9.0):** Migration, Aufträge, Start, Zutatenarten, Gebinde, Unterrezepte, Pause/Übergabe, Abbruch, Abschluss, Prüfseite – Wiegen zunächst nur von Hand mit Waagenwert. **C2 (0.9.1):** Auto-Quittung, Tara Software+Waage, Behälter wiegen (K09-13), Behälter wechseln (K09-14), Höchstlast, 45-s-Pause, `zero` am Ende, Handbetrieb, Live-Nachrichten `weigh`. |
| K09-9 | Unterrezept-Auftrag | Darf an jeder Station gestartet werden; der Hauptteig darf schon laufen, nur die Unterrezept-Zeile wartet. |
| K09-10 | Abschluss | **GEÄNDERT (Michael, Sprachchat 11:53):** Charge mit der letzten Zutat `done`; **Abnehmen des Behälters schließt automatisch ab** (`zero`, Station frei, `finish_ack_at`); Hinweistext bleibt bis „OK“ (Abschnitt 6.6). |
| K09-11 | Handwaage während der Verwiegung | **NEU (Michael, Sprachchat 11:53):** Taste „Handwaage“ pausiert den Teig, **reserviert an der Station**; normale Waage mit Tara; danach „Weiter“ (Abschnitt 9). |
| K09-12 | Prüfung beim „Weiter“ | **NEU (Michael, Sprachchat 11:53):** Gesamtlast beim Pausieren merken, beim „Weiter“ vergleichen; ≤ 5 g (im Admin einstellbar) → weiter; sonst Meldung, Weitermachen mit Bestätigung, protokolliert (Abschnitt 9). |
| K09-13 | Behältergewicht | **NEU (Michael, Sprachchat und 12:11):** Start sendet immer `tare`, Behältergewicht unbekannt. Freiwillige Taste **„Behälter wiegen“** (Name gewählt 12:11), **jederzeit** (12:22): Waage leeren → `tare` + `zero` → Behälter aufstellen → Gewicht merken → `tare`; Gewicht angezeigt und von Hand änderbar; darin „Ohne Behälter“ (Gewicht 0). Umsetzung mit C2, Spalte in Migration 0007 (Abschnitt 6.2a). |
| K09-14 | Behälter wechseln | **NEU (Michael 12:14, Lösung mit `zero` bestätigt 12:17):** Teilmenge speichern, Behälter abnehmen und ausleeren, beim Abnehmen `tare` + `zero` (12:22), leeren Behälter aufstellen (Gewicht wird gemerkt), `tare`, weiter mit dem Rest. Auch zwischen Zutaten. Umsetzung mit C2 (Abschnitt 6.2b). |

## 16. Auswirkungen auf andere Module

- **02:** Migration 0007 (K09-1/K09-2, Spalten an `batch`, Einstellungen). Modul 04 → 0008.
- **06:** nur Aufruf der vorhandenen Funktionen; keine Änderung.
- **07:** M07-4 geändert (Waage wird tariert); Add-on 2 unverändert. docs/waage.md 6.3 („tare nur für Sonderfälle“) und Hinweis Modul 09 nachziehen.
- **08:** neue Live-Nachrichtentypen; Mittelsmann unverändert.
- **10:** Tablet-Oberfläche nutzt diese API und die Live-Nachrichten.
- **11:** Chargennummer ersetzen, Auswertung auf `batch*`/`weighing_event` inkl. neuer Quittierungsarten.
- **Doku:** R4 4 s → 2 s einstellbar (architektur.md 5, bedienkonzept.md 4).

## 17. Verzeichnisstruktur

```
rezeptbuch/app/production/  __init__.py, orders.py, batches.py, weigh.py, runner.py, settings.py, router.py
rezeptbuch/app/db/migrations/0007_production.sql
rezeptbuch/app/web/static/production.html   Prüfseite /admin/ablauf, Reiter „Ablauf“
rezeptbuch/tests/test_prod_*.py
docs/ablauf.md                               dieses Dokument (ins Repo mit C1)
```

## 18. Änderungen

| Datum | Änderung |
|---|---|
| 19.11.2026, 11:50 | Konzept erstellt (Schritt B), Konzeptfragen K09-1 bis K09-10 offen. |
| 19.11.2026, 11:47 | K09-3 (Tara-Bestätigung bis 3 s) von Michael bestätigt. |
| 19.11.2026, 11:53 | K09-10 geändert (Abnehmen schließt ab), K09-11 Handwaage während der Verwiegung (reserviert) und K09-12 Lastprüfung beim „Weiter“ (5 g, einstellbar) neu (Michael, Sprachchat); übrige K09 wie vorgeschlagen. Abschnitte 3, 6.6, 9, 10, 11, 12, 15 angepasst. |
| 19.11.2026, 12:12 | K09-13 Behältergewicht neu (Michael): Start mit Tara, Gewicht unbekannt; freiwillige Taste „Behälter wiegen“ mit „Ohne Behälter“. Abschnitte 4, 6.2a, 11, 12, 15 angepasst. |
| 19.11.2026, 12:17 | K09-14 Behälter wechseln neu (Michael): Teilmenge, Ausleeren, `zero` bei `-----`, leerer Behälter, Tara, Rest. Abschnitte 6.2b, 11, 12, 15 angepasst. |
| 19.11.2026, 12:22 | Michael: „Behälter wiegen“ jederzeit (mit Teilmenge mitten in einer Zutat); beim Behälterwechsel nach dem Abnehmen `tare` + `zero`. Abschnitte 6.2a, 6.2b, 15 angepasst. |
| 19.11.2026, 12:25 | **Konzept freigegeben (Michael).** Nächster Schritt: Teil C1 (0.9.0) auf Zweig `modul09`. |
| 19.11.2026, 22:38 | Michael: nach dem Behälter wiegen ½ s nach der letzten Tara `zero` (6.2a 4a); Befund: „Weiter“ bei ungültigem Waagenwert wird abgelehnt (9). |
| 24.11.2026, 04:37 | M09-19: nach dem Behälter nur Tara (6.2a 4a), Tasten an der Waage ändern nie Ist/Tara (auch beim Wiegen), Taste „Null“ am Tablet nur bei Gesamtlast ≤ 50 g (`POST …/stations/{nr}/hand/zero`). 0.10.32. |
| 23.11.2026, 20:28 / 20:50 | M09-17 „Weiter“ ohne neue Tara, drei Tasten; M09-18 angefangene Zutat nicht an der anderen Station (Abschnitte 7, 9, 11). Umsetzung in 0.10.31 mit Migration 0013 (`batch.snap_*`). |
| 19.11.2026, 23:02 | Michael: KERN verwirft `tare`/`zero` bei Unruhe und piept trotzdem → bei beiden Nullungen `tare`, ½ s, `zero`, stabil abwarten, `zero` erneut (6.2a 2 und 4a). |
| 19.11.2026, 17:14 | Michael: beim Behälter wiegen/wechseln Pause zwischen `tare` und `zero`, `zero` bis zu zweimal wiederholen, wenn nicht bestätigt. Abschnitte 6.2a, 6.2b. |

## 19. Umsetzung Teil C1 (0.9.0) – Ergänzungen und Abweichungen

Hinweise Claude zur Umsetzung (19.11.2026), im Rahmen des freigegebenen Konzepts; bei Einwand ändern:

- **Einstellungen:** Startwerte stehen im Code (`app/production/settings.py`), die Tabelle `setting` enthält nur geänderte Werte (statt `INSERT OR IGNORE` in 0007; ein bestehender Test erwartet eine leere Tabelle). Lesen ohne PIN zusätzlich unter `GET /api/v1/production-settings`.
- **Migration 0007 zusätzlich:** `production_order.sub_modes` (Auswahl „je Teig/für alle“ bis zum Start), `batch.current_position` (aktuelle Zutat übersteht einen Neustart), eindeutiger Index „höchstens ein laufender Teig je Station“, `weighing_event.note` (Vermerk). Abgeschlossene Charge: nur `finish_ack_at` darf einmal gesetzt werden (Trigger angepasst, K09-10).
- **`GET /api/v1/batches?station=`:** offene Chargen (laufend, pausiert, fertig mit Behälter auf der Waage) für Prüfseite und Tablet.
- **`sub-check`:** ist der Unterrezept-Teig fertig, „Unterrezept gewogen“ (`sub_done`, Ist = Ist-Summe der Unterrezept-Charge) ohne Rückfrage; sonst Abhaken mit Bestätigung (`sub_checked`, Ist = Soll). Bei „für alle“ und mehreren Teigen ist das Ist je Teig dessen Anteil (Soll).
- **Abschließen von Hand** ist in C1 immer möglich (Prüfseite); das Abnehmen des Behälters als Abschluss folgt in C2.
- **Lastprüfung beim „Weiter“ (K09-12)** braucht die Tara-Summe und folgt in C2; in C1 setzt „Weiter“ nur den neuen Bezug.
- **Mittelsmann (Modul 08):** neue öffentliche Methode `broadcast()` für die Live-Nachrichten `batch`/`orders` (eine Zeile, Verhalten sonst unverändert).
- Gesperrte und archivierte Rezepte können nicht als Auftrag angelegt werden (Vorwahl zeigt nur freigeschaltete, Modul 05); Unterrezepte dürfen gesperrt sein (R05-9).

## 20. Umsetzung Teil C2 (0.9.1) – Ergänzungen

Hinweise Claude zur Umsetzung (19.11.2026), im Rahmen des freigegebenen Konzepts; bei Einwand ändern:

- **Hintergrund:** `app/production/automation.py` prüft jede Waage alle 0,2 s (Auto-Quittung, 45-s-Pause, Abschluss durch Abnehmen, Behälter-Schritte, Live `weigh`). Die Wiegelogik ohne Datenbank steht in `weigh.py`.
- **Gesamtlast:** Die Software verfolgt die Tara der Waage (jede Tara/Null). Zeigt die Waage brutto, ist sie 0. Nach einem Neustart mit netto zeigender Waage ist sie unbekannt; dann rechnet die Höchstlast-Warnung mit der Anzeige, und die Lastprüfung beim „Weiter“ entfällt.
- **Lastprüfung (K09-12):** Der Stand beim Pausieren wird zusätzlich in `pause_load_g` gespeichert; geprüft wird nur an derselben Waage und ohne Neustart dazwischen.
- **Höchstlast vor der Zutat:** Gesamtlast plus alle noch offenen Rohstoffmengen des Teigs.
- **Protokoll:** `tare_g` = Tara gesamt (Tara der Waage + Bezug der Software); bei Teilmengen Vermerk „mit Teilmengen … g“ am Ereignis `weighed`.
- **Behälter wiegen:** Steht ein tarierter Behälter noch auf der Waage und ist die Gesamtlast bekannt, wartet die Software bei „Waage leeren“ (Schritt abbrechbar). „Ohne Behälter“ geht im Schritt „aufstellen“. Bestätigung „anderer Behälter“ nur beim Wechseln und nur, wenn ein Behältergewicht bekannt ist.
- **Abschließen von Hand** bleibt in der Schnittstelle immer möglich; das Tablet (Modul 10) kann die Taste auf „Waage getrennt“ beschränken.
- **Mittelsmann:** `broadcast()` ist jetzt auch aus Anfragen (Threads) sicher (Übergabe an die Ereignisschleife).
