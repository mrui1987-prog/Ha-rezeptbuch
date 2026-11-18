# Kennzeichnungspass-Leser (VC04-e, Übergangsquelle)

Liest den vom datenlink-Portal erzeugten **Kennzeichnungspass (PDF)** und liefert eine neutrale
Zwischenstruktur (angelehnt an das datenlink-XML). Nur Lesen: keine Datenbank, kein Netzwerk,
keine Änderung an der Anwendung. Der Einbau in den Rezeptserver folgt erst nach der
Felder-Entscheidung (docs/modulstatus-04.md, VC04-e Schritt 2).

```
python3 -I tools/kennzeichnungspass/kennzeichnungspass.py pass.pdf [weitere.pdf ...]   # JSON
python3 -I tools/kennzeichnungspass/pruefe_leser.py ORDNER                              # Selbstprüfung
KENNZEICHNUNGSPASS_PDF_DIR=ORDNER python3 -m pytest tools/kennzeichnungspass            # Tests
```

Benötigt `pdfplumber` (nicht Teil des Add-ons). Die PDFs liegen nicht im Repo.

## Regeln

- **Unbekannt ≠ nicht enthalten:** `None` = „keine Angabe“ / „keine Informationen verfügbar“, `[]` = Angabe
  vorhanden, nichts enthalten. Gilt für Allergene (je Spalte), Nährwerte und Zutaten.
- **Titel aus den Dateimetadaten**, nicht aus dem Seitentext: der Text verliert Zeichen
  („DOONY?S“, „Herstel ung“, „Dreisa tbroten“), die Metadaten sind vollständig.
- **Allergene über Koordinaten und Zellfarbe:** rot = „in Rezeptur / als Zutat enthalten“, orange =
  Kreuzkontamination; das gedruckte „X“ dient als Gegenprobe. Weichen beide ab, gibt es eine Warnung.
- **Referenzmenge** (100 g / 100 ml) und **Verarbeitungsstatus** über das Kästchen-„x“ vor der Option.
- **Zutaten:** `PLAINTEXT` („Zutaten: …“), `STRUCTURED` (Tabelle Bezeichnung/Anteil) oder `None`.
- **Hinweise statt Korrekturen:** nennt die Zutatenliste ein Allergen in Großbuchstaben, das im Raster
  nicht angekreuzt ist (z. B. WEIZENMEHL ohne Kreuz bei „Weizen“), steht das als Warnung im Ergebnis.
