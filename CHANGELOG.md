# Änderungen

## 0.10.37 – Wareneingang: Gebinde je Scan, Rückgängig, Artikel mit Code ausblenden

Befunde Michael 27.11.2026 beim Abhaken einer Lieferung per Kamera:

- **Menge je Scan:** Sahne („VE à 5 L“) buchte je Scan nur 1 kg. Bisher galt das Gebinde am Rohstoff (Waagen-Gebinde) vor dem Gebinde laut Beleg, und ohne beides zählte ein Scan stillschweigend 1 Belegeinheit. Neu: 1. Liefergebinde am Rohstoff, 2. Gebinde laut Beleg („2 VE à 5 L“ → 5 L je Scan), 3. Gebinde am Rohstoff, 4. ist nichts bekannt, wird einmal gefragt (gilt nur für diese Lieferung, am Rohstoff ändert sich nichts). Steht das Gebinde laut AB in einer anderen Einheit als die Menge (z. B. Menge in KG, „1 VE à 5 L“), fragt das System einmal je Lieferung und schlägt den Wert laut AB vor („laut AB 1 VE = 5 L, gezählt wird aber in KG“). Die Meldung zeigt die Menge je Scan („+1 VE = 5 L Sahne → 10 L“). Die ± Tasten an der Zeile nutzen denselben Schritt.
- **Rückgängig beim Abhaken:** breite Taste „↶ Rückgängig – letzter Scan“ (mehrfach). War der Code bei diesem Scan neu zugeordnet, wird die Zuordnung wieder gelöst; ein begonnener Ersatz wird entfernt. Neu: `POST /api/v1/barcodes/release` (ohne PIN, nur frisch zugeordnete Codes der letzten 10 Minuten, nie umgehängt; ältere nur an der Rohstoffseite mit PIN).
- **Fenster „Code unbekannt“:** Artikel der Lieferung, die schon einen Code haben, sind ausgeblendet; Taste „Auch Artikel mit Code zeigen (n)“. „Ersatz für …“ zeigt weiter alle.
- Belegzeilen liefern `rm_delivery_pack_g`, `rm_delivery_pack_label` und `rm_has_code` mit. Keine Migration.

## 0.10.36 – Handelsware und Pfand (Teil H1)

- **Neue Art „Handelsware“** (docs/handelsware.md, K03-85 bis K03-93, Freigabe Michael 27.11.2026, 09:39): gebaut wie die Hilfs- und Betriebsstoffe, Bestand in Stück (intern 1 Stück = 1000), Haken **Pfand**, **Kassennummer** (Vectron, aktiv eindeutig; ohne: „ohne Kassenartikel, nur Inventur“). Nie in Rezepten, Stücklisten oder im Planer. Handelsware und übrige Arten haben getrennte Namensräume (H-Milch als Rohstoff und als Handelsware).
- **Wareneingang:** sechste Taste **„Handelsware“** (zuordnen / neu mit Stück je Liefereinheit aus dem Gebindetext und Haken Pfand, vorgehakt nur bei BÄKO-Warengruppe 1405 bzw. Gruppe Leergut), Vorschlag bei gelernter Warengruppe HW/Leergut. Liefertag bucht Liefermenge × Stück je Liefereinheit; fehlt die Angabe, wird beim Buchen gefragt. **„Nicht erwartet“** mit Vorfilter Rohstoff / Hilfs- und Betriebsstoff / Handelsware / Sonstiges (Sonstiges ohne Bestand, nur vermerkt).
- **Rechnung** setzt den Preis je Stück an der Bezugsquelle (Netto ÷ gelieferte Stück, K03-88). **Gutschrift** mit Pfand-Artikel bucht „Pfand zurück“ automatisch (K03-74); Beleg löschen mit „zurückbuchen“ nimmt auch diesen Abgang zurück. Buchungsgruppe-Vorschlag: Handelsware → HW, Pfand → Leergut.
- **Abgangsgrund „Pfand zurück“** (nur Pfand-Artikel) am Artikel, in „Bestand erfassen“ und an der Scan-Seite; der Reiter „Bestand“ am Artikel hat jetzt auch „Abgang buchen“.
- **Kassenimport Vectron-Abverkauf** (.xlsx, Spalten über die Überschrift, Zeitraum aus der Datei vorgeschlagen): bucht je Kassennummer „Verkauf laut Kasse“ (neue Buchungsart), Sammelartikel 500 und Unzugeordnetes nur angezeigt, jeder Zeitraum nur einmal (auch Überlappung abgelehnt), Rücknahme mit Gegenbuchung (K03-86).
- **Rohstoff + Handelsware** (K03-93): Handelsware als Verweis auf den Rohstoff mit Gewicht je Stück; nur der Rohstoff führt Bestand, Kassenverkäufe buchen dort ab.
- **„Verschieben nach …“ / „Kopieren nach …“** (K03-89) an jedem Artikel und bei den sonstigen Artikeln; Umrechnung von Bestand, Preis und Bezugsquellen über das Gewicht je Stück bzw. Stück je VE. In Rezepten/Stücklisten verwendete Rohstoffe nur kopieren. Handelsware → Rohstoff kopieren: der Rohstoff übernimmt Bestand, Bezugsquellen und Codes, die Handelsware wird Verweis.
- **Pfand-Übersicht** in Euro: Pfand BÄKO, Pfand Kunden (Kassenimport), Pfand gesamt (K03-87).
- **Inventur:** Handelsware in Stück, eigene Zwischensumme Handelsware, Pfand getrennt; Inventur-Differenz bei Handelsware mit Vermerk „Schwund laut Inventur“.
- **Migration 0015:** `raw_material` neu aufgebaut (Art `goods`, `is_deposit`, `register_no`, `stock_ref_id`, `piece_g`), `stock_movement` neu aufgebaut (Art `sale`, Grund `deposit_return`, `sales_import_id`), neu `sales_import`, `sales_import_line`, `stocktake_line.is_deposit`. Neu: `POST /api/v1/admin/raw-materials/{id}/move|copy`, `POST /api/v1/admin/other-articles/{id}/move|copy`, `GET /api/v1/admin/deposit-overview`, `POST/GET /api/v1/admin/sales-imports`, `GET/DELETE …/{id}`.
- Abweichungen vom Konzept: Kopieren legt keine BÄKO-Artikelnummer an die Kopie (eine Artikelnummer gehört genau einem Artikel); Kopieren nach „Sonstiger Artikel“ gibt es nicht (nur Verschieben). Gramm ↔ Stück ohne Gewichtsangabe beendet die Bestandsführung (neu zählen).

## 0.10.35 – Inventur (Teil I1), Wareneingang „Dauerhaft umstellen“ legt den neuen Rohstoff an

