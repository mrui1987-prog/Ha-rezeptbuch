# Kennzeichnungspass-Leser (Aufruf am PC)

Der Leser liegt seit 21.11.2026 in **Add-on 3** (`rezeptbuch_leser/app/leser/`, M04-23).
Die beiden Dateien hier rufen ihn nur auf, damit es keine zweite Fassung gibt.

```
python3 -I tools/kennzeichnungspass/kennzeichnungspass.py pass.pdf [...] [-o ordner] [--roh]
python3 -I tools/kennzeichnungspass/pruefe_leser.py ORDNER                       # Selbstprüfung
cd rezeptbuch_leser && KENNZEICHNUNGSPASS_PDF_DIR=ORDNER python3 -m pytest      # Tests
```

Benötigt `pdfplumber`. Die PDFs liegen nicht im Repo. Beschreibung der Struktur: Kopf von
`rezeptbuch_leser/app/leser/zwischenstruktur.py`; Vertrag mit Add-on 1: docs/kennzeichnungspass-import.md 15.
