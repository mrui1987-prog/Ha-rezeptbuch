# Änderungen

## 0.10.3 – Modul 09: „Behälter wiegen“ beginnt bei 0 (in Entwicklung)

- **„Behälter wiegen“ mitten in einer Zutat** speichert das bisher Gewogene nicht mehr als Teilmenge: Im neuen Behälter beginnt die Zutat wieder bei 0 (Michael, Praxisprüfung). Teilmengen gibt es nur bei „Behälter wechseln“

## 0.10.2 – Modul 10: Stationsoberfläche nach der ersten Praxisprüfung (in Entwicklung)

- **Ecke oben links umgedreht** (M10-15 geändert): oben Datum und Wetter – dort darf das Bild-im-Bild-Fenster liegen –, darunter die Uhrzeit, die frei bleibt
- **Wiegeansicht:** Name der Zutat etwa doppelt so groß; Soll/Ist und Balken sitzen weiter unten (gleiche Größe); direkt darunter zwei gleich große Tasten **Quittieren** und **Zutat übergehen**; Tara, Behälter, Behälter wechseln und Handwaage kleiner in einer Leiste ganz unten

## 0.10.1 – Modul 09: Korrekturen aus der Praxisprüfung (in Entwicklung)

- **Befund B1:** Die automatische Quittung verlangt mindestens das halbe Soll (aufgerundet, mindestens 1 g). Vorher wurde z. B. Boerol mit 4 g Soll und ±20 g Toleranz schon bei 0 g quittiert
- **Neue Einstellung „Mindestlast Autoquittierung“** (Standard 70 g, 0 = aus): Darunter wird nur von Hand quittiert – mit der vollen Toleranz
- **Befund B2:** Liegt die nächste Zutat schon auf, bevor die Waage nach der Tara ruhig bei 0 stand, erkennt die Software die ausgeführte Tara trotzdem (Wechsel auf netto oder Anzeige fällt um das tarierte Gewicht); keine 3 s Sperre mehr. Auch eine verspätet ausgeführte Tara mit Last drauf wird jetzt richtig erkannt

## 0.10.0 – Modul 10 Teil C1: Stationsoberfläche für das Tablet (in Entwicklung)

- **Stationsoberfläche** `/station/1` und `/station/2` (ohne PIN), Querformat für das Tablet an der Waage: Ecke oben links mit Uhrzeit (bleibt beim Bild-im-Bild sichtbar), Datum und Wetter; Kopfzeile mit Rezept, Teig, Menge, Fortschritt und nächstem Auftrag; rechts Wiegen/Übersicht/Hinweis, unten Start, Pause/Weiter, Abbruch, Vorwahl, Produktionsliste (beide folgen in 0.10.1), Chargen, Menü 🔒
- **Wiegeansicht:** Soll und Ist groß, Grob- und Feinbalken mit rotem Soll-Strich, Fortschritt der Auto-Quittung als Rand, Gebinde („1 × Sack quittieren“, dann Rest), Handzugabe, Unterrezept übernehmen/abhaken, Behälter wiegen/eingeben/wechseln mit Schrittanzeige, Handwaage, Übergehen; Abschlussanzeige mit Hinweis und Knetzeit
- **Startbild:** Handbetrieb (Tara, Null mit Rückfrage), Karten für laufende und pausierte Teige (Weiter/Übernehmen/Abbrechen); „Start“ startet bis zur Vorwahl den nächsten offenen Teig von heute
- **Meldeleiste** (rot/grau/orange/blau) für Serverfehler (B5), getrennte Verbindung (Tasten gesperrt, Neuaufbau nach 1/2/5/10 s), Waagenzustand und Höchstlast; eigene Dialoge und Zahlenfeld statt Browser-Dialogen; Tasten bis zur Antwort gesperrt
- **Startseite** `/`: öffnet die im Gerät gespeicherte Station oder fragt einmal danach (K10-3); Menü 🔒 mit PIN → Admin-Bereich oder Station ändern
- **Wetter:** `GET /api/v1/display/weather` liest die Entität der neuen Option `weather_entity` (Standard `weather.forecast_home`) über die Supervisor-API (`homeassistant_api: true`), Zwischenspeicher 15 min; ohne Wetter fehlt nur die Anzeige
- Gemeinsame Dateien `ui/common.css` und `ui/common.js` (relative Pfade, Ingress-sicher)

## 0.9.1 – Modul 09 Teil C2: Waage im Wiegeablauf (in Entwicklung)

