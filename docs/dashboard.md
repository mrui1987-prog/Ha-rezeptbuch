# Modul 10 – Dashboard (Schritt B: Konzept)

Status: **Konzept erstellt am 19.11.2026, 13:05. Konzeptfragen K10-1 bis K10-8 am 13:08 wie vorgeschlagen entschieden (Michael: „Alles wie vorgeschlagen“). Konzept am 19.11.2026, 13:24 freigegeben (Michael: „Konzeptfrei“). Teil C1 (0.10.0) umgesetzt, siehe Abschnitt 13.**
Grundlage: Entscheidungen M10-1 bis M10-16 (docs/modulstatus-10.md, 12:37/12:46/12:56), docs/bedienkonzept.md (1–6), docs/architektur.md (2–5), docs/ablauf.md (11 REST/Live, 19 Umsetzung C1), docs/schnittstellen.md (6–9), docs/waage.md (5).
Zielversionen: Add-on 1 `rezeptbuch` **0.10.0 (C1), 0.10.1 (C2), 0.10.2 (C3)**, VC10-b als eigener Teil (0.10.3). Add-on 2 unverändert.

## 1. Zweck und Umfang

Tablet-Oberfläche für die Stationen `/station/1` und `/station/2` und einheitliche Gestaltung des Admin-Bereichs. **Die Oberfläche rechnet und entscheidet nichts**: Zustand, Toleranz, Auto-Quittung, Tara, Besitz und Sperren kommen vom Server (Modul 09). Fehlt eine Angabe zur Anzeige, wird sie in Modul 09 ergänzt (Abstimmung), nicht im Browser nachgebaut.

**Nicht enthalten:** Chargensuche, Protokoll, Druck (Modul 11), PIN ändern (Modul 12), neue Ablaufregeln (Modul 09).

## 2. Aufbau

```
 Tablet (Fully Kiosk) ──HA-Ingress──▶ Add-on 1
   station.html  ──REST /api/v1/orders…, /batches…, /stations…, /display/weather
                 ◀─Live /api/v1/live (scale, weigh, batch, orders, link, ping)
```

- **REST ist die Wahrheit, Live ist der Anstoß:** `weigh` und `scale` werden direkt gezeichnet; bei `batch`/`orders` lädt die Seite den betroffenen Stand per REST neu (`GET /api/v1/batches?station=`, `GET /api/v1/batches/{id}`, `GET /api/v1/orders`). So bleibt die Anzeige auch nach verpassten Nachrichten richtig.
- **Jede Taste** sendet einen REST-Aufruf mit Station und ist bis zur Antwort gesperrt (kein Doppeltippen, K10-8). Die Antwort liefert den neuen Stand.

## 3. Bildschirmaufteilung (Querformat, 1920 × 1200 als Bezug)

```
┌───────────────┬───────────────────────────────────────────┬─────────┐
│ 12:56  ← Uhr  │ Kopfzeile: Waage 1 · 112 Kernige · 48,5 kg │         │
├───────────────┤ · 3 Teige · nächster Auftrag …             │ Wiegen  │
│ Do 19.11.2026 ├───────────────────────────────────────────┤         │
│ 🌧 7 °C       │                                           │Übersicht│
│ 9° / 4°       │          Arbeitsfläche (Ansicht)          │         │
│ (Bild-im-Bild)│                                           │ Hinweis │
├───────────────┘                                           │         │
│                                                           │         │
├───────────────────────────────────────────────────────────┴─────────┤
│ Meldeleiste (nur wenn nötig: rot/orange/grau)                        │
├──────────────────────────────────────────────────────────────────────┤
│ Start │ Pause │ Abbruch │ Vorwahl │ Produktionsliste │ Chargen │ Menü🔒 │
└──────────────────────────────────────────────────────────────────────┘
```

