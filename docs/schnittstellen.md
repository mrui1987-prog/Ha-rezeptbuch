# Modul 08 – MQTT- & Kommunikationsschnittstellen (Konzept und Schnittstellen-Doku)

Status: **Konzept erstellt am 19.11.2026, 09:40, von Michael am 19.11.2026, 09:41 freigegeben** („Konzept frei, K08 wie vorgeschlagen“). Konzeptfragen K08-1 bis K08-8 (Abschnitt 14) wie vorgeschlagen entschieden. **Umgesetzt in Teil C1 (Add-on 1 0.8.0, Zweig `modul08`), Praxisprüfung offen.**
Grundlage: Entscheidungen M08-1 bis M08-13 (docs/modulstatus-08.md, 19.11.2026, 08:42/09:28), docs/waage.md (Schema 2, Abschnitte 5, 6), docs/architektur.md (Abschnitte 2, 4, 6), docs/bedienkonzept.md (Abschnitt 6 „Waagen“), docs/datenmodell.md (Tabelle `station`).
Zielversion: Add-on 1 `rezeptbuch` **0.8.0** (Zweig `modul08`). Add-on 2 bleibt unverändert (0.7.6).

## 1. Zweck und Umfang

Add-on 1 bekommt eine Waagen-Anbindung: Es empfängt den Zustand beider Stationen von Add-on 2, sendet `tare`/`zero` und gibt den Zustand live an Tablets und Prüfseite weiter.

**Enthalten (M08-1):** MQTT-Client, Mittelsmann (M08-7), Offline-Regel (M08-4), REST-Waagenendpunkte (M08-5), WebSocket `/api/v1/live` (M08-6), Prüfseite `/admin/waagen` (M08-11), Health-Erweiterung (M08-10), Doku (M08-12).
**Nicht enthalten:** Wiegeablauf, Tara-Rechnung, 4 s / 45 s (Modul 09); Tablet-Oberfläche (Modul 10); HA-Entitäten; Änderungen an Add-on 2.

## 2. Architektur

```
 Add-on 2 ──MQTT──► Mosquitto ──MQTT──┐
                                      │  Add-on 1: rezeptbuch
                       ┌──────────────▼──────────────┐
                       │ MQTT-Verbindung (paho, Thread)│
                       └──────────────┬──────────────┘
                                      ▼ (an asyncio übergeben)
                       ┌─────────────────────────────┐
                       │ Mittelsmann (ScaleHub)      │  Zustand je Station,
                       │                             │  Offline-Regel, Befehle
                       └──┬──────────┬───────────┬───┘
                          ▼          ▼           ▼
                    REST /api/v1  WebSocket   Modul 09 (später)
                    /stations…    /api/v1/live
                          ▼          ▼
                     Prüfseite /admin/waagen, Tablets (Modul 10)
```

- **Ein Mittelsmann** ist der einzige Ort, der MQTT kennt (M08-7). REST, WebSocket und später Modul 09 fragen nur ihn.
- **paho-mqtt läuft in seinem eigenen Thread** (`loop_start`); eingehende Nachrichten werden mit `call_soon_threadsafe` an die asyncio-Schleife von FastAPI übergeben. Der Zustand wird nur in der asyncio-Schleife geändert → keine Sperren nötig.
- Zustand **nur im Speicher** (M08-3). Nach einem Neustart sind alle Stationen `offline`, bis der erste Zustand kommt (Add-on 2 sendet alle 500 ms).

## 3. Zustand je Station (Mittelsmann)