- **Tara an der Waage** (M09-5, K09-3): Beim Start, nach jeder Quittung, beim „Weiter“ und auf Tastendruck tariert die Software und sendet `tare` an die Waage; die nächste Zutat wird erst gewogen, wenn die Waage stabil bei etwa 0 steht (höchstens 3 s, sonst rechnet die Software allein weiter und zeigt einen Hinweis). Eine verspätet ausgeführte Tara wird erkannt
- **Automatische Quittung** (M09-4): 2 s stabil in der Toleranz, Wanderung höchstens 5 g – beides unter „Einstellungen“ änderbar. Ein Hintergrund prüft die Waagen fünfmal je Sekunde
- **Höchstlast-Vorwarnung** (M09-7): Gesamtlast (Tara der Waage + Anzeige) plus noch zu wiegende Menge ab Höchstlast − 1 000 g; nur Warnung
- **Waage getrennt** (M09-8): nach 45 s ohne Waage wird der Teig pausiert; die Rückkehr hebt die Pause nicht auf
- **Abschluss durch Abnehmen** (K09-10): Nach der letzten Zutat schließt das Abnehmen des Behälters den Teig ab, die Software sendet `zero`, die Station ist frei
- **Lastprüfung beim „Weiter“** (K09-12): an derselben Waage Vergleich der Gesamtlast mit dem Stand beim Pausieren; mehr als 5 g Abweichung nur mit Bestätigung (`confirm_deviation`), wird protokolliert
- **Behälter wiegen** (K09-13) und **Behälter wechseln** (K09-14) über `POST /api/v1/batches/{id}/container` (`weigh`, `change`, `none`, `set`, `confirm`, `cancel`): Waage leeren bzw. Behälter abnehmen → Tara + Null → Behälter aufstellen → Gewicht gemerkt → Tara. Beim Wechseln wird die schon gewogene Menge als Teilmenge gespeichert und beim Rest mitgezählt
- **Handbetrieb** (M09-13): `POST /api/v1/stations/{nr}/hand/tare`, Stand unter `GET /api/v1/stations/{nr}/weigh`
- **Live-Kanal:** neue Nachricht `weigh` je Station (Ist, Soll, Toleranz, Bereich, Fortschritt der Auto-Quittung, Tara läuft, Gesamtlast, Höchstlast-Warnung, Hinweis, Behälter-Schritt)
- **Prüfseite „Ablauf“:** Live-Werte, Behälter-Tasten, Handbetrieb, Bestätigung bei Abweichung

## 0.9.0 – Modul 09 Teil C1: Wiegeablauf im Server (in Entwicklung)

- **Aufträge** (`/api/v1/orders`, ohne PIN, K09-6): anlegen mit derselben Eingabe wie die Berechnung plus „Fest an Waage“ und Datum; Produktionsliste je Tag; löschen nur offen und mit Bestätigung. Gesperrte und archivierte Rezepte sind nicht wählbar. Über der Obergrenze fragt die Schnittstelle „Nach Obergrenze teilen?“ (`split_question`)
- **Teig starten** (`POST /api/v1/orders/{id}/start`): fixiert beim ersten Teig die Rezeptversion für den ganzen Auftrag, legt die Unterrezept-Aufträge an (je Teig oder für alle), erzeugt Charge und Sollwerte; vorläufige Chargennummer `JJJJMMTT-NNN` (K09-5)
- **Zutaten** (`/api/v1/batches/{id}/…`): Wiegen von Hand mit dem Waagenwert (nur in der Toleranz und bei gültigem Wert; „manuell (stabil)“ / „manuell (nicht stabil)“, K09-2), ganze Einheiten bei Gebinden, Handzugaben, Übergehen mit Bestätigung, Unterrezept „gewogen“ (Ist-Summe, K09-1) oder „abgehakt“ (Ist = Soll), Zutat wählen, Tara von Hand (Software)
- **Pause und Übergabe:** Pause gibt den Teig für jede Station frei (außer „Fest an Waage“), „Weiter“ übernimmt atomar (die zweite Station bekommt „bereits übernommen“), Taste „Handwaage“ pausiert und hält den Teig an der Station (K09-11). Nach einem Neustart sind laufende Teige pausiert
- **Abbruch** mit Bestätigung (Gewogenes bleibt im Protokoll), **Abschluss** von Hand („Station frei“); der Auftrag ist fertig, wenn alle Teige fertig oder abgebrochen sind
- **Einstellungen** des Wiegeablaufs (`/api/v1/production-settings`, Ändern mit PIN): Auto-Quittung 2 s / 5 g, Waagenausfall 45 s, Vorwarnung Höchstlast 1 000 g, Tara-Bestätigung 3 s, Lastprüfung beim „Weiter“ 5 g – wirksam ab Teil C2
- **Live-Kanal:** neue Nachrichten `batch` und `orders` auf `/api/v1/live`
- **Prüfseite „Ablauf“** `/admin/ablauf` (PIN), neuer Reiter auf allen Admin-Seiten
- **Datenbank – Migration 0007:** neue Quittierungsarten `manual_stable`, `sub_done`; neue Protokollarten `resume_deviation`, `container`, `partial` mit Vermerk; an der Charge Pausegrund, Pausezeit, Gesamtlast bei Pause, Abschluss, Behältergewicht, aktuelle Zutat; höchstens ein laufender Teig je Station; abgeschlossene Charge nimmt nur noch den Abschluss an
- Folgt in Teil C2 (0.9.1): Auto-Quittung, Tara an der Waage mit Bestätigung, Höchstlast-Warnung, Pause nach 45 s Waagenausfall, Abschluss durch Abnehmen des Behälters, Lastprüfung beim „Weiter“, „Behälter wiegen“/„Behälter wechseln“, Handbetrieb, Live-Nachrichten `weigh`