- **Inventur mit Stichtag, Zählliste, Abschluss und Inventurwert** (VC03-e, docs/strichcode.md 5, Abschnitt 17). Neues Panel „Inventur“ im Unterreiter Bestand (PIN): anlegen (Bezeichnung, Stichtag, Umfang), Zählliste drucken (nach Lagerort, blind), Vorschau mit gezählt/Buchbestand/seit Zählung/neu/Differenz/Wert, Ungezählte „unverändert“ oder einzeln „auf 0“, Abschluss in einer Transaktion (Vermerk „Inventur TT.MM.JJJJ“), Verwerfen, Archiv mit Excel-Export (Zwischensummen Rohstoffe / Hilfs- und Betriebsstoffe, Blatt „ohne Preis“). Preis und Wert werden beim Abschluss festgeschrieben (K03-58).
- **Zählen ohne PIN** auf der Scan-Seite, neuer Modus „Inventur zählen“: Lagerort wählen oder Ort-Code scannen (jederzeit, O-3), Scan = +1 Gebinde, „Menge“ von Hand („3 Sack + 12,5 kg“, O-5) oder 0, „Ort fertig“ (O-4), Einträge löschen, Rückgängig, Filter „nur noch nicht gezählte“, Fußleiste „noch zu zählen: n“. Während der Inventur darf weiter verwogen und gebucht werden – der Abschluss rechnet Bewegungen seit der Zählung dazu.
- **Hilfs- und Betriebsstoffe** zeigen Bestand und Meldewert in Rohstoffliste, Rohstoffseite, Schnellerfassung und Meldeliste jetzt in Verpackungseinheiten statt kg.
- **Migration 0014:** `stocktake`, `stocktake_count`, `stocktake_line`. Neu: `GET /api/v1/stocktakes/open`, `POST/DELETE /api/v1/stocktakes/open/counts`, `POST /api/v1/stocktakes/open/location-done`, `GET/POST /api/v1/admin/stocktakes`, `GET …/{id}`, `POST …/{id}/close`, `POST …/{id}/cancel`, `GET …/{id}/countlist`, `GET …/{id}.xlsx`.
- Abweichung: Zählliste als Druck aus der Seite statt PDF vom Server (keine PDF-Bibliothek im Add-on).
- **Wareneingang – Befund Michael 27.11.2026 (Quark zum zweiten Mal als Ersatz):** „Dauerhaft umstellen …“ beim Hochladen der AB sprang sofort zu „Rohstoff austauschen“, ohne den neuen Rohstoff anzulegen – dort fehlte er, die Zuordnung der AB ging verloren. Jetzt: Rückfrage → Fenster „Neuer Rohstoff“ (Name vorbelegt) → beim Speichern wird er angelegt, danach „Rohstoff austauschen“ mit alt **und** neu vorbelegt (als Nummer + Name, eindeutig auch bei mehreren Quark-Rohstoffen); „Später“ bleibt möglich.
- Rückfrage am Liefertag (zweiter gleicher Ersatz beim Buchen) sagt jetzt, dass der neue Rohstoff dafür schon angelegt sein muss.
- `recipes.html` versteht `?view=replace&old=…&new=…`; Belegpositionen liefern die Rohstoffnummer mit.

## 0.10.34 – Waren- und Hauptgruppen im Planer, Hinweis bei Tasten an der Waage, klarere „Weiter“-Tasten

- **Waren- und Hauptgruppen mit Namen (Planer, Modul 10):** Neuer Import „Waren- und Hauptgruppen aus der Vectron (.xlsx)“ unter Rezepte → Import/Export (Probelauf → Übernehmen, PIN); erkennt Warengruppen-Export (Nummer, Name, A-Hauptgruppe) und Hauptgruppen-Export (Nummer, Name). Planer an der Station sortiert und filtert nach Hauptgruppe („7 Kuchen“, darunter Warengruppen, wenn mehrere), Artikelliste gliedert den Filter nach Hauptgruppen, Artikel zeigen Waren- und Hauptgruppe; ohne Namen bleibt die Nummer. Gespeichert als Einstellungen, keine Migration. Neu: `GET /api/v1/articles/group-names`, `POST /api/v1/admin/articles/group-names/import` (Michael 24.11.2026, 12:56/13:03/13:21).
- **Hinweis nach Tastendruck an der Waage:** Erkennt die Software Tara/Null von Hand, steht 30 s lang ein gelber Hinweis an der Station („Hey! Die Waage bitte nicht über ihre Tasten bedienen – das geht hier am Tablet.“) – beim Wiegen im Hinweisfeld, in Handwaage/Handbetrieb über der Taste „Weiter“; ohne Bestätigung (Michael 24.11.2026, 12:51).
- **Tara bei Strichen:** Tara bleibt ohne gültigen Wert verboten, die Meldung sagt jetzt „Leere Waage: bitte „Null“ drücken“.
- **Tara/Null von Hand an der Waage wird jetzt wirklich erkannt** (Befund Michael 24.11.2026, 12:37: im Probelauf nie erkannt). Die KERN zeigt beim Tastendruck kurz Striche – die alte Regel (zwei Werte direkt hintereinander, höchstens 0,7 s) griff deshalb nie. Neu: letzter ruhiger Wert als Anker; kommt innerhalb von 3 s ein Wert bei 0 ohne Zwischengewicht (Striche erlaubt), war es eine Taste. Weiterhin nur im Add-on-Protokoll („… von Hand an der Waage erkannt“), kein Fenster.
- **„Weiter“ mit abweichendem Gewicht:** Die Tasten sagen jetzt, was mit der gewogenen Menge passiert, und nennen sie: „1.907 g sind im Kessel – sie zählen“ (bisher „Schon in den Kessel gegeben“) und „Neu anfangen – 1.907 g zählen nicht“ (bisher „Behälter neu aufgestellt, nichts zugegeben“). Grund: Wer ausgekippt und den leeren Behälter zurückgestellt hat, für den klang beides richtig (Michael 24.11.2026, 12:13).

## 0.10.33 – Buchführung: leerer Export erklärt, Prüfliste behält geprüfte Artikel, Rechnung gegen Lieferung, Zuordnung im Archiv

- **Export:** Die Seite zeigt, für welche Monate Rechnungen/Gutschriften eingelesen sind, und wählt den neuesten davon vor. Ohne Rechnung im Monat gibt es statt einer leeren Excel-Datei einen Hinweis – Auftragsbestätigungen zählen nicht für die Buchführung (K03-78). Neu: `GET /api/v1/admin/booking/months`.
- **„Buchungsgruppen prüfen“ (Wunsch Michael 24.11., 10:08):** Bestätigte Artikel verschwinden nicht mehr, sondern stehen grün hinterlegt in der Liste und bleiben über „Ändern“ bearbeitbar; offene zuerst. Taste oben „Geprüfte ausblenden/einblenden“ (merkt sich die Wahl). Neu: `GET /api/v1/admin/booking/articles`.
- **Rechnung gegen Lieferung (Wunsch Michael 24.11., 10:29, Anlass Kirschwasser):** Nach dem Einlesen einer Rechnung und im Archiv über „Zuordnung“ stehen Rohstoff-Positionen, die laut AB nicht (voll) geliefert/gebucht sind, **rot** mit „Nachbuchen“ (bucht die fehlende Menge auf die AB-Position, ohne AB direkt auf den Rohstoff; fehlt das Gewicht je Einheit, wird gefragt) und „Nicht buchen“. Neu: `POST /api/v1/admin/receiving/documents/{id}/lines/{line}/rebook`.
- **Archiv: Taste „Zuordnung“** zwischen „PDF“ und „Löschen“: zeigt je Position Artikel (und bei Rechnungen die Buchungsgruppe) und lässt sie ändern. Noch nicht gebuchte Positionen: Artikel umhängen (die BÄKO-Artikelnummer wandert mit) oder „Kein Rohstoff“; gebuchte nur die Gruppe. Neu: `GET …/documents/{id}/assignment`, `PATCH /api/v1/admin/receiving/lines/{id}`.
- **Korrektur:** AB-Nummer, Lieferschein und Lieferdatum je Rechnungsposition wurden aus dem Leser unter falschem Namen gelesen und blieben leer; jetzt gespeichert (alte Rechnungen: AB-Nummer wird aus dem gespeicherten Leserergebnis nachgelesen).
- **„Ersatzware – Pass prüfen“:** zeigt zusätzlich Ersatz, der auf einer Auftragsbestätigung eingetragen, aber noch nicht geliefert ist („erwartet“). Die Marke am Rohstoff (M03-35) kommt weiterhin erst beim Buchen am Liefertag. Neu: `GET /api/v1/admin/receiving/substitutes/pending`.

## 0.10.32 – Tara-Modell M09-19

