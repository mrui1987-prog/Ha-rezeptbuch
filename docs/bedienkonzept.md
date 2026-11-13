# Bedienkonzept HA-Rezeptbuch

Vorbild für die Bedienlogik ist eine industrielle Teigmacher-Steuerung (Profi-Dosiersystem mit Touch-Bedienung). Übernommen wird nur das **Bedienprinzip**, nicht das Aussehen, die Namen oder das Logo des Herstellers. Alles ist auf eine kleine Backstube mit Tablet und 1–2 Tischwaagen zugeschnitten.

## Grundprinzip

- **Ein Dashboard pro Waagestation.** Waage 1 und Waage 2 stehen meist räumlich getrennt, deshalb hat jede Station ihr eigenes Dashboard (eigenes Tablet). Eine Station zeigt nur ihre eigene Waage.
- **Ein Startbild als Ausgangspunkt.** Von hier aus erreicht man jede Funktion, und jede Funktion führt mit „Zurück“ wieder hierher.
- **Feste Tastenleisten.** Unten die Ablauf-Tasten, rechts die Ansichten. Die Tasten stehen immer an derselben Stelle.
- **Große Ziffern, wenige Eingaben.** Bedienung mit Mehlfingern: große Flächen, Zahlenfeld statt Tastatur, wo es geht.
- **Farbe zeigt Zustand.** Gelb = zu wenig, Grün = in Toleranz, Rot = zu viel.
- **Produktion ist frei, Änderungen sind geschützt.** Abwiegen geht ohne Anmeldung. Rezepte und Rohstoffe ändern nur über PIN → Admin-Dashboard.

## 1. Startbild (Stations-Dashboard)

Es gibt zwei getrennte Dashboards mit identischem Aufbau:

- **Waage 1** – Dashboard für Station 1 (Tablet an Waage 1)
- **Waage 2** – Dashboard für Station 2 (Tablet an Waage 2, nur wenn eingerichtet)

Jedes Tablet öffnet fest sein eigenes Dashboard. Ein Wechsel zur anderen Station ist im Alltag nicht nötig.

**Kopfzeile:** Stationsname, aktuelles Rezept (Nummer, Name), Gesamtmenge in kg, Stückzahl. Darunter der nächste offene Auftrag aus der Produktionsliste.

**Mitte:** Die eigene Waage groß mit aktuellem Gewicht und Status (Bereit / Wiegen / Stopp).

**Rechte Leiste:**

| Taste | Funktion |
|-------|----------|
| Wiegen | Wiegeansicht des laufenden Rezepts |
| Übersicht | alle Zutaten des laufenden Rezepts mit Haken für erledigte |
| Hinweis | Rezepthinweise der letzten Rezepte (z. B. Bestreuung, Deko) |

**Untere Leiste:**

| Taste | Funktion |
|-------|----------|
| Start | startet das vorgewählte Rezept |
| Pause | hält die Verwiegung an und gibt das Rezept für alle Stationen frei; „Weiter“ setzt fort. Taste rot, solange Pause aktiv |
| Abbruch | bricht das Rezept ab (Sicherheitsabfrage Ja/Nein) |
| Vorwahl | Rezept auswählen und Menge festlegen |
| Produktionsliste | Tagesaufträge anzeigen und abarbeiten |
| Chargen | Protokoll der gewogenen Teige |
| Menü 🔒 | PIN-Eingabe → Admin-Dashboard |

## 2. Vorwahl (Rezept auswählen)

