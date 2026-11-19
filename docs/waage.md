# Modul 07 – Waagenkommunikation (Schritt B: Konzept)

Status: **Konzept erstellt am 18.11.2026, 21:00, von Michael am 18.11.2026, 21:12 freigegeben.** Konzeptfragen K07-1 bis K07-9 (Abschnitt 13) wie vorgeschlagen entschieden.
Grundlage: Entscheidungen M07-1 bis M07-14 und Test CONT (18.11.2026, docs/modulstatus-07.md Abschnitt 6), docs/feldtest.md (12./13.11.2026), docs/architektur.md (Abschnitte 2, 5, 6), docs/bedienkonzept.md (R4–R6, Handbetrieb), Code-Stand `main` 29aa529 (Add-on `rezeptbuch_waage` 0.1.0, Gerüst aus Modul 01).
Zielversion: Add-on `rezeptbuch_waage` **0.7.0** (Zweig `modul07`). Add-on 1 `rezeptbuch` bleibt unverändert.

## 1. Zweck und Umfang

Add-on 2 liest bis zu zwei KERN-Waagen und meldet je Station **Gewicht in ganzen Gramm, Stabilität und Status** per MQTT. Es kennt keine Rezepte, Aufträge oder Toleranzen und läuft auch ohne Add-on 1 (Simulator).

**Enthalten (Modul 07 = ganzes Add-on 2, M07-10)**
- Anbindung je Station wählbar: **TCP zum Waveshare (Standard)** oder **Roh-Topic der Waveshare-MQTT-Funktion** (M07-1).
- Telegramm der KERN KFB-TM im Sendemodus **CONT** lesen (`ST`/`US`, `G`/`N`, `-----`) (M07-2, Test 20:50).
- **Stabilität in der Software** (Fenster und Spanne je Station), Merker der Waage zusätzlich (M07-3).
- Status „ok“, „kein gültiger Wert“, „offline“, „Fehler“ (M07-5, M07-6).
- Melden bei Änderung, sonst mindestens 2× je Sekunde, Verfügbarkeit über Letzten Willen (M07-7).
- Befehle Tara (`T`) und Nullstellen (`Z`) empfangen und an die Waage senden (M07-4, M07-10).
- Simulator als zweiter Treiber (M07-9), dazu ein Waveshare-Ersatz zum Testen des TCP-Wegs (K07-7).
- Konfiguration mit deutschen Namen, Erklärung und Standardwert je Feld; Info-Felder Baudrate/Format/Sendemodus (M07-13).

**Nicht enthalten**
- Tara-Rechnung (netto = brutto − Tara), 4 s bis zur Auto-Quittung, 45 s bis Pause, Warnung Höchstlast → **Modul 09/10** (M07-3, M07-4, M07-6, M07-12).
- MQTT-Gegenstelle in Add-on 1, Live-Weitergabe an die Tablets, Topic-Doku für Nutzer → **Modul 08** (M07-10).
- Home-Assistant-Entitäten für die Waagen (M07-8). Die Test-Entitäten „Waage Test“ aus dem Feldtest bleiben unverändert bestehen.

## 2. Architektur

```
            ┌──────────── Add-on 2: rezeptbuch_waage ────────────┐
 Waveshare ─┤ Anschluss TCP ─┐                                   │
  (TCP)     │                ├─► Zeilen ─► KERN-Telegramm ─► Station ─► Melder ─┼─► MQTT …/scale/state
 Waveshare ─┤ Anschluss MQTT ┘   (CR LF)    (Gewicht, ST/US,  (Stabilität,       │
  (Roh-Topic)                                G/N, -----)       Status, Wächter)  │
            │ Treiber Simulator ─────────► (gleiche Zeilen) ──┘                  │
            │                                                                    │
            │ Befehle ◄── MQTT …/scale/cmd ◄── Modul 08/09 (Add-on 1)            │
            └─────────────────────────────────────────────────────────────────────┘
```

