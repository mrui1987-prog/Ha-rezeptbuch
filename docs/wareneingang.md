# Wareneingang aus BÄKO-Belegen (VC03-c) – Konzept (Schritt B)

Status: **Konzept erstellt am 21.11.2026, 09:00 (Auftrag Michael 08:17 „WE schreiben“, damit es mit der Praxisprüfung mitgeprüft werden kann). Fragen K03-42, K03-46, K03-47 am 21.11.2026, 09:06 und K03-43 bis K03-45, K03-48 bis K03-50 am 13:20 wie vorgeschlagen entschieden (Michael: „Die drei übernehme ich“ / „offene sind alle okay“).** **Ergänzt 22.11.2026, 08:05 nach `docs/strichcode.md` (H-A, K03-61, M03-26, H-D): fünfte Taste „Hilfs- und Betriebsstoff“, Migration = nächste freie Nummer, Scan-Abhaken.** **Konzept freigegeben 21.11.2026, 13:30 (Michael, Sprachchat: „Wareneingang gebe ich schon mal frei“). Umsetzung W1 wartet auf Michael: erst Kameratest, dann Strichcode, Inventur und Wareneingang gemeinsam planen (M03-24, 13:30).**
Betrifft: Modul 03 (Bestand, Rohstoffverwaltung), Modul 04 (Bezugsquellen, Add-on 3), Modul 02 (Migration), Modul 10 (Gestaltung, Wunsch Michael 08:10).
Grundlage, alles entschieden: M03-15 bis M03-18, K03-18 bis K03-32 (docs/bestand.md 8, docs/modulstatus-03.md), M04-5/M04-14/M04-24 (Bezugsquellen, Preis, „g je Mengeneinheit“, Warengruppe), M04-23/M04-27 (Belegleser in Add-on 3, JSON-Vertrag docs/kennzeichnungspass-import.md 15.4), M03-19 bis M03-23 (Rohstoffverwaltung, Unterreiter „Wareneingang“), Wunsch Michael 21.11.2026, 08:10 (touchfreundlich, Knöpfe groß, verschachteln).

## 1. Ziel und Umfang

Bestellung bei der BÄKO (Chefslist) → **Auftragsbestätigung (AB) als PDF hochladen** → das System legt einen **erwarteten Zugang** an (bucht nichts) → **am Liefertag** Positionen abhaken, Fehlmengen, Ersatz, Rückstand eintragen → **buchen** (Zugang in den Bestand). Später die **Rechnung** hochladen: Abgleich mit der AB und **Preise** an die Bezugsquelle. **Gutschriften** buchen Rückgaben.

**Enthalten:** Hochladen von AB, Rechnung, Gutschrift (Leser in Add-on 3, Schema 1); Zuordnung Beleg-Artikel ↔ Rohstoff (einmalig, danach automatisch); Liste „Sonstige Artikel“; erwartete Zugänge, Liefertag, Rückstand; Preisübernahme aus der Rechnung; Rückgabe aus Gutschrift; Belegarchiv; touchfreundliche Seiten; Migration; Tests.

**Nicht enthalten:** Bestellen selbst (bleibt in Chefslist); Kennzeichnungspass-Import (C2-I, eigener Teil, gleiche Bauweise); Buchhaltung; andere Händler als BÄKO (Aufbau offen, Leser kennt nur BÄKO); OCR für gescannte Belege.

## 2. Ablauf im Betrieb

```
 Chefslist-Bestellung
        │  AB kommt als PDF (Mail)
        ▼
 [1] AB hochladen ──► Add-on 3 liest ──► Zuordnung prüfen ──► „erwartet am …“   (bucht nichts)
        │
        ▼  Liefertag (Lieferschein auf dem Tisch)
 [2] Lieferung öffnen ──► abhaken / Menge ändern / fehlt / Ersatz ──► „Buchen“    (Zugang in den Bestand)
        │                                                   └─► Rest bleibt als Rückstand offen oder gestrichen
        ▼  Tage später
 [3] Rechnung hochladen ──► über AT-Nummer zur AB ──► Abweichungen anzeigen ──► Preise (vorgehakt) übernehmen
 [4] Gutschrift hochladen ──► Rückgabe (vorgehakt) buchen, Hinweis auf passende Lieferung
```