1. Rezeptliste mit Nummer und Name, blättern seitenweise.
2. Suchfilter über Zahlen-/Buchstabenfeld, umschaltbar Name/Nummer.
3. Rezept antippen → **Menge festlegen.** Gespeichert ist immer das **Grundrezept**; das Arbeitsrezept entsteht aus dieser Auswahl:
   - **Stückzahlen je Stückgewicht:** Für jedes im Rezept angelegte Stückgewicht die gewünschte Anzahl eingeben (z. B. Brötchenteig: 100 × Stück 65 g, 5 × Kleines Flitt 400 g). Daraus ergibt sich der Gesamtteig.
   - oder **Gesamtteig** direkt in g/kg
   - oder **Chargengröße:** vorkonfigurierte Tasten des Rezepts (z. B. „Großer Teig“)
   - oder **Mehl gesamt:** Summe aller Mehle (Bäckerprozent-Bezug)
   - dazu **Anzahl Teige** (jeder Teig wird eine eigene Charge)
4. Bestätigen → **Rezeptübersicht** mit allen benötigten Zutaten und Mengen.
   - Die Übersicht zeigt auch die **Knetzeit**.
   - Hier kann der Bediener einen **Leitrohstoff** wählen und dessen Menge festsetzen (z. B. „nur noch 7 500 g Quark“, Eingabe in g, kg oder **Liter**, 1 l = 1 000 g für Literrezepte). Die übrigen Zutaten werden entsprechend angepasst.
5. Optional: Haken **„Fest an dieser Waage“** setzen. Ohne Haken ist das Rezept zwischen den Stationen übergebbar (siehe Abschnitt 4a). Der Haken ist eine einmalige, freiwillige Einstellung – es gibt keine wiederkehrende Abfrage.
6. Bestätigen → es geht direkt in die **Wiegeansicht** (Abschnitt 4).

Jedes Dashboard kann jedes Rezept auswählen. Gesperrte Rezepte und alte Rezeptversionen erscheinen in der Vorwahl nicht.

## 3. Produktionsliste (Tagesplan) – Teil von Version 1

- **Eine gemeinsame Liste für beide Stationen.** Jede Station sieht alle offenen Aufträge.
- Tippt eine Station einen Auftrag an, **übernimmt** sie ihn. Solange er dort läuft, ist er an der anderen Station als „in Arbeit an Waage X“ gesperrt.
- Über die Pause kann der Auftrag an die andere Station wandern (siehe Abschnitt 4a).
- Auch beim Anlegen eines Auftrags gibt es den optionalen Haken **„Fest an Waage 1/2“**.
- Mehrere Aufträge nacheinander anlegen (Rezept, Menge, Anzahl Teige). Anlegen auch im Admin-Bereich, z. B. am Vorabend.
- Auftrag antippen → Detailansicht mit allen Zutaten.
- Wasser- oder Mengenänderung im Auftrag gilt **nur für diesen Auftrag**, nicht für das Rezept.
- Die Rezeptversion wird erst beim **Start der Verwiegung des ersten Teigs** fixiert und gilt dann für alle Teige des Auftrags. Wird das Rezept nach dem Anlegen des Auftrags, aber vor dem Start geändert, gilt die Änderung noch für den Auftrag.
- Enthält ein Auftrag ein Unterrezept (Vorteig, Brühstück, Sauerteig), ist das Unterrezept ein **eigener, mit dem Hauptteig verknüpfter Auftrag**. Im Hauptteig ist es mit **+** markiert und muss zuerst abgearbeitet oder abgehakt werden. Danach wird aus dem + ein grüner Haken. Das Unterrezept kann auch an der anderen Station gewogen werden.
- **Unterrezept abhaken:** Wurde es schon anderweitig hergestellt, wird es als erledigt abgehakt. Alle Ist-Werte werden dann mit den Soll-Werten gefüllt (Protokoll: „abgehakt, nicht gewogen“), und es geht mit dem nächsten Rohstoff weiter.
- Löschen eines Auftrags mit Sicherheitsabfrage.

## 4. Wiegeansicht (Kern des Systems)