| Feld | Bedeutung |
|---|---|
| `station` | 1 oder 2 |
| `name` | Name aus Tabelle `station` (z. B. „Waage 1“) |
| `configured` | Station in Tabelle `station` aktiv (M08-9) |
| `status` | `ok`, `invalid`, `error`, `offline` – wie Add-on 2, aber **nach der Offline-Regel von Add-on 1** (Abschnitt 4) |
| `offline_reason` | leer oder `scale` (Add-on 2 meldet die Waage offline), `bridge` (Add-on 2 weg), `broker` (MQTT getrennt), `silent` (3 s kein Zustand) |
| `offline_since` | Zeitpunkt des Übergangs nach `offline` (für die 45 s in Modul 09), sonst leer |
| `weight_g`, `stable`, `scale_stable`, `net`, `capacity_g`, `resolution_g` | unverändert aus Schema 2; bei `offline` `weight_g` leer, `stable` falsch |
| `ts` | Zeitstempel aus Add-on 2 |
| `received_at` | Empfangszeit in Add-on 1 |

Zeiten intern UTC (ISO 8601), Anzeige in Ortszeit (wie im übrigen Projekt).

**Schnittstelle für Modul 09 (M08-7, `app/scales/hub.py`):**
- `current_state(station) → StationScale` (unveränderlich)
- `subscribe() → asyncio.Queue` mit jeder Änderung (`{"type":"scale", …}` und `{"type":"link", …}`, inkl. Übergang nach/aus `offline`); `unsubscribe(queue)`
- `send_command(station, "tare" | "zero") → Ergebnis` (`sent`, `offline`, `not_configured`, `mqtt_down`, `unknown_station`)

## 4. Offline-Regel (M08-4)

Eine Station ist in Add-on 1 `offline`, sobald eines gilt (Grund in `offline_reason`, Vorrang in dieser Reihenfolge):
1. MQTT-Verbindung von Add-on 1 getrennt oder nicht verfügbar → `broker` (alle Stationen)
2. Verfügbarkeit `rezeptbuch/v1/scale_bridge/availability` = `offline` → `bridge` (alle Stationen)
3. **seit 3 s kein Zustand** für diese Station → `silent` (Wächter prüft alle 250 ms)
4. Add-on 2 meldet für sie `status: offline` → `scale`

Zurück zu `ok`/`invalid`/`error` mit dem nächsten gültigen Zustand; `offline_since` wird dann geleert. Bleibt die Station offline und ändert sich nur der Grund, bleibt `offline_since` erhalten.
`invalid` und `error` sind **kein** Offline (wie Modul 07).

## 5. MQTT

| Punkt | Festlegung |
|---|---|
| Zugang (M08-2) | `services: mqtt:need` in `config.yaml`; Zugangsdaten über `http://supervisor/services/mqtt` mit `SUPERVISOR_TOKEN` (aus Umgebung, sonst s6-Datei – Erfahrung aus 0.7.1); nichts im Code oder in der Konfiguration |
| Abos | `rezeptbuch/v1/station/+/scale/state` (QoS 0), `rezeptbuch/v1/scale_bridge/availability` (QoS 1, retained) |
| Befehle | `rezeptbuch/v1/station/<nr>/scale/cmd`, `{"v":2,"cmd":"tare"|"zero"}`, **QoS 1, nie retained** (K08-1) |
| Client-ID | `rezeptbuch-addon1` (eigener Name, kein Konflikt mit Add-on 2) |
| Neuaufbau | paho selbst; Supervisor ohne MQTT-Dienst → Meldung „MQTT-Dienst nicht gefunden – Mosquitto installiert?“, neuer Versuch alle 30 s (wie Add-on 2) |
| Eingangsprüfung (M08-8) | nur gültiges JSON, `v` = 2, Station 1/2 passend zum Topic, `status` bekannt; sonst verworfen, Protokolleintrag höchstens 1× je Minute je Fehlerart |

**Code-Herkunft (K08-3):** Supervisor-Abfrage und Token-Lesen werden aus Add-on 2 übernommen (kopiert, mit eigenen Tests). Ein gemeinsames Paket lohnt bei zwei getrennt gebauten Add-ons nicht.

## 6. REST-Endpunkte (M08-5, ohne PIN)