- **Rechnung ohne AB** (K03-26): Die Rechnung kann selbst gebucht werden (Lieferdatum aus dem Lieferschein-Abschnitt). Schon über eine AB gebuchte Aufträge erkennt das System an der AT-Nummer und bucht sie nicht doppelt.
- **Derselbe Beleg zweimal** (K03-20): erkannt an Händler + Belegnummer; Hinweis „schon eingelesen am …“, nichts Neues angelegt.

## 3. Zuordnung (K03-18, M03-16, K03-24, K03-27, K03-28, K03-32)

Jede Belegposition wird über **Händler + Artikelnummer** gesucht:

| Treffer | Ergebnis |
|---|---|
| Bezugsquelle eines Rohstoffs (BÄKO, Artikelnummer) | **Rohstoff** – automatisch, ohne Rückfrage |
| Bezugsquelle eines Hilfs- und Betriebsstoffs | **Hilfs- und Betriebsstoff** – automatisch, Menge in Verpackungseinheiten (M03-26) |
| Eintrag in „Sonstige Artikel“ | **sonstiger Artikel** – ausgeblendet, über „Sonstige anzeigen“ einblendbar |
| Warengruppe aus früheren Rechnungen in der Ignorierliste (801, 901, 1001, 1002, 1201, 1405; Einstellung) | **sonstiger Artikel** – nur wenn die Artikelnummer noch keinem Rohstoff und keinem Hilfs- und Betriebsstoff zugeordnet ist (H-A) |
| Warengruppe 1301 (Strecke) | **Strecke** – nur gespeichert, Hinweis „Zugang von Hand buchen“ (K03-30) |
| nichts | **unbekannt** – fünf große Tasten: |

**Unbekannte Position – fünf Tasten** (fünfte seit H-A, 22.11.):
1. **Zu Rohstoff zuordnen** – Liste mit Namensvorschlägen (Belegtext gegen Name, Kurzname, Passbezeichnung); bei Auswahl wird an diesem Rohstoff eine **Bezugsquelle BÄKO mit der Artikelnummer** angelegt (oder die vorhandene BÄKO-Bezugsquelle bekommt die Nummer, wenn sie leer ist). Ist die Einheit nicht KG, wird **„g je Mengeneinheit“** gleich mit abgefragt (K03-19), Vorschlag aus der Gebindegröße des Rohstoffs, wenn sie passt (M04-24).
2. **Neuer Rohstoff** – Anlegen-Fenster mit Name aus dem Belegtext (änderbar), Bezugsquelle BÄKO + Artikelnummer + ggf. „g je ME“; **Toleranz Pflicht und leer** (K03-28, K03-3).
3. **Kein Rohstoff** – kommt in „Sonstige Artikel“ (BÄKO, Artikelnummer, Bezeichnung, Warengruppe), ab dann ausgeblendet (M03-16, K03-27).
4. **Ersatz für Rohstoff …** – nur für **diese** Position (K03-32): Rohstoff wählen, Menge wie gewohnt (bei Einheit ≠ KG „g je ME“ nur für diese Buchung), fremde Artikelnummer **nicht** an der Bezugsquelle, **kein Preis**; Vermerk an der Buchung: „Ersatz für Rohstoff X – BÄKO <Artikelnummer> <Bezeichnung> – anderer Hersteller, Pass prüfen“ (M03-17).
**Ersatz – einheitlicher Ablauf (23.11.2026, 19:55, M03-35/M03-36):** Ein Ersatz (andere Marke, anderer Hersteller) ist eine Lieferausnahme und wird **immer auf den bestellten Artikel** gebucht – auf der AB (Taste 4, einzige Stelle mit Auswahlliste), am Liefertag per Taste „Ersatz“ (nur „Gebinde gleich groß?“, bei Hilfs- und Betriebsstoffen nichts) und per Scan (fremder Code nur für diese Lieferung). Nie wird dafür ein neuer Artikel angelegt; Artikelnummer und Code werden nicht dauerhaft gespeichert, kein Preis übernommen, Buchungsgruppe = die des bestellten Artikels. **M03-35:** Der Rohstoff bekommt die sichtbare Marke **„Ersatzware im Bestand – Pass prüfen“**, bis ein Admin sie quittiert. **M03-36:** Kommt derselbe Ersatz (gleiche fremde Artikelnummer bzw. gleicher Code für denselben Rohstoff) ein **zweites Mal**, fragt das System **„Dauerhaft umstellen?“** → „Rohstoff austauschen“ (C3-E9, M04-7: neuer Rohstoff mit eigenem Pass, Rezepte umhängen). Das ist der einzige Weg zu einem neuen Artikel.
5. **Hilfs- und Betriebsstoff** – zuordnen oder neu anlegen (Art „Hilfs- und Betriebsstoff“, Verpackungseinheit, Bezugsquelle BÄKO + Artikelnummer, Preis je Einheit H-B); ab dann wie ein Rohstoff mit Bestand in Einheiten.