- **Rezepthinweis:** Ist im Rezept „zu Beginn“ eingestellt, erscheint der Hinweistext zusätzlich vor der ersten Zutat. Am Ende steht er immer in der Abschlussanzeige.
- Zutatennummer und -name groß oben.
- Links **Soll**, rechts **Ist** in großen Ziffern.
- Darunter ein Balken: **gelb** zu wenig, **grün** in Toleranz, **rot** zu viel.
- **Quittieren nur bei Grün:**
  - Meldet die Waage **4 Sekunden durchgehend stabil** im Toleranzbereich, wird **automatisch quittiert** und die nächste Zutat erscheint.
  - Liegt der Wert in der Toleranz, ist die Waage aber noch nicht stabil, kann mit der Taste **Quittieren** von Hand bestätigt werden. Das wird im Protokoll als „manuell (nicht stabil)“ gekennzeichnet.
  - Bei Gelb oder Rot ist Quittieren nicht möglich.
- **Tara:** Nach jeder quittierten Zutat tariert die Software automatisch, sodass alle Zutaten nacheinander in denselben Behälter gewogen werden können. Mit der Taste **Tara** lässt sich der Tara-Wert zusätzlich von Hand setzen.
- Tasten:
  - **Quittieren** (nur aktiv, wenn grün)
  - **Tara**
  - **Zutat übergehen** (mit Rückfrage, wird im Protokoll vermerkt)
  - **Übersicht** (alle Zutaten des Rezepts mit Haken für erledigte)
- **Waagenausfall:** Kurze Aussetzer werden ignoriert. Kommen 45 Sekunden lang keine Werte, geht der Auftrag automatisch auf Pause und das Tablet zeigt einen Hinweis.
- **Sollhandzugabe:** Zutaten mit Toleranz 0 werden nicht gewogen, nur quittiert (z. B. bereits vorbereitetes Quellstück). Anzeige mit gelbem Hinweis „Handzugabe“.
- **Gebinde und Stück:** Hat der Rohstoff eine Gebinde-/Stückgröße (z. B. Mehlsack 25 kg, Ei 55 g), wird die Sollmenge aufgeteilt: Die **ganzen Einheiten** werden als Anzahl angezeigt und **von Hand quittiert** (z. B. „1 Sack“, „10 Eier“), danach wird der **Rest gewogen** (z. B. 30 kg = 1 Sack + 5 kg wiegen; 580 g Eier = 10 Eier + 30 g wiegen). Es wird nicht auf ganze Stück gerundet. Die volle Toleranz des Rohstoffs gilt für den Rest.
- **Handzugabe nach Bedarf:** Zutaten mit Menge 0 g (z. B. „Vanille/Zitrone“) erscheinen mit dem Hinweis „Handzugabe“. Der Bediener entscheidet als Fachmann selbst, wie viel, und quittiert.
- Rezept ist fertig, wenn alle Zutaten quittiert sind → Eintrag im Chargenprotokoll.
- **Abschlussanzeige „Wiegevorgang abgeschlossen“:** erscheint **immer** nach der Verwiegung und zeigt die **Hinweise aus dem Rezept** und die **Knetzeiten** (langsam + schnell). Sie bleibt stehen, bis der Bediener sie **quittiert**; danach Rückkehr zum Startbild.
- Im Chargenprotokoll steht pro Zutat die **Quittierungsart**: „automatisch (stabil)“, „manuell (nicht stabil)“, „Handzugabe“, „abgehakt, nicht gewogen“, „übergangen“.

## 4a. Rezept zwischen Stationen übergeben (Pause)

Zweck: Eine Zutat, die gerade nur am anderen Standort steht, dort abwiegen, ohne das Rezept neu zu starten.

**Regeln**

- Ein laufendes Rezept gehört der Station, an der es gestartet wurde. Nach jeder quittierten Zutat springt die Anzeige automatisch auf die nächste offene Zutat.
- Auf der anderen Station ist das laufende Rezept **gesperrt** (sichtbar, aber nicht bedienbar).
- Wird **Pause** gedrückt, ist das Rezept auf **allen** Stationen freigegeben.
- Die Station, die als nächste **Weiter** drückt, übernimmt das Rezept. Es ist dann an der jeweils anderen Station wieder gesperrt.
- Dort kann jede offene Zutat angewählt werden, nicht nur die nächste in der Reihenfolge. Danach geht es wieder automatisch mit der nächsten offenen Zutat weiter.
- Bereits quittierte Zutaten bleiben quittiert, egal an welcher Station sie gewogen wurden. Im Chargenprotokoll steht pro Zutat, an welcher Waage sie gewogen wurde.
- Ist **„Fest an dieser Waage“** gesetzt, wird das Rezept auch in der Pause nicht freigegeben. Es kann nur an der festen Station fortgesetzt werden.

