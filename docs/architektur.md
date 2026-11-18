# Modul 01 – Architektur (Schritt B: Konzept)

Status: **freigegeben am 12.11.2026** (2 Add-ons)

## 1. Eckdaten (aus Schritt A)

| Punkt | Entscheidung |
|-------|--------------|
| Name | HA-Rezeptbuch |
| Lizenz | MIT |
| Sprache | Deutsch (Oberfläche und Doku) |
| Stationen | bis zu 2 (Waage 1, Waage 2), je ein eigenes Dashboard |
| Anmeldung | ein gemeinsamer Zugang am Tablet, keine Erfassung, wer wiegt |
| Schutz | PIN für alle ändernden Funktionen (Admin-Bereich) |
| Bedienung | nach Bedienkonzept, siehe [bedienkonzept.md](bedienkonzept.md) |

## 2. Gesamtbild

```
 Tablet Waage 1          Tablet Waage 2         Handy / PC (Admin)
 /station/1              /station/2             /admin  (PIN)
      │                       │                      │
      └──────────── Web-UI über HA-Ingress ──────────┘
                              │  REST /api/v1 + Live-Updates (WebSocket)
                ┌─────────────▼──────────────┐
                │  Add-on 1: rezeptbuch      │
                │  FastAPI · SQLite · Logik  │
                └─────────────▲──────────────┘
                              │  MQTT (Mosquitto)
                ┌─────────────┴──────────────┐
                │  Add-on 2: rezeptbuch_waage│
                │  Treiber KERN (weitere opt.)│
                └──────┬───────────────┬─────┘
                       │ TCP           │ TCP
                 Waveshare 1      Waveshare 2
                  RS-232            RS-232
                 KERN Waage 1     KERN Waage 2
```

**Add-on 1 – `rezeptbuch`:** Datenbank, Rohstoffe, Rezepte, Berechnung, Produktionsliste, Wiegeablauf, Chargen, PIN-Prüfung, Web-Oberfläche.

**Add-on 2 – `rezeptbuch_waage`:** liest die Waagen über die Waveshare-Konverter und veröffentlicht Gewicht und Stabilität per MQTT. Kennt keine Rezepte. Kann ohne Add-on 1 getestet werden (Simulator). *Seit Modul 07 (M07-1, 18.11.2026): Anbindung je Station per TCP (Standard) oder über das Roh-Topic der MQTT-Funktion des Waveshare; Einzelheiten in docs/waage.md.*

**Warum eigene Web-Oberfläche statt Lovelace-Dashboards:** Die Bedienung nach optidos-Vorbild (Ampelbalken, Sperren zwischen Stationen, Pause-Übergabe) lässt sich mit Lovelace-Karten nur mit vielen Hilfsentitäten bauen. Eine eigene Oberfläche bleibt übersichtlich und wird mit dem Add-on ausgeliefert. Home Assistant liefert Anmeldung (Ingress), Seitenleiste und Backup.

## 3. Die drei Oberflächen

| Adresse | Gerät | Inhalt |
|---------|-------|--------|
| `/station/1` | Tablet an Waage 1 | Startbild, Vorwahl, Produktionsliste, Wiegeansicht, Handbetrieb |
| `/station/2` | Tablet an Waage 2 | identisch, eigene Waage |
| `/admin` | Tablet, Handy, PC | Rohstoffe, Rezepte, Aufträge anlegen, Waagen, Export, System |

Jedes Tablet wird einmal auf seine Station-Adresse eingestellt (Browser im Vollbild/Kiosk-Modus). Taste „Menü“ öffnet die PIN-Eingabe und führt nach `/admin`.

## 4. PIN-Schutz – echter Schutz statt nur Dashboard-Wechsel

Weil die Oberfläche aus dem eigenen Add-on kommt, prüft **der Server** die PIN, nicht nur die Anzeige:

- Alle ändernden API-Aufrufe (`/api/v1/admin/...`) verlangen eine gültige Admin-Sitzung.
- PIN wird nur als Hash gespeichert (kein Klartext, nicht im Repo).
- Admin-Sitzung endet nach einstellbarer Zeit ohne Eingabe (Vorgabe: 5 Minuten) und beim Verlassen des Admin-Bereichs.
- Nach 5 falschen Eingaben wird die PIN-Eingabe für 1 Minute gesperrt.
- Wer nur die Adresse `/admin` kennt, kommt ohne PIN nicht weiter.

Damit ist der in Modul 1 angesprochene Schwachpunkt (Dashboard-Adresse direkt aufrufbar) behoben.

## 5. Ablauf-Logik Wiegen (zentral im Server)

Der Zustand eines Auftrags liegt nur im Server. Beide Tablets zeigen ihn live an.

```
 offen ──Start an Station X──▶ läuft (Besitzer X)
                                  │  ▲
                            Pause │  │ Weiter an Station X oder Y
                                  ▼  │ (Y nur ohne „Fest an Waage“)
                               pausiert (frei für alle)
 läuft ──alle Zutaten quittiert──▶ fertig  → Chargenprotokoll
 läuft/pausiert ──Abbruch (Ja)──▶ abgebrochen → Protokoll
```