## 0.8.1 – Korrektur aus der Praxisprüfung Modul 08 (Modul 08 freigegeben am 19.11.2026)

- **Protokoll (Befund B1):** Die Add-on-Option „Protokollstufe“ (`log_level`) wird jetzt angewendet. Bisher zeigte das Protokoll des Rezeptbuchs nur Warnungen und Fehler; jetzt erscheinen auch Infomeldungen wie „MQTT verbunden“, „Waage 1 wieder verbunden“ oder „Befehl tare an Waage 1 gesendet“, jeweils mit Datum und Uhrzeit in Ortszeit (Startzeile „HA-Rezeptbuch 0.8.1 startet (Protokollstufe info, Ortszeit Europe/Berlin)“). Dafür ist `tzdata` im Abbild

## 0.8.0 – Modul 08: Waagen-Anbindung im Rezeptbuch (freigegeben am 19.11.2026)

- **Waagen-Anbindung per MQTT** (Modul 08, docs/schnittstellen.md): Das Rezeptbuch empfängt den Zustand der Waagen von „HA-Rezeptbuch Waage“ (Schema 2) und sendet Tara/Null. Zugangsdaten vom Supervisor (`services: mqtt:need`), neue Abhängigkeiten `paho-mqtt` 2.1 und `websockets` (Live-Kanal unter uvicorn)
- **Mittelsmann** `app/scales/hub.py`: einzige Stelle für den Waagenzustand (später auch für den Wiegeablauf, Modul 09). Eine Station gilt als **offline**, wenn die Waage keine Werte liefert, das Waagen-Add-on weg ist, MQTT getrennt ist oder seit 3 s keine Meldung kam; Grund (`offline_reason`) und Beginn (`offline_since`) werden mitgegeben
- **Schnittstelle ohne PIN:** `GET /api/v1/stations`, `GET /api/v1/stations/{nr}/scale`, `POST /api/v1/stations/{nr}/scale/tare` und `…/zero` (202 gesendet; 409 offline oder Station nicht eingerichtet; 503 ohne MQTT). Befehle mit QoS 1, nie „retained“
- **Live-Kanal** WebSocket `/api/v1/live`: beim Verbinden alle Stationen, danach jede Änderung, Herzschlag alle 15 s
- **Prüfseite „Waagen“** `/admin/waagen` (PIN): Live-Gewicht, Status, Stabilität, Tasten Tara/Null; neuer Reiter „Waagen“ auf den Admin-Seiten
- **Ohne MQTT** läuft das Rezeptbuch weiter (Rezepte, Rohstoffe, Berechnung); neuer Versuch alle 30 s. `/api/v1/health` meldet zusätzlich `mqtt` (Status bleibt 200)
- Versionsnummer folgt ab jetzt dem zuletzt begonnenen Modul (0.8.0); Korrekturen an Modul 06 erscheinen als 0.8.x

## 0.6.4 – Wiederherstellen mit archiviertem Unterrezept (in Entwicklung)

- **Alte Version wiederherstellen:** Enthält die alte Version ein archiviertes Unterrezept, fragt die Oberfläche „„Vorteig“ ist archiviert – mit wiederherstellen?“. „Mit wiederherstellen“ holt das Unterrezept (und dessen archivierte Unterrezepte) und die alte Version in einem Schritt zurück, alles oder nichts. R05-23 bleibt bestehen (kein aktives Rezept mit archiviertem Unterrezept). Schnittstelle: `POST …/versions/{n}/restore` mit zusätzlichem `restore_sub_recipes: true`; ohne dieses Feld weiterhin 409 `archived_sub_recipe`, jetzt mit der Liste `sub_recipes`

## 0.6.3 – Wünsche aus der Praxisprüfung C2 (in Entwicklung)

- **Erklärung zu „Anteil %“ und „Bäcker %“:** Taste „ⓘ“ an den Spalten auf der Rezeptseite (Zutaten und alte Versionen) und auf der Prüfseite „Berechnung“ (Zeilen und Zusammenfassung); eigenes Fenster, kein Browser-Dialog
- **Sprung aus einer Rezeptzeile:** „Rohstoff öffnen ↗“ öffnet den Rohstoff auf der Rohstoffseite, „← Zurück zum Rezept“ führt zurück; „Unterrezept öffnen ↗“ öffnet das Unterrezept, „← Zurück zu …“ zum Hauptrezept. Ungespeicherte Änderungen: zuerst Rückfrage „verwerfen?“. Die Rezeptseite öffnet mit `?open=<id>` direkt ein Rezept (auch nach der Anmeldung)
- **Alte Version wiederherstellen:** Taste „Diese Version wiederherstellen“ in der Ansicht einer alten Version; legt den Inhalt als neue aktuelle Version an, die alte bleibt unverändert. Geht auch bei produzierten Versionen; „*“-Markierungen und archivierte Rohstoffe werden übernommen; ein archiviertes Unterrezept verhindert es weiterhin (R05-23). Schnittstelle `POST /api/v1/admin/recipes/{id}/versions/{n}/restore`

