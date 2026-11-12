# HA-Rezeptbuch

Rezeptverwaltung, Produktionsliste und Wiegeablauf für kleine Bäckereien.

**Stand 0.1.0:** Grundgerüst. Die Oberfläche zeigt nur eine Statusseite.

## Voraussetzungen

- Home Assistant OS oder Supervised (Add-ons)
- MQTT-Broker (Add-on „Mosquitto broker“)
- Add-on „HA-Rezeptbuch Waage“ für die Waagenanbindung

## Oberflächen

| Adresse | Zweck |
|---------|-------|
| `/station/1` | Tablet an Waage 1 |
| `/station/2` | Tablet an Waage 2 |
| `/admin` | Rezepte, Rohstoffe, Aufträge (PIN) |

Die PIN wird beim ersten Start in der Oberfläche festgelegt. Sie steht nicht in der Add-on-Konfiguration.

## Haftung

Die Software wird ohne Gewährleistung bereitgestellt (MIT-Lizenz). Rezeptmengen und Allergenangaben sind vom Betrieb zu prüfen.
