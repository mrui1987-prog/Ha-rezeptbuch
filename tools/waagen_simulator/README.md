# Waagen-Simulator (Waveshare-Ersatz)

Gibt sich als Waveshare-Konverter im Modus **TCP-Server** mit angeschlossener KERN-Waage (KFB-TM, Sendemodus **CONT**) aus. Damit lässt sich der TCP-Weg des Add-ons `rezeptbuch_waage` ohne Hardware prüfen (docs/waage.md Abschnitt 8, K07-7). Nicht Teil des Add-on-Abbilds.

Nutzt denselben Simulator-Kern wie der Treiber `simulator` im Add-on (`rezeptbuch_waage/app/simulator.py`); deshalb im Repo-Ordner starten, nicht einzeln kopieren.

## Start

Python 3.11 oder neuer, keine weiteren Pakete.

```
python tools/waagen_simulator/simulator.py              # Ablauf 60 s, Port 8899
python tools/waagen_simulator/simulator.py --fest 2500  # festes Gewicht 2 500 g, immer stabil
python tools/waagen_simulator/simulator.py --port 9000 --host 127.0.0.1 -v
```

| Option | Standard | Bedeutung |
|---|---|---|
| `--host` | `0.0.0.0` | Adresse, auf der gelauscht wird (alle) |
| `--port` | `8899` | TCP-Port (wie Waveshare ab Werk) |
| `--fest GRAMM` | – | festes Gewicht statt Ablauf |
| `--seed` | `7` | Startwert für das Schwanken |
| `-v` | aus | jede Sekunde die aktuelle Zeile zeigen |

Beenden mit Strg+C.

## Verhalten

- Sendet 10 Zeilen je Sekunde an alle verbundenen Gegenstellen, z. B. `ST,G    1.200kg` + CR LF.
- Ablauf (ohne `--fest`): leer → Behälter 1 200 g → Befüllen bis 5 000 g mit Schwanken (`US`) → ruhig (`ST`) → 2 s `-----` → Abnehmen → leer → **8 s keine Zeilen** (Verbindung bleibt offen; im Add-on erscheint „offline“ mit Hinweis „Sendemodus prüfen“).
- Nimmt `T` (Tara → danach netto `N`) und `Z` (Nullstellen → brutto) an, mit oder ohne CR LF; andere Zeichen werden ignoriert. Wie an der echten Waage: nach Tara und Abnehmen des Behälters kommt `-----`.

## Mit dem Add-on prüfen

1. Simulator auf einem Rechner im Heimnetz starten.
2. Add-on: „Waage 1 – Treiber“ = `kern`, „Anbindung“ = `tcp`, „Adresse des Waveshare“ = IP des Rechners, „TCP-Port“ = 8899.
3. In HA unter MQTT „Auf ein Topic hören“: `rezeptbuch/v1/station/1/scale/state`.
4. Befehl senden: „Ein Paket veröffentlichen“ auf `rezeptbuch/v1/station/1/scale/cmd` mit `{"v":2,"cmd":"tare"}` – das Simulator-Fenster zeigt „Befehl T → Tara“, der Zustand `net: true`.

## Tests

```
python -m pytest -q tools/waagen_simulator
```