- **Nach „Behälter wiegen/wechseln“ nur noch Tara, kein Null mehr mit dem Behälter auf der Waage.** Die KERN löscht beim Nullen die Tara und „versteckt“ den Behälter – dadurch stimmte die Gesamtlast nicht mehr. Wird die Tara nicht bestätigt, sendet die Software sie bei ruhiger Anzeige bis zu zweimal neu. Null gibt es nur noch auf leerer Waage.
- **Tasten an der Waage ändern nie Ist oder Tara der Software** – jetzt auch beim laufenden Wiegen. Erkannte Tara/Null von Hand steht nur im Protokoll („… von Hand an der Waage erkannt – Ist und Gesamtlast bleiben“), ohne Fenster am Tablet.
- **Taste „Null“ am Tablet** (Handwaage, Handbetrieb) nur noch bei wirklich leerer Waage: Der Server prüft die Gesamtlast (höchstens 50 g) statt der Anzeige; bei `-----` (Last abgenommen) erlaubt. Neu: `POST /api/v1/stations/{nr}/hand/zero`.

## 0.10.31 – Rechnung/Gutschrift einlesen (W2a), Export für die Buchführung (B1), Ersatzware (M03-35/36), Beleg-Foto (M03-37), „Weiter“ ohne neue Tara (M09-17/18)

- **Migration 0013:** Buchungsgruppen (neun Vorgaben: Leergut, Wurst, Spirituosen, Feinkost, Handelsware, Kaffee, Zeitung, Rohstoffe, Unkosten), gelernte Zuordnung Warengruppe → Gruppe, Gruppe + „geprüft“ an Rohstoff und sonstigem Artikel, Gruppe/Betrag nach Skonto/Ersatz-Bezug an der Belegposition, Marke „Ersatzware im Bestand“ am Rohstoff.
- **W2a:** „Beleg hochladen“ nimmt jetzt auch BÄKO-Rechnungen und -Gutschriften. Zuordnen wie bei der AB, dazu je Position die Buchungsgruppe (Vorschlag, „Ändern“); neue Warengruppe ohne Gruppe muss einmal gewählt werden und wird gelernt. Bucht keinen Bestand, keine Preise (W2b später).
- **B1:** neue Kachel „Buchführung“ (PIN): Monat anzeigen und als Excel laden (Spalte Nr. leer, Brutto/MwSt./Netto, Netto je Gruppe, Netto und MwSt. je 7 %/19 %, Prüfspalte, Summenzeile; Gutschriften negativ); Liste „Buchungsgruppen prüfen“ (automatisch gesetzte bestätigen oder umstellen); Gruppen pflegen (anlegen, umbenennen, Reihenfolge, archivieren).
- **M03-35:** Ersatz am Liefertag (Taste, Scan, Ersatz von der AB) setzt am Rohstoff „Ersatzware im Bestand – Pass prüfen“; Liste unter „Buchführung“ mit „Pass geprüft“.
- **M03-36:** Kommt derselbe Ersatz (gleiche fremde Artikelnummer bzw. gleicher Code) ein zweites Mal, fragt die Seite „Dauerhaft umstellen?“ und öffnet „Rohstoff austauschen“ bei den Rezepten (neu: `admin/rezepte?view=replace&old=…`).
- **M03-37 (Beleg-Foto zu „Zugang buchen“):** kein Beleg-Zwang; neue Taste „📷 Beleg fotografieren“ am Rohstoff (Reiter Bestand) und „📷 Beleg“ in der Schnellerfassung (nur Zugang). Das Foto wird auf dem Gerät auf höchstens 1600 px verkleinert und nach der Buchung an den Zugang gehängt (ohne PIN, nur Zugänge, ein Foto, bis 60 Minuten nach der Buchung). Ablage `belege/zugang/` neben der Datenbank; im Verlauf „📎 Beleg“ (Ansicht mit PIN). Migration 0013: `stock_movement.attachment`. Station folgt mit Modul 10 C2.

- **M09-17 (Wiegeablauf, „Weiter“ ohne neue Tara):** „Weiter“ an derselben Waage tariert nicht mehr neu, wenn die Gesamtlast höchstens 5 g vom Stand beim Pausieren abweicht – das Ist der angefangenen Zutat läuft weiter (Handwaage, Pause, 45 s Waagenausfall, Neustart des Add-ons). Weicht sie ab, fragt die Station: „Schon in den Kessel gegeben“ (bisher Gewogenes zählt als Teilmenge, Rest wiegen; nur bei angefangener Zutat), „Behälter neu aufgestellt, nichts zugegeben“ (neue Tara) oder „Abbrechen“. Migration 0013: Spalten `snap_*` an `batch` (Stand der Waage dauerhaft).
- **Tara/Null von Hand während der Handwaage:** Drückt jemand während der Handwaage (oder einer Pause) an der Waage Tara oder Null, erkennt die Software den Sprung auf 0 und führt die Gesamtlast nach – „Weiter“ mit dem richtigen Behälter läuft dann ohne Rückfrage weiter (Befund Michael 23.11.2026, 21:09/21:36). Erkannt wird ein direkter Sprung einer ruhigen, tarierten Anzeige auf ~0 (höchstens 0,7 s, nicht in den 3 s nach einem eigenen Befehl); das Add-on-Protokoll meldet „Tara/Null von Hand an der Waage erkannt“.
- **Behälter:** Die Taste „Gewicht eingeben“ heißt jetzt „Gewicht notieren (ohne Tara)“ – sie speichert nur das Behältergewicht und ändert das Ist nicht.
- **M09-18:** Eine angefangene Zutat wird nach einer automatischen Pause nicht an der anderen Waage übernommen (wie der Stationswechsel im Normalbetrieb): „Die Zutat ist an Waage X angefangen – bitte dort fertig wiegen und quittieren.“

## 0.10.30 – Wareneingang: Kamerabild füllt den Rahmen, Ersatz immer auf den bestellten Artikel

- Liefertag mit Kamera (iPhone): das Bild lag klein oben, der Scan-Rahmen darunter im Schwarzen. Jetzt feste Höhe, das Bild füllt die Fläche, der Rahmen liegt im Bild (Michael 23.11.2026, 18:05).
- „Ersatz“ am Liefertag bucht immer auf den bestellten Artikel (andere Marke/anderer Hersteller, Vermerk „Pass prüfen“) – keine Auswahlliste mehr, kein neuer Artikel; nur die Gebindegröße wird gefragt, bei Hilfs- und Betriebsstoffen gar nichts (Michael 18:04/19:48: als Ersatz für Cola nicht in Apfelschorle buchen, für Weizenmehl 550 von Hersteller Y keinen neuen Rohstoff anlegen). Taste und Scan nutzen denselben Ablauf. Keine Migration.

## 0.10.29 – Wareneingang: Auswahlliste auf dem iPhone, PDF im Archiv, Löschen mit Zurückbuchen, Bestandsführung vorgehakt

- Fenster „Zu welchem Rohstoff?“ (Zuordnen, Ersatz, unbekannter Code, Archiv „zum Rohstoff machen“): die Tasten der Liste wurden zusammengedrückt, die zweite Zeile („Rohstoff“) war abgeschnitten und lief unter die nächste Taste (Michael 23.11.2026, 17:17, iPhone). Jetzt volle Höhe, Schrift an kleine Bildschirme angepasst, Nummer fett vor dem Namen, Suchfeld „Suchen …“.
- Archiv: „PDF“ zeigt den Beleg jetzt in der Seite (Vollbild mit „Schließen“ und „Herunterladen“). Vorher lud der Server das PDF, das neue Fenster wurde aber von Safari/HA-App blockiert, weil es erst nach dem Laden geöffnet wurde (Michael 17:22).
- Archiv: Beleg löschen, aus dem schon gebucht wurde – Rückfrage „Zurückbuchen und löschen“: jeder Zugang bekommt eine Gegenbuchung „Rückgängig“ mit Vermerk „Beleg … gelöscht“, der Bestandsverlauf bleibt erhalten (z. B. wenn keine Rechnung kommt; M03-33, Michael 17:22). Zuordnungen am Rohstoff (Bezugsquelle, Artikelnummer, Gewicht je Einheit) bleiben.
- Liefertag: „Bestand ab jetzt führen“ ist vorgehakt (M03-34, ändert K03-46); nach den ersten beiden ABs war fast nichts im Bestand gelandet. Abwählen je Zeile möglich. Keine Migration.

