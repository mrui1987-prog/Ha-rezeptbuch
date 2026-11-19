# HA-Rezeptbuch Waage

Liest bis zu zwei KERN-Waagen (IFB 30K-3 mit Anzeigegerät KFB-TM) über je einen Waveshare-Konverter und meldet **Gewicht in ganzen Gramm, Stabilität und Status** per MQTT an das HA-Rezeptbuch. Das Add-on kennt keine Rezepte; es läuft auch allein (Simulator).

**Stand 0.7.4 (Modul 07, Teil C2):** Lesen, Stabilität, Status, Meldungen und Befehle Tara/Nullstellen. Im Rezeptbuch sichtbar wird der Zustand erst mit Modul 08.

## Aufbau

```
Waage (RS-232, 9600 8n1, CONT) → Waveshare → dieses Add-on → MQTT → HA-Rezeptbuch
                                   ├─ TCP (Standard, Port 8899)
                                   └─ oder MQTT-Roh-Topic (wie im Feldtest)
```

Voraussetzung: Add-on „Mosquitto broker“. Die Zugangsdaten holt sich das Add-on selbst vom Supervisor.

## Einrichtung

**Waage:** Baudrate 9600, Format 8n1, Sendemodus **CONT** (sendet auch instabile Werte).

**Weg A – TCP (empfohlen):**
1. Waveshare-Weboberfläche: Arbeitsmodus **TCP Server**, Port **8899**, MQTT-Funktion aus. Seriell 9600, 8, n, 1.
2. Add-on-Konfiguration: „Waage 1 – Anbindung“ = `tcp`, „Adresse des Waveshare“ = IP-Adresse eintragen.

**Weg B – MQTT-Roh-Topic (jetzige Feldtest-Einstellung):**
1. Waveshare bleibt wie im Feldtest (MQTT, Pub Topic `rezeptbuch/test/waage1/raw`, Sub Topic `rezeptbuch/test/waage1/cmd`).
2. Add-on: „Anbindung“ = `mqtt`. Die Topics sind vorausgefüllt.

**Ohne Waage:** „Treiber“ = `simulator`. Ablauf in Schleife (60 s): leer → Behälter 1 200 g → Befüllen bis 5 000 g → ruhig → kurz „kein gültiger Wert“ → Abnehmen → 8 s Ausfall. Tara/Nullstellen wirken auch hier.

**TCP-Weg ohne Hardware prüfen:** Werkzeug `tools/waagen_simulator/simulator.py` aus dem Repo auf einem Rechner im Netz starten (`python simulator.py`, Port 8899; `--fest 2500` für ein festes Gewicht), dann „Anbindung“ = `tcp` und als Adresse die des Rechners eintragen. Siehe `tools/waagen_simulator/README.md`.

Jedes Feld zeigt in HA einen deutschen Namen mit Standardwert und eine Erklärung. Baudrate, Datenformat und Sendemodus sind **Info-Felder**: Sie werden an Waage und Waveshare eingestellt; das Add-on zeigt sie im Protokoll und nennt sie in Fehlermeldungen.

| Feld | Standard | Bedeutung |
|---|---|---|
| aktiv | Waage 1 ja, Waage 2 nein | Station verwenden |
| Treiber | `kern` | `simulator` = Testbetrieb |
| Anbindung | `tcp` | `tcp` oder `mqtt` |
| Adresse / TCP-Port | leer / 8899 | nur TCP |
| Roh-Topic / Befehls-Topic | `rezeptbuch/test/waage<n>/raw` / `…/cmd` | nur MQTT |
| Baudrate, Datenformat, Sendemodus | 9600, 8n1, CONT | Info |
| Stabil: Zeitfenster / Schwankung | 1000 ms / 2 g | stabil, wenn das Gewicht so lange höchstens so viel schwankt |
| Offline nach | 5 s | ohne Zeile von der Waage |
| Höchstlast / Auflösung | 30000 g / 1 g | wird mitgemeldet |

Fehlt bei TCP die Adresse (oder bei MQTT ein Topic), startet nur diese Waage nicht (Status `error`, Meldung im Protokoll); die andere läuft weiter.

## Schnittstelle (Schema 2)

**Zustand** – `rezeptbuch/v1/station/<nr>/scale/state`, QoS 0, nicht retained; sofort bei Änderung, sonst alle 500 ms:

```json
{"v": 2, "station": 1, "status": "ok", "weight_g": 9500, "stable": true,
 "scale_stable": true, "net": false, "capacity_g": 30000, "resolution_g": 1,
 "ts": "2026-11-18T20:00:00.123+00:00"}
```

| `status` | Bedeutung | `weight_g` |
|---|---|---|
| `ok` | Gewicht gelesen | Zahl (ganze Gramm) |
| `invalid` | Waage zeigt `-----` (Überlast, Negativwert, starke Bewegung) – kein Ausfall | `null` |
| `offline` | seit 5 s keine Zeile (oder noch nie) | `null` |
| `error` | seit 3 s nur unlesbare Daten, oder Konfiguration fehlerhaft | `null` |

`stable` = Stabilität aus dem Add-on (Fenster/Spanne); `scale_stable` = Merker der Waage (`ST`/`US`), nur zur Information; `net` = Waage meldet netto (nach Tara an der Waage). Gemeldet wird immer der zuletzt gelesene Wert.

**Verfügbarkeit** – `rezeptbuch/v1/scale_bridge/availability`: `online`/`offline`, retained (Letzter Wille).

**Befehle** – `rezeptbuch/v1/station/<nr>/scale/cmd`: `{"v": 2, "cmd": "tare"}` (Tara, `T` an die Waage) oder `{"v": 2, "cmd": "zero"}` (Nullstellen, `Z`).

- Angenommen nur, wenn die Waage Zeilen liefert (`ok`, `invalid`, `error`); bei `offline` verworfen.
- Zwischen zwei Befehlen an dieselbe Waage liegt mindestens **1 s**; weitere warten (höchstens einer je Art, doppelte werden zusammengefasst). Wird die Waage vorher offline, werden wartende Befehle verworfen.
- Keine Bestätigung: die Wirkung zeigt der nächste Zustand (`net: true` bzw. Gewicht 0).
- TCP: über die offene Verbindung; MQTT-Weg: auf das Befehls-Topic des Waveshare (`T\r\n`); Simulator: im Simulator.
- Hinweis: Im Wiegeablauf tariert das Rezeptbuch in der Software (Modul 09). Tara an der Waage führt nach dem Abnehmen des Behälters zu `-----`.

**Befehl von Hand senden (Test):** Einstellungen → Geräte & Dienste → MQTT → Konfigurieren → „Ein Paket veröffentlichen“, Topic `rezeptbuch/v1/station/1/scale/cmd`, Inhalt `{"v":2,"cmd":"tare"}`.

## Zustand ansehen

Einstellungen → Geräte & Dienste → MQTT → Konfigurieren → „Auf ein Topic hören“: `rezeptbuch/v1/station/1/scale/state`.

Protokollstufe `debug` zeigt jede Zeile der Waage mit Gewicht und Schwankung im Zeitfenster (zum Einstellen der Stabilitätswerte).

## Fehlerbilder

| Protokoll | Ursache / Abhilfe |
|---|---|
| „keine Verbindung zu …:8899“ | Waveshare aus, falsche Adresse, nicht im TCP-Server-Modus. Das Add-on versucht es weiter (1, 2, 5, dann alle 10 s). |
| „keine Zeilen – Sendemodus CONT an der Waage prüfen“ | Verbindung steht, aber die Waage sendet nicht. |
| „liefert unlesbare Daten – Baudrate 9600 und Format 8n1 … prüfen“ | Einstellungen von Waage und Waveshare passen nicht zusammen. |
| „MQTT-Dienst nicht gefunden – Mosquitto installiert?“ | Mosquitto-Add-on fehlt; neuer Versuch alle 30 s. |
| „Keine Waage aktiv“ | „Waage 1 – aktiv“ einschalten. |
| „Befehl … verworfen – Waage liefert keine Zeilen (offline)“ | Befehl kam, während die Waage getrennt war; nach der Verbindung erneut senden. |
| „Befehl verworfen – kein gültiges JSON / falsche Version / unbekannter Befehl“ | Inhalt muss `{"v":2,"cmd":"tare"}` oder `…"zero"}` sein. |
| „Befehl … nicht gesendet – keine Verbindung“ | TCP-Verbindung oder MQTT gerade weg; Befehl erneut senden. |