- **Eine Kette für alle Wege:** Anschluss (TCP, MQTT-Roh-Topic oder Simulator) liefert nur Bytes. Zerlegung in Zeilen, Auswertung, Stabilität, Status und Melden sind für alle Wege gleich (M07-1). Der Simulator erzeugt echte KERN-Zeilen, damit dieselbe Auswertung durchlaufen wird.
- **Je Station ein eigener Ablauf** (asyncio-Aufgabe); ein Fehler an Waage 2 berührt Waage 1 nicht.
- **Eine MQTT-Verbindung** für das ganze Add-on (paho-mqtt 2.1, wie im Gerüst). Zugangsdaten vom Supervisor (`services: mqtt:need`, Abfrage `http://supervisor/services/mqtt` mit `SUPERVISOR_TOKEN`), nie im Code oder in der Konfiguration.
- **Zeitquelle austauschbar:** Stabilität und Wächter rechnen mit einer übergebenen Uhr (monoton), damit die Tests ohne Warten auskommen.

## 3. Telegramm der Waage (Treiber `kern`)

Grundlage: Feldtest Abschnitt 4 und Test CONT (20:50).

| Zeile (vor CR LF) | Bedeutung | Ergebnis der Auswertung |
|---|---|---|
| `ST,G    0.077kg` | stabil (Merker), brutto | Gewicht 77 g, Merker stabil, brutto |
| `US,G    0.091kg` | instabil, brutto | Gewicht 91 g, Merker instabil, brutto |
| `ST,N    0.000kg` | netto nach `T` an der Waage | Gewicht 0 g, netto |
| `-----` | Überlast, Negativwert, starke Bewegung | **kein gültiger Wert** |
| alles andere | z. B. falsche Baudrate, abgeschnittene Zeile | **unlesbar** |

**Regeln der Auswertung**
- Zeilenende CR LF; einzelnes CR oder LF wird ebenfalls als Zeilenende angenommen. Leere Zeilen werden übersprungen.
- Kopf 1: `ST` oder `US`. Kopf 2: `G`/`GS` = brutto, `N`/`NT` = netto (Anleitung und Gerät weichen ab, Feldtest Widerspruch 7). Danach Vorzeichen oder Leerzeichen, Zahl mit Punkt, Einheit `kg`.
- Umrechnung in **ganze Gramm** exakt über Dezimalzahl (kein `float`), kaufmännisch gerundet (bei 3 Nachkommastellen und 1 g Auflösung tritt kein Runden auf).
- Ein Minuszeichen wird angenommen (Gewicht negativ), obwohl die Waage Negativwerte bisher nur als `-----` gesendet hat (Feldtest 11.2).
- Andere Einheit als `kg` → unlesbar.
- **Längenschutz:** Kommt 64 Zeichen lang kein Zeilenende, wird der Puffer verworfen (unlesbar). So kann eine falsche Baudrate den Speicher nicht füllen.
- Das Roh-Topic des Waveshare liefert Pakete nach 10 ms Pause (Feldtest 7). Ein Paket kann eine halbe oder mehrere Zeilen enthalten – die Zeilenzerlegung behandelt das wie den TCP-Strom.

## 4. Stabilität (M07-3)

**Definition:** Eine Station ist **stabil**, wenn seit mindestens **Fenster** (Standard 1000 ms) nur gültige Gewichte gekommen sind und deren größter und kleinster Wert in diesem Fenster höchstens um die **Spanne** (Standard 2 g) auseinanderliegen.

- Ein `-----`, eine unlesbare Zeile, „offline“ oder ein Wechsel brutto/netto **setzt die Prüfung zurück** (das Fenster beginnt neu).
- Gemeldet wird der **zuletzt gelesene Wert**, nicht ein Mittelwert (K07-5).
- Der Merker der Waage (`ST`/`US`) wird zusätzlich als `scale_stable` gemeldet, entscheidet aber nichts.
- Bei 1 g Auflösung und Linearität ±4 g sind 2 g in 1 s ein vorsichtiger Startwert; die Werte werden in der Praxisprüfung mit echten Rohstoffen eingestellt (Protokollstufe `debug` zeigt die Spanne je Fenster).
- Die **4 s bis zur automatischen Quittung zählt Modul 09** ab dem ersten `stable: true` innerhalb der Toleranz.

## 5. Status und Überwachung (M07-5, M07-6)

