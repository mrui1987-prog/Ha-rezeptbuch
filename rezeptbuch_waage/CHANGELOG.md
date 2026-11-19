# Änderungen – HA-Rezeptbuch Waage

## 0.7.5 – Korrektur aus der Praxisprüfung C2

- **Nullstellen nur bei leerer Waage (Z07-1):** `zero` wird nur angenommen, wenn die Waage ein gültiges Gewicht **brutto** zeigt und höchstens **±50 g** (neues Feld „Nullstellen nur bis ±g“ je Waage, 0–1000). Sonst „Befehl Nullstellen verworfen – …“. Grund: Die KFB-TM stellt bis knapp 10 kg auf 0 und meldet danach brutto 0 g, obwohl Last aufliegt. Die Bedingung wird beim Senden noch einmal geprüft. Die Null-Taste an der Waage selbst ist davon nicht betroffen.
- **Protokoll in Ortszeit (Befund O1):** 0.7.3 wirkte nicht, weil das Programm unter s6 ohne `TZ` startet. `TZ` wird jetzt wie das Supervisor-Token aus der s6-Umgebungsdatei gelesen, sonst Europe/Berlin. Startzeile „Protokoll in Ortszeit …“. `ts` in den Meldungen bleibt UTC.
- Neues Feld ist optional: Beim Update bleibt die bisherige Konfiguration gültig (Standard 50 g).

## 0.7.4 – Modul 07, Teil C2 (in Entwicklung)

- **Befehle Tara und Nullstellen:** `{"v":2,"cmd":"tare"|"zero"}` auf `rezeptbuch/v1/station/<nr>/scale/cmd` geht als `T`/`Z` + CR LF an die Waage – per TCP über die offene Verbindung, beim MQTT-Weg auf das Befehls-Topic des Waveshare, beim Simulator im Simulator
- **Warteschlange je Waage:** mindestens 1 s zwischen zwei Befehlen, höchstens einer je Art wartet, doppelte werden zusammengefasst; bei `offline` verworfen; ungültige Befehle mit Protokolleintrag verworfen
- **Werkzeug `tools/waagen_simulator`:** Waveshare-Ersatz per TCP (Port 8899) mit simulierter KERN-Waage, nimmt `T`/`Z` an; zum Prüfen des TCP-Wegs ohne Hardware

## 0.7.3 – Korrektur aus der Praxisprüfung C1

- **Protokoll:** Zeitstempel in Ortszeit (Europe/Berlin) statt UTC

## 0.7.2 – Korrektur aus der Praxisprüfung C1

- **Telegramm:** Zeilen mit einem Komma nach dem Modus (`ST,G ,   0.000kg`) werden gelesen; sie galten bisher als unlesbar

## 0.7.1 – Korrektur aus der Praxisprüfung C1

- **MQTT-Zugangsdaten:** Das Add-on findet das Supervisor-Token jetzt auch in der s6-Umgebungsdatei (`/run/s6/container_environment`); in 0.7.0 meldete es bei `init: false` „SUPERVISOR_TOKEN fehlt“
- **Hinweis beim Update von 0.1.0:** Die alte Konfiguration (`stations`) passt nicht mehr; im Reiter Konfiguration über ⋮ „Auf Standardwerte zurücksetzen“ wählen

## 0.7.0 – Modul 07, Teil C1 (in Entwicklung)

- **KERN-Treiber:** liest die Zeilen der KFB-TM im Sendemodus CONT (`ST`/`US`, brutto/netto, `-----`) und rechnet exakt in ganze Gramm um; Längenschutz gegen Datenmüll
- **Anbindung je Waage wählbar:** TCP zum Waveshare (Standard, Port 8899, Neuaufbau 1/2/5/10 s) oder Roh-Topic der Waveshare-MQTT-Funktion (wie im Feldtest)
- **Stabilität in der Software:** stabil, wenn das Gewicht im Zeitfenster (Standard 1000 ms) höchstens um die erlaubte Schwankung (Standard 2 g) schwankt; Merker der Waage zusätzlich als `scale_stable`
- **Status** `ok`, `invalid` (`-----`, kein Ausfall), `offline` (5 s ohne Zeile), `error` (3 s nur unlesbare Daten, oder Konfiguration fehlerhaft) mit Hinweisen im Protokoll
- **MQTT-Schnittstelle Schema 2:** Zustand je Station sofort bei Änderung, sonst alle 500 ms; Verfügbarkeit `rezeptbuch/v1/scale_bridge/availability` mit Letztem Willen; Zugangsdaten vom Supervisor
- **Simulator** als Treiber (Wiegeverlauf in Schleife, 60 s)
- **Konfiguration flach je Waage** mit deutschem Namen, Standardwert und Erklärung je Feld; Info-Felder Baudrate, Datenformat, Sendemodus; keine IP-Adressen als Voreinstellung

## 0.1.0 – Modul 01

- Grundgerüst