## 0.6.2 – Modul 06, Teil C3, und Preis je kg (in Entwicklung)

- **Bezugsarten kombinieren** (V06-1): Gesamtteig, Stückzahlen, Chargengrößen (auch dieselbe mehrmals) und **Faktor × Grundrezept** (neu, VC06-e) in einem Auftrag, in Gramm zusammengezählt; „Mehl gesamt“ und Leitrohstoff nur allein
- **Obergrenze und Aufteilung in Teige** (V06-2): Haken **„aktiv (Obergrenze)“** bei den Chargengrößen in der Rezeptbearbeitung (höchstens einer je Rezept; Kopie, Export und Import übernehmen ihn, Spalte „Obergrenze“ im Blatt Chargengrößen). Liegt der Bedarf darüber, wird in mehrere Teige geteilt: „voll auffüllen“ oder „gleichmäßig“, Anzahl Teige nur erhöhbar. Obergrenze nur für den Auftrag eingebbar (mit aktiver Chargengröße nur kleiner). Bei „Mehl gesamt“ und Leitrohstoff Rückfrage „Nach Obergrenze teilen?“. Bei Unterrezepten Auswahl „je Teig“ oder „einmal für alle“
- Prüfseite „Berechnung“: Bezugsarten „Faktor“ und „Kombiniert“, Obergrenze, Rückfragen, Teige als Reiter, Zusammenfassung „dieser Teig / ganzer Auftrag“, Unterrezept-Aufträge; **„Mehl gesamt“ in ganzen Gramm** (kaufmännisch gerundet)
- Schnittstelle `POST /api/v1/calculation` zusätzlich mit `demand`, `split`, `doughs`, `order_totals`, `order_summary`, `sub_orders` (bisherige Felder unverändert); `basis-options` mit `limit`; Funktionen für Modul 09: `plan_doughs`, `sub_order_targets`, `build_batch_items` je Teig, erweitertes `validate_basis`
- **Preis je kg am Rohstoff** (Modul 03, VC03-a): Feld „Preis je kg (€ netto)“ auf der Rohstoffseite und Spalte „€/kg“, „Preis geändert am“ automatisch, ohne PIN lesbar; mehr als 2 Nachkommastellen werden mit Hinweis gerundet. CSV-Export mit zwei neuen Spalten am Ende, CSV-Import liest die Preisspalte (leere Zelle löscht, fehlende Spalte lässt den Preis stehen)
- Datenbank-Migration `0006_order_doughs.sql`: `recipe_batch_size.is_limit`, Bezugsarten `factor`/`combined`, Obergrenze und Teilungsart am Auftrag, Tabellen `order_batch_size` und `order_dough`, `parent_dough_index`, Preisspalten am Rohstoff. Die Tabelle `production_order` wird dabei neu aufgebaut (SQLite kann CHECK-Regeln nicht ändern); dafür kennt die Migration den Schalter `-- migration: foreign_keys=off` in der ersten Zeile

## 0.6.1 – Modul 06, Teil C2 (in Entwicklung)

- **Anteil und Bäckerprozent in der Rezeptverwaltung:** neue Spalten „Anteil %“ und „Bäcker %“ in den Zutaten und in alten Versionen, dazu „Mehl gesamt (mit Unterrezepten)“; die Lese-Schnittstelle liefert zusätzlich `sums.flour_total_g` und je Zeile `share_tenths`/`baker_tenths` (vorhandene Felder unverändert)
- **Ansicht „Zusammenfassung“** auf der Prüfseite „Berechnung“: jeder Rohstoff einmal über alle Unterrezepte, Anteil, Bäckerprozent, Mehlmischung; die Schnittstelle `POST /api/v1/calculation` liefert dafür `summary` und `flour_mix`
- **Sitzungsprüfung** beim Öffnen und beim Reiterwechsel der Seiten Rohstoffe, Rezepte und Berechnung: abgelaufene Sitzung → gleich PIN-Eingabe, danach weiter zur gewählten Seite; neue Schnittstelle `GET /api/v1/admin/session` (verlängert die Sitzung nicht)

## 0.6.0 – Modul 06, Teil C1 (in Entwicklung)