| Status (`status`) | Anzeige (Modul 10) | Wann | `weight_g` | `stable` |
|---|---|---|---|---|
| `ok` | „bereit“ | gültiges Gewicht gelesen | Zahl | nach Abschnitt 4 |
| `invalid` | „kein gültiger Wert“ | letzte Zeile war `-----` | leer | immer `false` |
| `offline` | „Waage getrennt“ | seit **5 s** (einstellbar) keine Zeile, oder noch nie eine | leer | immer `false` |
| `error` | „Waage liefert unlesbare Daten“ | seit 3 s nur unlesbare Zeilen (K07-6) | leer | immer `false` |

```
 offline ──Zeile──► ok ◄──► invalid
    ▲                │         │
    └── 5 s keine Zeile / Verbindung weg ┘
 ok/invalid ──3 s nur unlesbar──► error ──gültige Zeile──► ok/invalid
```

- **Lebenszeichen** ist jede empfangene Zeile, auch `-----` und unlesbare Zeilen. `-----` ist **kein Ausfall** (M07-5).
- **„offline“ nach 5 s** gilt für beide Wege gleich. Bricht die TCP-Verbindung ab, wird sofort neu verbunden (Wartezeit 1, 2, 5, dann alle 10 s); gelingt das innerhalb der 5 s, bleibt der Status unverändert. Beim MQTT-Weg gibt es keinen Verbindungsabbruch zur Waage zu erkennen (Waveshare ohne Letzten Willen, Feldtest 7), dort zählt nur „keine Zeile“.
- Die **45 s bis zur Pause zählt Modul 09 ab „offline“** (M07-6).
- Beim Start ist jede Station `offline`, bis die erste Zeile kommt.

## 6. Schnittstelle MQTT (Abstimmung mit Modul 08)

Topics nach Konvention `rezeptbuch/v1/station/<nr>/scale/<wert>` (Architektur 6). Die Feldtest-Topics `rezeptbuch/test/waage1/…` sind nur das **Roh-Topic des Waveshare** beim MQTT-Weg (M07-13), nie Ausgabe des Add-ons.

### 6.1 Zustand – `rezeptbuch/v1/station/<nr>/scale/state`

QoS 0, nicht „retained“ (M07-7). **Schema 2** (K07-1):

```json
{"v": 2, "station": 1, "status": "ok", "weight_g": 9500, "stable": true,
 "scale_stable": true, "net": false, "capacity_g": 30000, "resolution_g": 1,
 "ts": "2026-11-18T20:00:00.123+00:00"}
```

| Feld | Inhalt |
|---|---|
| `v` | Schema-Version, **2** (neu: Status `invalid`, Felder `scale_stable`, `net`, `capacity_g`, `resolution_g`) |
| `station` | 1 oder 2 |
| `status` | `ok`, `invalid`, `offline`, `error` (Abschnitt 5) |
| `weight_g` | Ganzzahl in Gramm (auch negativ möglich) oder `null` außer bei `ok` |
| `stable` | Stabilität aus der Software (Abschnitt 4); `false` außer bei `ok` |
| `scale_stable` | Merker der Waage `ST` = `true`, `US` = `false`; `null` ohne gültige Zeile |
| `net` | `true`, wenn die Waage netto meldet (nach `T` an der Waage); `null` ohne gültige Zeile. Im Normalbetrieb `false` (Waage bleibt brutto, M07-4) |
| `capacity_g`, `resolution_g` | Höchstlast und Auflösung aus der Konfiguration (M07-12), Standard 30 000 und 1 |
| `ts` | Zeitpunkt der zugrunde liegenden Zeile (UTC, Millisekunden); bei `offline` Zeitpunkt der Meldung |

**Melderegel (M07-7):** sofort bei Änderung von `status`, `weight_g`, `stable`, `scale_stable` oder `net`; sonst Wiederholung alle **500 ms** (fest). Die Waage sendet in CONT ca. 10 Zeilen/s, also höchstens ca. 10 Meldungen/s je Station.

### 6.2 Verfügbarkeit – `rezeptbuch/v1/scale_bridge/availability`

`online` beim Verbinden, `offline` als Letzter Wille (K07-2). QoS 1, „retained“, damit Add-on 1 auch nach eigenem Neustart weiß, ob Add-on 2 läuft. Ist Add-on 2 weg, gelten beide Stationen für Modul 09 als offline.

### 6.3 Befehle – `rezeptbuch/v1/station/<nr>/scale/cmd`