**Bestand ist schon da:** Die Vorlage aus der Kundeninventur (M04-28) und spätere Importe legen Rohstoffe an; die Bezugsquelle mit Artikelnummer entsteht beim ersten Beleg über „Zu Rohstoff zuordnen“ (Vorschläge machen das zu einem Tipp).

## 4. Mengen (K03-19, M03-18, K03-22)

- Jede Position wird **doppelt** geführt: **Menge in Belegeinheit** (wie gedruckt, z. B. 20 L, 3 BT, 400 KG) und **Menge in Gramm** für den Bestand. KG × 1 000; sonst × „g je Mengeneinheit“ der Bezugsquelle.
- Fehlt „g je ME“ bei Einheit ≠ KG, kann die Position nicht gebucht werden (Hinweis „g je L fehlt“, Feld direkt in der Zeile).
- **Abweichende Liefermenge** wird in der **Belegeinheit** eingegeben; Hilfe über das Gebinde: bei „16 SCK à 25 KG“ Tasten **– 1 Sack / + 1 Sack** (25 kg Schritte), daneben Ziffernblock. **Bei Hilfs- und Betriebsstoffen zählen die Tasten in Verpackungseinheiten** (M03-26).
- **Mit Kamera abhaken:** siehe `docs/strichcode.md` 6 (Start bei 0, +1 Gebinde je Scan, „Nicht in der Lieferung“, „Zusätzlich aufnehmen?“, Ersatz mit Gebinde-Rückfrage H-D).
- **Bestellartikel „B“** sind beim Abhaken **nicht vorgehakt** (K03-22).
- **Rückstand:** nicht (voll) gelieferte Menge bleibt **offen** (taucht beim nächsten Liefertag wieder auf) oder wird **gestrichen**.

## 5. Preise (K03-25, K03-29)

- **AB-Preis:** nur Hinweis („freibleibend“), wird nie übernommen.
- **Rechnung:** Preis je kg = **Netto vor Skonto ÷ Menge in kg**; Anzeige alt → neu je Bezugsquelle, **alle vorgehakt**, abwählbar; Übernahme an der **Bezugsquelle**, ist sie aktiv, gilt der Preis für den Rohstoff (M04-14), „Preis geändert am“ automatisch.
- **Gutschrift, Ersatz, Strecke, sonstige Artikel:** kein Preis an Rohstoffen. Sonstige Artikel merken sich den letzten Preis je Einheit nur als Info.

## 6. Datenmodell (Migration: nächste freie Nummer nach S1/I1, K03-61)

**`receiving_document`** – ein eingelesener Beleg

| Spalte | Bedeutung |
|---|---|
| id, dealer_id (FK dealer) | Händler (BÄKO wird beim ersten Beleg angelegt bzw. über den Namen gefunden) |
| kind | `order_confirmation` / `invoice` / `credit_note` |
| doc_no | AT…/RE…/GS…, **eindeutig je Händler und Art** (K03-20) |
| doc_date, expected_date | Belegdatum, voraussichtliches Lieferdatum (AB) |
| chefslist_ref | CL… |
| status | AB: `expected` / `partial` / `booked` / `cancelled`; Rechnung: `open` / `matched` / `booked`; Gutschrift: `open` / `booked` |
| reader_version, reader_json | Leser-Version und das vollständige JSON aus Add-on 3 (Nachweis, was gelesen wurde) |
| file_name, file_sha256, file_path | PDF unter `/data/belege/` (K03-48) |
| net_cents | Netto-Summe laut Beleg |
| created_at, booked_at, note | |

**`receiving_line`** – eine Belegposition

