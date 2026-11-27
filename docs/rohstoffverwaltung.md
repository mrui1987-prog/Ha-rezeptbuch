# Rohstoffverwaltung – Umbau der Rohstoffseite (Modul 03, Schritt B: Konzept)

Stand: 20.11.2026, 14:55 · Status: **freigegeben am 20.11.2026, 13:20 durch Michael** („Sonst alle übernehmen“, K03-36 geändert) · **umgesetzt als 0.10.15 (Teil R1, Zweig `rohstoffverwaltung`), Praxisprüfung offen**
Grundlage: Entscheidungen M03-19 bis M03-23 (20.11.2026, docs/modulstatus-03.md), docs/rohstoffe.md, docs/bestand.md (VC03-b, VC03-c), docs/kennzeichnungspass-import.md (Modul 04: Händler, Bezugsquellen, Kennzeichnung, Massenpflege M04-6, M04-24), docs/rezepte.md (Sammelaktionen C3-E1/C3-E8 als Vorbild), docs/dashboard.md (Modul 10 C3 Admin-Gestaltung).

Die Konzeptfragen K03-33 bis K03-41 sind entschieden (Abschnitt 10). Umsetzungshinweise in Abschnitt 11, Prüfpunkte in Abschnitt 12.

## 1. Ziel und Abgrenzung

Die Rohstoffseite `/admin/rohstoffe` war eine Liste mit Fenstern (Formular, „Bestand“). Mit Bestand, Schnellerfassung, Händlern, Bezugsquellen, Kennzeichnung (Modul 04) und Wareneingang aus BÄKO-Belegen (VC03-c) wird sie zum **Bereich „Rohstoffverwaltung“** umgebaut. Der Rohstoffteil der Admin-Gestaltung aus Modul 10 C3 wird damit vorgezogen (M03-23).

| Teil | Inhalt | Wann |
|---|---|---|
| C1 (Modul 04) | Händler, Bezugsquellen, Preis je Bezugsquelle, Massenpflege „aktive Bezugsquelle setzen“, Migration 0009 | 0.10.14, in `main` |
| **R1** | Unterreiter, Rohstoffliste mit Filtern und Sammelaktionen, Rohstoff als eigene Seite (Grunddaten, Bestand, Bezugsquellen), Unterreiter Bestand mit Schnellerfassung (VC03-d), Unterreiter Händler, gemeinsamer Reiter Import/Export | **0.10.15** (K03-40) |
| C2 (Modul 04) | Reiter „Kennzeichnung“, Import Kennzeichnungspässe im Reiter Import/Export | Modul 04 C2 |
| VC03-c | Unterreiter „Wareneingang“ (erwartete Zugänge, Belege), „Sonstige Artikel“ beim Händler | nach R1 |

Nicht Teil: Gestaltung der übrigen Admin-Seiten (bleibt Modul 10 C3), Station (Modul 10 C2: „Zugang buchen“ ohne PIN).

## 2. Aufbau

Obere Reiterleiste: **Rohstoffe | Rezepte | Gruppen | Import/Export | Berechnung | Waagen | Ablauf**.

Unter „Rohstoffe“ eine zweite Leiste (Unterreiter):

| Unterreiter | Inhalt | ab |
|---|---|---|
| **Liste** | Rohstoffliste (Abschnitt 3) | R1 |
| **Bestand** | Schnellerfassung, Meldeliste, Verlauf aller Rohstoffe (Abschnitt 6) | R1 |
| **Händler** | Händlerliste (aus C1 hierher), später „Sonstige Artikel“ je Händler | R1 |
| **Wareneingang** | Belege einlesen, erwartete Zugänge | VC03-c |

Unterreiter erscheinen erst, wenn es ihren Inhalt gibt. Unter 700 px Breite wird die Unterreiterleiste zur Auswahlliste (K03-41).

Der ganze Bereich liegt hinter der PIN-Anmeldung. **Präzisierung zu M03-19 (B):** Auf der Admin-Seite ist man immer angemeldet; eine eigene PIN-Abfrage beim Umschalten auf „Gesamtbestand“ entfällt dort (K03-39). „Zugang ohne PIN“ (M03-13) gilt für die Station (Modul 10 C2).

## 3. Rohstoffliste (Unterreiter „Liste“)

