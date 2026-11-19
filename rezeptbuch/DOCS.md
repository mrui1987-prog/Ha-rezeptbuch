# HA-Rezeptbuch

Rezeptverwaltung, Produktionsliste und Wiegeablauf für kleine Bäckereien.

**Stand 0.6.4:** Rohstoffverwaltung (Modul 03) mit CSV-Export und CSV-Import unter `/admin`, Rezeptverwaltung (Modul 05) mit Import aus der Importvorlage und Export (.xlsx) unter `/admin/rezepte`, Rezeptberechnung (Modul 06) mit Prüfseite unter `/admin/berechnung`. Die Oberfläche ist noch schlicht; die Gestaltung folgt in Modul 10.

## Datenbank

- Datei: `/data/rezeptbuch.db` (wird vom Home-Assistant-Backup erfasst)
- Beim Start wird die Datenbank geprüft und bei Bedarf auf den neuesten Stand gebracht.
- Vor jeder solchen Aktualisierung entsteht eine Sicherungskopie in `/data/backups/` (die letzten 5 bleiben erhalten).
- Ist die Datenbank beschädigt oder neuer als das Add-on, startet das Rezeptbuch nicht im Produktionsbetrieb und meldet den Fehler im Add-on-Protokoll.

## Voraussetzungen

- Home Assistant OS oder Supervised (Add-ons)
- MQTT-Broker (Add-on „Mosquitto broker“); ohne ihn läuft das Rezeptbuch, aber ohne Waagen
- Add-on „HA-Rezeptbuch Waage“ für die Waagenanbindung

## Oberflächen

| Adresse | Zweck |
|---------|-------|
| `/admin` | Rohstoffe (PIN), mit Preis je kg (€ netto; lesen auch ohne PIN über die Schnittstelle) |
| `/admin/rezepte` | Rezepte, Rezeptgruppen, Import/Export (PIN); Aufträge folgen in späteren Modulen |
| `/admin/berechnung` | Berechnung nachprüfen (PIN, speichert nichts) |
| `/admin/waagen` | Waagen – Verbindung prüfen: Live-Gewicht, Status, Tara/Null (PIN) |
| `/admin/ablauf` | Ablauf prüfen: Aufträge, Teig starten, wiegen und quittieren, Pause/Weiter, Einstellungen (PIN; Prüfseite bis zur Tablet-Oberfläche) |

Die Stationsadressen für die Tablets an den Waagen folgen in Modul 10 und sind in dieser Version noch nicht vorhanden.

Im Probebetrieb gilt die PIN **1234** (roter Hinweisbalken). Die PIN-Änderung folgt in Modul 12. Es wird nur ein Hash gespeichert. Nach 5 Fehlversuchen ist die Eingabe 5 Minuten gesperrt. Die Sitzungsdauer stellt die Add-on-Option `admin_timeout_minutes` ein (Standard 5 Minuten). Beim Öffnen einer Admin-Seite und beim Reiterwechsel wird die Sitzung geprüft; ist sie abgelaufen, kommt gleich die PIN-Eingabe und danach die gewählte Seite (ungespeicherte Änderungen werden vorher abgefragt).

## Rohstoffe importieren (CSV)

Taste **„CSV-Import“** in der Rohstoffliste. Die Datei hat das Format des CSV-Exports (Semikolon, Kopfzeile `Nummer;Name;Kurzname;Typ;Toleranz;Toleranzeinheit;Gebindegröße g;Gebindebezeichnung;Herkunft;archiviert;geändert am;Preis je kg €;Preis geändert am`; die beiden Preisspalten seit 0.6.2, ältere Dateien ohne sie gehen weiter). Gelesen werden „CSV UTF-8“ und „CSV (Trennzeichen-getrennt)“ aus Excel.

