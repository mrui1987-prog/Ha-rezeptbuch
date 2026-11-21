# Änderungen – HA-Rezeptbuch Leser

## 0.1.0 – Modul 04 Teil C2-L (Add-on 3, M04-23) – freigegeben 21.11.2026 (M04-27)

- Neues Add-on: PDF rein, JSON raus (Vertrag Fassung 1), schreibt nichts
- **Kennzeichnungspass-Leser** aus `tools/kennzeichnungspass/` übernommen, Leser-Code unverändert (freigegeben 18.11.2026); `tools/kennzeichnungspass/` ruft ihn nur noch auf
- HTTP-Server (Standardbibliothek) auf Port 8100, nur internes Netz; `GET /v1/gesundheit`, `POST /v1/lesen/kennzeichnungspass`
- Jede Datei in eigenem Prozess mit Zeitlimit 30 s; Grenzen 10 MB / 20 Seiten
- Selbsttest beim Bau des Images (pdfplumber auf Alpine)
- **BÄKO-Belegleser** (`POST /v1/lesen/baeko-beleg`, Schema 1): Auftragsbestätigung, Rechnung (2026 und 2024 mit Skonto je Position, Strecke), Gutschrift; prüft Netto-Summe, MwSt.-Sätze, Überträge und Warengruppen auf den Cent – sonst `unlesbar`; trennt im PDF übereinander gedruckte Bezeichnungen; Name/Anschrift des Kunden werden nicht übernommen
- Geprüft an 6 echten Belegen (165 Positionen, alle Summen stimmen)