- **Suche** (Nummer, Name, Kurzname) wie bisher.
- **Filter (M03-22), kombinierbar mit der Suche:**
  - Status: aktiv / archiviert / alle
  - Typ: Mehl / Standard / alle
  - Bestand: am/unter Meldewert · im Minus · ohne Bestandsführung
  - Toleranz 0 % (vorhanden)
  - ohne Preis
  - in keinem Rezept verwendet (K03-34)
  - Händler, ohne Bezugsquelle; später Herkunft eigen/datenlink, ohne Pass (C2)
- **Spalten** (K03-38): Haken · Nr. · Name · Kurzname · Typ · Toleranz · Bestand · Meldewert · €/kg · aktive Bezugsquelle. Gebinde, Herkunft und Datum nur auf der Rohstoffseite.
- **Tipp auf eine Zeile** öffnet den Rohstoff als eigene Seite (Abschnitt 4). Taste **„Neuer Rohstoff“** öffnet dieselbe Seite leer.
- Suche und Filter bleiben beim Zurückkehren erhalten (im `sessionStorage`).

## 4. Rohstoff als eigene Seite

Adresse `/admin/rohstoffe/{nummer}` (neu: `/admin/rohstoffe/neu`), mit Reitern:

| Reiter | Inhalt | ab |
|---|---|---|
| **Grunddaten** | bisheriges Formular (Nummer, Name, Kurzname, Typ, Toleranz, Gebinde, Preis bzw. Preis der aktiven Bezugsquelle, Meldewert, Herkunft), Tasten Speichern, Archivieren/Wiederherstellen, Löschen, „Verwendet in n Rezepten“ mit Sprung | R1 |
| **Bestand** | Bestand, Meldewert, Zugang buchen, Bestand setzen, Verlauf (bisher Fenster „Bestand“) | R1 |
| **Bezugsquellen** | aus C1 (Händler, Artikelnummer, Preis, aktiv, g je Mengeneinheit, Warengruppe) | R1 (Inhalt aus C1) |
| **Kennzeichnung** | Modul 04 C2 | C2 |

Oben „← Zurück zur Liste“ und ‹ › für vorheriger/nächster Rohstoff der gefilterten Liste (K03-33). Ungespeicherte Änderungen: Rückfrage beim Verlassen. Der Rückweg von der Rezeptseite (0.10.9, B1) führt auf die Rohstoffseite.

## 5. Sammelaktionen (M03-21)

- Haken je Zeile, **„alle wählen“** wählt die **angezeigten** Rohstoffe (Suche und Filter wirken); ändert sich der Filter, bleiben nur sichtbare gewählt (wie Rezepte).
- Sobald etwas gewählt ist: Leiste **„n gewählt → Aktion“**.
- Jede Aktion: **Vorschau** (in einer Transaktion ausprobiert und zurückgerollt) mit Liste „wird geändert / ohne Änderung / übersprungen (Grund)“, dann **eine Bestätigung**. Nicht erlaubte Rohstoffe werden übersprungen und genannt, die übrigen ausgeführt (nicht „alles oder nichts“, wie C3-E1). Höchstens 1 000 je Aktion. Jede Änderung ins `change_log`, Bestandsbuchungen ins `stock_movement`.

| Nr. | Aktion | Regeln |
|---|---|---|
| 1 | **Archivieren / Wiederherstellen** | wie einzeln (Rückfrage B2 aus 0.10.9); bei Rohstoffen mit Bestandsführung erscheint in der Vorschau eine **Liste „Bestand auf Null setzen“ mit allen betroffenen Rohstoffen (Bestand je Zeile), alle vorgewählt, einzeln abwählbar** (K03-36, Michael 13:20); Wiederherstellen bei gleichnamigem aktivem Rohstoff → übersprungen |
| 2 | **Toleranz setzen** | Wert und Einheit wie im Formular (%, g, 0 = Sollhandzugabe; M03-4); gilt für alle gewählten, Vorschau alt → neu (K03-35) |
| 3 | **Typ setzen** | Mehl/Standard; Vorschau mit Hinweis „betrifft n Rezepte“ je Rohstoff (M03-5) |
| 4 | **Meldewert setzen** | kg, leer = löschen |
| 5 | **Bestand: Führung beenden / auf 0 setzen** | Auswahl in der Leiste; als Inventur gebucht, Notiz „Sammelaktion“ (H2) |
| 6 | **Aktive Bezugsquelle setzen** | aus C1 (M04-6/M04-14), als Aktion `active_source` |
| 7 | **Auswahl exportieren** | CSV im Aufbau des Rohstoff-Exports, nur die gewählten, wieder importierbar (K03-37) |