| Methode, Pfad | Antwort |
|---|---|
| `GET /api/v1/stations` | `{"mqtt", "bridge", "stations": [...]}` – alle Stationen aus Tabelle `station` plus Stationen, für die Zustand kommt, je mit Zustand nach Abschnitt 3; `mqtt: connected|disconnected|unavailable`, `bridge: online|offline|unknown` |
| `GET /api/v1/stations/{nr}/scale` | Zustand einer Station; 404 `unknown_station` |
| `POST /api/v1/stations/{nr}/scale/tare` | 202 `{"result":"sent","detail":…}`; 409 `offline` oder `not_configured`; 503 `mqtt_down`; 404 `unknown_station` |
| `POST /api/v1/stations/{nr}/scale/zero` | wie `tare` |

„Gesendet“ heißt nicht „ausgeführt“: Add-on 2 kann `zero` ablehnen (über ±50 g, Z07-1/Z07-2) und meldet das nur im eigenen Protokoll (K07-3). Die Wirkung zeigt der nächste Zustand. Antworttext enthält diesen Hinweis.

**Nicht eingerichtete Station (M08-9, K08-5):** wird angezeigt, Befehle werden mit `not_configured` abgelehnt.

## 7. Live-Kanal WebSocket `/api/v1/live` (M08-6)

- Ohne PIN; läuft über HA-Ingress (Tablets sind ohnehin per HA angemeldet). Aufruf mit **relativem Pfad** (Ingress-Präfix), `wss://` bei HTTPS.
- **Beim Verbinden:** `{"type":"link","mqtt":…,"bridge":…}` und Schnappschuss aller Stationen (`{"type":"scale","station":…, …Zustand}` je Station).
- **Danach:** eine Nachricht je Änderung (Felder wie REST; eine reine Wiederholung mit neuer Zeit zählt nicht als Änderung) und `link` bei Änderung von MQTT/Waagen-Add-on. Höchstens ca. 10 je Sekunde und Station (Add-on 2 sendet nicht mehr). Langsamer Empfänger: je Verbindung höchstens 200 Meldungen gepuffert, die ältesten fallen weg.
- **Herzschlag:** `{"type":"ping"}` alle 15 s ohne andere Meldung, damit Ingress/Proxy die Verbindung nicht schließen und das Tablet einen Abbruch erkennt (K08-2). Die Prüfseite baut nach 40 s ohne Nachricht neu auf.
- Der Client sendet nichts (Befehle laufen über REST). Er baut bei Abbruch selbst neu auf und bekommt dann wieder den Schnappschuss.
- **Erweiterbar:** Modul 09 ergänzt eigene Nachrichtentypen (z. B. `"type":"batch"`); Format `type` + Daten bleibt.
- Unter uvicorn braucht der WebSocket die Bibliothek `websockets` (in `requirements.txt`).
- **Zu prüfen in der Praxisprüfung:** WebSocket über Ingress in der HA-App (iOS) und im Tablet-Browser.

## 8. Stationen (M08-9)

- Maßgeblich ist Tabelle `station` (`active = 1`). Gelesen beim Start und dann alle 30 s (Änderungen kommen später aus dem Admin-Bereich, Modul 10).
- Waagenparameter (IP, Port, Stabilität, Höchstlast) nur in Add-on 2; `capacity_g`/`resolution_g` kommen über Schema 2.

## 9. Ohne MQTT (M08-10)

- Add-on 1 startet und läuft auch ohne Broker oder ohne MQTT-Dienst; Rezepte, Rohstoffe, Berechnung unverändert.
- Stationen: `offline`, Grund `broker`; Anzeige „Waage nicht verbunden“.
- `GET /api/v1/health`: neues Feld `mqtt` (`connected`/`disconnected`/`unavailable`); **Status bleibt 200** – 503 nur wie bisher bei Datenbankfehler.

## 10. Prüfseite `/admin/waagen` (M08-11)