**Ablauf-Beispiel**

1. Station 1 wiegt „Das Kernige“, die Saaten stehen aber an Station 2.
2. An Station 1 **Pause** drücken.
3. An Station 2 das Rezept antippen, Zutat „Saaten“ wählen, **Weiter**, abwiegen, quittieren.
4. An Station 2 **Pause** drücken.
5. An Station 1 **Weiter** → es geht mit der nächsten offenen Zutat weiter.

## 5. Handbetrieb

Jede Station lässt ihre Waage ohne Rezept als normale Waage benutzen (Tara, Wiegen). Wird an dieser Station ein Rezept gestartet, schaltet der Handbetrieb dort automatisch ab. Die andere Station ist davon nicht betroffen.

## 6. Admin-Dashboard (nach PIN)

| Bereich | Inhalt |
|---------|--------|
| Rohstoffliste | anlegen, bearbeiten, archivieren, löschen |
| Rezepturen | anlegen, bearbeiten, kopieren, sperren, archivieren, löschen |
| Produktionsliste | Aufträge anlegen, Station zuweisen, löschen |
| Waagen | Station 1/2 einrichten, Waage zuordnen, Verbindung prüfen |
| Export / Druck | Rezepte und Rohstoffe als CSV exportieren oder drucken |
| System | PIN ändern, Sicherung, Abmelden |

Die Admin-Sitzung endet automatisch nach einer einstellbaren Zeit ohne Eingabe und kehrt zum Startbild zurück.

**Archivieren statt Löschen:** Rohstoffe und Rezepte, die schon in einem Rezept, Auftrag oder einer Charge vorkommen, werden archiviert. Endgültig löschen lässt sich nur, was nie verwendet wurde.

### Rohstoff

- Herkunft: aus **BÄKO Datenlink** übernommen oder **eigener Rohstoff** (die Rohstoffdatenbank ist um eigene Rohstoffe erweiterbar)
- Nummer (reine Zahl, eindeutig; das System arbeitet mit der Nummer, nicht mit dem Namen)
- Name
- **Toleranz pro Rohstoff:** ein Wert, gilt nach unten und oben gleich (±). Einheit wählbar: **Gramm** (Standard) oder **Prozent** der Sollmenge (auf Zehntelprozent, z. B. 2,5 %). Gilt als Vorgabe für Rezeptzeilen.
- Typ: Standard oder Mehl (zählt zu „Mehl gesamt“ und zu den Bäckerprozenten)
- **Gebinde-/Stückgröße** in Gramm mit Bezeichnung (z. B. „Sack“ 25 000 g, „Ei“ 55 g), optional
- Allergene, Nährwerte, Zutatenverzeichnis und Lieferanten folgen, sobald klar ist, was BÄKO Datenlink liefert

### Rezept