- **Ecke oben links (M10-15):** 25 % Breite × 25 % Höhe. Erste Zeile **Uhrzeit** ganz oben am Rand (bleibt frei), darunter Datum und Wetter. Unterhalb der Uhrzeitzeile liegt nichts Bedienbares; das Bild-im-Bild-Fenster darf diesen Bereich überdecken.
- **Kopfzeile:** Stationsname, laufendes Rezept (Nummer, Kurzname), Teig x von n, Menge in kg, darunter nächster offener Auftrag.
- **Rechte Leiste:** Wiegen, Übersicht, Hinweis (Bedienkonzept 1).
- **Untere Leiste:** Start, Pause (rot, solange pausiert), Abbruch, Vorwahl, Produktionsliste, Chargen, Menü 🔒. Tasten, die gerade nicht gehen, sind grau statt ausgeblendet (feste Plätze).
- Mindestgröße einer Taste 12 mm, Soll/Ist-Ziffern mindestens 15 % der Bildschirmhöhe.

## 4. Ansichten der Arbeitsfläche

| Ansicht | Inhalt | Teil |
|---|---|---|
| **Startbild** | Waage groß (Gewicht, Status Bereit/Wiegen/Stopp), laufende/pausierte Chargen dieser und der anderen Station | C1 |
| **Wiegeansicht** | Zutat (Nummer, Kurzname) groß; Soll links, Ist rechts; Balken (K10-4); Rand um Ist füllt sich mit `auto_ack_progress`; Tasten Quittieren (nur grün), Tara, Übergehen, Behälter wiegen, Behälter wechseln, Handwaage | C1 |
| Sonderfälle Wiegeansicht | **Gebinde:** Schritt „1 Sack – quittieren“, dann Rest wiegen. **Handzugabe** (Toleranz 0 oder Menge 0): gelber Hinweis, Taste „Zugegeben“. **Unterrezept:** „+“-Zeile, Tasten „Unterrezept starten“/„Abhaken“. **Tara läuft** (`taring`): Ist grau „Tara …“. **Warten auf Nullpunkt:** Text aus `hint` | C1 |
| **Übersicht** | alle Zutaten des Teigs: Soll, Ist, Haken, Quittierungsart, Station; aktuelle Zutat hervorgehoben; nach Übernahme jede offene antippbar (`select`) | C1 |
| **Hinweis** | Rezepthinweis, Knetzeit (später Teigtemperatur/-ruhe) | C1 |
| **Abschluss** „Wiegevorgang abgeschlossen“ | Hinweise, Knetzeit langsam + schnell, Chargennummer; „Behälter abnehmen“ schließt ab (K09-10), sonst Taste „OK“ | C1 |
| **Fremde Charge** | an der anderen Station: grau „in Arbeit an Waage X – Zutat n von m“; pausiert: Taste „Übernehmen“ → Übersicht zur Zutatwahl (nicht bei „Fest an Waage“ oder Handwaage-Reservierung) | C1 |
| **Handbetrieb** | Gewicht groß, Tara, Null (Hinweis Z07-1 „nur bei leerer Waage“) | C1 |
| **Chargen** | heutige Chargen der Station, nur lesen (M10-11) | C1 |
| **Vorwahl** | Gruppen-Reiter + „Alle“, Suche Nummer/Name; Menge einfach, „Erweitert“ für Kombination/Faktor/Obergrenze/Teilungsart; Rückfragen V06; „Fest an dieser Waage“; danach Rezeptübersicht mit Leitrohstoff → Start | C2 |
| **Produktionsliste** | Aufträge des Tages, Status, „in Arbeit an Waage X“, Antippen → Details → Start; Unterrezept-Aufträge verknüpft | C2 |
| **Rezeptübersicht / Zusammenfassung** | eingeklappte Unterrezepte, Anteil, Bäcker %, Stückhinweis; je Teig / ganzer Auftrag | C2 |

## 5. Dialoge (eigene, keine Browser-Dialoge)

