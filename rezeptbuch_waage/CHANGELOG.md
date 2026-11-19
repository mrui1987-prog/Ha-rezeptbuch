# Änderungen – HA-Rezeptbuch Waage

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
