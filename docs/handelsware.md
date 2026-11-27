# Handelsware und Pfand – Konzept (Modul 03, Teil H1)

Stand: 27.11.2026. **Status: entschieden, Freigabe zum Bauen Michael 27.11.2026, 09:39; gebaut mit 0.10.36 (Migration 0015).**
Grundlage: M03-28, M03-29 (23.11., 10:05), K03-73 bis K03-76 (entschieden, eingetragen 17:20), K03-77 zurückgestellt, M03-31/K03-63 (Reihenfolge: nach I1), M03-39 (Buchungsgruppe Handelsware/Leergut).
Entscheidungen K03-85 bis K03-93: Abschnitt 12. Die Abschnitte 3 bis 11 geben den entschiedenen Stand wieder.

## 1. Ziel

Cola, H-Milch, Getränke, verpackte Ware und Pfand werden heute als Hilfs- und Betriebsstoff oder als „Sonstiger Artikel“ zugeordnet. Künftig sind sie **Handelsware mit Bestand in Stück**:

- Lieferung = Zugang.
- Inventur = Zählung und Wert.
- Buchführung = Gruppe „HW“ bzw. „Leergut“.
- Nie in Rezepten, nie im Planer.

## 2. Bereits entschieden

| Nr. | Inhalt |
|---|---|
| M03-28 | Eigene Art mit Bestand, sechste Taste „Handelsware“ beim Zuordnen; Preis, Code, Lagerort, Abgang, Zwischensumme im Inventurwert; nie in Rezepten/Planer (Vorbild Art `aid`) |
| M03-29 | Pfand = Handelsware mit Bestand; Lieferung = Zugang, Rückgabe per Gutschrift oder Abgang „Pfand zurück“ |
| K03-73 | Gezählt in **Stück**; Karton = Liefereinheit, beim Eingang in Stück umgerechnet |
| K03-74 | Gutschrift bucht Pfand automatisch runter, zusätzlich Taste „Pfand zurück“ |
| K03-75 | Fracht, Maut, Gebühren: kein Bestand, Gruppe Unkosten, je Artikel gemerkt |
| K03-76 | Nach I1, eigene Migration |
| K03-77 | Kassenabgleich zurückgestellt |

## 3. Datenmodell (K03-85, K03-93)

Neue Art **`goods`** in `raw_material`, gebaut wie `aid`, damit Bestand, Scanner, Lagerorte, Inventur und Archiv ohne zweite Tabelle mitlaufen:

- Bestand intern in Tausendstel Stück (1 Stück = 1000, wie die VE bei `aid`), Anzeige „Stück“; keine Toleranz, kein Liefergebinde in Gramm.
- Neues Feld **`raw_material.is_deposit`** (Pfand ja/nein, nur bei `goods`).
- Bezugsquelle: **Stück je Liefereinheit** (z. B. KT = 24 Stück), in dem Feld, das heute „Gramm je ME“ trägt.
- Prüfungen (CHECK) wie bei `aid`; Rezepte, Stücklisten und Planer lehnen `goods` ab.
- Neues Feld **Kassennummer** (Vectron-Artikelnummer, aus der Artikelliste des Planers wählbar, leer erlaubt).
- **Doppelter Artikel (K03-93):** Gibt es einen Artikel als Rohstoff **und** als Handelsware (z. B. H-Milch), führt **nur der Rohstoff** den Bestand. Die Handelsware ist dann nur ein Verweis auf den Rohstoff mit Kassennummer. Verkäufe aus dem Kassenimport buchen beim Rohstoff ab, umgerechnet über das Gewicht je Stück (z. B. 1 H-Milch = 1.000 g). Lieferung und Inventur laufen nur über den Rohstoff.

## 4. Wareneingang (AB, Liefertag)

- Unbekannte Position: sechste Taste **„Handelsware“** (K03-92) → „Vorhandene zuordnen“ / „Neu anlegen“ (Name, **Stück je Liefereinheit** mit Vorbelegung aus dem Gebindetext, z. B. „24 ST à …“, darunter Haken **„Pfand“**). Der Haken ist **nur vorgehakt, wenn der Beleg den Artikel als Pfand oder Leergut ausweist** (BÄKO-Warengruppe 1405 bzw. Buchungsgruppe Leergut), und bleibt am Artikel jederzeit änderbar.
- Vorschlag „Handelsware“, wenn die BÄKO-Warengruppe schon als Handelsware gelernt ist (wie M03-39).
- Liefertag: Abhaken bucht **Liefermenge × Stück je Liefereinheit** als Zugang. Scan und Ersatz wie bei Rohstoffen; Ersatz nur auf Handelsware.
- **„Nicht erwartet“ (K03-91):** erst vier Tasten **Rohstoff · Hilfs- und Betriebsstoff · Handelsware · Sonstiges**, danach nur die Liste dieser Art mit Suchfeld. Sonstige Artikel haben keinen Bestand, die Lieferung wird nur vermerkt.

