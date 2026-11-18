# HA-Rezeptbuch

Rezeptverwaltung, Produktionsliste und Wiegeablauf für kleine Bäckereien.

**Stand 0.5.10:** Rohstoffverwaltung (Modul 03) mit CSV-Export und CSV-Import unter `/admin`, Rezeptverwaltung (Modul 05) mit Import aus der Importvorlage und Export (.xlsx) unter `/admin/rezepte`. Die Oberfläche ist noch schlicht; die Gestaltung folgt in Modul 10.

## Datenbank

- Datei: `/data/rezeptbuch.db` (wird vom Home-Assistant-Backup erfasst)
- Beim Start wird die Datenbank geprüft und bei Bedarf auf den neuesten Stand gebracht.
- Vor jeder solchen Aktualisierung entsteht eine Sicherungskopie in `/data/backups/` (die letzten 5 bleiben erhalten).
- Ist die Datenbank beschädigt oder neuer als das Add-on, startet das Rezeptbuch nicht im Produktionsbetrieb und meldet den Fehler im Add-on-Protokoll.

## Voraussetzungen

- Home Assistant OS oder Supervised (Add-ons)
- MQTT-Broker (Add-on „Mosquitto broker“)
- Add-on „HA-Rezeptbuch Waage“ für die Waagenanbindung

## Oberflächen

| Adresse | Zweck |
|---------|-------|
| `/admin` | Rohstoffe (PIN) |
| `/admin/rezepte` | Rezepte, Rezeptgruppen, Import/Export (PIN); Aufträge folgen in späteren Modulen |

Die Stationsadressen für die Tablets an den Waagen folgen in Modul 09/10 und sind in dieser Version noch nicht vorhanden.

Im Probebetrieb gilt die PIN **1234** (roter Hinweisbalken). Die PIN-Änderung folgt in Modul 12. Es wird nur ein Hash gespeichert. Nach 5 Fehlversuchen ist die Eingabe 5 Minuten gesperrt. Die Sitzungsdauer stellt die Add-on-Option `admin_timeout_minutes` ein (Standard 5 Minuten).

## Rohstoffe importieren (CSV)

Taste **„CSV-Import“** in der Rohstoffliste. Die Datei hat das Format des CSV-Exports (Semikolon, Kopfzeile `Nummer;Name;Kurzname;Typ;Toleranz;Toleranzeinheit;Gebindegröße g;Gebindebezeichnung;Herkunft;archiviert;geändert am`). Gelesen werden „CSV UTF-8“ und „CSV (Trennzeichen-getrennt)“ aus Excel.

- Zuerst läuft immer ein **Probelauf**; er zeigt neue, überschriebene und unveränderte Rohstoffe, Fehler und Hinweise. Gespeichert wird erst mit **„Importieren“**, und nur wenn die Datei keinen Fehler enthält (alles oder nichts).
- Zuordnung über die **Nummer**, ohne Nummer über den **Namen**; passt keiner, wird der Rohstoff neu angelegt.
- **Vorhandene Rohstoffe werden überschrieben** (Bestätigung nötig). Leere Toleranz bleibt unverändert, leerer Kurzname und leeres Gebinde werden geleert, leerer Typ bleibt. Nummer und Herkunft ändern sich nie. „Herkunft“ und „geändert am“ werden nicht ausgewertet.
- **Neue Rohstoffe ohne Toleranz erhalten 0 %.** 0 % wird gewogen (bei der Verwiegung mindestens ±1 g); nur **0 g** ist eine Handzugabe. Mit dem Filter „nur Toleranz 0 %“ lassen sich diese Rohstoffe später finden.
- Spalte **„archiviert“**: ja = archivieren, nein = wiederherstellen. Rohstoffe, die nicht in der Datei stehen, bleiben unverändert.
- Viele Rohstoffe bearbeiten: CSV-Export → in Excel ändern → als CSV speichern → CSV-Import.
- Namen und Kurznamen dürfen nicht mit `=`, `+`, `-` oder `@` beginnen (Schutz vor Excel-Formeln).
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
- **Mehrere Rezepte auf einmal:** In der Liste Rezepte anhaken (oder „alle auswählen“ oben links für alle angezeigten). Die Leiste bietet Freischalten, Sperren, Archivieren, Löschen und Exportieren; sind archivierte Rezepte angehakt, zusätzlich **Wiederherstellen** (nicht möglich, wenn ein aktives Rezept gleich heißt – das Rezept wird dann übersprungen und genannt). Vorher zeigt eine Vorschau, was passiert und was übersprungen wird; beim Freischalten stehen alle offenen „*“ und Toleranzen 0 % in einer Liste. Es gelten dieselben Regeln wie beim einzelnen Rezept.
- Der Haken **„mit archivierten Rohstoffen“** zeigt Rezepte, deren aktuelle Version einen archivierten Rohstoff enthält.
- **Sperren** blendet ein Rezept nur in der Vorwahl aus; als Unterrezept bleibt es nutzbar. **Archivieren** geht nicht, solange das Rezept als Unterrezept in einem aktiven Rezept steckt. Archivierte Rezepte können wiederhergestellt, aber nicht bearbeitet werden. **Löschen** nur, wenn das Rezept nie verwendet wurde.
- **Rohstoff austauschen** (Taste über der Rezeptliste): auszutauschenden Rohstoff, neuen Rohstoff und Faktor wählen (neue Menge = alte Menge × Faktor, auf ganze Gramm gerundet; 0 g bleibt 0 g, sonst mindestens 1 g), dazu höchstens zwei Zusatzzutaten mit Faktor auf die alte Menge (z. B. Butter 1 000 g → Margarine × 0,82 = 820 g + Wasser × 0,16 = 160 g; die Zusatzzeilen kommen direkt unter die getauschte Zeile im selben Schritt). „Rezepte anzeigen“ listet alle nicht archivierten Rezepte, deren aktuelle Version den Rohstoff direkt enthält, mit „alt → neu“; einzelne Rezepte abwählen, dann „Austauschen“. **Jedes geänderte Rezept bekommt eine neue Version**; öffentlich/gesperrt bleibt. Eine eigene Zeilentoleranz bleibt erhalten. Wahlweise: geänderte Zeilen mit „*“ markieren; alten Rohstoff archivieren, wenn er danach in keinem Rezept mehr vorkommt. Wurde ein Rezept inzwischen an einem anderen Gerät geändert, wird es übersprungen und genannt.
- **Alte Versionen ansehen:** Neben jeder Menge steht kursiv die Menge der aktuellen Version („aktuell: …“, gelb = abweichend, „entfällt“ = nicht mehr enthalten); Zeilen, die nur die aktuelle Version hat, stehen kursiv am Ende. Am Handy steht der Wert unter der Menge.
- **Kopieren** übernimmt die aktuelle Version, Stückgewichte und Chargengrößen als „Kopie von …“ (gesperrt).
- Gesamtgewicht und Summe Mehl zeigen den gespeicherten Stand der direkten Zeilen; Anteile und Bäckerprozent folgen mit Modul 06.
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

## Haftung

Die Software wird ohne Gewährleistung bereitgestellt (MIT-Lizenz). Rezeptmengen und Allergenangaben sind vom Betrieb zu prüfen.