Ein gemeinsames Dialogfenster mit großem Text und höchstens drei Tasten. Verwendet für: Übergehen, Abbruch, Auftrag löschen (je „Ja/Nein“, `confirm: true`), Lastabweichung beim „Weiter“ (K09-12, „Trotzdem weiter“ → `confirm_deviation`), Behälter wiegen (Schritte nach K09-13 mit „Ohne Behälter“ und Zahlenfeld), Behälter wechseln (Schritte nach K09-14), Vorwahl-Rückfragen. Zahlenfeld als eigenes Tastenfeld (0–9, Komma, Löschen, g/kg).

## 6. Meldeleiste (M10-7, M10-8, B5)

Eine Zeile über der unteren Leiste, höchste Stufe gewinnt:

| Stufe | Auslöser | Text (Beispiel) | Wirkung |
|---|---|---|---|
| rot | REST 5xx / Health 503 | „Server-/Datenbankfehler – bitte Chef rufen“ | Tasten gesperrt |
| grau | Live-Verbindung weg (> 40 s ohne Nachricht oder Abbruch) | „Verbindung unterbrochen – verbinde neu …“ | Tasten gesperrt, Neuaufbau nach 1, 2, 5, 10 s |
| rot | Waage `offline` | broker: „Nachrichtendienst nicht erreichbar“ · bridge: „Waagen-Add-on läuft nicht“ · silent: „Waage sendet nicht“ · scale: „Waage aus oder nicht verbunden“ | Wiegen stoppt (Server pausiert nach 45 s) |
| orange | `invalid` / `error` | „Waage zeigt keinen gültigen Wert“ | – |
| orange | `capacity_warning` | „Waage fast voll – noch x kg“ | blockiert nichts |
| blau | 409 vom Server (z. B. andere Station war schneller) | Text aus der Antwort | Stand wird neu geladen |

## 7. Wetter, Datum, Uhrzeit (M10-16, entschieden 12:56)

- Uhrzeit (HH:MM) und Datum („Do, 19.11.2026“) aus der Tablet-Uhr, Aktualisierung jede Sekunde.
- **Server:** `app/display/weather.py` und `router.py`, `GET /api/v1/display/weather` ohne PIN:
  `{"available":true,"condition":"rainy","text":"Regen","temp_c":7,"max_c":9,"min_c":4,"updated_at":…}`; sonst `{"available":false}`.
- Abruf über die Supervisor-API mit `SUPERVISOR_TOKEN`: Zustand `GET http://supervisor/core/api/states/<entity>`, Tageswerte `POST http://supervisor/core/api/services/weather/get_forecasts?return_response` mit `{"entity_id":…, "type":"daily"}`. Zwischenspeicher 15 min, Zeitlimit 5 s, nur Standardbibliothek (`urllib` im Thread), keine neue Abhängigkeit.
- `config.yaml`: `homeassistant_api: true`, Option `weather_entity` (Schema `str?`, Vorgabe `weather.forecast_home`); leer, fehlend oder Fehler → `available: false`, Fehler nur im Protokoll (Stufe Warnung, höchstens einmal je 15 min).
- Symbol und Text aus den HA-Wetterzuständen (sunny → ☀ „Sonnig“, clear-night → 🌙 „Klar“, partlycloudy → ⛅ „Teils bewölkt“, cloudy → ☁ „Bewölkt“, rainy → 🌧 „Regen“, pouring → 🌧 „Starkregen“, snowy → ❄ „Schnee“, snowy-rainy → 🌨 „Schneeregen“, fog → 🌫 „Nebel“, hail → 🌨 „Hagel“, lightning/lightning-rainy → ⛈ „Gewitter“, windy/windy-variant → 💨 „Windig“, exceptional → ⚠ „Unwetter“). Tablet fragt alle 15 min.

## 8. Dateien

