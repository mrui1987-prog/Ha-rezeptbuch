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
3. Rezept antippen → Menge eingeben: **Stückzahl** oder **Gesamtgewicht** (das andere rechnet sich mit), dazu Anzahl Teige.
4. Optional: Haken **„Fest an dieser Waage“** setzen. Ohne Haken ist das Rezept zwischen den Stationen übergebbar (siehe Abschnitt 4a). Der Haken ist eine einmalige, freiwillige Einstellung – es gibt keine wiederkehrende Abfrage.
5. OK → Rezept steht im Startbild bereit.

Jedes Dashboard kann jedes Rezept auswählen. Gesperrte Rezepte erscheinen in der Vorwahl nicht.

## 3. Produktionsliste (Tagesplan) – Teil von Version 1

- **Eine gemeinsame Liste für beide Stationen.** Jede Station sieht alle offenen Aufträge.
- Tippt eine Station einen Auftrag an, **übernimmt** sie ihn. Solange er dort läuft, ist er an der anderen Station als „in Arbeit an Waage X“ gesperrt.
- Über die Pause kann der Auftrag an die andere Station wandern (siehe Abschnitt 4a).
- Auch beim Anlegen eines Auftrags gibt es den optionalen Haken **„Fest an Waage 1/2“**.
- Mehrere Aufträge nacheinander anlegen (Rezept, Menge, Anzahl Teige). Anlegen auch im Admin-Bereich, z. B. am Vorabend.
- Auftrag antippen → Detailansicht mit allen Zutaten.
- Wasser- oder Mengenänderung im Auftrag gilt **nur für diesen Auftrag**, nicht für das Rezept.
- Die Rezeptversion wird erst beim **Start der Verwiegung** fixiert. Wird das Rezept nach dem Anlegen des Auftrags geändert, gilt die Änderung noch für den Auftrag.
- Enthält ein Auftrag ein Unterrezept (Vorteig, Brühstück, Sauerteig), ist das Unterrezept ein **eigener, mit dem Hauptteig verknüpfter Auftrag**. Im Hauptteig ist es mit **+** markiert und muss zuerst abgearbeitet oder abgehakt werden. Danach wird aus dem + ein grüner Haken. Das Unterrezept kann auch an der anderen Station gewogen werden.
- **Unterrezept abhaken:** Wurde es schon anderweitig hergestellt, wird es als erledigt abgehakt. Alle Ist-Werte werden dann mit den Soll-Werten gefüllt (Protokoll: „abgehakt, nicht gewogen“), und es geht mit dem nächsten Rohstoff weiter.
- Löschen eines Auftrags mit Sicherheitsabfrage.

## 4. Wiegeansicht (Kern des Systems)

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
- **Gebinde:** Bei großen Mengen wird ein ganzer Sack als Handzugabe quittiert, nur der Rest wird gewogen (z. B. 30 kg = 25-kg-Sack + 5 kg wiegen).
- Rezept ist fertig, wenn alle Zutaten quittiert sind → Eintrag im Chargenprotokoll, Rückkehr zum Startbild.
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
| Rohstoffliste | anlegen, bearbeiten, löschen |
| Rezepturen | anlegen, bearbeiten, kopieren, sperren, löschen |
| Produktionsliste | Aufträge anlegen, Station zuweisen, löschen |
| Waagen | Station 1/2 einrichten, Waage zuordnen, Verbindung prüfen |
| Export / Druck | Rezepte und Rohstoffe als CSV exportieren oder drucken |
| System | PIN ändern, Sicherung, Abmelden |

Die Admin-Sitzung endet automatisch nach einer einstellbaren Zeit ohne Eingabe und kehrt zum Startbild zurück.

### Rohstoff

- Herkunft: aus **BÄKO Datenlink** übernommen oder **eigener Rohstoff** (die Rohstoffdatenbank ist um eigene Rohstoffe erweiterbar)
- Nummer (eindeutig, das System arbeitet mit der Nummer, nicht mit dem Namen)
- Name
- **Toleranz pro Rohstoff** (Plus/Minus), Einheit wählbar: **Gramm** (Standard) oder **Prozent** der Sollmenge. Gilt als Vorgabe für Rezeptzeilen.
- Typ: Standard, Mehl (für Bäckerprozente), Text (nur Hinweiszeile im Rezept)
- Gebindemenge (z. B. 25 kg)
- Löschen nur möglich, wenn der Rohstoff in keinem Rezept mehr steht; sonst Liste der betroffenen Rezepte

### Rezept

- Kopf: Nummer, Name, Stückgewicht, Stückzahl, Gesamtgewicht (rechnet sich aus den Zeilen), Hinweistext
- Status-Taste **Öffentlich / Gesperrt** (gesperrte Rezepte sind in der Produktion unsichtbar)
- Zeilen: Rohstoff, Sollmenge, Toleranz (übernimmt die Toleranz des Rohstoffs, kann pro Zeile überschrieben werden; keine Waagenauswahl pro Zeile – ein Teig läuft immer an der Station, die ihn gerade übernommen hat)
- Zeilen einfügen, verschieben, löschen
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