- **Rezeptberechnung** als eigenes Paket `app/calculation/` (Rechenkern ohne Datenbank, exakte Brüche, Rundung nur einmal je Zeile)
- Bezugsgrößen Gesamtteig, Stückzahlen, Chargengröße, Mehl gesamt (inklusive Unterrezepten) und Leitrohstoff („gesamt“ oder je Zeile, Eingabe auch in kg oder Liter)
- Jede Zutat auf ganze Gramm aufgerundet; Prozent-Toleranz abgerundet, mindestens 1 g; Gebinde/Stück + Rest; Anteil und Bäckerprozent; Hinweis „ergibt n Stück“; Plausibilitätsprüfungen und Hinweise
- Schnittstelle ohne PIN: `GET /api/v1/recipes/{id}/basis-options`, `POST /api/v1/calculation`
- Funktionen für den Wiegeablauf (Modul 09): `validate_basis` (Befund B4), `build_batch_items` (Befund B2), `tolerance_g`
- Datenbank-Migration `0005_batch_item_version.sql`: Spalte `production_order.basis_item_position` (Leitrohstoff je Zeile) und Trigger gegen Chargenzeilen aus einer anderen Rezeptversion (Befund B2)
- Prüfseite **„Berechnung“** unter `/admin/berechnung` mit Reiter auf den Seiten Rohstoffe und Rezepte; nach der Anmeldung geht es zur Prüfseite zurück
- Migrationstests prüfen den neuesten Stand nicht mehr über eine feste Zahl

## 0.5.11 – Modul 05, Korrektur B1/B2 aus dem Freigabebericht (freigegeben am 18.11.2026)

**Modul 05 (Rezeptverwaltung) am 18.11.2026 von Michael freigegeben** – umfasst 0.5.0 bis 0.5.11.

- **Wiederherstellen und Kopieren nur ohne archiviertes Unterrezept** (R05-23): Enthält die aktuelle Version ein archiviertes Unterrezept, kommt die Meldung „… enthält das archivierte Unterrezept „…“ – bitte zuerst wiederherstellen“. So kann kein aktives Rezept mit archiviertem Unterrezept mehr entstehen
- **Sammelaktion „Wiederherstellen“** stellt Haupt- und Unterrezept gemeinsam wieder her, wenn beide angehakt sind (Reihenfolge egal)
- Meldetexte in der Einzahl: „1 Rohstoff wird überschrieben“, Vorschau „1 Rezept wird …“

## 0.5.10 – Modul 05, Korrektur (freigegeben am 18.11.2026)

- **Export → Re-Import mit archivierten Rohstoffen:** Ein vorhandenes Rezept, dessen aktuelle Version einen inzwischen archivierten Rohstoff schon verwendet, darf ihn beim Import behalten (wie beim Speichern im Formular). Vorher meldete der Import „Der Rohstoff … ist archiviert“. Neue Rezepte und neu hinzukommende Zeilen mit archivierten Rohstoffen bleiben ein Fehler

## 0.5.9 – Modul 05, Ergänzungen C3-E9, C3-E10 (freigegeben am 18.11.2026)

- **Rohstoff austauschen** (C3-E9, Taste über der Rezeptliste): alten und neuen Rohstoff mit Faktor wählen, dazu bis zu zwei Zusatzzutaten mit Faktor auf die alte Menge (direkt unter der getauschten Zeile, im selben Schritt). Angezeigt werden alle Rezepte, deren aktuelle Version den Rohstoff enthält, mit „alt → neu“; einzelne lassen sich abwählen. Jedes geänderte Rezept bekommt eine neue Version, Status und eigene Zeilentoleranz bleiben. Wahlweise „*“ an geänderten Zeilen und Archivieren des alten Rohstoffs, wenn er nirgends mehr vorkommt
- **Alte Versionen ansehen** (C3-E10): neben jeder Menge kursiv die Menge der aktuellen Version (gelb = abweichend, „entfällt“), neue Zeilen der aktuellen Version am Ende; am Handy unter der Menge

## 0.5.8 – Modul 05, Ergänzungen C3-E7, C3-E8, C3-E11 (freigegeben am 18.11.2026)

- **Umrechnung im Blatt „Rohstoffe“** (C3-E7, ersetzt das Blatt „Umrechnung“): Spalten „Umrechnung Einheit“ und „Gramm je Einheit“ beim Rohstoff, z. B. Eier: Stück, 65 – in der Rezeptzeile reicht dann „20“ „Stück“ „Eier“. Für ml gilt der Wert auch für l (× 1 000) und umgekehrt. Der Wert wird nicht gespeichert, er dient nur dem Import
- **Jede umgerechnete Zeile bekommt „*“** zum Prüfen; der Probelauf zeigt alle Umrechnungen vorab in einem eigenen Fenster („Weiter“), danach den Bericht
- Eine Zeile im Blatt „Rohstoffe“ nur mit Name und Umrechnung ändert einen vorhandenen Rohstoff nicht
- Ein Blatt „Umrechnung“ aus älteren Vorlagen wird übergangsweise weiter gelesen (Hinweis „veraltet“). Mustervorlage und Export enthalten es nicht mehr
- Hinweis zu LibreOffice („als .xlsx speichern“) in Mustervorlage, Export und Doku
- **Sammelaktion „Wiederherstellen“** für archivierte Rezepte (C3-E8), gleiche Regeln wie beim einzelnen Rezept
- **Musterdaten der Mustervorlage werden beim Import übersprungen** (C3-E11, erkannt am Namen); Hinweis im Bericht, Datei nur mit Musterdaten = „nichts zu importieren“. Zum Ausprobieren: Haken „Musterdaten der Mustervorlage mit importieren“