## 5. Rechnung, Gutschrift, Buchführung

- Rechnungsposition auf Handelsware: Gruppe **HW**; Pfand: Gruppe **Leergut** (M03-31). Wie bisher lernend und mit Prüfliste (K03-84).
- **Gutschrift mit Pfand-Artikel:** Abgang „Pfand zurück“ automatisch beim Speichern (K03-74), Menge in Stück.
- „Rechnung gegen Lieferung“ (M03-41) gilt auch für Handelsware.
- Fracht, Maut, Gebühren bleiben „Sonstiger Artikel“ mit Gruppe Unkosten (K03-75); das läuft seit 0.10.31 schon so → nur prüfen (Abschnitt 11).

## 6. Bestand, Kassenimport und Abgang (K03-86)

Zweigleisig (Michael: „Wir bauen das jetzt gleich mit ein, … im Endeffekt muss es aber über die Inventur oder Zwischeninventur immer wieder korrigiert werden“). Damit ist der zurückgestellte Kassenabgleich K03-77 wieder drin.

- **Kassenimport:** Import des Vectron-Abverkaufs (.xlsx, Artikelnummer, Anzahl, Wert). Je Handelsware mit Kassennummer wird die verkaufte Stückzahl abgebucht (Abgang „Verkauf laut Kasse“).
- **Nicht gebucht, nur angezeigt:** Sammelartikel 500 „Offene Handelswaren“ und alle Kassenartikel ohne Zuordnung.
- **Doppelt-Schutz:** Jeder Zeitraum lässt sich nur einmal importieren.
- **Ohne Kassennummer:** In der Liste der Handelsware steht „ohne Kassenartikel, nur Inventur“. Der Bestand ändert sich dann nur über Lieferung, Abgänge von Hand und Inventur. Wird die Nummer nachgetragen, läuft der Artikel ab dem nächsten Import mit.
- **Inventur/Zwischeninventur** korrigiert, was sonst abweicht. Die Differenz wird als „Schwund laut Inventur“ gebucht.
- Von Hand möglich: Abgang „Pfand zurück“, „Bruch/Verderb“ (wie M03-27), „Eigenverbrauch“.
- Kein Hinweis „Bestand reicht nicht“ für Handelsware.

## 7. Pfand

- Pfand-Artikel = Handelsware mit Haken „Pfand“ (z. B. Kiste, Flasche).
- Zugang mit der Lieferung, Abgang per Gutschrift oder Taste **„Pfand zurück“** (Rohstoffseite, Schnellerfassung, Scanner).
- **Pfand-Übersicht (K03-87), in Euro:** drei Zahlen nebeneinander
  - **Pfand BÄKO:** aus Lieferungen und Gutschriften,
  - **Pfand Kunden:** aus dem Kassenimport, z. B. „Pfand Einweg“ 1003,
  - **Pfand gesamt:** die Differenz der beiden.
  
  Euro statt Stück, weil die Kasse je Flasche bucht und die BÄKO teils je Kiste oder Gebinde.

## 8. Preis und Inventurwert (K03-88)

- Preis je Stück = **Netto der letzten Rechnung ÷ gelieferte Stück**, an der Bezugsquelle gespeichert (für Handelsware vorgezogen aus W2b).
- Inventur: Handelsware als **eigene Zwischensumme**, Pfand getrennt („Leergut“).

## 9. Inventur (Abstimmung mit I1)

- Handelsware erscheint in Zählliste, Scanner-Modus und Haken „Zwischeninventur“ wie Hilfs- und Betriebsstoffe (K03-72), gezählt in Stück.
- Abschluss bucht die Differenz nach Abschnitt 6.
- I1 ist mit 0.10.35 und Migration 0014 gebaut (`app/stocktake/`). H1 hängt die Art `goods` dort an: Zwischensumme Handelsware, Pfand getrennt.

## 10. Verschieben und Kopieren zwischen den Arten (K03-89)

Jeder Reiter (Rohstoffe, Hilfs- und Betriebsstoffe, Handelsware, Sonstige Artikel) bekommt zwei Tasten:

- **„Verschieben nach …“** ändert die Art desselben Artikels. Bezugsquelle, Belege und Verlauf bleiben dran.
- **„Kopieren nach …“** legt einen neuen Artikel in der anderen Art an. Der alte bleibt, wie er ist.
- **Grenze:** Ein Rohstoff, der in Rezepten oder Stücklisten steckt, lässt sich nur kopieren, nicht verschieben.
- Nach dem Kopieren gilt bei Rohstoff + Handelsware die Regel aus Abschnitt 3 (nur der Rohstoff führt Bestand).

