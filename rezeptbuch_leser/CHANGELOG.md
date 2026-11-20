# Änderungen – HA-Rezeptbuch Leser

## 0.1.0 – Modul 04 Teil C2-L (Add-on 3, M04-23) – nicht freigegeben

- Neues Add-on: PDF rein, JSON raus (Vertrag Fassung 1), schreibt nichts
- **Kennzeichnungspass-Leser** aus `tools/kennzeichnungspass/` übernommen, Leser-Code unverändert (freigegeben 18.11.2026); `tools/kennzeichnungspass/` ruft ihn nur noch auf
- HTTP-Server (Standardbibliothek) auf Port 8100, nur internes Netz; `GET /v1/gesundheit`, `POST /v1/lesen/kennzeichnungspass`
- Jede Datei in eigenem Prozess mit Zeitlimit 30 s; Grenzen 10 MB / 20 Seiten
- Selbsttest beim Bau des Images (pdfplumber auf Alpine)
- BÄKO-Belegleser folgt, sobald echte Belege zum Prüfen vorliegen