## 0.10.28 – Wareneingang: offene Positionen rot, Gewicht verständlich abfragen

- „Noch nicht zugeordnet“ und „Gewicht … fehlt“ stehen jetzt rot statt grün (Karte war schon rot umrandet; Michael 23.11.2026, 11:56).
- Statt „Gewicht je L – Wie viel Gramm sind 1 L?“ fragt die Seite „Wie schwer ist 1 Liter?“ mit Anhaltswerten (Wasser/Milch/Sahne ≈ 1000 g, Alkohol ≈ 950 g, Öl ≈ 920 g, Sirup ≈ 1300 g); bei Dose, Beutel, Karton … „Wie schwer ist 1 Dose?“. Einheiten ausgeschrieben auch auf Tasten, Hinweisen und Server-Meldungen („Gewicht je Liter eintragen“).
- Ungewöhnliche Werte (1 Liter unter 500 g oder über 2000 g, sonst unter 10 g) fragen „Wirklich … g?“ mit „Nochmal eingeben“. Gilt auch für Ersatz am Liefertag. Keine Migration.

## 0.10.27 – Wareneingang: Toleranz-Hinweis immer sichtbar, Einheiten nur aus der eigenen Gruppe

- Neuer Hilfs- und Betriebsstoff: die Einheiten-Tasten zeigen neben Karton, Paket, Eimer, Sack, Dose nur Einheiten, die schon an Hilfs- und Betriebsstoffen stehen (nicht mehr die Waagen-Gebinde der Rohstoffe wie Ei, Löffel, Würfel; Wunsch Michael 10:47).
- Fehlermeldungen lesbar: die Meldeleiste wurde in der Seitenspalte zusammengedrückt (Text lief weiß über die Karten); jetzt volle Höhe und beim Scrollen oben sichtbar (10:49).
- Fehler beim Speichern nennen die Position („Pos. n: Der Rohstoff hat schon die BÄKO-Artikelnummer …“); die Seite springt zur Karte und umrandet sie rot (10:53).
- Jede neue Ansicht beginnt oben; nach „Beleg speichern“ mit allen Zuordnungen springt die Seite also an den Anfang der Lieferung (10:50).
- Markierung „B“ heißt jetzt „Bestellartikel“ (10:48).
- Vorschlags-Tasten bei unbekannten Positionen fragen „Gramm je ME“ ab wie „Rohstoff zuordnen“; die Prüfung vor „Beleg speichern“ erkennt auch fehlende Gramm bei zugeordneten Positionen (Ursache der Meldung „Pos. 5 … Gramm je PK fehlt“).
- Neuer Rohstoff: der Hinweis „0 g = wird nicht gewogen (Zugabe von Hand, ohne Waage)“ steht dauerhaft unter dem Toleranzfeld, nicht erst bei 0 (Wunsch Michael 23.11.2026, 10:46). Keine Migration.

## 0.10.26 – Wareneingang: Fenster auf Höhe des angetippten Artikels, Einheiten-Vorauswahl

- Rückfrage-, Auswahl- und Zahlenfenster der Seite `/wareneingang` erscheinen auf Höhe der zuletzt angetippten Zeile statt mittig (in der HA-App ist die Seite so hoch wie ihr Inhalt, das Fenster lag weit weg).
- Ein noch offenes Fenster wird beim Öffnen eines neuen abgebrochen; zwei Fenster liegen nie mehr übereinander.
- Neuer Hilfs- und Betriebsstoff: Einheit per Taste wählbar – Karton, Paket, Eimer, Sack, Dose und alle bereits vergebenen Einheiten (`GET /api/v1/barcodes/candidates` mit Parameter `limit`, höchstens 200).
- Neuer Rohstoff: bei Toleranz 0 erscheint der Hinweis „0 g = wird nicht gewogen (Zugabe von Hand, ohne Waage)“.
- Sitzung läuft bei der Zuordnung nicht mehr ab: solange die Zuordnung eines Belegs offen ist, wird sie jede Minute verlängert; ist sie trotzdem abgelaufen, fragt „Beleg speichern“ nur die PIN neu ab, die Zuordnungen bleiben erhalten.
- Fehler 500 beim Speichern behoben: gleicher Artikel zweimal in einer AB (z. B. Pfand) als „Sonstiger Artikel“ bzw. neu angelegt – der zweite nutzt jetzt denselben Eintrag; die Entscheidung wird auf noch offene Positionen mit gleicher Artikelnummer übernommen („wie Pos. n“).
- „Ungültige Zahl“ beim Speichern ersetzt: bekannte Rohstoffe ohne „Gramm je ME“ sind jetzt orange markiert („Gramm je … fehlt“); „Beleg speichern“ nennt alle offenen Positionen und springt zur ersten, der Server meldet „Pos. n (…): Gramm je … fehlt“.
- `ui/common.js`: Option `nearTap` für `RB.dialog` und `RB.numpad` (nur der Wareneingang nutzt sie; Station und übrige Seiten unverändert). Keine Migration.

## 0.10.25 – Wareneingang: Ersatz per Scan

Entscheidung Michael 22.11.2026 (Sprachchat, „so umsetzen“ 14:40), `docs/strichcode.md` H-D.

- Unbekannter Code beim „Mit Kamera abhaken“: neue Taste **„Ersatz für …“** – bestellten Rohstoff wählen, sofort Rückfrage **„Gebinde gleich groß?“**, sonst Größe in kg eingeben
- Der fremde Code gilt **nur für diese Lieferung** (wird nicht am Rohstoff gespeichert); weitere Scans desselben Codes zählen direkt auf die Zeile
- Buchung mit Vermerk „Ersatz für Rohstoff … – anderer Hersteller, Pass prüfen“, bei anderem Gebinde zusätzlich „Gebinde x kg“

## 0.10.24 – Wareneingang, Teil W1 (in Entwicklung)

Konzept `docs/wareneingang.md` (W1) und `docs/strichcode.md` Abschnitt 6.

- Neue Seite **Wareneingang** (Kachel auf der Startseite, Link in der Rohstoffverwaltung)
- **Beleg hochladen** (PIN): BÄKO-Auftragsbestätigung als PDF, gelesen vom Belegleser (Add-on 3); unbekannte Positionen zuordnen: Rohstoff, neuer Rohstoff, Hilfs- und Betriebsstoff, sonstiger Artikel, Ersatz
- **Lieferungen** (ohne PIN): Positionen abhaken, Menge per ± Gebinde oder Zahlenfeld, Fehlt / Ersatz / Rest als Rückstand oder streichen, „Bestand ab jetzt führen“, nicht erwartete Ware ergänzen, alles in einer Buchung
- **Mit Kamera abhaken**: Start bei 0, jeder Scan = +1 Gebinde; unbekannter Code → Auswahl aus der Lieferung
- **Archiv & Sonstige** (PIN): Belege als PDF ansehen, löschen (nur ohne Buchung), sonstige Artikel archivieren oder zum Rohstoff machen
- Rechnungen und Gutschriften kommen mit Teil W2
- Neue Option `reader_url` (nur falls der Belegleser nicht automatisch gefunden wird)

## 0.10.23 – Planer, Teil P-B (in Entwicklung)

Konzept `docs/planer.md` (freigegeben 21.11.2026, 00:21), Entscheidungen K10-P5 bis K10-P25.