- Zuerst läuft immer ein **Probelauf**; er zeigt neue, überschriebene und unveränderte Rohstoffe, Fehler und Hinweise. Gespeichert wird erst mit **„Importieren“**, und nur wenn die Datei keinen Fehler enthält (alles oder nichts).
- Zuordnung über die **Nummer**, ohne Nummer über den **Namen**; passt keiner, wird der Rohstoff neu angelegt.
- **Vorhandene Rohstoffe werden überschrieben** (Bestätigung nötig). Leere Toleranz bleibt unverändert, leerer Kurzname und leeres Gebinde werden geleert, leerer Typ bleibt. Nummer und Herkunft ändern sich nie. „Herkunft“ und „geändert am“ werden nicht ausgewertet.
- **Neue Rohstoffe ohne Toleranz erhalten 0 %.** 0 % wird gewogen (bei der Verwiegung mindestens ±1 g); nur **0 g** ist eine Handzugabe. Mit dem Filter „nur Toleranz 0 %“ lassen sich diese Rohstoffe später finden.
- Spalte **„archiviert“**: ja = archivieren, nein = wiederherstellen. Rohstoffe, die nicht in der Datei stehen, bleiben unverändert.
- Viele Rohstoffe bearbeiten: CSV-Export → in Excel ändern → als CSV speichern → CSV-Import.
- Namen und Kurznamen dürfen nicht mit `=`, `+`, `-` oder `@` beginnen (Schutz vor Excel-Formeln).
- **Preis je kg €** (€ netto, z. B. „2,35“): leere Zelle löscht den Preis, fehlt die Spalte ganz, bleibt er. Mehr als 2 Nachkommastellen werden kaufmännisch gerundet (Hinweis im Bericht). „Preis geändert am“ setzt das Rezeptbuch selbst. Der Preis steht nur im CSV, nicht in der Importvorlage .xlsx.
- Höchstens 5 MB und 5 000 Zeilen je Datei.

## Rezepte

Reiter **„Rezepte“** im Admin-Bereich.