| Spalte | Bedeutung |
|---|---|
| id, document_id, line_no | |
| article_no, description, commodity_group | wie gedruckt; Warengruppe nur aus Rechnungen |
| qty_milli, unit_code, pack_text | Menge in Belegeinheit × 1000, Einheit (KG, L, BT …), Gebinde („16 SCK à 25 KG“) |
| price_e4, price_unit, net_cents, vat_percent | Preis × 10 000, EIN/HDT/TSD, Netto, MwSt. |
| order_item | Bestellartikel „B“ |
| order_no, delivery_note_no, delivery_date | Rechnung: AT…, LI…, Lieferdatum |
| target | `raw_material` / `other` / `substitute` / `strecke` / `unknown` (Hilfs- und Betriebsstoffe sind `raw_material` mit Art „aid“) |
| raw_material_id, other_article_id | Ziel |
| state | `open` / `booked` / `backorder` / `cancelled` |
| delivered_qty_milli, grams, grams_per_unit_used | gebuchte Menge in Belegeinheit, in Gramm, benutzter Faktor (M03-18) |
| stock_movement_id | die Buchung |
| invoice_line_id | Rechnung: Bezug zur AB-Zeile |
| note | Vermerk (Ersatz, Abweichung) |

**`other_article`** – „Sonstige Artikel“ je Händler (K03-27): dealer_id, article_no (eindeutig je Händler), description, commodity_group, last_price_e4, last_unit, archived, created_at. Einkaufsverlauf = `receiving_line` mit `target = other`. „Zum Rohstoff machen“ legt Rohstoff + Bezugsquelle an und hängt die bisherigen Zeilen um (Bestand erst ab dann).

**`stock_movement`** (Neuaufbau wie in 0010): neue Art **`return`** (Rückgabe aus Gutschrift, K03-29), neue Spalte **`receiving_line_id`**; Zugänge aus Belegen sind `receipt` mit `source = receiving`.

**`setting`:** `receiving_ignored_groups` (Vorgabe „801,901,1001,1002,1201,1405“).

## 7. Regeln

| Nr. | Regel |
|---|---|
| W1 | Hochladen und Löschen mit PIN; **Lieferung abhaken und buchen ohne PIN** (K03-21, wie „Zugang buchen“). Löschen eines erwarteten Zugangs nur, solange nichts gebucht ist. |
| W2 | Nur Belege mit `status = ok` aus Add-on 3 werden angelegt; sonst Meldung mit Grund, nichts gespeichert (K03-31, nichts geraten). |
| W3 | Buchen ist **eine Transaktion** je Lieferung: alle angehakten Zeilen oder keine. Jede Zeile einzeln im Bestandsverlauf (Art Zugang, Vermerk „BÄKO AT… Pos. n“). |
| W4 | Rohstoff ohne Bestandsführung: siehe K03-46. |
| W5 | Rechnung ↔ AB über AT-Nummer und Artikelnummer; Abweichungen (Menge, Preis, Artikel nur auf einer Seite) werden angezeigt, **nichts automatisch umgebucht** (K03-20). |
| W6 | Gutschrift: negative Menge = Rückgabe (vorgehakt, abwählbar), ohne Menge nur gespeichert; Hinweis „gehört vermutlich zu Lieferung LI… vom …“ über Artikelnummer + Datum (K03-29). |
| W7 | Ersatz: nur Zeile, nie Bezugsquelle, nie Preis (K03-32). |
| W8 | Ist Add-on 3 nicht erreichbar: Meldung „Leser nicht erreichbar – Add-on ‚HA-Rezeptbuch Leser‘ starten“; Liefertag und Buchen bereits eingelesener Belege gehen trotzdem (K04-14). |
| W9 | Die Kundendaten auf dem Beleg (Name, Anschrift) liest Add-on 3 nicht aus; das PDF selbst wird abgelegt (K03-48). |

## 8. Seiten – touchfreundlich (Wunsch Michael 08:10)

**Grundsätze für alle Wareneingang-Seiten** (gelten als Vorlage für Modul 10 C3):
- Tasten **mindestens 56 px hoch** (Tablet 64 px), ganze Zeile antippbar, Abstand ≥ 8 px; keine kleinen Links.
- **Eine Hauptaufgabe je Seite**, Details eine Ebene tiefer (antippen → aufklappen oder eigene Seite), immer mit großer **„‹ Zurück“**-Taste oben links.
- Seite wird **ganz ausgenutzt**: im Querformat Liste links, Arbeitsfläche rechts; im Hochformat (iPhone) untereinander.
- Zahlen über **großen Ziffernblock** bzw. **± Gebinde-Tasten**, nicht über Tastatur.
- Unten feste Leiste mit der **einen** Abschlusstaste („Buchen“, „Speichern“), grün, breit.