## 0.5.7 – Modul 05, Ergänzung C3-E5 (freigegeben am 18.11.2026)

- **Import vorhandener Rezepte erzeugt neue Versionen** (Wunsch Michael, ersetzt „vorhandene Nummer/Name = Fehler“): Ein Rezept der Datei, dessen Nummer (sonst Name) schon vorhanden ist, bekommt nach Bestätigung eine **neue Version**; die bisherige wird zur alten Version „old (n)“. Gleicher Inhalt = unverändert, keine Bestätigung nötig. Nummer, Gruppe und interne Notiz bleiben, wenn sie in der Datei leer sind; Stückgewichte und Chargengrößen werden über die Bezeichnung fortgeführt. Enthält die neue Version „*“, wird das Rezept gesperrt. Archivierte Rezepte und widersprüchliche Nummer/Name-Paare bleiben Fehler
- Bericht und Rückfrage nennen die Rezepte mit „Version n → neu n+1“

## 0.5.6 – Modul 05, Ergänzung C3-E4 (freigegeben am 18.11.2026)

- **Suche in der Rezeptliste mit Operatoren:** `R:Sonnenblumen` sucht unter den Rohstoffnamen, `K:Sonnenbl` unter den Kurznamen (jeweils in der aktuellen Version, Teiltreffer, ohne Groß-/Kleinschreibung). Ohne Operator wird wie bisher im Rezeptnamen gesucht (die Nummer geht weiter mit, ist aber nicht mehr im Hinweistext)

## 0.5.5 – Modul 05, Ergänzung C3-E3 (freigegeben am 18.11.2026)

- **Neue Filter in der Rezeptliste:** „öffentliche zeigen“ (Haken vorausgewählt, zum Ausblenden der öffentlichen Rezepte), „nie verwogen“ (noch nie in einem Auftrag oder einer Charge verwendet – solange es keine Wiegedaten gibt, trifft das auf alle Rezepte zu) und „enthält Unterrezepte“ (aktuelle Version). Lese-API: `include_public`, `never_weighed`, `has_sub_recipes`

## 0.5.4 – Modul 05, Ergänzung C3-E2 (freigegeben am 18.11.2026)

- **Mustervorlage herunterladen** (Reiter „Import/Export“): .xlsx mit Anleitung und allen Blättern der Importvorlage, gefüllt mit einem Musterrezept „Schwarzwälder Kirschtorte (Muster)“ (Unterrezept Schoko-Biskuit, Stück/ml über „Umrechnung“, „*“, Handzugabe, Zeilentoleranz, Stückgewicht, Chargengrößen) und Musterrohstoffen („Muster …“, damit echte Rohstoffe nicht überschrieben werden). Die gelben Musterzeilen vor dem echten Import löschen
- Hinweis „Bitte einen Rohstoff wählen“ beim Speichern erscheint jetzt als Fenster in der Mitte (wie Speichern/Löschen), nicht nur oben

## 0.5.3 – Modul 05, Ergänzung C3-E1 (freigegeben am 18.11.2026)

- **Sammelaktionen in der Rezeptliste:** Haken je Rezept und „alle auswählen“; sobald etwas angehakt ist, erscheint eine Leiste mit **Freischalten, Sperren, Archivieren, Löschen, Exportieren** und „Auswahl aufheben“
- Vor jeder Aktion eine Vorschau: was ausgeführt wird, was übersprungen wird (mit Grund, z. B. „ohne Zeilen“, „als Unterrezept verwendet“, „wird verwendet – bitte archivieren“) und beim Freischalten alle offenen „*“ und Toleranzen 0 % in einer Liste; eine Bestätigung für alle
- Es gelten dieselben Regeln wie beim einzelnen Rezept; nicht erlaubte Rezepte werden übersprungen, die übrigen ausgeführt. Haupt- und Unterrezept können gemeinsam archiviert oder gelöscht werden
- „Exportieren“ erzeugt die .xlsx-Datei nur mit den ausgewählten Rezepten und ihren Unterrezepten

## 0.5.2 – Modul 05, Teil C3 (freigegeben am 18.11.2026)