- **Neues Rezept:** Nummer wird vorgeschlagen (änderbar, solange das Rezept nirgends verwendet wurde). Der Name muss unter den nicht archivierten Rezepten eindeutig sein. Neue Rezepte starten **gesperrt** und erscheinen erst nach **„Freischalten“** in der Vorwahl.
- **Zutaten:** Rohstoff oder Unterrezept über Nummer oder Name wählen, Menge in ganzen Gramm. **0 g = Handzugabe** (nur quittieren). Toleranz leer = Toleranz des Rohstoffs; 0 % wird gewogen (mindestens ±1 g). Archivierte Rohstoffe und Rezepte sind für neue Zeilen nicht wählbar. Ein Rezept darf sich nicht über Unterrezepte selbst enthalten.
- **Speichern und Versionen:** Wurde die aktuelle Version schon produziert, entsteht automatisch eine neue Version. Sonst fragt das Rezeptbuch „Neue Version“ oder „Überschreiben“. Nur die Bestätigung einer „*“-Zeile mit „geprüft“ überschreibt ohne Rückfrage. Alte Versionen stehen als „old (n)“ in der Versionsliste und können nur angesehen werden.
- Die Taste **„Zutaten speichern“** speichert Rezeptkopf, Schritte und Zutaten. **Hinweis an der Waage:** „am Anfang und am Ende“ oder „nur am Ende“; ein leerer Hinweistext erscheint nicht.
- **Interne Notiz:** nur im Admin-Bereich sichtbar, nie an der Waage; Ändern legt keine neue Version an.
- Hat ein anderes Gerät das Rezept inzwischen gespeichert, wird nichts überschrieben: Fenster „bitte neu laden“.
- **Stückgewichte und Chargengrößen** gehören zum Rezept und haben eine eigene Taste im eigenen Kasten (keine neue Version). Ungespeicherte Änderungen dort werden deutlich angezeigt; „Zutaten speichern“ fragt dann „Beides speichern“ oder „Nur Zutaten speichern“. Wird ein Stückgewicht gelöscht, fragt das Rezeptbuch sofort nach den zugehörigen Chargengrößen, die mit wegfallen.
- **Mehrere Rezepte auf einmal:** In der Liste Rezepte anhaken (oder „alle auswählen“ oben links für alle angezeigten). Die Leiste bietet Freischalten, Sperren, Archivieren, Löschen und Exportieren; sind archivierte Rezepte angehakt, zusätzlich **Wiederherstellen** (nicht möglich, wenn ein aktives Rezept gleich heißt oder ein Unterrezept noch archiviert ist – das Rezept wird dann übersprungen und genannt; Haupt- und Unterrezept zusammen anhaken geht). Vorher zeigt eine Vorschau, was passiert und was übersprungen wird; beim Freischalten stehen alle offenen „*“ und Toleranzen 0 % in einer Liste. Es gelten dieselben Regeln wie beim einzelnen Rezept.
- Der Haken **„mit archivierten Rohstoffen“** zeigt Rezepte, deren aktuelle Version einen archivierten Rohstoff enthält.
- **Sperren** blendet ein Rezept nur in der Vorwahl aus; als Unterrezept bleibt es nutzbar. **Archivieren** geht nicht, solange das Rezept als Unterrezept in einem aktiven Rezept steckt. Archivierte Rezepte können wiederhergestellt, aber nicht bearbeitet werden; enthält die aktuelle Version ein archiviertes Unterrezept, muss zuerst das Unterrezept wiederhergestellt werden. **Löschen** nur, wenn das Rezept nie verwendet wurde.
- **Rohstoff austauschen** (Taste über der Rezeptliste): auszutauschenden Rohstoff, neuen Rohstoff und Faktor wählen (neue Menge = alte Menge × Faktor, auf ganze Gramm gerundet; 0 g bleibt 0 g, sonst mindestens 1 g), dazu höchstens zwei Zusatzzutaten mit Faktor auf die alte Menge (z. B. Butter 1 000 g → Margarine × 0,82 = 820 g + Wasser × 0,16 = 160 g; die Zusatzzeilen kommen direkt unter die getauschte Zeile im selben Schritt). „Rezepte anzeigen“ listet alle nicht archivierten Rezepte, deren aktuelle Version den Rohstoff direkt enthält, mit „alt → neu“; einzelne Rezepte abwählen, dann „Austauschen“. **Jedes geänderte Rezept bekommt eine neue Version**; öffentlich/gesperrt bleibt. Eine eigene Zeilentoleranz bleibt erhalten. Wahlweise: geänderte Zeilen mit „*“ markieren; alten Rohstoff archivieren, wenn er danach in keinem Rezept mehr vorkommt. Wurde ein Rezept inzwischen an einem anderen Gerät geändert, wird es übersprungen und genannt.
- **Alte Versionen ansehen:** Neben jeder Menge steht kursiv die Menge der aktuellen Version („aktuell: …“, gelb = abweichend, „entfällt“ = nicht mehr enthalten); Zeilen, die nur die aktuelle Version hat, stehen kursiv am Ende. Am Handy steht der Wert unter der Menge.
- **Rohstoff öffnen ↗ / Unterrezept öffnen ↗** in jeder gespeicherten Zeile: springt zum Rohstoff (Rohstoffseite, „← Zurück zum Rezept“) bzw. ins Unterrezept („← Zurück zu …“). Bei ungespeicherten Änderungen kommt zuerst die Rückfrage „verwerfen?“.
- **Alte Version wiederherstellen:** in der Ansicht einer alten Version; legt sie als neue aktuelle Version an (die alte bleibt). Übernimmt „*“-Markierungen und archivierte Rohstoffe; nicht möglich, solange ein Unterrezept der alten Version archiviert ist. Stückgewichte, Chargengrößen, Gruppe und Status bleiben.
- **„ⓘ“ an „Anteil %“ und „Bäcker %“** erklärt, wie die Prozente zu lesen sind (auch auf der Prüfseite).
- **Kopieren** übernimmt die aktuelle Version, Stückgewichte und Chargengrößen als „Kopie von …“ (gesperrt); nicht möglich, solange ein Unterrezept archiviert ist.
- Spalten **Anteil %** und **Bäcker %** sowie „Mehl gesamt (mit Unterrezepten)“ zeigen den gespeicherten Stand; geänderte oder neue Zeilen zeigen „–“ bis zum Speichern. Bäckerprozent bezieht sich auf das ganze Mehl inklusive Unterrezepten.
- **Gruppen** im Reiter „Gruppen“: anlegen, umbenennen, Reihenfolge, löschen nur, wenn kein Rezept (auch kein archiviertes) darin ist.