Schnittstelle: `POST /api/v1/admin/raw-materials/bulk {action, ids, value?, preview?, confirm?, stock_zero_ids?}` (Vorbild `POST /api/v1/admin/recipes/bulk`); `stock_zero_ids` = die in der Vorschau angehakten Rohstoffe für „auf Null“. Export der Auswahl: `GET /api/v1/admin/raw-materials/export.csv?ids=1,2,3`.

## 6. Unterreiter „Bestand“

### 6.1 Schnellerfassung (VC03-d, M03-19)

- Bereich „Bestand erfassen“ oben im Unterreiter (eigene Fläche, kein Fenster).
- **Schalter: Zugang | Gesamtbestand** – bleibt stehen, bis er umgelegt wird; vor jedem Eintrag umschaltbar.
- **Suchfeld** (Name, Kurzname, Nummer) → Enter nimmt den ersten Treffer, Pfeiltasten wählen andere.
- Anzeige zum gewählten Rohstoff: **„gebucht: 23,4 kg · Meldewert 10 kg“** (bei Gebinden zusätzlich Stück, K03-9).
- **Menge in kg** (3 Nachkommastellen, Komma) → Vorschau **„neu: 48,4 kg“** → Enter **bucht sofort** → Fokus zurück ins Suchfeld.
- Darunter die **Liste der Buchungen aus dieser Erfassung** (Zeit, Rohstoff, Art, Menge, neuer Bestand). Korrektur = neue Zeile (kein Rückgängig).
- Rohstoff **ohne Bestandsführung:** „Gesamtbestand“ startet die Führung; „Zugang“ fragt „Noch kein Bestand – ab 0 starten?“.
- Buchungsarten wie bisher: `receipt` (Zugang), `inventory` (Gesamtbestand), Quelle `quick_entry`.

### 6.2 Meldeliste

Alle aktiven Rohstoffe am/unter Meldewert und im Minus, sortiert nach Abstand zum Meldewert; Tipp öffnet die Rohstoffseite (Reiter Bestand).

### 6.3 Verlauf

Alle Buchungen aus `stock_movement`, Filter Zeitraum, Rohstoff, Art (Zugang, Inventur, Abzug, Rückbuchung), mit Chargennummer.

### 6.4 Inventur (seit 0.10.35, docs/strichcode.md 5 und 17)

Panel „Inventur“ oben im Unterreiter: anlegen, Zählliste drucken, zur Zählseite, Vorschau und Abschluss, verwerfen; Archiv mit Ansicht und Excel-Export.

## 7. Gemeinsamer Reiter „Import/Export“ (M03-20)

Ein Reiter für alles (auf der Rezeptseite), in Abschnitten:

| Abschnitt | Inhalt | ab |
|---|---|---|
| **Rezepte** | Mustervorlage, Vorlagen-Import (Probelauf, Bericht, Importieren), Export .xlsx (wie bisher) | vorhanden |
| **Rohstoffe** | CSV-Import (Probelauf wie bisher), CSV-Export (mit/ohne archivierte) | R1 (von der Rohstoffseite hierher) |
| **Kennzeichnungspässe** | PDF-Import (über Add-on 3, M04-23) | Modul 04 C2 |
| **BÄKO-Belege** | Hinweis/Sprung zu „Wareneingang“ | VC03-c |

Der Export **einer Auswahl** bleibt zusätzlich als Sammelaktion in der Liste. Die Tasten „CSV-Export“/„CSV-Import“ auf der Rohstoffseite entfallen.

## 8. Schnittstellen und Daten