Schlichte Admin-Seite im Stil der Prüfseite Berechnung, **hinter der PIN wie alle Admin-Seiten** (K08-4; die REST-Endpunkte selbst sind ohne PIN):
- je Station: Gewicht groß, Status in Worten (docs/waage.md 5, plus „Waage nicht verbunden“), stabil (Software) / Merker der Waage, Hinweis „Tara an der Waage aktiv“ bei `net`, Höchstlast und Auflösung, letzte Meldung (Ortszeit), Offline seit, Grund
- Tasten **Tara** und **Null** (nur bei eingerichteter Station und nicht offline), Hinweis „Null nur bei leerer Waage (±50 g)“
- Kopfzeile: Live-Verbindung, MQTT verbunden ja/nein, Waagen-Add-on online ja/nein
- Live über `/api/v1/live`; keine Browser-Dialoge (`alert`/`confirm`) wegen iOS-App (Erfahrung 0.3.2/0.3.3)
- Reiter „Waagen“ auf den Admin-Seiten (Rohstoffe, Rezepte, Berechnung)

## 11. Verzeichnisstruktur (umgesetzt in 0.8.0)

```
rezeptbuch/
├── config.yaml              0.8.0, services: mqtt:need (war schon vorhanden)
├── requirements.txt         + paho-mqtt 2.1, websockets 13
├── app/
│   ├── scales/              neu
│   │   ├── __init__.py
│   │   ├── messages.py      Schema 2 lesen und prüfen, Befehl bauen, Topics
│   │   ├── supervisor.py    MQTT-Zugangsdaten, Token (aus Add-on 2 übernommen)
│   │   ├── mqtt_link.py     paho-Verbindung im eigenen Thread
│   │   ├── hub.py           Mittelsmann: Zustand, Offline-Regel, Abo, Befehle
│   │   ├── service.py       Start/Stopp, Wächter 250 ms, Stationen alle 30 s, Thread → asyncio
│   │   └── router.py        REST /api/v1/stations… und WebSocket /api/v1/live
│   ├── main.py              Start/Stopp der Waagen-Anbindung, Router, Health-Feld mqtt
│   └── web/static/scales.html   Prüfseite, Reiter „Waagen“ in admin/recipes/calc.html
└── tests/                   test_scale_messages, test_scale_hub, test_scale_link, test_scale_api
docs/schnittstellen.md       dieses Dokument
```

## 12. Fehlerbehandlung

| Fall | Verhalten |
|---|---|
| Mosquitto fehlt / Supervisor liefert nichts | Add-on 1 läuft, `mqtt: unavailable`, Versuch alle 30 s, Protokoll einmal je Fehlertext |
| Broker getrennt | alle Stationen `offline` (`broker`), paho baut neu auf |
| Add-on 2 gestoppt | Verfügbarkeit `offline` → alle Stationen `offline` (`bridge`) |
| Station stumm | nach 3 s `offline` (`silent`) |
| fehlerhafte Nachricht | verworfen, Protokoll gedrosselt |
| Befehl bei offline / nicht eingerichtet / ohne MQTT | abgelehnt mit 409/503, nichts gesendet |
| WebSocket bricht ab | Tablet baut neu auf, bekommt Schnappschuss |
| Ausnahme bei der Verarbeitung einer Nachricht | protokolliert, Schleife läuft weiter; bleibt danach der Zustand aus, wird die Station nach 3 s `offline` (`silent`) |

## 13. Tests

**Automatisch (GitHub):** Schema-2-Prüfung (gültig, falsche Version, falsche Station, Müll); Offline-Regel mit Uhr-Attrappe (3 s still, `bridge`, `broker`, `scale`, Rückkehr, `offline_since` bleibt beim Grundwechsel); Abo-Ereignisse und Überlauf; Befehle (gesendet, offline, nicht eingerichtet, ohne MQTT; QoS 1, nicht retained); Supervisor-Abfrage und MQTT-Verbindung mit nachgebildetem Client; Dienst mit und ohne MQTT; REST mit FastAPI-Testclient; WebSocket (Schnappschuss, Änderung, Herzschlag); Health; Prüfseite und Reiter. Bestehende Tests laufen unverändert (außer Health: neues Feld `mqtt`).