## Rezepte importieren und exportieren (.xlsx)

Reiter **„Import/Export“**.

- **Import** liest die Importvorlage: Blätter *Rohstoffe, Rezepte, Rezeptzeilen, Stückgewichte* und *Chargengrößen*. Spalten werden an der Überschrift erkannt; Zusätze in Klammern zählen nicht, Spalten mit „(Formel)“ oder „(nicht importieren)“ werden nicht gelesen. Die Datei muss als `.xlsx` gespeichert sein (nicht `.xlsb`). **Ohne Microsoft Office:** die Datei z. B. in LibreOffice Calc öffnen und beim Speichern „Excel 2007-365 (.xlsx)“ wählen (nicht .ods).
- Ablauf wie beim CSV-Import: **Probelauf** → Bericht → **„Importieren“**; alles oder nichts.
- Rohstoffe: wie der CSV-Import (Zuordnung über Nummer, sonst Name; vorhandene werden nach Bestätigung überschrieben; neue ohne Toleranz erhalten 0 %).
- Rezepte: Ist die Rezeptnummer (sonst der Name) schon vorhanden, bekommt das Rezept nach Bestätigung eine **neue Version**, die bisherige bleibt als „old (n)“; gleicher Inhalt = unverändert; archivierte Rezepte erst wiederherstellen. Leere Nummer = nächste freie. Fehlende Gruppen werden angelegt. Neue Rezepte sind **gesperrt**; Zeilen mit „*“ prüfen, dann freischalten.
- Zeilen: Zutat über den Rohstoffnamen, Unterrezept über die Import-ID. **Menge g = Menge Original × Faktor**, auf ganze Gramm gerundet. g und kg rechnet der Import selbst. **Für Stück, ml, Maß usw.** im Blatt *Rohstoffe* beim Rohstoff die Spalten **„Umrechnung Einheit“** und **„Gramm je Einheit“** ausfüllen (z. B. Eier: Stück, 65; dann reicht in der Rezeptzeile „20“ „Stück“ „Eier“ = 1 300 g). Für ml eingetragen gilt der Wert auch für l (× 1 000) und umgekehrt. Der Wert wird nicht gespeichert, er dient nur dem Import. Eine Zeile im Blatt *Rohstoffe* nur mit Name und Umrechnung ändert einen vorhandenen Rohstoff nicht. **Jede umgerechnete Zeile bekommt „*“**; der Probelauf zeigt alle Umrechnungen vorab in einem eigenen Fenster („Weiter“), danach den Bericht. Leere Menge = 0 g Handzugabe. Fehlt der Faktor, ist das ein Fehler.
- Ein Blatt *Umrechnung* aus älteren Vorlagen (Schlüssel „Einheit Zutat“, z. B. „Stück Ei“) wird übergangsweise noch gelesen; der Bericht weist dann auf „veraltet“ hin.
- **Mustervorlage** (Taste „Mustervorlage herunterladen“): Die gelben Musterzeilen (Rezepte „… (Muster)“, Rohstoffe „Muster …“) überspringt der Import; eigene Zeilen einfach darunter ergänzen. Mit dem Haken „Musterdaten der Mustervorlage mit importieren“ lassen sie sich zum Ausprobieren importieren. Bereits importierte Musterrezepte bleiben unverändert und können bei Bedarf gelöscht werden.
- Chargengröße „Gewicht“ ohne Wert (oder mit Formel) = Gesamtgewicht des Rezepts; „Stück“ braucht Wert und Stückgewicht-Bezeichnung.
- **Export:** alle Rezepte (aktuelle Version) mit den verwendeten Rohstoffen im Format der Vorlage, auf Wunsch mit archivierten. Die Datei kann in eine leere Datenbank wieder importiert werden. Kein Ersatz für die Datensicherung.

## Berechnung (Modul 06)

Reiter **„Berechnung“**: Rezept wählen (auch gesperrte, auf Wunsch archivierte, auch alte Versionen), Bezugsgröße wählen, „Berechnen“. Die Seite speichert nichts; sie rechnet genau so, wie später die Waage rechnet.