**Aufbau (Rohstoffverwaltung → Unterreiter „Wareneingang“):**

```
 Wareneingang (Startseite, Kacheln 2×2 bzw. 1×4)
 ┌──────────────────────┐ ┌──────────────────────┐
 │  📄 Beleg hochladen   │ │  🚚 Lieferungen (3)   │  ← Zahl = erwartet/offen
 └──────────────────────┘ └──────────────────────┘
 ┌──────────────────────┐ ┌──────────────────────┐
 │  € Rechnungen (1)     │ │  📁 Archiv / Sonstige │
 └──────────────────────┘ └──────────────────────┘
```

1. **Beleg hochladen:** große Fläche „PDF wählen“ (mehrere möglich) → je Beleg eine Karte: Art, Nummer, Datum, Positionen, Status. Unbekannte Positionen stehen oben mit den **fünf großen Tasten** (Abschnitt 3); erst wenn alle entschieden sind, wird „Übernehmen“ grün.
2. **Lieferungen:** Liste der erwarteten Zugänge nach Lieferdatum (heute zuerst, groß). Antippen → **Liefertag-Seite**:
   - eine Zeile je Position, **links großer Haken** (ganze Zeilenhöhe), Mitte Bezeichnung + eigener Rohstoffname, rechts Menge „400 kg (16 Sack)“;
   - Zeile antippen → Feld darunter klappt auf: **– 1 Sack / + 1 Sack**, Ziffernblock, Tasten **„Fehlt“**, **„Ersatz …“**, **„Rückstand / streichen“**;
   - Gruppen klappbar nach Warengruppe (soweit bekannt), sonstige Artikel und Strecke unten eingeklappt;
   - unten **„n Positionen buchen“**; danach Zusammenfassung mit neuem Bestand je Rohstoff.
3. **Rechnungen:** Liste; antippen → Abgleich mit der AB (Abweichungen farbig) und **Preise alt → neu (vorgehakt)** → „Preise übernehmen“.
4. **Archiv / Sonstige:** alle Belege (PDF öffnen, Status), Liste „Sonstige Artikel“ mit „zum Rohstoff machen“, Ignorierliste der Warengruppen.

**Am Tablet der Backstube** (K03-42): Kachel „Wareneingang“ auf der Startseite neben den Stationen, nur **Lieferungen** (abhaken, buchen) ohne PIN.

## 9. Schnittstellen (REST `/api/v1`, Add-on 1)

| Methode | Pfad | PIN | Inhalt |
|---|---|---|---|
| POST | `/admin/receiving/upload` | ja | ein PDF → Add-on 3 (`/v1/lesen/baeko-beleg`) → Beleg mit Zuordnungsvorschlägen (noch nicht gespeichert, Probelauf-Speicher wie C2) |
| POST | `/admin/receiving/commit` | ja | Beleg mit Entscheidungen zu unbekannten Positionen speichern |
| GET | `/receiving/deliveries`, `/receiving/deliveries/{id}` | nein | erwartete/offene Lieferungen mit Zeilen |
| POST | `/receiving/deliveries/{id}/book` | nein | Zeilen mit Menge/Ersatz/Rückstand buchen (eine Transaktion) |
| GET/POST | `/admin/receiving/invoices/{id}`, `…/apply-prices` | ja | Abgleich, Preisübernahme |
| POST | `/admin/receiving/credit-notes/{id}/book` | ja | Rückgaben buchen |
| GET/PATCH | `/admin/other-articles…` | ja | Sonstige Artikel, „zum Rohstoff machen“ |
| DELETE | `/admin/receiving/documents/{id}` | ja | Beleg löschen, solange nichts gebucht |
| GET | `/admin/receiving/documents/{id}.pdf` | ja | PDF |

## 10. Tests