```
rezeptbuch/app/
├── web/router.py              + /station/{nr} (nr 1|2, sonst 404), + / (Stationswahl, K10-3)
├── web/static/station.html    Stationsoberfläche (C1/C2)
├── web/static/ui/common.css   gemeinsame Gestaltung (Stationen, in C3 auch Admin) – K10-2
├── web/static/ui/common.js    API-Basis aus eigener Adresse, Live-Kanal mit Neuaufbau, Dialog, Zahlenfeld, Meldeleiste
├── display/                   __init__.py, weather.py, router.py
└── config.yaml                homeassistant_api, Option weather_entity
rezeptbuch/tests/  test_display_weather.py (Zuordnung, Zwischenspeicher, ohne Token/Entität, Zeitüberschreitung),
                   test_web_station.py (Seiten werden ausgeliefert, nr-Prüfung, keine alert/confirm/prompt/innerHTML-mit-Daten)
```

Alle Daten werden nur als Text eingefügt (wie Modul 03/05).

## 9. Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| Station nicht eingerichtet (`not_configured`) | Hinweis „Waage 2 ist nicht eingerichtet“, nur Uhr/Wetter, Menü |
| Seite lädt ohne Netz | Meldeleiste grau, wiederholt selbst |
| Server neu gestartet | Live bricht ab → Neuaufbau → Schnappschuss → Stand per REST; pausierte Charge mit Grund `restart` zeigt „Weiter“ |
| Antwort 400 | Meldung aus der Antwort im Dialog |
| Wetter nicht verfügbar | Wetterzeile ausgeblendet, kein Fehler |

## 10. Teile

- **C1 (0.10.0):** Rahmen (Ecke, Kopf, Leisten, Meldeleiste), Wetter-Endpunkt, Startbild, Wiegeansicht mit allen Sonderfällen, Übersicht, Hinweis, Abschluss, Pause/Weiter/Übernahme, Abbruch, Behälter-Tasten, Handwaage, Handbetrieb, Chargen heute, Stationswahl.
- **C2 (0.10.1):** Vorwahl, Produktionsliste, Rezeptübersicht/Zusammenfassung, Unterrezept-Aufträge.
- **C3 (0.10.2):** Admin-Seiten auf `common.css`, einheitliche Kopf-/Reiterleiste, Meldetexte 05 (Liste vorab zur Abnahme).
- **VC10-b (0.10.3):** Felder Teigtemperatur/Teigruhe (Migration = nächste freie), Rezeptbearbeitung, Import/Export, Anzeige.

## 11. Praxisprüfung (Auszug, Galaxy Tab A + Fully Kiosk)

Kiosk-Start und Stationswahl, WebSocket über Ingress, Bild-im-Bild lässt Uhrzeit frei, Bildschirm bleibt an, Lesbarkeit aus 1 m, Bedienung mit Handschuh/Mehlfingern, Meldeleiste bei gezogenem Waagen-Add-on, Übergabe zwischen zwei Geräten (zweites Gerät: Handy/PC als Station 2).

## 12. Konzeptfragen (alle entschieden 19.11.2026, 13:08 wie vorgeschlagen, Michael)