Das ersetzt die frühere Idee einer eigenen Liste „In Handelsware umwandeln“. Cola, H-Milch und Pfand, die heute als Hilfs- und Betriebsstoff oder Sonstiger Artikel geführt sind, werden damit umgestellt.

## 11. Umfang, Version, Migration (K03-90)

- **Alles in einem Stück (H1)** (Michael: „Nein, alles an einem Stück“). Dazu gehören:
  - Art `goods` und Kassennummer
  - Wareneingang mit sechster Taste und „Nicht erwartet“ mit Vorfilter
  - Gutschrift-Pfand und Abgänge
  - Kassenimport und Pfand-Übersicht
  - Verschieben/Kopieren
  - Inventur-Anbindung und Tests
- **Migration 0015, Version 0.10.36**, nachdem 0.10.35 (I1, Migration 0014) auf `main` ist. Vor dem Bau `origin/main` prüfen.
- **Praxisprüfung:**
  - AB mit Cola + Pfand, Liefertag, Rechnung
  - Gutschrift mit Pfand
  - Kassenimport einer Woche (auch zweimal → abgelehnt)
  - Pfand-Übersicht
  - Verschieben/Kopieren mit H-Milch
  - Zwischeninventur, Export

## 12. Entscheidungen (Michael, Sprachchat 27.11.2026, ca. 09:00–09:20; eingetragen 09:25)

| Nr. | Frage | Entscheidung |
|---|---|---|
| K03-85 | Datenmodell | **wie vorgeschlagen:** Art `goods` in `raw_material` wie `aid`, Bestand in Stück, Haken Pfand, nie in Rezepten/Planer („Das passt so“) |
| K03-86 | Wie sinkt der Bestand? | **geändert:** zweigleisig – Kassenimport bucht Verkäufe je Kassennummer ab, Sammelartikel 500 und Unzugeordnetes nur angezeigt, Zeitraum nur einmal; ohne Kassennummer „ohne Kassenartikel, nur Inventur“; Inventur korrigiert („Sehr gut. So machen wir das.“). Nimmt K03-77 wieder auf |
| K03-87 | Pfand | **geändert:** getrennt „Pfand BÄKO“, „Pfand Kunden“, „Pfand gesamt“ (Differenz), in Euro („Ja“) |
| K03-88 | Preis je Stück | **wie vorgeschlagen:** aus der letzten Rechnung (Netto ÷ Stück), an der Bezugsquelle („Das passt“) |
| K03-89 | Bestehende Artikel umstellen | **geändert:** „Verschieben nach“ / „Kopieren nach“ in jedem Reiter; in Rezepten/Stücklisten verwendete Rohstoffe nur kopieren („Genau, das passt so“) |
| K03-90 | Umfang | **geändert:** alles in einem Stück, Migration 0015, Version 0.10.36 |
| K03-91 | Nicht erwartet am Liefertag | **geändert:** Vorfilter mit vier Tasten Rohstoff / Hilfs- und Betriebsstoff / Handelsware / Sonstiges, dann gefilterte Liste („Das passt so“) |
| K03-92 | Taste und Pfand-Haken | **wie vorgeschlagen, ergänzt:** Taste „Handelsware“, Haken „Pfand“ im Fenster, vorgehakt nur bei Pfand/Leergut laut Beleg, am Artikel änderbar („Hört sich gut an“) |
| K03-93 | **neu:** Artikel als Rohstoff und Handelsware zugleich | Nur der Rohstoff führt Bestand; die Handelsware ist ein Verweis mit Kassennummer, Kassenverkäufe buchen über das Gewicht je Stück beim Rohstoff ab; Lieferung/Inventur nur über den Rohstoff (Michael: Aufteilen am Liefertag „zu kompliziert“; „Das passt so“) |

## 13. Änderungen

| Datum | Änderung |
|---|---|
| 27.11.2026, 08:40 | Konzept erstellt (Claude), Vorschläge K03-85 bis K03-92 |
| 27.11.2026, 09:25 | K03-85 bis K03-93 entschieden (Michael, Sprachchat); Abschnitte 3–12 angepasst. Freigabe zum Bauen offen |
| 27.11.2026, 09:39 | Freigabe zum Bauen (Michael); gebaut als 0.10.36 mit Migration 0015 (Zweig `h1-handelsware`). Abweichungen: Kopie ohne BÄKO-Artikelnummer; kein „Kopieren nach Sonstiger Artikel“; Gramm ↔ Stück ohne Gewicht beendet die Bestandsführung; Kassenimport lehnt auch überlappende Zeiträume ab und lässt sich zurücknehmen |