- Ersatz-Leser im Test (feste JSON-Antworten für AB, Rechnung 2026/2024, Gutschrift; kein Add-on 3, keine echten PDFs).
- Zuordnung: Bezugsquelle trifft, sonstiger Artikel, Ignorierliste, Strecke, die vier Tasten inkl. „g je ME“, Ersatz ohne Bezugsquelle/Preis, doppelter Beleg.
- Liefertag: alles, Teilmenge, fehlt, Rückstand bleibt offen und kommt wieder, gestrichen, Bestellartikel nicht vorgehakt, Einheit ≠ KG ohne Faktor gesperrt, eine Transaktion.
- Rechnung: Zuordnung über AT, Abweichungen, Preise vorgehakt/abgewählt, Rechnung ohne AB, keine Doppelbuchung.
- Gutschrift: Rückgabe, ohne Menge nur gespeichert, Hinweis auf Lieferung.
- Migration (nächste freie Nummer) auf befüllter Datenbank (Bestandsverlauf bleibt).
- Add-on 3 aus → Meldung, Liefertag geht.

## 11. Umsetzung in Teilen

| Teil | Inhalt | Praxisprüfung (Michael) |
|---|---|---|
| **W1** | Migration (nächste freie), AB hochladen, Zuordnung (5 Tasten), Scan-Abhaken, Lieferungen/Liefertag, Buchen, Rückstand, Ersatz, Archiv, Sonstige Artikel, Tablet-Kachel | echte AB hochladen, 5–10 Artikel zuordnen, Liefertag mit Fehlmenge, Ersatz und Rückstand, Bestand prüfen, zweite AB: Artikel automatisch erkannt |
| **W2** | Rechnung (Abgleich, Preise), Rechnung ohne AB, Gutschrift | Rechnung zur geprüften AB, Preise übernehmen, Gutschrift |

Versionen: nächste freie 0.10.x je Teil (Versionsregel 17:02). Zweig, Tests, GitHub-Testlauf, dann `main` (Projektregel 6). C2-I (Kennzeichnungspass-Import) bleibt ein eigener Teil; beide nutzen dieselbe Aufrufschicht zu Add-on 3 (`app/readers/`), die mit dem zuerst gebauten Teil entsteht.

## 12. Auswirkungen

| Modul | Auswirkung |
|---|---|
| 02 | Migration, nächste freie Nummer (`receiving_document`, `receiving_line`, `other_article`, Neuaufbau `stock_movement`) |
| 03 | eigene Seite `/wareneingang` (W1, Abweichung statt Unterreiter); Bestandsverlauf zeigt Belegbuchungen und Rückgaben |
| 04 | Bezugsquellen bekommen Artikelnummer, „g je ME“, Warengruppe aus Belegen; Add-on 3 unverändert |
| 10 | Touch-Grundsätze aus Abschnitt 8 als Vorlage für C3; Kachel auf der Startseite |
| 12 | zur Kenntnis: Lieferungen abhaken/buchen ohne PIN (K03-21) |
| 13 | PDF-Ablage `/data/belege/` gehört zur Sicherung |

## 13. Fragen – alle wie vorgeschlagen entschieden (K03-42/46/47 am 21.11.2026, 09:06; übrige 13:20)

| Nr. | Frage | Vorschlag |
|---|---|---|
| K03-42 | Liefertag auch am Backstuben-Tablet? | **Entschieden 09:06:** **Ja**, Kachel „Wareneingang“ auf der Startseite, nur Lieferungen abhaken/buchen, ohne PIN. Hochladen, Zuordnen, Rechnungen nur im Admin. |
| K03-43 | Lieferung ohne AB und ohne Rechnung (z. B. telefonisch) | **Entschieden 13:20:** Bleibt die **Schnellerfassung** (VC03-d); kein „leerer Beleg“. |
| K03-44 | Rückstand | **Entschieden 13:20:** Bleibt an der AB offen und erscheint bei **jeder** späteren Lieferung als eigener Block „Rückstand aus AT…“, bis gebucht oder gestrichen. |
| K03-45 | Liefermenge eingeben | **Entschieden 13:20:** In **Belegeinheit** mit **± Gebinde-Tasten** (Sack, Karton aus dem Gebindetext) und Ziffernblock; Gramm rechnet das System. |
| K03-46 | Rohstoff ohne Bestandsführung bekommt einen Zugang | **Entschieden 09:06:** Zeile zeigt „ohne Bestandsführung“; Haken **„Bestand ab jetzt führen (ab 0)“** je Zeile, **nicht vorgehakt**; ohne Haken wird die Zeile nur als geliefert vermerkt, kein Bestand. |
| K03-47 | Reihenfolge | **Entschieden 09:06:** **W1 vor C2-I**, W2 danach (Michael will den Ablauf mitprüfen). |
| K03-48 | PDF aufbewahren | **Entschieden 13:20:** **Ja**, unter `/data/belege/`, ohne automatisches Löschen; Löschen eines Belegs (PIN) nur ohne Buchungen. |
| K03-49 | Mehrere offene ABs am selben Tag | **Entschieden 13:20:** Liefertag-Seite zeigt **alle** fälligen ABs zusammen (je AB ein Block), gebucht wird je AB. |
| K03-50 | Händler | **Entschieden 13:20:** Händler „BÄKO“ wird über den gedruckten Namen gefunden bzw. beim ersten Beleg angelegt (Rückfrage); später andere Händler nur mit eigenem Leser. |