- **Bezugsgrößen** (je Teig): Gesamtteig (g/kg), Stückzahlen je Stückgewicht, Chargengröße, Mehl gesamt (nur bei Rezepten mit Mehl), Leitrohstoff (g/kg/l, 1 l = 1 000 g). Den Leitrohstoff gibt es einmal „gesamt“ (alle Zeilen inklusive Unterrezepten) und, wenn er mehrfach vorkommt, je Zeile des Hauptrezepts.
- **Rundung:** jede Zutat auf das nächste ganze Gramm **aufgerundet** (312,1 g → 313 g); 0 g bleibt 0 g (Handzugabe). Die Summe kann dadurch etwas über dem Ziel liegen.
- **Unterrezepte** werden mit ihrer gerundeten Menge als Gesamtteig gerechnet und erscheinen eingeklappt (▸ zum Aufklappen).
- **Toleranz:** Gramm unverändert (0 g = nur quittieren); Prozent von der Sollmenge, auf ganze Gramm abgerundet, **mindestens 1 g** (0 % wird mit ±1 g gewogen). Bei Gebinde/Stück gilt die ganze Toleranz für den gewogenen Rest.
- **Gebinde/Stück:** ganze Einheiten + Rest, z. B. „10 × Ei + 30 g wiegen“.
- **Anteil** am Gesamtgewicht und **Bäckerprozent** (bezogen auf das ganze Mehl inklusive Unterrezepten) aus dem Grundrezept, eine Nachkommastelle.
- **Zusammenfassung** (Umschalter „Zeilen / Zusammenfassung“): jeder Rohstoff einmal mit der Summe aus Hauptteig und allen Unterrezepten (so, wie gewogen wird), Anteil, Bäckerprozent und die **Mehlmischung** (Anteil jeder Mehlsorte am Mehl gesamt).
- **„Ergibt“:** Stückzahl je Stückgewicht, auf eine Nachkommastelle abgerundet (z. B. 12,4 Käsekuchen).
- **Hinweise:** Zeilen mit „*“, archivierte Rohstoffe/Unterrezepte, Toleranz 0 %, Aufrunden um mehr als 5 %, Leitrohstoff „gesamt“ über der Eingabe, gesperrtes/archiviertes Rezept.
- **Faktor × Grundrezept** (z. B. 1,5; 0,01 bis 100, höchstens 2 Nachkommastellen) und **Kombiniert**: Gesamtteig, Stückzahlen, Chargengrößen (Anzahl je Chargengröße, auch mehrmals) und Faktor werden in Gramm zum Bedarf zusammengezählt (auf ganze Gramm aufgerundet). „Mehl gesamt“ und Leitrohstoff gehen nur allein.
- **Obergrenze:** die Chargengröße mit Haken „aktiv (Obergrenze)“ (Rezeptbearbeitung, höchstens eine je Rezept; bei „Stück“ = Anzahl × Stückgewicht). Ohne aktive Chargengröße kann eine Obergrenze nur für den Auftrag eingegeben werden; mit aktiver nur kleiner. Liegt der Bedarf darüber, wird geteilt: mindestens so viele Teige wie nötig (mehr wählbar), **voll auffüllen** (20 + 12 kg) oder **gleichmäßig** (16 + 16 kg, auf ganze Gramm aufgerundet). Bei „Mehl gesamt“ und Leitrohstoff fragt die Seite „Nach Obergrenze teilen?“. Jeder Teig hat einen eigenen Reiter; die Zusammenfassung gibt es je Teig oder für den ganzen Auftrag.
- **Vorteig/Unterrezept bei mehreren Teigen:** je Teig ein eigener Unterrezept-Auftrag oder einer für alle (Hinweis, wenn er über der Obergrenze des Unterrezepts liegt).
- **Mehl gesamt** wird in ganzen Gramm angezeigt (kaufmännisch gerundet, genauer Wert beim Darüberfahren); die Bäckerprozente rechnen mit dem genauen Wert.
- Schnittstelle ohne PIN (für die Stationen ab Modul 09/10): `GET /api/v1/recipes/{id}/basis-options`, `POST /api/v1/calculation`.