```json
{"v": 2, "cmd": "tare"}
```

| `cmd` | an die Waage | Wirkung (Feldtest 5) |
|---|---|---|
| `tare` | `T` + CR LF | Waage tariert, meldet danach netto (`net: true`) |
| `zero` | `Z` + CR LF | Waage stellt auf 0, brutto |

- Angenommen nur, wenn die Station Zeilen liefert (`ok`, `invalid` oder `error`); bei `offline` verworfen mit Protokolleintrag. `zero` bei `invalid` ist gewollt (Feldtest: `Z` bei −77 g).
- **Mindestabstand 1 s** zwischen zwei Befehlen an dieselbe Waage (Feldtest 11.4: schnelle Befehle gingen teils verloren). Weitere Befehle warten, höchstens einer je Art; doppelte werden zusammengefasst.
- **Keine eigene Bestätigung** (K07-3): Die Waage bestätigt nicht; die Wirkung zeigt der nächste Zustand (`net`, Gewicht 0).
- Unbekannte Befehle, falsches JSON oder falsche Version → verworfen mit Protokolleintrag.
- Beim MQTT-Weg wird der Befehl auf das Befehls-Topic des Waveshare veröffentlicht (Feldtest: `rezeptbuch/test/waage1/cmd`), beim TCP-Weg über die offene Verbindung geschrieben, beim Simulator vom Simulator ausgeführt.

**Hinweis Modul 09/10:** Im Wiegeablauf und im Handbetrieb tariert die Software (M07-4). `tare` an die Waage führt nach dem Abnehmen des Behälters zu `-----`; es ist nur für Sonderfälle gedacht.

## 7. Konfiguration (M07-13)

**Flach je Waage statt Liste** (K07-4): Home Assistant zeigt deutsche Namen und Erklärungen nur für Felder der obersten Ebene zuverlässig an. Jedes Feld bekommt in `translations/de.yaml` einen deutschen Namen mit Standardwert, z. B. „Waage 1 – Baudrate (Standard 9600)“, und eine kurze Erklärung.

| Feld (Code) | Name in HA | Standard Waage 1 | Standard Waage 2 | Erklärung |
|---|---|---|---|---|
| `scale1_enabled` | Waage 1 – aktiv | ja | nein | Station verwenden |
| `scale1_driver` | – Treiber | `kern` | `kern` | `kern` = echte Waage, `simulator` = Testbetrieb ohne Waage |
| `scale1_connection` | – Anbindung | `tcp` | `tcp` | `tcp` = direkt zum Waveshare (empfohlen), `mqtt` = Roh-Topic des Waveshare (wie im Feldtest) |
| `scale1_host` | – Adresse des Waveshare | leer | leer | IP-Adresse oder Name, nur bei TCP; **trägt Michael selbst ein** |
| `scale1_port` | – TCP-Port | 8899 | 8899 | TCP-Server des Waveshare, ab Werk 8899 (K07-9) |
| `scale1_raw_topic` | – Roh-Topic | `rezeptbuch/test/waage1/raw` | `rezeptbuch/test/waage2/raw` | Pub Topic des Waveshare, nur bei MQTT |
| `scale1_cmd_topic` | – Befehls-Topic | `rezeptbuch/test/waage1/cmd` | `rezeptbuch/test/waage2/cmd` | Sub Topic des Waveshare, nur bei MQTT |
| `scale1_baud` | – Baudrate (Info) | 9600 | 9600 | nur Anzeige und Prüfhilfe, einstellen an Waage und Waveshare |
| `scale1_format` | – Datenformat (Info) | `8n1` | `8n1` | wie oben (`7E1`, `7o1`, `8n1`) |
| `scale1_mode` | – Sendemodus (Info) | `CONT` | `CONT` | wie oben (`CONT`, `STC`); ASK wird nicht unterstützt |
| `scale1_stable_window_ms` | – Stabil: Zeitfenster | 1000 | 1000 | 200–5000 ms |
| `scale1_stable_span_g` | – Stabil: erlaubte Schwankung | 2 | 2 | 0–50 g |
| `scale1_offline_after_s` | – Offline nach | 5 | 5 | 2–30 s ohne Zeile |
| `scale1_capacity_g` | – Höchstlast | 30000 | 30000 | Gramm, für die Warnung in Modul 09/10 |
| `scale1_resolution_g` | – Auflösung | 1 | 1 | Gramm |
| `log_level` | Protokollstufe | `info` | | `debug` zeigt jede Zeile und die Stabilitätsspanne |