- **Rezeptimport aus der Importvorlage (.xlsx)** im neuen Reiter „Import/Export“: Blätter Rohstoffe, Rezepte, Rezeptzeilen, Stückgewichte, Chargengrößen und Umrechnung; erst Probelauf mit Bericht, dann Import; alles oder nichts
- Rohstoffe aus der Vorlage wie beim CSV-Import (vorhandene werden nach Bestätigung überschrieben, neue ohne Toleranz erhalten 0 %)
- Rezeptnummer oder Rezeptname schon vorhanden = Fehler; fehlende Gruppen werden angelegt; importierte Rezepte starten **gesperrt**, Zeilen mit „*“ behalten die Prüfmarkierung
- Menge g rechnet der Import selbst (Menge Original × Faktor aus g/kg/Blatt „Umrechnung“, kaufmännisch gerundet); leere Menge = 0 g Handzugabe; fehlender Faktor = Fehler; Abweichung zum Formelwert der Datei als Hinweis
- Unterrezepte innerhalb der Datei (werden zuerst angelegt), Kreise werden mit Weg gemeldet
- **Export der Rezepte als .xlsx** im Format der Vorlage (aktuelle Versionen, verwendete Rohstoffe, auf Wunsch mit archivierten Rezepten); wieder importierbar in eine leere Datenbank; Texte werden nie als Formel geschrieben
- **Interne Notiz** je Rezept (nur Admin-Bereich, nie an der Station; Ändern ohne neue Version; in Kopie, Export und Import enthalten); Datenbank-Migration `0004_recipe_note.sql`
- Rezeptseite nach der Praxisprüfung C2: Beschriftung „Kurzname“ statt „Station“; Hinweis-Anzeige „am Anfang und am Ende“ / „nur am Ende“ mit Erklärung zum leeren Hinweis; Taste „Zutaten speichern“; Stückgewichte/Chargengrößen mit deutlichem Warnhinweis bei ungespeicherten Änderungen und Rückfrage „Beides speichern / Nur Zutaten speichern“ (Änderungen gehen nicht mehr still verloren); Rückfrage zu betroffenen Chargengrößen schon beim Löschen eines Stückgewichts; Haken „mit archivierten Rohstoffen“ in der Rezeptliste; Konflikt zweier Geräte als Fenster mit „Neu laden“
- Neue Bibliothek `openpyxl`

## 0.5.1 – Modul 05, Teil C2 (freigegeben am 18.11.2026)

- **Rezeptverwaltung** unter `/admin/rezepte` (Reiter „Rohstoffe | Rezepte | Gruppen“): Rezepte anlegen, bearbeiten, kopieren, sperren/freischalten, archivieren, wiederherstellen und löschen (nur nie verwendete)
- Rezeptkopf mit Nummer (Vorschlag, bis zur ersten Verwendung änderbar), Name (eindeutig), Gruppe, Knetzeit langsam + schnell und Hinweistext (Anzeige zu Beginn oder am Ende)
- Schritte und Zutatenzeilen: Rohstoff oder Unterrezept per Nummer oder Name, Menge in Gramm (0 g = Handzugabe), eigene Toleranz je Zeile (leer = Toleranz des Rohstoffs), Zeilen verschieben, einfügen, löschen; Prüfmarkierung „*“ mit Taste „geprüft“
- Unterrezepte ohne Kreise (Meldung mit dem Weg, z. B. „Hauptteig → Vorteig → Hauptteig“)
- **Versionen:** Wurde die Version schon produziert, entsteht beim Speichern automatisch eine neue; sonst Rückfrage „Neue Version / Überschreiben“. Alte Versionen als „old (n)“ nur zum Ansehen
- Schutz vor gleichzeitigem Bearbeiten an zwei Geräten („bitte neu laden“)
- Stückgewichte und Chargengrößen je Rezept (eigene Taste, ohne neue Version)
- Neue Rezepte und Kopien starten **gesperrt**; „Freischalten“ nur mit Zeilen, bei „*“ oder Toleranz 0 % mit Warnung und Bestätigung
- Rezeptgruppen anlegen, umbenennen, sortieren, löschen (nur leere)
- Lese-Schnittstelle für die Stationen: `GET /api/v1/recipes`, `/recipes/{id}`, `/recipes/{id}/versions/{n}`, `/recipe-groups`
- Sperre B2 auch für Rezept-, Gruppen- und Schrittnamen sowie Bezeichnungen von Stückgewichten und Chargengrößen

## 0.5.0 – Modul 05, Teil C1 (freigegeben am 18.11.2026)