**Praxisprüfung (Michael/Claude über HA):**
- (a) Update auf 0.8.0, Add-on 1 startet, Protokoll „MQTT verbunden“.
- (b) Prüfseite `/admin/waagen`: Waage 1 live, Gewicht und stabil wie auf der Waage.
- (c) Tara/Null über die Prüfseite wirken (Protokoll Add-on 2 „angenommen/gesendet“).
- (d) Waveshare vom Strom: Station `offline` (Grund `scale`), zurück nach Wiedereinstecken.
- (e) Add-on 2 stoppen: alle Stationen `offline` (`bridge`).
- (f) Mosquitto neu starten: kurz `broker`, danach automatisch wieder verbunden; Rezepte bleiben bedienbar.
- (g) Waage 2 als Simulator in Add-on 2 aktiv, im Rezeptbuch nicht eingerichtet: Anzeige mit Hinweis, Tasten gesperrt.
- (h) Prüfseite in der HA-App (iOS) und im Tablet-Browser: Live-Werte über Ingress.

## 14. Konzeptfragen (entschieden 19.11.2026, 09:41, Michael: „Konzept frei, K08 wie vorgeschlagen“)

| Nr. | Frage | Entscheidung (wie vorgeschlagen) |
|---|---|---|
| K08-1 | Befehle QoS / retained | **QoS 1, nie retained** – ein gespeicherter `tare` würde sonst bei jedem Neustart von Add-on 2 erneut ausgeführt. |
| K08-2 | Live-Kanal-Details | Schnappschuss beim Verbinden, alle Stationen an alle Tablets (Tablet filtert seine Station), Herzschlag 15 s, Befehle nur über REST. |
| K08-3 | MQTT-Code | Aus Add-on 2 kopieren (Supervisor, Token), eigene Tests; kein gemeinsames Paket. |
| K08-4 | Prüfseite | Hinter der PIN wie alle Admin-Seiten; REST und WebSocket ohne PIN. |
| K08-5 | Nicht eingerichtete Station | Anzeigen mit Hinweis, Befehle ablehnen. |
| K08-6 | Offline-Grund | Eigenes Feld `offline_reason` (`scale`, `bridge`, `broker`, `silent`) für verständliche Anzeigen und Fehlersuche. |
| K08-7 | Health | Feld `mqtt` ergänzen, Status bleibt 200 ohne MQTT. |
| K08-8 | Umsetzung | Ein Teil C1 = 0.8.0 auf `modul08`; Tests, GitHub-Testlauf, Praxisprüfung (a)–(h), dann `main` nach Freigabe. |

## 15. Auswirkungen auf andere Module

- **Modul 01:** `requirements.txt` von Add-on 1 ergänzt (abwärtskompatibel, M08-2); `services: mqtt:need` stand schon in `config.yaml`.
- **Modul 09:** nutzt nur den Mittelsmann (Abschnitt 3); `offline_since` für die 45 s; WebSocket für den Ablaufzustand erweitern.
- **Modul 10:** gestaltet die Prüfseite und die Statusanzeigen; nutzt `/api/v1/live`.
- **Modul 12:** REST-Waagenendpunkte und WebSocket bewusst ohne PIN.
- **Modul 06:** Korrekturen erscheinen künftig als 0.8.x (M08-13).
- **Add-on 2:** keine Änderung.

## 16. Änderungen

| Datum | Änderung |
|---|---|
| 19.11.2026, 09:40 | Konzept erstellt (Schritt B), Konzeptfragen K08-1 bis K08-8 offen. |
| 19.11.2026, 09:41 | **Konzept von Michael freigegeben**, K08-1 bis K08-8 wie vorgeschlagen entschieden. |
| 19.11.2026 | **Teil C1 umgesetzt (0.8.0):** Präzisierungen beim Umsetzen (Hinweise Claude): WebSocket in `router.py` statt eigener `live.py`, neue Datei `service.py` (Start/Stopp, Wächter); Vorrang der Offline-Gründe festgelegt (Abschnitt 4); Feld `name`; Ergebnis `unknown_station` (404); Puffer 200 Meldungen je Live-Verbindung; Bibliothek `websockets`; `services: mqtt:need` war schon in `config.yaml`. |
