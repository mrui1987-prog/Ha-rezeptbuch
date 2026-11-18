# Praxisprüfung Modul 06 – Version 0.6.4

Abhakliste für die Praxisprüfung in der HA-App (iPhone). Quelle der Punkte: docs/modulstatus-06.md.

Vorbereitung:

- [ ] Add-on in Home Assistant auf **0.6.4** aktualisieren
- [ ] Beim Start: Migration 0006 gelaufen, Sicherungskopie in `/data/backups/` vorhanden
- [ ] Ein Rezept mit Chargengrößen und eines mit Vorteig bereithalten

## Teil C3 (0.6.2)

- [ ] (a) Rezepte → Chargengrößen: Haken „aktiv (Obergrenze)“ setzen, auf andere Chargengröße umsetzen (alter Haken verschwindet), speichern; Kopieren übernimmt den Haken
- [ ] (b) Export .xlsx: Blatt Chargengrößen mit Spalte „Obergrenze (ja = aktiv)“; Re-Import in dieselbe Datenbank meldet „unverändert“
- [ ] (c) Berechnung → Kombiniert: z. B. Gesamtteig 5 kg + Stückzahl + 2 × Chargengröße + Faktor 0,5 → „Bedarf Auftrag“ mit Einzelbeiträgen
- [ ] (d) Teilen: Bedarf über aktiver Chargengröße → Teige als Reiter; „voll auffüllen“ / „gleichmäßig“ umschalten; Anzahl Teige erhöhen; zu wenige → Meldung, Auswahl springt zurück; Hinweis „Letzter Teig nur … – gleichmäßig teilen?“
- [ ] (e) Obergrenze nur für diesen Auftrag: mit aktiver Chargengröße höher → Meldung „höchstens … g“; kleiner → wird geteilt; Rezept ohne aktive Chargengröße: frei eingebbar
- [ ] (f) Mehl gesamt / Leitrohstoff über Obergrenze: Rückfrage „nach Obergrenze teilen?“; „Nein“ → ein Teig mit Hinweis; „Ja“ → Teige
- [ ] (g) Rezept mit Vorteig und 2 Teigen: Auswahl „je Teig / einmal für alle“; Liste „Unterrezept-Aufträge“; Zusammenfassung „ganzer Auftrag“ (Vorteig für alle zählt einmal)
- [ ] (h) Faktor allein (z. B. 1,5): Mengen × 1,5; „1,555“ → Meldung, Feld rot
- [ ] (i) „Mehl gesamt“ in ganzen Gramm (z. B. 577 g statt 576,742 g, kaufmännisch)
- [ ] (j) Rohstoffe – Preis je kg: „2,35“ speichern → „Preis geändert am“; „2,355“ → Hinweis „gerundet … 2,36 €“; Speichern ohne Preisänderung lässt das Datum stehen; Feld leeren löscht den Preis; Archivieren/Wiederherstellen behält den Preis
- [ ] (k) CSV-Export/-Import: zwei neue Spalten am Ende („Preis je kg €“, „Preis geändert am“); geänderter Preis → Import zeigt „alt → neu“; unveränderter Re-Import ändert nichts
- [ ] (l) Alles auf dem iPhone in der HA-App (Tabellen seitlich schiebbar, keine Browser-Dialoge)
- [ ] (m) Stichprobe Bestand: Rezept speichern, Berechnung „Gesamtteig“ wie bisher, Rohstoff anlegen

## Ergänzung 0.6.3 und Korrektur 0.6.4

- [ ] (n) „ⓘ“ an „Anteil %“ / „Bäcker %“ (Zutaten, alte Version, Prüfseite Zeilen und Zusammenfassung): Fenster mit Erklärung, „OK“ schließt
- [ ] (o) „Rohstoff öffnen ↗“ in einer Rezeptzeile: Rohstoff öffnet, oben „← Zurück zum Rezept“; zurück landet man im selben Rezept. Mit ungespeicherter Änderung zuerst Rückfrage „verwerfen?“ (Abbrechen bleibt im Rezept)
- [ ] (p) „Unterrezept öffnen ↗“ (z. B. Vorteig): Unterrezept öffnet, „← Zurück zu …“ führt zum Hauptrezept
- [ ] (q) „Diese Version wiederherstellen“ in einer alten Version: Rückfrage, dann neue Version mit altem Inhalt, Meldung „Version n als neue Version m angelegt“; alte Version bleibt unverändert. Mit archiviertem Unterrezept (z. B. Vorteig): Rückfrage „„Vorteig“ ist archiviert – mit wiederherstellen?“; „Mit wiederherstellen“ holt Unterrezept und alte Version in einem Schritt zurück; „Abbrechen“ ändert nichts
- [ ] (r) Alles auf dem iPhone in der HA-App (keine Browser-Dialoge)

## Ergebnis

- Datum und Uhrzeit:
- Bestanden / Korrektur nötig:
- Anmerkungen zu einzelnen Punkten (Buchstabe nennen):