- **Besitzer:** Nur die Besitzer-Station kann wiegen und quittieren. Die andere sieht „in Arbeit an Waage X“.
- **„Fest an Waage“:** Ein Auftrag mit diesem Haken kann nur an seiner Station fortgesetzt werden.
- **Gleichzeitiges „Weiter“:** Drücken beide Stationen fast gleichzeitig, gewinnt die erste beim Server; die zweite bekommt einen Hinweis.
- **Rezeptversion (R2):** Die Rezeptversion wird beim **Start der Verwiegung** fixiert, nicht beim Anlegen des Auftrags. Rezeptänderungen zwischen Anlegen und Start gelten also noch für den Auftrag.
- **Quittieren (R4):** nur innerhalb der Toleranz (grüner Balken).
  - Meldet die Waage **4 Sekunden durchgehend stabil** im Toleranzbereich, wird **automatisch quittiert**.
  - Liegt der Wert in der Toleranz, ist die Waage aber nicht stabil, kann **manuell quittiert** werden.
  - Außerhalb der Toleranz ist kein Quittieren möglich.
- **Tara (R5):** Nach jeder quittierten Zutat tariert die Software automatisch (Wiegen nacheinander in einen Behälter). Der Tara-Wert kann zusätzlich von Hand gesetzt werden.
- **Unterrezepte (R3):** Ein Unterrezept ist ein **eigener, mit dem Hauptteig verknüpfter Auftrag**. Alternativ kann es als erledigt abgehakt werden; dann werden alle Ist-Werte mit den Soll-Werten gefüllt und es geht mit dem nächsten Rohstoff weiter.
- **Ausfall einer Waage (R6):** Kurze Aussetzer lösen nichts aus. Kommen **45 Sekunden** lang keine neuen Werte, geht der laufende Auftrag automatisch auf Pause, mit Hinweis am Tablet.
- **Quittierungsart im Chargenprotokoll:** Jede Zutat wird mit ihrer Art gespeichert: „automatisch (stabil)“, „manuell (nicht stabil)“, „Handzugabe“, „abgehakt, nicht gewogen“ (Unterrezept), „übergangen“.

| Zeitwert | Vorgabe | Bedeutung |
|----------|---------|-----------|
| Stabil vor automatischer Quittung | 4 s | Waage muss durchgehend stabil im Toleranzbereich melden |
| Keine Waagenwerte bis Pause | 45 s | kürzere Aussetzer werden ignoriert |

## 6. Namenskonventionen

| Bereich | Regel | Beispiel |
|---------|-------|----------|
| Repository | Kleinschreibung mit Bindestrich | `ha-rezeptbuch` |
| Add-on-Slugs | Kleinschreibung mit Unterstrich | `rezeptbuch`, `rezeptbuch_waage` |
| Oberfläche, Doku, Meldungen | Deutsch | „Zutat quittieren“ |
| Code (Variablen, Funktionen, Tabellen) | Englisch, snake_case | `production_order`, `tolerance_plus` |
| Kommentare im Code | Deutsch | |
| API | versioniert, Plural-Substantive | `/api/v1/recipes`, `/api/v1/orders/{id}/pause` |
| MQTT-Topics | `rezeptbuch/v1/station/<nr>/scale/<wert>` | `rezeptbuch/v1/station/1/scale/state` |
| Gewichte intern | Gramm als Ganzzahl (keine Rundungsfehler) | 9500 = 9,500 kg |
| Versionen | SemVer, Gesamtversion im Add-on | `0.1.0` |

Englische Bezeichner im Code sind der übliche Standard und erleichtern anderen Entwicklern das Mitarbeiten. Alles, was ein Nutzer sieht, bleibt Deutsch.

## 7. Sicherheitskonzept

- **Zugang:** Nur über HA-Ingress, also mit HA-Anmeldung. Kein offener Port nach außen.
- **Tablets:** eigener HA-Benutzer ohne Admin-Rechte in HA, nur für das Rezeptbuch.
- **Admin:** PIN-Prüfung im Server (siehe Abschnitt 4).
- **Geheimnisse:** PIN-Hash und Waagenadressen nur in der Add-on-Konfiguration bzw. Datenbank, nie im Repo.
- **Betriebsdaten:** Rezepte und Rohstoffe liegen nur in der lokalen Datenbank, nicht im Repo.
- **Protokoll:** Jede Änderung im Admin-Bereich wird mit Zeit und Art der Änderung protokolliert (ohne Person, da gemeinsamer Zugang).
- **Backup:** Datenbank-Snapshot vor jedem Add-on-Update und regelmäßig, Übertragung über HA-Backup (Modul 13).
- **Haftung:** Hinweis in README und Oberfläche, dass Rezeptmengen und Allergenangaben vom Betrieb zu prüfen sind (MIT: keine Gewährleistung).

## 8. Offene Punkte

1. **GitHub:** Kontoname, und gibt es das Repo `ha-rezeptbuch` schon?
2. ~~**Waagen:** genaues KERN-Modell der ersten Waage (für den Treiber in Modul 07).~~ Geklärt im Feldtest 12./13.11.2026: **KERN IFB 30K-3 mit Anzeigegerät KFB-TM**, 9600 Baud, 8n1, Sendemodus CONT (docs/waage.md).
3. **Tablets:** welches Gerät/Betriebssystem (für den Kiosk-Modus)?

## 9. Änderungen

| Datum | Änderung |
|-------|----------|
| 12.11.2026 | Konzept freigegeben (2 Add-ons). |
| 12.11.2026 | Abschnitt 5 an Review-Entscheidungen R2–R6 angepasst (Versionsfixierung, automatische/manuelle Quittung, Tara, Unterrezepte, Waagenausfall, Zeitwerte, Quittierungsart). |
| 18.11.2026 | Modul 07: Abschnitt 8 Punkt 2 (KERN-Modell) erledigt; Hinweis zur Anbindung (M07-1) in Abschnitt 2. Präzisierungen zu R4–R6 aus Modul 07 (Stabilität in der Software, Tara in der Software, 45 s ab „offline“) stehen in docs/modulstatus-07.md und docs/waage.md. |