- **Keine Migration** für R1: alle Filter werden aus vorhandenen Daten berechnet (C1 brachte 0009).
- Lese-API `/api/v1/raw-materials` mit Filterparametern (H7) – Lesen bleibt ohne PIN (R03-16, M03-13).
- Neu: `POST /api/v1/admin/raw-materials/bulk` (Abschnitt 5); `GET /api/v1/admin/stock/movements?date_from=&date_to=&raw_material_id=&kind=` (Verlauf aller, mit PIN).
- Schnellerfassung nutzt die vorhandenen Endpunkte `…/stock/receipt` und `…/stock/inventory` mit `"source": "quick_entry"`.
- Seite: `admin.html` bleibt eine Datei mit Ansichten (Liste, Rohstoffseite, Bestand, Händler).

## 9. Tests (Auswahl)

Filter einzeln und kombiniert; „alle wählen“ nur sichtbare; jede Sammelaktion mit Vorschau, übersprungenen Fällen und Bestätigung; Typwechsel-Hinweis; Archivieren mit „auf Null“-Liste; Schnellerfassung Zugang/Gesamtbestand, ohne Bestandsführung, Enter-Ablauf, Gebinde; Rohstoffseite mit Reiterwechsel, Blättern und ungespeicherten Änderungen; Bezugsquellen aus C1 unverändert in der neuen Seite; Import/Export-Reiter (Rohstoff-CSV unverändert); Handy-Ansicht 390 px.

## 10. Konzeptfragen – entschieden 20.11.2026, 13:20 (Michael)

| Nr. | Frage | Entscheidung |
|---|---|---|
| K03-33 | Rohstoffseite: Blättern | ‹ › zum vorherigen/nächsten Rohstoff der gefilterten Liste, dazu „← Zurück zur Liste“ |
| K03-34 | „in keinem Rezept verwendet“ | in **keiner aktuellen Version eines nicht archivierten Rezepts**; alte Versionen und Chargen zählen nicht (Löschen bleibt nur bei „nie verwendet“) |
| K03-35 | Toleranz als Sammelaktion | ein Wert mit Einheit für alle gewählten, überschreibt; Vorschau zeigt alt → neu |
| K03-36 | Archivieren mehrerer mit Bestand | **geändert (Michael):** Liste „Bestand auf Null setzen“ mit allen betroffenen Rohstoffen, **alle vorgewählt, einzeln abwählbar** (statt einer gemeinsamen Ja/Nein-Frage) |
| K03-37 | Export der Auswahl | CSV im gleichen Aufbau wie der Rohstoff-Export, wieder importierbar |
| K03-38 | Spalten der Liste | fest: Nr., Name, Kurzname, Typ, Toleranz, Bestand, Meldewert, €/kg, aktive Bezugsquelle; keine Spaltenauswahl |
| K03-39 | PIN in der Schnellerfassung | keine eigene Abfrage, da der Admin-Bereich angemeldet ist (Abschnitt 2) |
| K03-40 | Umsetzung | **R1 als eigene Version (nächste freie Nummer) auf eigenem Zweig nach C1 in `main`**, ohne Migration; R1 übernimmt die C1-Oberfläche in die neue Struktur |
| K03-41 | Handy | Unterreiter als Auswahlliste unter 700 px; Liste seitlich schiebbar, Haken und Name bleiben stehen |

## 11. Umsetzung 0.10.15 (Teil R1) – Hinweise Claude

Zweig `rohstoffverwaltung` von `main` a31878c (0.10.14). Keine Migration.