## 14. Änderungen

| Datum | Änderung |
|---|---|
| 21.11.2026, 09:00 | Konzept erstellt (Auftrag Michael 08:17/08:43). K03-42 bis K03-50 offen. Liegt im Projektwissen; ins Repo mit der Umsetzung. |
| 21.11.2026, 09:06 | **K03-42, K03-46, K03-47 wie vorgeschlagen entschieden** (Michael: „Die drei übernehme ich“). |
| 21.11.2026, 13:20 | **K03-43 bis K03-45, K03-48 bis K03-50 wie vorgeschlagen entschieden** (Michael: „offene sind alle okay“). Alle Fragen entschieden; Freigabe offen. |
| 21.11.2026, 13:30 | **Konzept freigegeben** (Michael, Sprachchat). Umsetzung W1 zurückgestellt, bis Strichcode-Erfassung, Inventur (VC03-e) und Wareneingang gemeinsam geplant sind (M03-24). Inhalt unverändert. |
| 22.11.2026, 08:05 | **Nachgezogen nach `docs/strichcode.md`** (Entscheidungen Michael 22.11.): fünfte Taste „Hilfs- und Betriebsstoff“, Ignorierliste nur für nicht zugeordnete Artikel (H-A, ändert K03-27 – „Sonstige Artikel“ nur noch ohne Bestand), ± Tasten in Verpackungseinheiten, Scan-Abhaken mit Ersatz-Gebinde-Rückfrage (K03-60, H-D), Migration = nächste freie Nummer (K03-61). Freigabe vom 21.11. bleibt für den übrigen Inhalt. |
| 22.11.2026, 11:16 | **W1 umgesetzt als 0.10.24** (Zweig `w1-wareneingang`, Migration 0012, Testlauf grün; Übernahme offen; 0.10.23 ist Planer P-B). **Abweichungen (Vorschlag Claude – offen):** (1) eigene Seite `/wareneingang` mit drei Kacheln (Lieferungen ohne PIN; Beleg hochladen und Archiv & Sonstige mit PIN) statt Unterreiter im Admin – ein Weg für Tablet und iPhone; (2) Händler „BÄKO“ wird beim ersten Beleg ohne Rückfrage angelegt (K03-50); (3) Ignorierliste (Warengruppen) erst mit W2, Auftragsbestätigungen brauchen sie nicht; (4) Ersatz nur über die Taste „Ersatz“ an der Zeile, nicht per Scan mit Gebinde-Rückfrage (H-D); (5) ABs desselben Tages und Rückstände je AB in der Liste „Lieferungen“, nicht als gemeinsamer Block (K03-44/K03-49). |
| 22.11.2026, 13:35 | **W1 freigegeben** (Michael), Abweichungen 1–5 wie vorgelegt übernommen; 0.10.24 in `main` und seit 13:42 in HA. |
| 22.11.2026, 14:40 | **Abweichung 4 zurückgenommen (Michael, Sprachchat): Ersatz per Scan mit Gebinde-Rückfrage (H-D).** Im Fenster „unbekannter Code“ gibt es die Taste „Ersatz für …“ (zeigt alle offenen Rohstoffe der Lieferung, auch solche mit Code); Rückfrage „Gebinde gleich groß?“ sofort beim Ersatz, bei „Nein“ neue Größe in kg; der fremde Code gilt **nur für diese Lieferung** und wird nicht am Rohstoff gespeichert; Vermerk „… anderer Hersteller, Pass prüfen“, bei anderer Größe zusätzlich „Gebinde x kg“. Umgesetzt als **0.10.25**, freigegeben 14:58, in `main` (dc3db9b) und seit 15:01 in HA. |
| 23.11.2026, 10:29 | **0.10.26 aus der Praxisprüfung W1 (Michael 10:12–10:23, „ja jetzt übernehmen“ 10:29):** Fenster auf Höhe des angetippten Artikels, neues Fenster ersetzt das alte; Einheiten-Tasten beim neuen Hilfs- und Betriebsstoff (Karton, Paket, Eimer, Sack, Dose + vergebene); Hinweis „0 g = wird nicht gewogen“ beim neuen Rohstoff; Sitzung bleibt während der Zuordnung offen, beim Speichern sonst nur PIN neu; gleicher Artikel zweimal im Beleg (Fehler 500) nutzt denselben Eintrag, Entscheidung wird auf gleiche Artikelnummern übernommen; fehlende „Gramm je ME“ orange markiert, Speichern nennt offene Positionen. Keine Migration. In `main` (64bd992, Testlauf grün), seit 10:29 in HA. |
| 23.11.2026, 11:12 | **0.10.27 aus der Praxisprüfung W1 (Michael 10:44–10:53, „ja“ 11:11):** Hinweis „0 g = wird nicht gewogen“ dauerhaft; Einheiten-Tasten nur aus der eigenen Art (Hilfs- und Betriebsstoff) + Karton/Paket/Eimer/Sack/Dose; „Bestellartikel“ statt „B“; Fehlerleiste lesbar und oben fest; Vorschlags-Tasten fragen „Gramm je ME“; jede neue Ansicht beginnt oben; Fehler beim Speichern nennen die Position, Karte rot umrandet. Keine Migration. In `main` (0d0bb20, Testlauf grün), seit 11:12 in HA. |
| 23.11.2026, 12:07 | **0.10.28 aus der Praxisprüfung W1 (Michael 11:56, „Mach das“ 12:07):** offene Positionen („Noch nicht zugeordnet“, „Gewicht … fehlt“) rot statt grün; Gewicht je Einheit verständlich abgefragt („Wie schwer ist 1 Liter?“ mit Anhaltswerten, Einheiten ausgeschrieben), Rückfrage bei ungewöhnlichen Werten. Keine Migration. In `main` (3db2106), seit 12:07 in HA. **K03-78 (12:10): W2 wird vorgezogen, aber nur Rechnung/Gutschrift einlesen und zuordnen (W2a, für den Export `docs/buchfuehrung-export.md`); Preisübernahme und AB-Abgleich später (W2b).** |
| 23.11.2026, 17:35 | **0.10.29 aus der Praxisprüfung W1 (Michael 17:15–17:32, „Beides ja“):** Auswahlliste „Zu welchem Rohstoff?“ auf dem iPhone lesbar; „PDF“ im Archiv als Vollbild in der Seite (vorher blockte Safari/HA-App das neue Fenster); **M03-33** gebuchten Beleg löschen mit „Zurückbuchen und löschen“ (Gegenbuchung „Rückgängig“, Zuordnungen am Rohstoff bleiben; ergänzt K03-48/W1); **M03-34** „Bestand ab jetzt führen“ am Liefertag vorgehakt (ändert K03-46). Keine Migration. In `main` (4bb4c8e), seit 17:35 in HA. |
| 23.11.2026, 19:56 | **0.10.30 (Michael 18:04–19:55):** Kamerabild füllt am iPhone den Rahmen; „Ersatz“ am Liefertag ohne Auswahlliste, immer auf den bestellten Artikel (Taste und Scan gleicher Ablauf). **Ersatz-Ablauf vereinheitlicht** (Abschnitt 3), dazu **M03-35** Marke „Ersatzware im Bestand – Pass prüfen“ bis zur Quittung durch einen Admin und **M03-36** beim zweiten gleichen Ersatz Rückfrage „Dauerhaft umstellen?“ → „Rohstoff austauschen“ (entschieden, Umsetzung offen; Marke braucht ein Feld am Rohstoff → mit Migration 0013). In `main` (62b29c0), seit 19:56 in HA. |