- **Seite `/planer`** ohne PIN (Station: Taste „Planer“, Admin: Reiter „Planer → Planen“ eingebettet): Reiter Eingabe / Jetzt planen / Rohstoffe
- **Eingabe je Tag** (◀ ▶, Vorgabe morgen): Stück / halbe / ganze je Artikel, Auftragsnummer per Tippknopf, „+ Auftrag“, Suche und Warengruppen; „Plan übernehmen von …“ mit Haken, Mengen änderbar, Rückfrage beim Überschreiben
- **Jetzt planen:** Tage wählen, Vorschau je Produktionstag und Rezept mit Summe, Ausklappen (Artikel, Stückgewichte), Tippknopf Genau / Aufrunden / Abrunden / Streichen, Grammzahl antippen = Von Hand, „+“ Zuschlag in % oder g je Teig (Vorgabe am Rezept), Haken + „Ausgewählte zusammenfassen“ / „Trennen“ (auch über Tage, Produktionstag änderbar), Übertrag bei Zuschlag über der Obergrenze (eigene Zeile oder mit nächstem Auftrag zusammenfassen), Rohstoffbedarf aus Stücklisten mit Bestand
- **Aufträge anlegen** in einem Schritt; bei schon angelegten Aufträgen Wahl „Ersetzen“ oder „Nur Unterschied dazu“; Herkunft je Auftrag gespeichert
- **Rohstoffe für heute abbuchen** (nur bestandsgeführte, am Produktionstag; erneut nur der Unterschied, weniger → Rückfrage Zurückbuchen)
- **Station, Chargen:** je Charge Knöpfe „Zutaten“ (Soll/Ist/Abweichung/Quittung) und „Artikel“ (grau ohne Planer, „Auftrag in n Teigen“)
- **Admin-Schalter** „Planer in der Vorwahl der Stationen anzeigen“
- **Stückgewicht löschen**, das in Stücklisten steckt (K10-P24): Fenster je Stückgewicht – in Gramm umwandeln, durch anderes Stückgewicht ersetzen oder Zeilen entfernen
- **Sammelaktion „Austauschen“** (K10-P25) in der Artikelliste: Rezept, Rohstoff oder Stückgewicht in allen oder ausgewählten Stücklisten ersetzen, mit Faktor und Vorschau
- Intern: Auftrag anlegen in Prüfen und Schreiben geteilt (`prepare_order` / `insert_order_in_tx`), Verhalten unverändert

## 0.10.22 – Scanner: Korrekturen aus der Praxisprüfung

- Abgangsgründe „Bruch“ und „Verderb“ zusammengefasst zu **„Bruch/Verderb“** (M03-27); alte Buchungen zeigen den neuen Text
- Kamera startet nach Drehen (hoch/quer) neu – Bild war vorher abgeschnitten
- Auswahl-Tasten im Fenster „Code unbekannt“ größer, Text (auch „ohne Code“) bleibt in der Taste
- Erste Nutzung wählt die beste Rückkamera (iPhone: Triple-Kamera), danach gilt die gemerkte Wahl

## 0.10.21 – Strichcode-Scanner, Teil S1 (in Entwicklung)

Konzept `docs/strichcode.md`, freigegeben von Michael 22.11.2026, 08:09.

- **Scan-Seite `/scannen`** (Kachel „Scannen“ auf der Startseite, Menü 🔒 an der Station): erst Modus wählen, dann startet die Kamera; zuletzt benutzter Modus umrandet, nicht vorgewählt
- Modi: Info, **+1 Einkauf** (nur mit Beleg „Einkauf“), **+1 Korrektur** (PIN), **−1 Bruch / Verderb / Eigenverbrauch / Handelsware / Sonstiges**, **Bestand setzen** (PIN, „3 Sack + 12,5 kg“), **Code zuordnen** (Umhängen mit PIN)
- Jeder Scan bucht sofort; **Rückgängig** für eigene Scans der letzten 10 Minuten; derselbe Code zählt erst wieder nach 0,8 s außerhalb des Bilds; Aufleuchten, Ton, Vibration (Android)
- Unbekannter Code: Rohstoff suchen (ohne Code zuerst), Gebinde einmal abfragen und am Rohstoff speichern
- Codes: EAN/UPC/GTIN-14 gemeinsam auf 14 Stellen, GS1 nur GTIN (Charge/MHD weggelassen); Eingabefeld für Handscanner, Foto-Weg ohne https
- Rohstoff: **Liefergebinde** (z. B. Karton Eier), **Lagerort 1/2** mit Beschriftung, Art **Hilfs- und Betriebsstoff** (Verpackungseinheiten, nie in Rezept/Waage/Planer), Codes mit „entfernen“
- Unterreiter Bestand: **Lagerorte** pflegen; Schnellerfassung mit dritter Art **Abgang** und Grund; Verlauf mit Abgang/Korrektur/Rückgängig, Grund und Einkauf
- Migration 0011 (Lagerorte, Codes, Einkäufe, Neuaufbau `raw_material` und `stock_movement`, Inhalt unverändert)
- Prüfseite `/kameratest` entfällt

## 0.10.20 – Kameratest: Absturz durch DataMatrix vermeiden (in Entwicklung)

Befund 19:15 (Galaxy Tab A, HA-App, https): Live-Scan mit eingebautem Leser funktioniert (EAN-13, UPC-A, CODE_128); ein DataMatrix-Code der Post bringt die App zum Absturz.

- Gesucht werden nur noch EAN-13/-8, UPC-A/-E, Code 128, Code 39, ITF und QR (live und Foto); DataMatrix, PDF417 und Aztec nicht mehr
- Gleicher Code wird höchstens einmal je 3 s gemeldet; Steuerzeichen werden aus dem Ergebnis entfernt

## 0.10.19 – Kameratest: Live-Erkennung verbessert (in Entwicklung)

Befund 17:25 (iPhone, HA-App über https): Live-Kamera läuft, aber nur 640 × 480 und kein Treffer; Foto erkennt EAN-13.

- Live: 1920 × 1080 angefordert (auch bei gewählter Kamera), Dauerfokus wenn möglich, Lesen abwechselnd im Mittelstreifen und im ganzen Bild, zwei Binarisierer, nur übliche Strichcode-Formate, alle 120 ms
- Grüner Zielrahmen im Kamerabild, Anzeige „Leseversuche je Sekunde“ und „Fokus“; Bild nicht mehr beschnitten

## 0.10.18 – Kameratest: Fotoerkennung verbessert (in Entwicklung)

Befund Kameratest 13:43 (iPhone, HA-App): Live-Kamera gesperrt, weil die Seite über http läuft; Foto kam an, Code wurde nicht gefunden.

- Foto: bis zu 12 Leseversuche (Größen 2400/1600/1000/700 px, Ausschnitt Mitte 60/40 %, um 90° gedreht, zwei Binarisierer) statt einem Versuch bei 1600 px; Vorschaubild des Fotos; Fotogröße und Trefferweg im Protokoll
- Anzeige des Adress-Schemas und Hinweis, dass die Live-Kamera https braucht

## 0.10.17 – Prüfseite Kamera/Strichcode (in Entwicklung)

Vorarbeit für die Strichcode-Erfassung (Inventur, Bestand, Wareneingang; Wunsch Michael 21.11.2026). Reine Prüfseite, speichert und bucht nichts, keine Migration.

- **`/kameratest`** (ohne PIN, Link „Kameratest (Strichcode)“ auf der Startseite): **Weg 1 Live-Kamera** in der Seite, **Weg 2 Foto aufnehmen** über die Gerätekamera; Lesen mit dem eingebauten `BarcodeDetector`, sonst mit ZXing (zur Laufzeit aus dem Netz geladen)
- Zeigt, was auf dem Gerät geht: sichere Verbindung, eingebettete Seite, Kamera-Schnittstelle und -Berechtigung, Seitenrichtlinie, Formate, Fehlermeldungen; „Ergebnis kopieren“ für die Rückmeldung

## 0.10.16 – Modul 10 C2: Planer Teil P-A – Verkaufsartikel und Stückliste (in Entwicklung)

Nach docs/planer.md (Konzept freigegeben 21.11.2026, 00:21; K10-P1 bis K10-P23). Der Tagesplan selbst („Planen“) folgt mit Teil P-B.

