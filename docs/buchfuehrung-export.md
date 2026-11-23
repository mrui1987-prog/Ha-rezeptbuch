# Export für die Buchführung (Wareneingang, Teil B1)

Stand: 23.11.2026, 11:30 · Status: **Konzept erstellt, Fragen K03-78 bis K03-83 offen (Vorschläge Claude – offen)** · Modul 03 (VC03-c Wareneingang)

Grundlage: Wunsch Michael 23.11.2026, 11:17 (Muster „Wareneingang_Oktober_2026.xlsx“), Entscheidungen M03-31 (11:21/11:22) und M03-32 (11:23), docs/wareneingang.md, Migration 0012.

## 1. Ziel

Monatliche Liste der **abgerechneten** Einkaufsbelege für die Buchführung, im Aufbau des bisherigen Excel-Blatts: je Beleg eine Zeile mit Brutto, MwSt. und Netto, dahinter der Nettobetrag je **Buchungsgruppe**. Start **nur mit BÄKO-Belegen** (M03-31); Belege anderer Händler (Metro, Velten, PVG, C&C, Netto, Häusler …) kommen später über einen eigenen Belegleser bzw. eine Handeingabe dazu – die Buchungsgruppen werden **jetzt schon** angelegt.

## 2. Muster (Blatt Michael, Oktober 2026)

| Spalte | Inhalt |
|---|---|
| A | laufende Ablagenummer des Belegs (229, 230 …; Gutschrift ohne eigene Nummer) |
| B | Tag (Belegdatum) |
| C | Händler |
| D–F | Brutto, MwSt., Netto |
| G–O | Netto je Gruppe: Leergut, Wurst, Spirit., Feinkost, HW, Kaffee, Zeit., Rohst., Unk. |

Beispiel BÄKO 5.10.: Brutto 1 559,69 · MwSt. 111,20 · Netto 1 448,49 = Leergut 3,00 + HW 10,31 + Rohst. 1 366,81 + Unk. 68,37.

## 3. Entscheidungen

| Nr. | Inhalt |
|---|---|
| M03-31 (11:21/11:22) | Export **vor I1 und vor Handelsware**. Start **nur BÄKO**; die **Buchungsgruppen werden jetzt angelegt**; ein Belegleser für die anderen Händler ist nachführbar. |
| M03-32 (11:23) | **Pfand und Leergut sind eine Gruppe** (zwei Namen für dasselbe), Name „Leergut“. |

## 4. Vorschläge Claude – offen

| Nr. | Frage | Vorschlag |
|---|---|---|
| K03-78 | Welche Belege sind „abgerechnet“? | **Rechnungen und Gutschriften**, nicht Auftragsbestätigungen (die AB ist kein Buchungsbeleg; Beträge können abweichen). Dafür muss das **Hochladen von Rechnung und Gutschrift aus W2 vorgezogen** werden – mindestens Einlesen, Speichern, Zuordnen der Positionen; Preisübernahme und AB-Abgleich dürfen mit W2 folgen. Reihenfolge damit: Praxisprüfung W1 → **W2a Rechnung/Gutschrift einlesen + B1 Export** → I1 → Handelsware → C2-I + Nährwerte → W2b (Abgleich, Preise). |
| K03-79 | Buchungsgruppen | Eigene Liste im Admin (anlegen, umbenennen, Reihenfolge = Spaltenfolge, archivieren). Vorgabe: **Leergut, Wurst, Spirituosen, Feinkost, Handelsware, Kaffee, Zeitung, Rohstoffe, Unkosten**. Kurzname für die Spaltenüberschrift (Leergut, Wurst, Spirit., Feinkost, HW, Kaffee, Zeit., Rohst., Unk.). |
| K03-80 | Was bedeutet „Unk.“? | Annahme **Unkosten** (Verpackung, Reinigung, Fracht, Lieferpauschale – Velten 3,50 €). Dann: Hilfs- und Betriebsstoffe → Unkosten, Rohstoffe → Rohstoffe. Bitte bestätigen. |
| K03-81 | Wo hängt die Gruppe? | **Am Artikel, einmal gesetzt:** Rohstoff (Vorgabe Rohstoffe), Hilfs- und Betriebsstoff (Vorgabe Unkosten), sonstiger Artikel (Pflicht beim Zuordnen); später an der Handelsware. Vorschlag aus der BÄKO-Warengruppe: 1405 → Leergut, 1001 → Handelsware, 1002 → Kaffee. **An der Belegposition gespeichert** (Stand beim Buchen), damit spätere Änderungen alte Monate nicht verändern; einzelne Position im Beleg umstellbar. |
| K03-82 | Ablagenummer (Spalte A) | Feld „Ablagenummer“ am Beleg, Vorschlag = höchste vergebene + 1, änderbar, eindeutig; Gutschrift ohne Pflicht (wie im Muster). Rechnungsnummer der BÄKO zusätzlich als eigene Spalte. |
| K03-83 | Export | Seite Wareneingang → Archiv: „Export Buchführung“, Monat wählen (nach **Belegdatum**), **.xlsx** wie Muster; Gutschrift als eigene Zeile mit negativen Beträgen; Summenzeile; Prüfspalte „Netto = Summe Gruppen“ (Rundung auf den Cent, Abweichung rot). MwSt. je Beleg aus den Positionen (7 %/19 % zusätzlich als zwei Spalten, falls der Steuerberater das braucht – Frage). |

## 5. Datenmodell (Entwurf, Migration nächste freie = 0013; I1 rückt auf 0014)

- `booking_group` (id, name, short_name, sort, archived)
- `raw_material.booking_group_id`, `other_article.booking_group_id`
- `receiving_line.booking_group_id` (Stand beim Speichern)
- `receiving_document.filing_no` (Ablagenummer, eindeutig wenn gesetzt)
- Vorbelegung: neun Gruppen; Rohstoffe Art standard/flour → Rohstoffe, Art aid → Unkosten; sonstige Artikel nach Warengruppe, sonst leer (muss gesetzt werden, Export zeigt „ohne Gruppe“).

## 6. Grenzen

- Nur BÄKO, solange kein weiterer Leser bzw. keine Handeingabe existiert (offene Frage „Zugang von Hand auch nur mit Beleg?“).
- Skonto wird nicht abgezogen (Netto vor Skonto wie gedruckt).
- Keine Übergabe an DATEV o. Ä.; nur .xlsx.

## 7. Änderungen

| Datum | Änderung |
|---|---|
| 23.11.2026, 11:30 | Konzept erstellt (Claude) nach Wunsch Michael 11:17, M03-31/M03-32. |