Waage 2 hat dieselben Felder mit `scale2_…`. **Keine IP-Adressen und Passwörter im Repo** (feldtest.md, Datenschutz); Adresse trägt Michael in HA ein.

**Prüfung beim Start:** Fehlt bei TCP die Adresse oder bei MQTT ein Topic, startet die Station nicht (Status `error`, deutliche Meldung im Protokoll), die andere Station läuft weiter. Ist keine Station aktiv, meldet das Protokoll das und das Add-on wartet.

**Info-Felder als Prüfhilfe:** Beim Start stehen Baudrate, Format und Modus im Protokoll. Bei Status `error` (unlesbare Zeilen) nennt die Meldung die erwarteten Werte („Waage 1 liefert unlesbare Daten – Baudrate 9600 und Format 8n1 an Waage und Waveshare prüfen“). Bei `offline` mit verbundenem TCP: „keine Zeilen – Sendemodus CONT an der Waage prüfen“. Bei Modus `STC` Hinweis im Protokoll, dass die Waage keine instabilen Werte sendet.

## 8. Simulator (M07-9, K07-7)

**Treiber `simulator` im Add-on:** erzeugt KERN-Zeilen im CONT-Takt (10 Zeilen/s) und reagiert auf `tare`/`zero`. Ablauf in Schleife (ca. 60 s): leer → Behälter (1 200 g) → langsames Befüllen bis 5 000 g mit Schwanken → ruhig → kurz `-----` (Bewegung) → Abnehmen → kurzer Ausfall (8 s keine Zeilen, damit „offline“ sichtbar wird). Für Modul 09/10 reicht das zum Entwickeln ohne Waage.

**Werkzeug `tools/waagen_simulator/simulator.py`:** kleiner TCP-Server, der sich wie ein Waveshare mit KERN-Waage verhält (gleicher Simulator-Kern), um den TCP-Weg ohne Hardware zu prüfen, z. B. auf dem PC: `python simulator.py --port 8899`. Nicht Teil des Add-on-Abbilds.

## 9. Verzeichnisstruktur

```
rezeptbuch_waage/
├── config.yaml            0.7.0, Felder aus Abschnitt 7
├── translations/de.yaml   deutscher Name + Erklärung je Feld
├── DOCS.md                Einrichtung TCP/MQTT, Felder, Schnittstelle, Fehlerbilder
├── Dockerfile · build.yaml · requirements.txt   (unverändert, paho-mqtt 2.1)
├── app/
│   ├── __init__.py        __version__ = "0.7.0"
│   ├── main.py            Start, Konfiguration, Stationen, MQTT, sauberes Beenden
│   ├── config.py          Felder lesen und prüfen → StationConfig je Waage
│   ├── messages.py        Schema 2: Zustand, Befehl, Verfügbarkeit, Topics
│   ├── kern.py            Zeilenzerlegung und KERN-Telegramm → Reading
│   ├── stability.py       Fenster/Spanne
│   ├── station.py         Status, Wächter, Melderegel, Annahme der Befehle
│   ├── commands.py        Befehlswarteschlange (1 s Abstand, zusammenfassen) – seit 0.7.4
│   ├── transport_tcp.py   TCP-Anschluss mit Neuaufbau
│   ├── transport_mqtt.py  Roh-Topic-Anschluss
│   ├── mqtt_client.py     Broker-Verbindung (Supervisor), Letzter Wille
│   └── simulator.py       Simulator-Kern
└── tests/                 test_kern, test_stability, test_station, test_config,
                           test_messages, test_transport_tcp, test_transport_mqtt,
                           test_simulator
tools/waagen_simulator/    simulator.py, README.md, test_simulator_tool.py
docs/waage.md              dieses Konzept
```

Add-on 1 (`rezeptbuch/`) wird nicht angefasst.