- Kopf: Nummer (reine Zahl), Name, Gesamtgewicht (rechnet sich aus den Zeilen)
- **Stückgewichte:** beliebig viele je Rezept, jeweils Bezeichnung und Gewicht (z. B. Brötchenteig: Stück 65 g, Ballen 1 550 g, Ballen Hörnchen 2 800 g, Hörnchen 93 g, Kleines Flitt 400 g, Große Flitt 600 g)
- **Knetzeit:** Minuten langsam + Minuten schnell (z. B. „5+6“)
- **Hinweistext:** ein Text für das ganze Rezept (z. B. Bestreuung, Deko), mit Einstellung **„zu Beginn“** oder **„am Ende“ der Verwiegung anzeigen**. Keine Hinweiszeilen zwischen den Zutaten.
- **Chargengrößen:** feste Mengen für die Vorwahl, nur für dieses Rezept (Bezeichnung, Gewicht oder Stückzahl eines seiner Stückgewichte)
- Status-Taste **Öffentlich / Gesperrt** (gesperrte Rezepte sind in der Produktion unsichtbar)
- Zeilen: Rohstoff oder Unterrezept, Sollmenge in Gramm, Toleranz (übernimmt die Toleranz des Rohstoffs, kann pro Zeile überschrieben werden; keine Waagenauswahl pro Zeile – ein Teig läuft immer an der Station, die ihn gerade übernommen hat)
- Zeilen einfügen, verschieben, löschen
- **Speichern und Versionen:** Wurde das Rezept seit der letzten Änderung schon gewogen, entsteht beim Speichern automatisch eine neue Version. Sonst fragt das System, ob eine neue Version angelegt oder die aktuelle überschrieben werden soll. Alte Stände erscheinen als „old (1)“, „old (2)“ … mit Datum, nur im Admin-Bereich.
- **Rezept kopieren:** neue Nummer → Name ändern → entsperren
- **Unterrezept (Teig in Teig):** ein Rezept kann als Zutat in anderen Rezepten verwendet werden; farblich abgesetzt
- **Rezeptschritte:** Zeilen können Schritten zugeordnet werden (z. B. erst Vorteig, dann Hauptteig); farblich gruppiert
- **Übersicht:** ganzes Rezept auf einer Seite, wahlweise als Zusammenfassung mit Anteil am Gesamtgewicht und **Bäckerprozent** (bezogen auf Mehl)

## Bewusst weggelassen

Diese Funktionen des Vorbilds braucht eine kleine Backstube mit Tischwaagen nicht:

- Silos, Silozuordnung, Mehlwaage mit automatischer Dosierung
- Wassermischgerät, Eis- und Wärmeberechnung (ggf. später als Zusatzmodul)
- Kneter-Steuerung, SPS-Parameter
- Benutzerverwaltung mit Einzelrechten (ersetzt durch eine gemeinsame PIN)
- Waagenkalibrierung (macht die KERN-Waage selbst)

## Änderungen

| Datum | Änderung |
|-------|----------|
| 12.11.2026 | Bedienkonzept mit getrennten Stations-Dashboards, Produktionsliste und Pause-Übergabe festgelegt. |
| 12.11.2026 | An Review-Entscheidungen R1–R6 angepasst: Toleranz pro Rohstoff (Gramm/Prozent), Versionsfixierung beim Start, Unterrezepte als verknüpfte Aufträge, automatische/manuelle Quittung, automatische Tara, Waagenausfall nach 45 s, Quittierungsart im Protokoll. |
| 13.11.2026 | Abschlussanzeige „Wiegevorgang abgeschlossen“ mit Rezepthinweisen und Knetzeiten bis zur Quittierung; Knetzeit in der Rezeptübersicht; Handzugabe nach Bedarf für Zutaten mit 0 g. |
| 13.11.2026 | Vorwahl-Ablauf nach Vorgabe von Michael: Stückzahlen je Stückgewicht oder Gesamtteig → Rezeptübersicht mit optionalem Leitrohstoff → Wiegeansicht. Mehrere Stückgewichte und Knetzeit im Rezept. |
| 13.11.2026 | An Entscheidungen aus Modul 02 angepasst: Vorwahl mit Chargengrößen, Leitrohstoff (auch in Liter) und „Mehl gesamt“; Gebinde-/Stückgröße mit Handquittierung und Rest wiegen; eine Toleranz ±; Rohstofftyp „Text“ entfällt, stattdessen ein Hinweistext pro Rezept mit Anzeige zu Beginn oder am Ende; Versionsregel beim Speichern; Archivieren statt Löschen; Version gilt für alle Teige eines Auftrags. |