| Nr. | Frage | Entscheidung |
|---|---|---|
| K10-1 | **Start und Zweig** | 09 C1 ist seit 12:50 in `main`. Zweig `modul10` jetzt von `main`, parallel zu 09 C2. Was C2-Verhalten braucht (Abnehmen schließt ab, Lastabweichung, Behälterwechsel), zeigt die Oberfläche, sobald die API es liefert. Versionsnummer 0.10.0 erst beim Übernehmen nach 0.9.1 in `main`. |
| K10-2 | **Dateiaufbau** | Abweichung von „eine Datei je Seite“ (Modul 03): `station.html` plus gemeinsame `ui/common.css` und `ui/common.js`, eingebunden mit **relativen** Pfaden (Ingress-sicher); in der Praxisprüfung C1 am Tablet bestätigen, bei Problemen zurück zu einer Datei. |
| K10-3 | **Zugang am Tablet (ändert M10-5 leicht)** | Die Ingress-Adresse enthält einen wechselnden Schlüssel, eine feste `/station/1`-Adresse im Kiosk geht daher nicht zuverlässig. Fully Kiosk öffnet die HA-Seite des Add-ons (`http://<HA>:8123/hassio/ingress/<slug>`, eigener HA-Benutzer fürs Tablet mit „Seitenleiste immer ausblenden“). Die Startseite fragt einmal „Welche Station ist dieses Gerät?“ und merkt es sich im Gerät; Umstellen nur über Menü 🔒. |
| K10-4 | **Balken bei großen Mengen** | Bei 25 kg ± 50 g wäre die grüne Zone unsichtbar. Darum zwei Balken: oben **Grob** 0 … Soll + 2 × Toleranz, darunter **Fein** Soll ± 4 × Toleranz (erscheint ab Soll − 4 × Toleranz); roter Soll-Strich in beiden. |
| K10-5 | **Fremde Charge auf dem Startbild** | Graue Karte mit Rezept, Teig, Zutat n von m und Station; bei Pause Taste „Übernehmen“. |
| K10-6 | **Wetteranzeige** | Symbol + Text, aktuelle Temperatur groß, darunter Höchst/Tiefst; Abruf alle 15 min (Abschnitt 7). |
| K10-7 | **Texte der Meldeleiste** | wie Abschnitt 6. |
| K10-8 | **Doppeltippen** | Taste bis zur Antwort gesperrt, Quittieren zusätzlich 1 s Sperre nach der Antwort. |

## 13. Umsetzung Teil C1 (0.10.0) – Hinweise Claude

Im Rahmen des freigegebenen Konzepts; bei Einwand ändern:

- **Start ohne Vorwahl:** Bis zur Vorwahl/Produktionsliste (C2) startet die Taste „Start“ den nächsten offenen Teig aus den Aufträgen von heute (kleinste Listenposition, nicht „fest an“ der anderen Waage). Aufträge werden bis dahin auf der Prüfseite „Ablauf“ angelegt.
- **Höchstlast-Leiste:** Die Live-Nachricht `weigh` liefert nur „Warnung ja/nein“, keine Restmenge; die Leiste zeigt daher „Waage fast voll – Höchstlast bald erreicht“ ohne „noch x kg“.
- **Behälter:** eine Taste „Behälter (… g)“ mit Auswahl „Behälter wiegen“ / „Gewicht eingeben“, dazu „Behälter wechseln“. Während eines Behälter-Schritts zeigt die Arbeitsfläche nur Anweisung, Gewicht und die passenden Tasten.
- **Startbild:** Waage im Handbetrieb mit Tara/Null (Null mit Rückfrage „Waage leer?“, Z07-1), darunter Karten der übrigen Teige (eigene pausierte mit „Weiter“, fremde pausierte mit „Übernehmen“, laufende/fertige grau).
- **Menü 🔒:** PIN über das eigene Zahlenfeld, danach „Admin-Bereich“ oder „Station dieses Geräts ändern“ (zurück zur Startseite mit Auswahl).
- **Startseite `/`:** öffnet die im Gerät gespeicherte Station, sonst Auswahl Waage 1/2; ersetzt die bisherige Statusseite (Link zum Admin-Bereich bleibt).
- **Sicherheitsnetz:** neben den Live-Nachrichten lädt die Seite den Stand alle 10 s neu.

## 14. Änderungen

| Datum | Änderung |
|---|---|
| 19.11.2026, 13:05 | Konzept erstellt (Claude). K10-1 bis K10-8 offen. |
| 19.11.2026, 13:08 | K10-1 bis K10-8 wie vorgeschlagen entschieden (Michael). K10-3 ändert M10-5: Kiosk öffnet die HA-Seite des Add-ons, das Gerät merkt sich seine Station. |
| 19.11.2026, 13:24 | Konzept freigegeben (Michael). |
| 19.11.2026 | Teil C1 (0.10.0) umgesetzt, Hinweise in Abschnitt 13. |