## 10. Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| Waveshare per TCP nicht erreichbar | Status `offline`, Neuaufbau 1/2/5/10 s, Protokoll „Waage 1: keine Verbindung zu …:8899“ (einmal je Ausfall, nicht bei jedem Versuch) |
| Verbindung bricht ab | sofort Neuaufbau; erst nach 5 s ohne Zeile `offline` |
| keine Zeilen trotz Verbindung | nach 5 s `offline`, Hinweis Sendemodus |
| `-----` | Status `invalid`, kein Ausfall |
| unlesbare Zeilen | einzeln verworfen (Protokoll `debug`); 3 s nur unlesbar → `error` mit Hinweis Baudrate/Format |
| MQTT-Broker weg | paho baut selbst neu auf; Zustände werden in der Zeit verworfen (Live-Werte, kein Nachsenden); nach dem Neuaufbau `online` und aktueller Zustand |
| Supervisor liefert keine MQTT-Daten | Fehlermeldung „MQTT-Dienst nicht gefunden – Mosquitto installiert?“, neuer Versuch alle 30 s |
| Befehl bei `offline` / ungültiger Befehl | verworfen, Protokolleintrag |
| Fehler in einer Station | nur diese Station `error`, die andere läuft weiter; unerwartete Ausnahme wird protokolliert und die Station neu gestartet |
| falsche Konfiguration | Station startet nicht, klare Meldung; HA prüft Wertebereiche schon beim Speichern |
| Add-on beendet | Verfügbarkeit `offline` (sauber oder über Letzten Willen) |

## 11. Tests (Schritt D, Vorschau)

**Automatisch (GitHub):** Telegramme aus dem Feldtest (`ST,G    0.077kg`, `ST,N    0.000kg`, `US`, `-----`, `GS`/`NT`, Minus, falsche Einheit, Müll, überlange Zeile, geteilte und gebündelte Pakete); Stabilität mit Uhr-Attrappe (stabil nach 1 s, Rücksetzen durch `-----`/Wechsel netto, Spanne genau 2 g/3 g); Status-Übergänge und 5-s-Wächter; Melderegel (Änderung sofort, sonst 500 ms); Befehle (Abstand 1 s, Zusammenfassen, Verwerfen bei offline); Schema 2; Konfigurationsprüfung; TCP-Anschluss gegen lokalen Testserver (Abbruch, Neuaufbau); MQTT-Weg mit nachgebildetem Client; Simulator-Ablauf.

**Praxisprüfung (Michael, HA):** Add-on 0.7.0 mit echter Waage zuerst über **MQTT-Weg** (jetzige Feldtest-Einstellung), dann über **TCP** (Waveshare auf TCP-Server Port 8899, MQTT am Waveshare aus); Zustand ansehen in HA unter Einstellungen → Geräte & Dienste → MQTT → Konfigurieren → „Auf ein Topic hören“ `rezeptbuch/v1/station/1/scale/state`; Waage belasten/entlasten, Wackeln, Negativwert, Netzstecker Waveshare ziehen, `tare`/`zero` senden (auch schnell hintereinander, Feldtest 11.4), **Startwerte Stabilität** mit Mehl, Wasser und kleinen Mengen einstellen.

## 12. Umsetzung (Vorschlag)

| Teil | Inhalt | Version |
|---|---|---|
| C1 | Konfiguration, KERN-Telegramm, Stabilität, Status/Wächter, Schema 2, MQTT-Verbindung mit Letztem Willen, TCP- und MQTT-Weg, Simulator-Treiber, DOCS.md | 0.7.0 |
| C2 | Befehle `tare`/`zero` mit Warteschlange, Werkzeug `tools/waagen_simulator`, Korrekturen aus der Praxisprüfung | 0.7.1 → **0.7.4** (0.7.1–0.7.3 für Korrekturen aus der Praxisprüfung C1 verbraucht) |

Je Teil: Zweig `modul07`, Tests, GitHub-Testlauf, Praxisprüfung, dann `main` (nach Freigabe Michael). Erst wenn auch Modul 08 die Gegenstelle hat, wird der Zustand im Rezeptbuch sichtbar.

**Verbleibende kurze Tests aus Schritt A (Vorschlag K07-8):** `W`/`S` entfallen (CONT sendet von selbst); `0rAGE` nur ablesen und in feldtest.md notieren; schnelle Befehle und Startwerte Stabilität in der Praxisprüfung.

