# Export für die Buchführung (Wareneingang, Teil B1)

Stand: 23.11.2026, 17:20 · Status: **K03-78 bis K03-84 entschieden (Michael, Sprachchat, eingetragen 12:10); Konzept freigegeben (Michael, Sprachchat: „Ja, das gebe ich frei“, eingetragen 17:20)** · Modul 03 (VC03-c Wareneingang)

Grundlage: Wunsch Michael 23.11.2026, 11:17 (Muster „Wareneingang_Oktober_2026.xlsx“), Entscheidungen M03-31 (11:21/11:22), M03-32 (11:23), K03-78 bis K03-84 (Sprachchat, ~12:00), docs/wareneingang.md, Migration 0012.

## 1. Ziel

Monatliche Liste der **abgerechneten** Einkaufsbelege für die Buchführung, im Aufbau des bisherigen Excel-Blatts: je Beleg eine Zeile mit Brutto, MwSt. und Netto, getrennt nach **7 % und 19 %**, dahinter der Nettobetrag je **Buchungsgruppe**. Start **nur mit BÄKO-Belegen** (M03-31); Belege anderer Händler (Metro, Velten, PVG, C&C, Netto, Häusler …) kommen später über einen eigenen Belegleser – die Buchungsgruppen werden **jetzt schon** angelegt.

## 2. Muster (Blatt Michael, Oktober 2026)

| Spalte | Inhalt |
|---|---|
| A | laufende Buchungsnummer (229, 230 …) – **vergibt Michael in Excel** (K03-82) |
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
| K03-78 | **W2 vorgezogen, aber nur Einlesen und Zuordnen von Rechnung und Gutschrift** (Teil W2a). Abgerechnet = Rechnungen und Gutschriften, nicht ABs. Preisübernahme und AB-Abgleich bleiben in W2b (später). |
| K03-79 | Buchungsgruppen als **pflegbare Liste im Admin** (anlegen, umbenennen, Reihenfolge = Spaltenfolge, archivieren). Vorgabe: Leergut, Wurst, Spirituosen, Feinkost, Handelsware, Kaffee, Zeitung, Rohstoffe, Unkosten (Kurznamen wie im Muster). |
| K03-80 | **„Unk.“ = Unkosten.** Hilfs- und Betriebsstoffe → Unkosten, Rohstoffe → Rohstoffe. |
| K03-81 | **Gruppe am Artikel** (Rohstoff, Hilfs- und Betriebsstoff, sonstiger Artikel, später Handelsware), Vorschlag aus der BÄKO-Warengruppe; **an der Belegposition mitgespeichert**, damit alte Monate stabil bleiben; einzelne Position umstellbar. |
| K03-82 | **Keine Buchungsnummer im System** – die Spalte A bleibt im Export leer an ihrer Stelle; Michael trägt die erste Nummer ein und zieht in Excel nach unten. |
| K03-83 | Export .xlsx je Monat nach Belegdatum, Aufbau wie Muster, **zusätzlich Netto und MwSt. je Steuersatz 7 % und 19 % in eigenen Spalten** (Vorsteuerabzug); Gutschrift als eigene Zeile mit negativen Beträgen; Summenzeile; Prüfspalte „Netto = Summe Gruppen“ (Abweichung rot). |
| K03-84 | **Lernende Zuordnung mit Prüfung:** Das System merkt sich je BÄKO-Warengruppe die Buchungsgruppe; neue Artikel einer bekannten Warengruppe bekommen sie automatisch, bei einer nie gesehenen Warengruppe wird einmal gefragt. **Jede automatisch gesetzte Gruppe gilt als „ungeprüft“**, bis sie bestätigt wird; vor dem Monatsexport zeigt der **Admin-Bereich (PIN)** die Liste der ungeprüften Artikel zum Abhaken oder Umstellen – die Prüfung macht ein Admin, nicht wer die Ware annimmt. Ändern am Artikel jederzeit. (Michaels Zwischenidee „Gruppe beim Anlegen oben mit Ändern-Taste“ verworfen: „deins ist doch besser“.) |

## 4. Datenmodell (Entwurf, Migration 0013; I1 rückt auf 0014)

- `booking_group` (id, name, short_name, sort, archived)
- `commodity_group_booking` (dealer_id, commodity_group, booking_group_id) – gelernte Zuordnung Warengruppe → Buchungsgruppe
- `raw_material.booking_group_id`, `raw_material.booking_group_checked`; dasselbe an `other_article`
- `receiving_line.booking_group_id` (Stand beim Speichern)
- Vorbelegung: neun Gruppen; Rohstoffe Art standard/flour → Rohstoffe, Art aid → Unkosten, BÄKO 1405 → Leergut, 1001 → Handelsware, 1002 → Kaffee; alles Vorbelegte „ungeprüft“.

## 5. Ablauf

1. Rechnung oder Gutschrift hochladen (Seite Wareneingang, PIN) → Leser Add-on 3 → Positionen zuordnen wie bei der AB (bekannte automatisch, unbekannte über die Tasten) → speichern. Kein Bestand, keine Preise (W2b).
2. Admin → „Buchungsgruppen prüfen“: ungeprüfte Artikel abhaken oder umstellen.
3. Admin → „Export Buchführung“, Monat wählen → .xlsx. Hinweis, wenn noch ungeprüfte Artikel im Monat stecken.

## 6. Grenzen

- Nur BÄKO, solange kein weiterer Leser existiert.
- Skonto wird nicht abgezogen (Netto vor Skonto wie gedruckt).
- Keine Übergabe an DATEV o. Ä.; nur .xlsx.

## 7. Änderungen

| Datum | Änderung |
|---|---|
| 23.11.2026, 11:30 | Konzept erstellt (Claude) nach Wunsch Michael 11:17, M03-31/M03-32. |
| 23.11.2026, 12:10 | K03-78 bis K03-83 entschieden, K03-84 neu und entschieden (Michael, Sprachchat): W2a nur Einlesen/Zuordnen, Gruppen pflegbar, Unk. = Unkosten, Gruppe am Artikel, keine Buchungsnummer, 7 %/19 % getrennt, lernende Zuordnung mit „ungeprüft“-Liste im Admin. Freigabe offen. |
| 23.11.2026, 17:20 | **Konzept freigegeben** (Michael, Sprachchat zwischen 12:12 und 17:15). Fracht, Maut, Gebühren: kein Bestand, Buchungsgruppe Unkosten, gemerkt je Artikel (K03-75, Sprachchat). Umsetzung W2a + B1 mit Migration 0013 als nächste freie Version nach 0.10.29. |
