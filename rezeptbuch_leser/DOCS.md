# HA-Rezeptbuch Leser

Liest PDFs und gibt die Angaben als JSON zurück. **Schreibt nichts**: keine Datenbank, keine Dateien,
kein Zugriff nach außen. Das Rezeptbuch (Add-on 1) schickt die PDFs hierher und macht Zuordnung,
Probelauf und Speichern selbst (docs/kennzeichnungspass-import.md, Abschnitt 15).

## Leser

| Leser | Pfad | Stand |
|---|---|---|
| Kennzeichnungspass (datenlink) | `POST /v1/lesen/kennzeichnungspass` | ab 0.1.0, Schema 2 |
| BÄKO-Belege (Auftragsbestätigung, Rechnung, Gutschrift) | `POST /v1/lesen/baeko-beleg` | ab 0.1.0, Schema 1; Summen, Überträge, MwSt. und Warengruppen werden geprüft; ab 0.2.0 mit `bereich` je Position |
| Seitenbild (Vorschau der Zuordnung) | `POST /v1/seitenbild?seite=N` | ab 0.2.0, PNG |

`GET /v1/gesundheit` nennt Version und Leser.

## Betrieb

- Erreichbar nur für andere Add-ons im internen Netz, Port 8100. Kein Ingress, kein offener Port.
- Grenzen je PDF: 10 MB, 20 Seiten, 30 s.
- Ist der Leser gestoppt, meldet das Rezeptbuch das beim PDF-Import; Wiegen und alles andere laufen weiter.
- Protokoll: eine Zeile je PDF (Leser, Ergebnis, Dauer, Prüfsumme) – nie Inhalte.

## Ergebnis

`status`: `ok` (übernehmbar) · `unlesbar` (Aufbau weicht ab – nichts wird geraten) ·
`falsches_dokument` · `fehler`. Nur `ok` darf das Rezeptbuch übernehmen.

## Am PC aufrufen

```
python3 -I rezeptbuch_leser/app/leser/baeko_beleg.py beleg.pdf          # JSON
cd rezeptbuch_leser && BAEKO_BELEG_PDF_DIR=ORDNER python3 -m pytest     # Prüfung an echten Belegen
```

Echte Belege und Pässe gehören nicht ins Repo (Kundendaten). Gescannte PDFs ohne Text werden als
`falsches_dokument` abgelehnt.
