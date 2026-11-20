# HA-Rezeptbuch

Digitale Rezeptverwaltung und Wiegestation für kleine Bäckereien auf Basis von Home Assistant.

## Eckdaten

- **Lizenz:** MIT – frei verwendbar, änderbar und für den eigenen Gebrauch nutzbar (siehe [LICENSE](LICENSE))
- **Sprache:** Deutsch
- **Arbeitsplätze:** 2 (damit bei Bedarf eine zweite Waage eingebunden werden kann)
- **Bedienung:** eine gemeinsame Anmeldung am Tablet; wer abwiegt, wird nicht erfasst

## Geschützte Funktionen

Änderungen an Rezepten, Rohstoffen und Einstellungen sind gesperrt. Die Taste „Menü“ fragt eine **PIN** ab und wechselt in den Admin-Bereich, in dem alle gesperrten Funktionen zusammengeführt sind. Die PIN wird vom Server geprüft – wer nur die Adresse des Admin-Bereichs kennt, kommt ohne PIN nicht weiter.

## Aufbau

Drei Home-Assistant-Add-ons aus diesem Repository:

| Add-on | Aufgabe |
|--------|---------|
| `rezeptbuch` | Rezepte, Rohstoffe, Produktionsliste, Wiegeablauf, Oberfläche |
| `rezeptbuch_waage` | Anbindung der Waagen (RS-232 über Netzwerk-Konverter) per MQTT |
| `rezeptbuch_leser` | Liest Kennzeichnungspässe und BÄKO-Belege (PDF) und liefert JSON an `rezeptbuch`; schreibt nichts |

```
├── repository.yaml          Add-on-Quelle für Home Assistant
├── rezeptbuch/              Add-on 1
├── rezeptbuch_waage/        Add-on 2
├── rezeptbuch_leser/        Add-on 3 (PDF-Leser)
├── tools/kennzeichnungspass/ Leser am PC aufrufen
├── tools/waagen_simulator/  Testen ohne Waage
├── docs/                    Architektur und Bedienkonzept
└── .github/workflows/       automatische Tests
```

## Installation (sobald veröffentlicht)

1. In Home Assistant: Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories
2. Repository-URL dieses Projekts hinzufügen
3. „Mosquitto broker“, „HA-Rezeptbuch Waage“ und „HA-Rezeptbuch“ installieren

## Haftung

Die Software wird ohne Gewährleistung bereitgestellt. Rezeptmengen und Allergenangaben sind vom Betrieb selbst zu prüfen.

## Module

| Modul | Inhalt | Status |
|-------|--------|--------|
| 01 | Architektur (siehe [docs/architektur.md](docs/architektur.md)) und Bedienkonzept (siehe [docs/bedienkonzept.md](docs/bedienkonzept.md)) | Im Test |
| 02 | Datenbank | Nicht begonnen |
| 03 | Rohstoffe | Nicht begonnen |
| 04 | BÄKO-Import | Nicht begonnen |
| 05 | Rezepte | Nicht begonnen |
| 06 | Berechnung | Nicht begonnen |
| 07 | Waage (Treiber KERN) | Nicht begonnen |
| 08 | MQTT / REST | Nicht begonnen |
| 09 | Wiegeablauf und Produktionsliste | Nicht begonnen |
| 10 | Dashboard (Stationen, Admin) | Nicht begonnen |
| 11 | Chargen | Nicht begonnen |
| 12 | PIN / Rechte | Nicht begonnen |
| 13 | Backup | Nicht begonnen |
| 14 | Test und Freigabe | Nicht begonnen |

## Lizenz

MIT – siehe [LICENSE](LICENSE).