- **Rohstoff-CSV-Import** im Admin-Bereich (Taste „CSV-Import“): Format wie der CSV-Export, erst Probelauf mit Bericht, dann Import; alles oder nichts
- Vorhandene Rohstoffe werden mit den Werten der Datei **überschrieben** (Zuordnung über die Nummer, ohne Nummer über den Namen); der Bericht zeigt je Feld „alt → neu“, der Import startet erst nach der Bestätigung „n Rohstoffe werden überschrieben“
- Neue Rohstoffe mit leerer Toleranz erhalten **0 %** (wird gewogen, mindestens ±1 g) und werden im Bericht aufgelistet; leere Toleranz bei vorhandenen Rohstoffen bleibt unverändert
- Spalte „archiviert“ archiviert bzw. stellt wieder her; Rohstoffe, die nicht in der Datei stehen, bleiben unverändert
- Dateien aus Excel („CSV UTF-8“ und „CSV (Trennzeichen-getrennt)“) werden gelesen, ebenso Zahlen wie „25.000“
- Rohstoffliste: Filter **„nur Toleranz 0 %“**; Hinweis unter dem Toleranzfeld: 0 g = Handzugabe, 0 % wird gewogen
- **Sperre B2:** Namen und Kurznamen, die mit `=`, `+`, `-` oder `@` beginnen, werden beim Anlegen, Umbenennen und Import abgelehnt (vorhandene Namen bleiben)
- Datenbank-Migration `0003_recipe.sql`: Bearbeitungsstand je Rezept, Sperre der Rezeptnummer nach der ersten Verwendung (Vorbereitung für Teil C2)

## 0.3.4 – Korrektur nach Freigabeprüfung

- Ziffern-Sonderzeichen (z. B. „²“) in Rohstoffnummer oder Gebindegröße führten zu einem Serverfehler; jetzt erscheint die normale Meldung „muss eine ganze Zahl sein“

## 0.3.3 – Korrektur nach Praxisprüfung

- Rückfragen („endgültig löschen?“, Typwechsel) erschienen in der iOS-App nur mit „OK“ und ohne „Abbrechen“; jetzt eigene Rückfrage mit beiden Tasten

## 0.3.2 – Korrektur nach Praxisprüfung

- Startseite und Admin-Seite blieben beim ersten Aufruf in der iOS-Companion-App leer (erst nach Berührung sichtbar); erstes Zeichnen wird jetzt erzwungen

## 0.3.1 – Korrektur nach Praxisprüfung

- Startseite war im dunklen Home-Assistant-Design weiß auf weiß (Text unsichtbar); jetzt fester heller Hintergrund mit gut sichtbarer Taste „Admin-Bereich“, ebenso für die Admin-Seite

## 0.3.0 – freigegeben am 15.11.2026 (Modul 03: Rohstoff- & Zutatenverwaltung; Korrekturen 0.3.1 bis 0.3.4)

- Rohstoffverwaltung unter `/admin`: anlegen, bearbeiten, archivieren, wiederherstellen, löschen (nur wenn unbenutzt), Suche, CSV-Export
- Rohstoffnummer: nächste freie Nummer wird vorgeschlagen, bis zur ersten Verwendung änderbar; keine doppelten Namen (ohne Beachtung von Groß-/Kleinschreibung), Hinweis auf ähnliche Namen
- Optionaler Kurzname, der überall an der Station angezeigt wird (z. B. „Margarine“)
- Toleranz ist Pflichtfeld (g oder %); bei der Verwiegung gilt mindestens 1 g, 0 = Handzugabe
- Typwechsel Standard ↔ Mehl mit Warnung und Bestätigung, wenn Rezepte betroffen sind
- PIN-Schutz für alle ändernden Aufrufe, vorgezogen aus Modul 12: Probebetrieb mit PIN 1234 und rotem Hinweisbalken, nur Hash gespeichert, Sperre 5 Minuten nach 5 Fehlversuchen, Sitzungsdauer über Option `admin_timeout_minutes`
- Befund B6 aus Modul 02 behoben: eigene Datenbankverbindung je Anfrage
- Zurückgestellt (keine BÄKO-Anbindung): Allergene, Nährwerte, Zutatenliste, Lieferanten, Erstbefüllung und CSV-Import (Modul 05)

## 0.2.0 – freigegeben am 14.11.2026 (Modul 02: Datenbank & Datenmodell)

- Rezeptserver: SQLite-Datenbank `/data/rezeptbuch.db` mit 18 Tabellen (Rohstoffe, Rezepte mit Versionen, Stückgewichten und Knetzeit, Chargengrößen, Aufträge, Chargen pro Teig, Wiegeprotokoll, Änderungsprotokoll)
- Mehrere Stückgewichte je Rezept, Knetzeit, Handzugabe nach Bedarf (0 g), Prüfmarkierung „*“ für importierte Mengen
- Datenintegrität über Fremdschlüssel, Prüfregeln und Trigger (fixierte Rezeptversionen, abgeschlossene Chargen und abgeschlossene Aufträge unveränderlich, Protokolle nur anhängbar; 38 Trigger)
- Nummerierte Migrationen mit automatischer Sicherungskopie und Rückrollen bei Fehlern
- Integritätsprüfung beim Start; bei Fehlern meldet `/api/v1/health` Status 503
- Doku: `docs/datenmodell.md` neu, `docs/bedienkonzept.md` an die Entscheidungen aus Modul 02 angepasst
- Add-on `rezeptbuch_waage` unverändert (0.1.0)

## 0.1.0 – in Arbeit

- Modul 01: Architektur und Bedienkonzept freigegeben
- Repository-Grundgerüst mit zwei Add-ons (`rezeptbuch`, `rezeptbuch_waage`)