## 13. Konzeptfragen (entschieden 18.11.2026, 21:12, Michael: „Vorschläge passen, Konzept freigeben“)

| Nr. | Frage | Entscheidung (wie vorgeschlagen) |
|---|---|---|
| K07-1 | **Schema-Erweiterung (M07-5)** – berührt Modul 08 | **Schema 2** wie Abschnitt 6.1: neuer Status `invalid`, neue Felder `scale_stable`, `net`, `capacity_g`, `resolution_g`; Topic-Präfix bleibt `rezeptbuch/v1`. Modul 08 ist noch nicht begonnen, Add-on 1 liest noch nichts – die Änderung kostet dort nichts. `messages.py` verlangt bei Formatänderung eine neue Schema-Nummer. |
| K07-2 | **Verfügbarkeit (Letzter Wille)** | Ein gemeinsames Topic `rezeptbuch/v1/scale_bridge/availability` (`online`/`offline`, retained), weil eine MQTT-Verbindung nur einen Letzten Willen hat. |
| K07-3 | **Befehle** | JSON `{"v":2,"cmd":"tare"/"zero"}`, keine eigene Bestätigung, Mindestabstand 1 s, nur wenn Zeilen kommen. |
| K07-4 | **Konfiguration flach** | Felder `scale1_…`/`scale2_…` statt der Liste aus dem Gerüst, damit jedes Feld einen deutschen Namen und eine Erklärung bekommt (M07-13). |
| K07-5 | **Gemeldetes Gewicht** | Zuletzt gelesener Wert (kein Mittelwert); Startwerte Stabilität 1000 ms / 2 g, Feinabstimmung in der Praxisprüfung. |
| K07-6 | **Unlesbare Zeilen** | Zählen als Lebenszeichen; nach 3 s nur unlesbar Status `error` mit Hinweis auf Baudrate/Format. |
| K07-7 | **Simulator** | Treiber im Add-on **und** Waveshare-Ersatz als Werkzeug (`tools/waagen_simulator`, war in Modul 01 schon vorgesehen). |
| K07-8 | **Umsetzung und Resttests** | Zwei Teile C1 (0.7.0) und C2 (0.7.1); `W`/`S` nicht mehr testen; `0rAGE` nur ablesen. |
| K07-9 | **TCP-Port** | Standard **8899** (Werkseinstellung Waveshare) statt 4196 aus dem Gerüst. |

## 14. Auswirkungen auf andere Module

- **Modul 08:** liest Schema 2 und das Verfügbarkeits-Topic, sendet Befehle nach 6.3 (Abstimmung über K07-1 bis K07-3).
- **Modul 09:** Tara in der Software, 4 s ab `stable: true`, 45 s ab `offline` (oder Verfügbarkeit `offline`), Warnung bei `weight_g` > `capacity_g`; `invalid` ist kein Ausfall; `net: true` als Hinweis behandeln.
- **Modul 10:** Statusanzeigen nach Abschnitt 5; Admin „Waagen – Verbindung prüfen“ (Bedienkonzept 6) nutzt den Zustand.
- **Modul 14:** vor Echtbetrieb MQTT-Passwort der Waage und Waveshare-Login ändern (unverändert).
- **Doku:** docs/architektur.md 8.2 (KERN-Modell) erledigt, Hinweis zu M07-1 ergänzt; docs/feldtest.md 11.1 nachgetragen.

## 15. Änderungen

| Datum | Änderung |
|---|---|
| 18.11.2026, 21:00 | Konzept erstellt (Schritt B), Konzeptfragen K07-1 bis K07-9 offen. |
| 18.11.2026, 21:12 | **Konzept von Michael freigegeben**, K07-1 bis K07-9 wie vorgeschlagen entschieden. Damit gilt Schema 2 auch als Abstimmung mit Modul 08 (K07-1 bis K07-3). |
| 19.11.2026 | **Teil C2 umgesetzt als 0.7.4** (Auftrag Michael): Befehle nach 6.3, Warteschlange in eigener Datei `app/commands.py` (statt in `station.py`), Werkzeug `tools/waagen_simulator` mit Option `--fest`; eigener GitHub-Testlauf für das Werkzeug. Keine Entscheidung geändert. |