## Waagen-Anbindung (Modul 08)

Das Rezeptbuch liest die Waagen nicht selbst, sondern über das Add-on **„HA-Rezeptbuch Waage“** und MQTT (Mosquitto). Die Zugangsdaten holt es selbst vom Supervisor; einzustellen ist nichts. Fehlt MQTT, läuft das Rezeptbuch normal weiter und versucht es alle 30 s erneut; die Stationen zeigen dann „Waage nicht verbunden“.

- **Welche Stationen es gibt**, bestimmt das Rezeptbuch (Waage 1 eingerichtet, Waage 2 nicht). Liefert das Waagen-Add-on Werte für eine nicht eingerichtete Station, zeigt die Prüfseite sie mit Hinweis an, Befehle sind dort gesperrt. Adresse, Port und Stabilitätswerte der Waage stellt man nur im Waagen-Add-on ein.
- **Offline** ist eine Station, wenn die Waage keine Werte liefert, das Waagen-Add-on gestoppt ist, MQTT getrennt ist oder 3 s lang keine Meldung kam. „Kein gültiger Wert“ (`-----`) ist kein Ausfall.
- **Tara/Null** über die Prüfseite oder `POST /api/v1/stations/{nr}/scale/tare|zero` (ohne PIN). „Gesendet“ heißt nicht „ausgeführt“: Null nimmt das Waagen-Add-on nur bei leerer Waage (bis ±50 g) an; die Wirkung zeigt der nächste Wert.
- **Live-Kanal** für Tablets: WebSocket `/api/v1/live` (relativer Pfad, funktioniert hinter HA-Ingress).
- Schnittstelle und Nachrichten im Einzelnen: `docs/schnittstellen.md` im Repository.

## Wiegeablauf (Modul 09)

Aufträge, Teige, Zutaten und Protokoll liegen im Rezeptbuch; die Tablets (Modul 10) zeigen nur an. Bis dahin lässt sich alles auf der Prüfseite **„Ablauf“** bedienen.

- **Auftrag** anlegen (Rezept, Bezug, Menge, Obergrenze, Teige, „Fest an Waage“), dann je Teig **„Starten an Waage …“**. Beim ersten Teig wird die Rezeptversion fixiert; Unterrezepte werden eigene Aufträge.
- **Wiegen:** Der Behälter steht beim Start auf der Waage; die Software tariert die Waage (Anzeige 0). Zutat auflegen: Liegt sie 2 s ruhig in der Toleranz, wird automatisch quittiert und neu tariert. „Quittieren“ geht auch von Hand. Mit **„Behälter wiegen“** lässt sich das Behältergewicht ermitteln, mit **„Behälter wechseln“** eine Zutat in mehreren Behältern wiegen (Teilmengen zählen mit).
- **Waage getrennt:** Nach 45 s ohne Waage wird der Teig pausiert. **Höchstlast:** Warnung 1 kg vor der Höchstlast der Waage.
- **Pause / Weiter:** Ein pausierter Teig kann an jeder eingerichteten Waage weitergehen (außer „Fest an Waage“). „Handwaage“ hält den Teig an der Station. Nach einem Neustart des Add-ons sind laufende Teige pausiert.
- **Abschließen:** Nach der letzten Zutat den Behälter abnehmen – die Software stellt die Waage auf Null und gibt die Station frei. Ohne Waage gibt es die Taste „Abschließen (Station frei)“.
- **Weiter an derselben Waage:** Weicht die Gesamtlast um mehr als 5 g vom Stand bei der Pause ab, fragt die Software „richtiger Behälter?“.
- **Einstellungen** (Zeit und Wanderung der Auto-Quittung, 45 s, Vorwarnung, Tara-Bestätigung, Lastprüfung) auf der Prüfseite, Ändern mit PIN.
- Ablauf und Regeln im Einzelnen: `docs/ablauf.md` im Repository.

## Haftung

Die Software wird ohne Gewährleistung bereitgestellt (MIT-Lizenz). Rezeptmengen und Allergenangaben sind vom Betrieb zu prüfen.
