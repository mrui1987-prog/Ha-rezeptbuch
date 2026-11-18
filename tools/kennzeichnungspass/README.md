# Kennzeichnungspass-Leser (VC04-e, Testleser)

Liest den vom datenlink-Portal erzeugten **Kennzeichnungspass (PDF)** und liefert eine neutrale
Zwischenstruktur (Schema 2, angelehnt an das datenlink-XML). Nur Lesen: keine Datenbank, kein Netzwerk,
keine Änderung an der Anwendung. Der Einbau in den Rezeptserver folgt erst nach der Felder-Entscheidung
(docs/modulstatus-04.md, VC04-e Schritt 2). Beschreibung der Struktur: Kopf von `zwischenstruktur.py`.

```
python3 -I tools/kennzeichnungspass/kennzeichnungspass.py pass.pdf [...] [-o ordner] [--roh]
python3 -I tools/kennzeichnungspass/pruefe_leser.py ORDNER                       # Selbstprüfung
KENNZEICHNUNGSPASS_PDF_DIR=ORDNER python3 -m pytest tools/kennzeichnungspass     # Tests
```

Benötigt `pdfplumber` (nicht Teil des Add-ons). Die PDFs liegen nicht im Repo.

- `kennzeichnungspass.py` – Leser (Rohdaten Schema 1), `zwischenstruktur.py` – Schema 2,
  `pruefe_leser.py` – Selbstprüfung mit von Hand geprüften Stichproben.
- Grundsatz: nichts erfinden; Unklares → `warnungen`, Rechen-/Regelverstöße → `plausibilitaet`.
- Hinweis (keine Korrektur): nennt die Zutatenliste ein Allergen in Großbuchstaben, das im Raster nicht
  angekreuzt ist, steht es unter `plausibilitaet`.