- **Migration 0010:** Tabellen Verkaufsartikel und Stücklistenzeilen; am Rezept neu „darf vorproduziert werden“ und „Abwiegezuschlag“ (Zehntelprozent, 0–20 %)
- **Reiter „Planer“** in allen Admin-Seiten (`/admin/planer`), Unterreiter **Planen** (Platzhalter bis P-B) und **Artikel**: Liste mit Suche (Nummer oder Name), Warengruppe, Status (in der Kasse / nicht mehr in der Kasse / alle), „ohne Stückliste“, „nicht planen“; Sammelaktionen „nicht planen“, „wieder planen“, „Stück je Ganzes“ setzen/leeren
- **Artikelseite:** Stück je Ganzes, planen ja/nein, Bemerkung; **Stückliste** mit Rezepten (Gramm oder Stückgewicht) und Rohstoffen (Gramm oder Stück × Gebindegröße), Reihenfolge ↑↓, Summe je Ganzes bzw. Stück, Hinweise bei archivierten Rezepten/Rohstoffen, „Kopieren von Artikel-Nr.“
- **Vectron-Import** im Reiter Import/Export der Rezeptseite: Probelauf mit Warengruppen-Auswahl (Vorgabe 1–14), dann Import; neu/geändert/wieder da/nicht mehr in der Kasse (nie gelöscht), Überschriften (#), leere Zeilen und WG 0 übersprungen, doppelte Nummern = Fehler; WG 12 → 12, WG 13 → 14 Stück je Ganzes. **Export** als .xlsx (Blätter Artikel und Stückliste)
- **Rezept, Kasten „Planung“:** „darf vorproduziert werden“ und „Abwiegezuschlag %“, eigene Taste, keine neue Version
- Ein Stückgewicht, das in einer Stückliste verwendet wird, lässt sich nicht löschen
- **Migration 0010 enthält auch die Tabellen für P-B** (H1): Pläne je Tag mit Auftragsnummer, Planläufe, Artikel je Auftrag, Zuschlag/Übertrag am Auftrag (Anzeige), Abbuchungen; Buchungsarten „Planer“ und „Planer zurück“ im Bestandsverlauf (Tabelle der Buchungen neu aufgebaut, Inhalt unverändert)
- **Rezept-Export und Vorlagen-Import** (H2): Spalten „Darf vorproduziert werden (ja/nein)“ und „Abwiegezuschlag %“ am Ende des Blatts „Rezepte“, auch in der Mustervorlage; leer = unverändert
- **Schnittstelle:** `GET /api/v1/articles` (`q`, `group`, `status`, `without_lines`, `not_planned`), `/articles/groups`, `/articles/{id}` ohne PIN; mit Admin `POST /admin/articles/import?mode=check|run&groups=…`, `GET /admin/articles/export.xlsx`, `POST /admin/articles/bulk`, `PATCH /admin/articles/{id}`, `PUT /admin/articles/{id}/lines`, `POST /admin/articles/{id}/copy-lines`, `PUT /admin/recipes/{id}/planning`

## 0.10.15 – Modul 03: Rohstoffverwaltung (Teil R1, in Entwicklung)

Umbau der Rohstoffseite nach docs/rohstoffverwaltung.md (Konzept freigegeben 20.11.2026, 13:20; M03-19 bis M03-23, K03-33 bis K03-41). Keine Migration.

- **Bereich „Rohstoffverwaltung“** mit Unterreitern **Liste · Bestand · Händler** (auf dem Handy als Auswahlliste); obere Reiter jetzt auch „Gruppen“ und „Import/Export“
- **Rohstoff als eigene Seite** (`/admin/rohstoffe/<Nummer>`, neu: `/admin/rohstoffe/neu`) mit den Reitern **Grunddaten · Bestand · Bezugsquellen**; ‹ › blättert durch die gefilterte Liste, „← Zurück zur Liste“, Rückfrage bei ungespeicherten Änderungen; Archivieren/Wiederherstellen, Löschen (nur nie verwendet) und „Rezepte mit diesem Rohstoff“ auf der Seite. Tipp auf eine Zeile der Liste öffnet die Seite
- **Filter** (kombinierbar, bleiben beim Zurückkehren erhalten): Status, Typ, Bestand (am/unter Meldewert, im Minus, ohne Bestandsführung), Händler bzw. „ohne Bezugsquelle“, Toleranz 0 %, ohne Preis, in keinem Rezept verwendet (= keine aktuelle Version eines nicht archivierten Rezepts)
- **Sammelaktionen**: Haken je Zeile, „alle wählen“ wählt die angezeigten; Archivieren/Wiederherstellen, Toleranz setzen, Typ setzen, Meldewert setzen, Bestand (Führung beenden / auf 0), aktive Bezugsquelle setzen, Auswahl exportieren (CSV). Vorschau, dann eine Bestätigung; nicht Erlaubtes wird übersprungen und genannt. Beim Archivieren mit Bestand Liste „Bestand auf 0“, alle vorgewählt, einzeln abwählbar (K03-36)
- **Unterreiter Bestand**: **Bestand erfassen** (Suche → Enter → kg → Enter bucht sofort; Schalter Zugang/Gesamtbestand; Anzeige „gebucht … · Meldewert …“ und Vorschau „neu: …“; ohne Bestandsführung startet „Gesamtbestand“ die Führung, „Zugang“ fragt „ab 0 starten?“), **Meldeliste** und **Verlauf aller Rohstoffe** mit Filtern
- **Import/Export gemeinsam** im Reiter „Import/Export“ der Rezeptseite: dort jetzt auch Rohstoff-CSV-Import und -Export; die Tasten auf der Rohstoffseite entfallen
- **Schnittstelle:** Filter `status`, `type`, `stock`, `no_price`, `unused`, `dealer_id`, `no_source` an `GET /api/v1/raw-materials`; `POST /api/v1/admin/raw-materials/bulk` (`preview`/`confirm`, `stock_zero_ids`); `GET /api/v1/admin/stock/movements`; `GET …/export.csv?ids=…`; Buchungen der Schnellerfassung mit Quelle `quick_entry`

## 0.10.14 – Modul 04 Teil C1: Händler, Bezugsquellen, Preis je Bezugsquelle (in Entwicklung)

- **Migration 0009** (mit Sicherungskopie vorher): Rohstofftabelle neu aufgebaut (Herkunft „eigen“/„datenlink“ statt „eigen“/„BÄKO“, Feld datenlink-ID für Teil C2; Inhalt unverändert), neue Tabellen Händler, Bezugsquellen und – schon für Teil C2 – Kennzeichnungspass, Allergene (feste Liste mit 26 Einträgen), Nährwerte (M04-11).
- **Händler:** Taste „Händler“ in der Rohstoffliste – anlegen, umbenennen, archivieren, löschen (nur wenn nie verwendet). Jeder Name einmal, ohne Groß-/Kleinschreibung (M04-5, R04-11).
- **Bezugsquellen** im Formular „Bearbeiten“: Händler, Artikelnummer, Preis je kg, „g je Mengeneinheit“ mit Einheit, Warengruppe, Bemerkung; genau eine aktiv, ein Händler einmal je Rohstoff (M04-5, K04-11, M04-24).
- **Preis je Bezugsquelle (M04-14):** Der Preis des Rohstoffs ist der Preis der aktiven Bezugsquelle; das Preisfeld im Formular ist dann nur Anzeige. Die erste Bezugsquelle übernimmt den bisherigen Preis samt Datum (K04-1); „Preis geändert am“ ändert sich nur, wenn sich der gültige Preis ändert (K04-2). Ohne Bezugsquelle wie bisher.
- **Massenpflege (M04-6):** Rohstoffe in der Liste markieren, Händler wählen, „als aktive Bezugsquelle setzen …“ → Vorschau mit Preisänderungen → Speichern. Fehlt der Händler, wird die Bezugsquelle angelegt.
- **Liste:** neue Spalte „Händler (aktiv)“, Haken zum Markieren.
- **CSV:** Export mit drei Info-Spalten am Ende („Händler (aktiv)“, „Artikelnummer (aktiv)“, „datenlink-ID“), Import wertet sie nicht aus (K04-3). Die Preisspalte ändert bei Rohstoffen mit aktiver Bezugsquelle deren Preis (Hinweis im Bericht).
- **Schnittstelle:** `active_source` und `datenlink_id` an jedem Rohstoff; `GET /api/v1/dealers`, `GET /api/v1/raw-materials/{id}/sources` ohne PIN (K04-4); Pflege unter `/api/v1/admin/dealers…`, `/api/v1/admin/raw-materials/{id}/sources…`, `POST /api/v1/admin/raw-materials/bulk-active-source` (mit `dry_run`).

## 0.10.13 – Modul 09: Null doppelt, erst bei ruhiger Anzeige (in Entwicklung)

- **Behälter wiegen / wechseln:** Die KERN piept auch, wenn sie `tare`/`zero` wegen unruhiger Anzeige verwirft (Michael 23:02) – das Piepen ist keine Bestätigung. Deshalb jetzt bei beiden Nullungen (leere Waage und nach dem Aufstellen des Behälters): `tare`, ½ s, `zero`, auf stabile Anzeige warten (höchstens 3 s), `zero` erneut. Bei leerer Waage danach wie bisher Bestätigung abwarten und bis zu zweimal wiederholen
- Die Pause zwischen `tare` und dem ersten `zero` auf leerer Waage ist damit ½ s statt 2 s

## 0.10.12 – Modul 09: Null nach dem Behälter wiegen, „Weiter“ nur mit gültigem Wert (in Entwicklung)

- **Behälter wiegen / wechseln:** Nach der letzten Tara mit dem Behälter wartet die Software ½ s und sendet `zero` – das Piepen der Waage zeigt dem Bediener das Ende an (Michael 22:38). Was die Waage danach zeigt, wird der neue Bezug
- **„Weiter“ nach Pause/Handwaage:** Zeigt die Waage keinen gültigen Wert (`-----`, unter 0 oder Überlast), wird „Weiter“ abgelehnt: „Bitte den Behälter des Teigs wieder aufstellen“ (Befund Michael 22:38: vorher ohne Rückfrage weiter). Am Tablet als Fenster

## 0.10.11 – Bestand: Rückfragen am Tablet (in Entwicklung)

- **Station:** Beim Abbrechen eines Teigs mit schon abgezogenem Gewogenen erscheint jetzt ein Fenster „Gewogenes vom Bestand abgezogen lassen?“ mit „Ja, abgezogen lassen“, „Nein, zurückbuchen“ und „Zurück“ (Praxisprüfung Michael 22:07: bisher nur kurz als blauer Text unten, ohne Tasten, der Abbruch lief nicht durch). Ebenso beim Start die Rückfrage „Bestand reicht nicht“ mit „OK, trotzdem starten“ und „Abbrechen“

## 0.10.10 – Modul 10: Balken, Kompaktansicht, Zutat überspringen (in Entwicklung)

- **Soll-Strich wird grün**, sobald der Balken über der Toleranz rot ist – er bleibt so sichtbar (normale und Kompaktansicht)
- **Feinbalken** von Anfang an sichtbar (vorher erst kurz vor dem Soll eingeblendet – das wirkte verzögert)
- **„Zutat überspringen“** statt „Zutat übergehen“: die Zutat bleibt offen, es geht mit der nächsten offenen weiter; die übersprungene kommt am Ende wieder. Dafür geht es nach jeder Quittung hinter der quittierten Zutat weiter und erst danach wieder vorn (Server, Modul 09; im normalen Ablauf unverändert)
- **Endgültig weglassen** nur noch in der Übersicht (Zutat antippen → „Weglassen“, Rückfrage); im Protokoll „weggelassen“ statt „übergangen“; Prüfseite „Ablauf“: Taste „Weglassen“
- **Grobbalken:** das Soll liegt bei 2/3 der Skala (vorher am rechten Rand); bei sehr kleinem Soll mit großer Toleranz reicht die Skala bis Soll + 2 × Toleranz
- **Kompaktansicht:** oben große Tasten Tara, Behälter, Behälter wechseln, Zutat überspringen, Quittieren und „Normale Ansicht“; Grobbalken dafür etwas niedriger, „Zutat x von y“ klein oben im Grobbalken

## 0.10.9 – Befunde aus der Praxisprüfung Modul 06 (in Entwicklung)

- **Ganzer Rückweg beim Springen** (B1): Rezept → „Unterrezept öffnen“ → „Rohstoff öffnen“ → „Zurück zum Rezept“ führt ins Unterrezept, dort steht wieder „← Zurück zu <Hauptrezept>“; jedes „Zurück“ geht einen Schritt zurück, „← Zur Liste“ bleibt immer da
- **Rohstoff archivieren nur nach Rückfrage** (B2): „Rohstoff „…“ (Nr. …) archivieren?“ im eigenen Fenster (vorher ohne Rückfrage)
- **Archivieren/Wiederherstellen im Rohstoff-Formular** (B3), z. B. nach dem Sprung aus einem Rezept, mit derselben Rückfrage

## 0.10.8 – Rückfragefenster auf Höhe der Taste (in Entwicklung)

- **Bestätigungs- und Hinweisfenster öffnen sich auf Höhe der gedrückten Taste** statt in der Bildschirmmitte (Wunsch Michael 19.11.2026, 20:52): In der HA-App auf dem iPhone ist die Seite so hoch wie ihr Inhalt, „Mitte“ lag deshalb mitten auf der Seite und man musste dorthin scrollen. Liegt die Taste am Rand, rückt das Fenster so weit, dass es ganz sichtbar bleibt. Gilt für Rohstoffe (auch Fenster „Bestand“), Rezepte, Import/Export, Berechnung (Erklärung „ⓘ“) und die Prüfseite Ablauf (Rückfragen schweben über der Taste). Die Station bleibt unverändert

## 0.10.7 – Modul 03: Rohstoffbestand und Meldewert (in Entwicklung)

- **Bestand und Meldewert je Rohstoff** (VC03-b, docs/bestand.md): Spalten und Filter „am/unter Meldewert“ in der Rohstoffliste, Taste „Bestand“ mit „Zugang buchen“, „Bestand setzen“ (Inventur, leer = Führung beenden) und Verlauf; Meldewert im Formular; CSV-Export und -Import mit „Bestand kg“ und „Meldewert kg“
- **Abzug beim Verwiegen** bei jeder Quittung; Rückfrage beim Start, wenn der Bestand nicht reicht; beim Abbrechen Rückfrage, ob das Gewogene abgezogen bleibt (sonst Rückbuchung); Bestand darf negativ werden
- **Archivieren und „Rohstoff austauschen“** fragen „Bestand auf Null setzen?“
- Schnittstelle: `GET /api/v1/orders/{id}/stock` (Bestandsstatus für die Rezeptübersicht, orange/gelb in Modul 10), `POST /api/v1/raw-materials/{id}/stock/receipt` (ohne PIN), `POST /api/v1/admin/raw-materials/{id}/stock/inventory` (PIN), `GET /api/v1/raw-materials/{id}/stock/movements`
- Migration 0008 (`raw_material.stock_g`, `stock_alert_g`, Tabelle `stock_movement`)

## 0.10.6 – Modul 10: neue Aufteilung der Wiegeansicht, ausblendbare Leiste, Kompaktansicht (in Entwicklung)

- **Oben:** Mitte die aktuelle Zutat sehr groß (lange Namen werden kleiner, bis sie passen), darunter „Zutat x von y“; rechts eine Infotafel mit Waage, Rezept, Teig, Charge und nächstem Auftrag in kleiner Schrift – dort darf das Bild-im-Bild-Fenster liegen
- **Wiegeansicht:** Soll/Ist füllen die freie Höhe; Quittieren, Zutat übergehen, Tara, Behälter, Behälter wechseln und Handwaage alle gleich hoch und größer
- **Untere Tastenleiste** beim Wiegen ausgeblendet; **„☰ Mehr“** rechts blendet sie ein (zu nach einer Taste, mit „✕ Weniger“ oder nach 15 s). Ohne laufenden Teig bleibt sie sichtbar
- **Kompaktansicht** (Taste „Kompakt“ in der unteren Leiste): Vollbild mit großem Grobbalken – darin am unteren Rand Zutat, Soll und Ist – und durchgehendem Feinbalken (Soll ± 4 × Toleranz) mit Abweichung; oben „Quittieren“ und „✕ Normale Ansicht“. Bei Gebinde, Handzugabe, Unterrezept und Behälter-Schritten gilt kurz die normale Ansicht

## 0.10.5 – Modul 09: Null beim Behälter wiegen zuverlässig (in Entwicklung)

- **„Behälter wiegen“ und „Behälter wechseln“:** Nach `tare` wartet die Software 2 s, bevor sie `zero` sendet. Bestätigt die Waage die Null nicht innerhalb von 2 s, wird `zero` bis zu zweimal wiederholt (Michael, Praxisprüfung: Null musste mehrfach von Hand gedrückt werden). Klappt es trotzdem nicht, steht da „Waage leer lassen und an der Waage Null drücken“
- Hinweis während des Nullens: „Waage wird genullt – bitte warten“

## 0.10.4 – Modul 10: Wiegeansicht passt auf iPad, Galaxy Tab A und iPhone (in Entwicklung)

- **Name der Zutat wurde abgeschnitten** (Praxisprüfung, iPad quer, Galaxy Tab A, iPhone 16 Pro quer): Abstände und Soll/Ist-Ziffern etwas kleiner, nichts in der Wiegeansicht wird mehr gestaucht; passt etwas nicht, lässt sich die Fläche verschieben statt abzuschneiden
- **Rohstoffnummer** steht nicht mehr vor dem Namen der Zutat (Michael: eher verwirrend)

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

## 0.6.4 – Wiederherstellen mit archiviertem Unterrezept (freigegeben 19.11.2026 mit Modul 06)

- **Alte Version wiederherstellen:** Enthält die alte Version ein archiviertes Unterrezept, fragt die Oberfläche „„Vorteig“ ist archiviert – mit wiederherstellen?“. „Mit wiederherstellen“ holt das Unterrezept (und dessen archivierte Unterrezepte) und die alte Version in einem Schritt zurück, alles oder nichts. R05-23 bleibt bestehen (kein aktives Rezept mit archiviertem Unterrezept). Schnittstelle: `POST …/versions/{n}/restore` mit zusätzlichem `restore_sub_recipes: true`; ohne dieses Feld weiterhin 409 `archived_sub_recipe`, jetzt mit der Liste `sub_recipes`

## 0.6.3 – Wünsche aus der Praxisprüfung C2 (freigegeben 19.11.2026 mit Modul 06)

- **Erklärung zu „Anteil %“ und „Bäcker %“:** Taste „ⓘ“ an den Spalten auf der Rezeptseite (Zutaten und alte Versionen) und auf der Prüfseite „Berechnung“ (Zeilen und Zusammenfassung); eigenes Fenster, kein Browser-Dialog
- **Sprung aus einer Rezeptzeile:** „Rohstoff öffnen ↗“ öffnet den Rohstoff auf der Rohstoffseite, „← Zurück zum Rezept“ führt zurück; „Unterrezept öffnen ↗“ öffnet das Unterrezept, „← Zurück zu …“ zum Hauptrezept. Ungespeicherte Änderungen: zuerst Rückfrage „verwerfen?“. Die Rezeptseite öffnet mit `?open=<id>` direkt ein Rezept (auch nach der Anmeldung)
- **Alte Version wiederherstellen:** Taste „Diese Version wiederherstellen“ in der Ansicht einer alten Version; legt den Inhalt als neue aktuelle Version an, die alte bleibt unverändert. Geht auch bei produzierten Versionen; „*“-Markierungen und archivierte Rohstoffe werden übernommen; ein archiviertes Unterrezept verhindert es weiterhin (R05-23). Schnittstelle `POST /api/v1/admin/recipes/{id}/versions/{n}/restore`

## 0.6.2 – Modul 06, Teil C3, und Preis je kg (freigegeben 19.11.2026 mit Modul 06)

- **Bezugsarten kombinieren** (V06-1): Gesamtteig, Stückzahlen, Chargengrößen (auch dieselbe mehrmals) und **Faktor × Grundrezept** (neu, VC06-e) in einem Auftrag, in Gramm zusammengezählt; „Mehl gesamt“ und Leitrohstoff nur allein
- **Obergrenze und Aufteilung in Teige** (V06-2): Haken **„aktiv (Obergrenze)“** bei den Chargengrößen in der Rezeptbearbeitung (höchstens einer je Rezept; Kopie, Export und Import übernehmen ihn, Spalte „Obergrenze“ im Blatt Chargengrößen). Liegt der Bedarf darüber, wird in mehrere Teige geteilt: „voll auffüllen“ oder „gleichmäßig“, Anzahl Teige nur erhöhbar. Obergrenze nur für den Auftrag eingebbar (mit aktiver Chargengröße nur kleiner). Bei „Mehl gesamt“ und Leitrohstoff Rückfrage „Nach Obergrenze teilen?“. Bei Unterrezepten Auswahl „je Teig“ oder „einmal für alle“
- Prüfseite „Berechnung“: Bezugsarten „Faktor“ und „Kombiniert“, Obergrenze, Rückfragen, Teige als Reiter, Zusammenfassung „dieser Teig / ganzer Auftrag“, Unterrezept-Aufträge; **„Mehl gesamt“ in ganzen Gramm** (kaufmännisch gerundet)
- Schnittstelle `POST /api/v1/calculation` zusätzlich mit `demand`, `split`, `doughs`, `order_totals`, `order_summary`, `sub_orders` (bisherige Felder unverändert); `basis-options` mit `limit`; Funktionen für Modul 09: `plan_doughs`, `sub_order_targets`, `build_batch_items` je Teig, erweitertes `validate_basis`
- **Preis je kg am Rohstoff** (Modul 03, VC03-a): Feld „Preis je kg (€ netto)“ auf der Rohstoffseite und Spalte „€/kg“, „Preis geändert am“ automatisch, ohne PIN lesbar; mehr als 2 Nachkommastellen werden mit Hinweis gerundet. CSV-Export mit zwei neuen Spalten am Ende, CSV-Import liest die Preisspalte (leere Zelle löscht, fehlende Spalte lässt den Preis stehen)
- Datenbank-Migration `0006_order_doughs.sql`: `recipe_batch_size.is_limit`, Bezugsarten `factor`/`combined`, Obergrenze und Teilungsart am Auftrag, Tabellen `order_batch_size` und `order_dough`, `parent_dough_index`, Preisspalten am Rohstoff. Die Tabelle `production_order` wird dabei neu aufgebaut (SQLite kann CHECK-Regeln nicht ändern); dafür kennt die Migration den Schalter `-- migration: foreign_keys=off` in der ersten Zeile

## 0.6.1 – Modul 06, Teil C2 (freigegeben 19.11.2026 mit Modul 06)

- **Anteil und Bäckerprozent in der Rezeptverwaltung:** neue Spalten „Anteil %“ und „Bäcker %“ in den Zutaten und in alten Versionen, dazu „Mehl gesamt (mit Unterrezepten)“; die Lese-Schnittstelle liefert zusätzlich `sums.flour_total_g` und je Zeile `share_tenths`/`baker_tenths` (vorhandene Felder unverändert)
- **Ansicht „Zusammenfassung“** auf der Prüfseite „Berechnung“: jeder Rohstoff einmal über alle Unterrezepte, Anteil, Bäckerprozent, Mehlmischung; die Schnittstelle `POST /api/v1/calculation` liefert dafür `summary` und `flour_mix`
- **Sitzungsprüfung** beim Öffnen und beim Reiterwechsel der Seiten Rohstoffe, Rezepte und Berechnung: abgelaufene Sitzung → gleich PIN-Eingabe, danach weiter zur gewählten Seite; neue Schnittstelle `GET /api/v1/admin/session` (verlängert die Sitzung nicht)

## 0.6.0 – Modul 06, Teil C1 (freigegeben 19.11.2026 mit Modul 06)

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