- **Dateien:** `app/raw_materials/bulk.py` (neu, Sammelaktionen), `service.py` (Filter), `stock.py` (Verlauf aller, Quelle `quick_entry`), `router.py` (`POST /admin/raw-materials/bulk`, `GET /admin/stock/movements`, `export.csv?ids=`), `app/web/router.py` (`/admin/rohstoffe/<rest>`), `admin.html` (neu aufgebaut, eine Datei mit Ansichten), `recipes.html` (Rohstoff-CSV im Reiter Import/Export, `?view=io|groups`, `?q=` für die Suche). Tests `test_raw_material_bulk.py` (13), `test_raw_material_bulk_api.py` (2, GitHub).
- **H1 Händler:** Das C1-Feld „Händler“ in der Werkzeugleiste ist jetzt der Unterreiter „Händler“; die C1-Massenpflege ist Sammelaktion 6 (gleiche Logik `bulk_active_source_in_tx`). Der Endpunkt `bulk-active-source` aus C1 bleibt bestehen.
- **H2 Sammelaktion 5:** Rohstoffe **ohne Bestandsführung** bleiben bei „auf 0 setzen“ und „Führung beenden“ unverändert („keine Bestandsführung“); „auf 0“ startet also keine neue Führung. „auf 0“ bei Bestand 0 = ohne Änderung.
- **H3 Obere Reiter:** „Gruppen“ und „Import/Export“ führen auf die Rezeptseite (`?view=groups`, `?view=io`); die Rezeptseite selbst ist unverändert bis auf den Rohstoff-CSV-Teil im Import/Export.
- **H4 „Verwendet in n Rezepten“:** Taste „Rezepte mit diesem Rohstoff“ öffnet die Rezeptliste mit der Suche `R:<Name>` (C3-E4). Löschen erscheint nur bei nie verwendeten Rohstoffen.
- **H5 Meldeliste:** Filter `stock=attention` (am/unter Meldewert oder im Minus), sortiert nach Abstand zum Meldewert; Tipp öffnet die Rohstoffseite im Reiter „Bestand“.
- **H6 Verlauf aller:** mit PIN, neueste 500, Filter von/bis (Tag), Art, Rohstoff; Quelle als Text (Schnellerfassung, Station, Verwiegung, Admin).
- **H7 Filterparameter:** heißen `status`, `type`, `stock` (`below_alert`, `negative`, `none`, `attention`), `zero_percent` (wie bisher), `no_price`, `unused`, `dealer_id`, `no_source` (Abschnitt 8 nannte `zero_tolerance`/`supplier` als Platzhalter).
- **H8 Prüfung:** Die Oberfläche konnte in dieser Sitzung nicht im Browser getestet werden (FastAPI lokal nicht installiert); Skripte syntaktisch geprüft, Server-Logik mit 13 Tests. Darum Praxisprüfung (Abschnitt 12) besonders gründlich.

## 12. Prüfpunkte Praxisprüfung R1

- (a) Unterreiter Liste/Bestand/Händler, auf dem iPhone als Auswahlliste; obere Reiter Gruppen und Import/Export öffnen die Rezeptseite im richtigen Reiter.
- (b) Filter einzeln und kombiniert; nach Öffnen eines Rohstoffs und „← Zurück zur Liste“ sind Suche und Filter noch da.
- (c) Tipp auf eine Zeile öffnet die Rohstoffseite (Adresse `/admin/rohstoffe/<Nr.>`); ‹ › blättert; Browser-Zurück funktioniert; neu laden auf der Rohstoffseite öffnet denselben Rohstoff.
- (d) Grunddaten ändern → Speichern → „Gespeichert.“; ändern ohne Speichern → Liste → Rückfrage „verwerfen?“.
- (e) Neuer Rohstoff → nach dem Speichern auf seiner Seite, Reiter Bestand/Bezugsquellen da.
- (f) Archivieren/Wiederherstellen und Löschen auf der Rohstoffseite; „Rezepte mit diesem Rohstoff“.
- (g) Reiter Bestand: Zugang, Bestand setzen, leer = beenden, Verlauf.
- (h) Reiter Bezugsquellen wie in C1 (hinzufügen, aktiv setzen, entfernen, Preis grau bei Grunddaten).
- (i) Sammelaktionen 1–7 je einmal: Vorschau, „Ausführen“, übersprungene mit Grund; Archivieren mit „Bestand auf 0“-Liste, einzelne abwählen.
- (j) „alle wählen“ wählt nur die angezeigten; Filter ändern → nur sichtbare bleiben gewählt.
- (k) Bestand erfassen: Suche → Enter → Menge → Enter; Pfeiltasten; Schalter Zugang/Gesamtbestand; Vorschau „neu: …“; Rohstoff ohne Bestand mit Zugang („ab 0 starten?“) und mit Gesamtbestand.
- (l) Meldeliste und Verlauf aller Rohstoffe mit Filtern.
- (m) Händler anlegen, umbenennen, archivieren, löschen.
- (n) Import/Export: Rohstoff-CSV-Probelauf, Import, Export (mit/ohne archivierte); Export der Auswahl aus der Liste.
- (o) Sprung aus einer Rezeptzeile zum Rohstoff und „← Zurück zum Rezept“.
