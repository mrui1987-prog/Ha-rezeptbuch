"""Mustervorlage zum Herunterladen (Modul 05, Ergänzung C3-E2, Wunsch Michael 17.11.2026).

Eine Importvorlage mit denselben Blättern und Spalten wie die echte Vorlage, ausgefüllt mit
**Musterrohstoffen** und einem **Musterrezept „Schwarzwälder Kirschtorte“** – mit
Schoko-Biskuit als Unterrezept, damit alle Möglichkeiten einmal vorkommen: Schritte, Stück-
und ml-Angaben über die Umrechnung im Blatt „Rohstoffe“ (seit 0.5.8, C3-E7), „*“ zum Prüfen,
Handzugabe (leere Menge), eigene Zeilentoleranz, Stückgewicht, Chargengrößen (Gewicht und
Stück), Knetzeit, Hinweis und interne Notiz.

Die Musterzeilen sind gelb hinterlegt und in der Spalte „Bemerkung“ gekennzeichnet. Der Import
**überspringt sie** (C3-E11, erkannt an den Namen in ``SAMPLE_RECIPE_NAMES`` und
``SAMPLE_RAW_NAMES``), außer mit dem Haken „Musterdaten mit importieren“. Die Spalten „Faktor“
und „Menge g“ enthalten Excel-Formeln zur Kontrolle; der Import liest sie nicht (K05-6).
Es werden keine Betriebsdaten verwendet.
"""

from __future__ import annotations

import io
from datetime import datetime

from .. import __version__

MUSTER = "Muster – löschen oder überschreiben"
FORMULA_ROWS = 300          # Zeilen mit Kontrollformeln im Blatt „Rezeptzeilen“

# Überschriften wie die Importvorlage vom 14.11.2026 (ohne reine Formel-/Infospalten der Datenblätter)
RECIPES = ["Import-ID", "Rezeptnummer (leer = nächste freie)", "Rezeptname", "Rezeptgruppe",
           "Knetzeit langsam (min)", "Knetzeit schnell (min)", "Hinweistext",
           "Hinweis anzeigen (Beginn = am Anfang und am Ende, Ende = nur am Ende)", "Notiz intern",
           "Darf vorproduziert werden (ja/nein)", "Abwiegezuschlag % (z. B. 1,2; leer = keiner)", "Bemerkung"]
LINES = ["Import-ID", "Position", "Schritt", "Zeilenart (Rohstoff/Unterrezept)", "Zutat (bereinigt)",
         "Unterrezept Import-ID", "Menge Original", "Einheit Original (g/kg/ml/Stück/Maß)",
         "Faktor g je Einheit (Formel)", "Menge g (Formel)", "Toleranzeinheit (g/percent, optional)",
         "Toleranzwert (optional)", "Prüfen", "Bemerkung / Prüfgrund"]
PIECES = ["Import-ID", "Bezeichnung", "Gewicht g", "Reihenfolge", "Bemerkung"]
BATCHES = ["Import-ID", "Bezeichnung (Taste)", "Art (Gewicht/Stück)", "Wert (g bzw. Stück)",
           "Stückgewicht-Bezeichnung (nur bei Stück)", "Reihenfolge", "Obergrenze (ja = aktiv)", "Bemerkung"]
RAW = ["Nummer", "Name", "Kurzname", "Typ (standard/flour)", "Toleranz (leer = 0 %)", "Toleranzeinheit (g/percent)",
       "Gebindegröße g", "Gebindebezeichnung", "Umrechnung Einheit (nur für den Rezeptimport, z. B. Stück)",
       "Gramm je Einheit (z. B. Eier: 65)", "archiviert (0/1)", "Bemerkung (nicht importieren)"]
CONVERSION_NOTE = ("Nur ausfüllen, wenn Rezepte über Umrechnung importiert werden sollen.\n"
                   "Beispiel Eier: Umrechnung Einheit „Stück“, Gramm je Einheit 65. In der Rezeptzeile reicht dann "
                   "Menge 20, Einheit „Stück“, Zutat „Eier“ (= 1 300 g, Zeile bekommt „*“).\n"
                   "Für „ml“ eingetragen, gilt der Wert automatisch auch für „l“ (× 1 000) und umgekehrt.\n"
                   "Der Wert wird nicht gespeichert, er dient nur dem Import.")

SAMPLE_RECIPES = [
    ["M1", None, "Schoko-Biskuit (Muster)", "Torten", None, None,
     "Bei 180 °C etwa 30 Minuten backen.", "Ende", None, "ja", None, MUSTER + " (Unterrezept der Torte)"],
    ["M2", None, "Schwarzwälder Kirschtorte (Muster)", "Torten", None, None,
     "Boden zweimal durchschneiden und mit Kirschwasser tränken.", "Beginn",
     "Musterrezept aus der Mustervorlage", "nein", "1,2", MUSTER],
]
# Import-ID, Position, Schritt, Zeilenart, Zutat, Unterrezept, Menge, Einheit, Tol.-Einheit, Tol.-Wert, Prüfen, Bemerkung
SAMPLE_LINES = [
    ["M1", 1, "aufschlagen", "Rohstoff", "Muster Ei", None, 6, "Stück", None, None, None,
     "Stück → Gramm über die Umrechnung im Blatt „Rohstoffe“ (bekommt automatisch „*“)"],
    ["M1", 2, "aufschlagen", "Rohstoff", "Muster Zucker", None, 180, "g", None, None, None, None],
    ["M1", 3, "unterheben", "Rohstoff", "Muster Weizenmehl 405", None, 120, "g", None, None, None, None],
    ["M1", 4, "unterheben", "Rohstoff", "Muster Speisestärke", None, 40, "g", None, None, None, None],
    ["M1", 5, "unterheben", "Rohstoff", "Muster Kakaopulver", None, 30, "g", None, None, None, None],
    ["M1", 6, "unterheben", "Rohstoff", "Muster Butter", None, 50, "g", None, None, None, "flüssig"],
    ["M2", 1, "Boden", "Unterrezept", "Schoko-Biskuit (Muster)", "M1", 720, "g", None, None, None,
     "Unterrezept: Verweis über die Import-ID"],
    ["M2", 2, "Kirschfüllung", "Rohstoff", "Muster Sauerkirschen", None, 0.7, "kg", None, None, None, "kg → 700 g"],
    ["M2", 3, "Kirschfüllung", "Rohstoff", "Muster Zucker", None, 50, "g", None, None, None, None],
    ["M2", 4, "Kirschfüllung", "Rohstoff", "Muster Speisestärke", None, 40, "g", None, None, None, None],
    ["M2", 5, "Kirschfüllung", "Rohstoff", "Muster Kirschwasser", None, 40, "ml", "percent", 5, None,
     "ml → Gramm über die Umrechnung (Schätzwert, automatisch „*“); eigene Toleranz 5 %"],
    ["M2", 6, "Sahne", "Rohstoff", "Muster Sahne", None, 1, "kg", None, None, None, None],
    ["M2", 7, "Sahne", "Rohstoff", "Muster Vanillezucker", None, 16, "g", None, None, None, None],
    ["M2", 8, "Garnitur", "Rohstoff", "Muster Schokoraspeln", None, None, None, None, None, None,
     "leere Menge = 0 g Handzugabe"],
]
SAMPLE_PIECES = [["M2", "Stück (1/16)", 170, 1, MUSTER]]
SAMPLE_BATCHES = [
    ["M2", "1 Torte", "Gewicht", None, None, 1, None, "leerer Wert = Gesamtgewicht des Rezepts"],
    ["M2", "16 Stück", "Stück", 16, "Stück (1/16)", 2, None, "Stückzahl über das Stückgewicht"],
]
SAMPLE_RAW = [[None, "Muster Kirschwasser", "M-Kirschw.", "standard", 5, "percent", None, None, "ml", 0.95, 0,
               "Musterrohstoff mit allen Spalten. Leere Nummer = nächste freie. Gleicher Name wie ein vorhandener "
               "Rohstoff = überschreiben (mit Rückfrage). Umrechnung ml: Schätzwert (Alkohol leichter als Wasser)."]]
for _n in ["Ei", "Zucker", "Weizenmehl 405", "Speisestärke", "Kakaopulver", "Butter", "Sauerkirschen", "Sahne",
           "Vanillezucker", "Schokoraspeln"]:
    SAMPLE_RAW.append([None, "Muster " + _n, None, "flour" if _n.startswith("Weizen") else "standard", None, None, None,
                       None, "Stück" if _n == "Ei" else None, 50 if _n == "Ei" else None, 0,
                       "Umrechnung: Gramm je Ei – an den eigenen Wert anpassen" if _n == "Ei"
                       else "nur nötig, damit das Musterrezept ohne Vorarbeit importierbar ist"])

# Feste Namensliste der Musterdaten: der Import überspringt sie (C3-E11)
SAMPLE_RECIPE_NAMES = tuple(r[2] for r in SAMPLE_RECIPES)
SAMPLE_RAW_NAMES = tuple(r[1] for r in SAMPLE_RAW)

GUIDE = [
    ("HA-Rezeptbuch – Mustervorlage für den Rezeptimport", True),
    ("", False),
    ("So geht es", True),
    ("1. Gelb hinterlegte Zeilen sind Muster (Schwarzwälder Kirschtorte mit Schoko-Biskuit als Unterrezept, Rohstoffe "
     "„Muster …“). Der Import überspringt sie automatisch (erkannt am Namen); eigene Zeilen einfach darunter ergänzen. "
     "Zum Ausprobieren lassen sie sich mit dem Haken „Musterdaten mit importieren“ einmal importieren.", False),
    ("2. Blatt „Rezepte“: eine Zeile je Rezept. Die Import-ID (z. B. R1, M2) verbindet alle Blätter; sie wird nicht gespeichert.", False),
    ("3. Blatt „Rezeptzeilen“: eine Zeile je Zutat. Zutat = Name des Rohstoffs wie im Rohstoffstamm "
     "(Groß-/Kleinschreibung egal). Unterrezept: Zeilenart „Unterrezept“ und die Import-ID des anderen Rezepts.", False),
    ("4. Menge: Menge Original + Einheit. g und kg rechnet der Import selbst. Für alles andere (Stück, ml, Maß) im Blatt "
     "„Rohstoffe“ beim Rohstoff „Umrechnung Einheit“ und „Gramm je Einheit“ eintragen, z. B. Eier: Stück, 65. "
     "ml gilt automatisch auch für l. Jede umgerechnete Zeile bekommt „*“ zum Prüfen; der Probelauf zeigt "
     "alle Umrechnungen vorab in einem eigenen Fenster. Leere Menge = 0 g Handzugabe.", False),
    ("5. „*“ in der Spalte „Prüfen“ markiert Zeilen, die nach dem Import kontrolliert werden sollen.", False),
    ("6. Blatt „Rohstoffe“ ist nur nötig für neue oder zu ändernde Rohstoffe und für Umrechnungen. Vorhandene Rohstoffe "
     "werden über die Nummer, sonst den Namen gefunden und mit den Werten der Datei überschrieben (der Probelauf zeigt "
     "„alt → neu“). Eine Zeile nur mit Name und Umrechnung ändert einen vorhandenen Rohstoff nicht.", False),
    ("7. Im Admin-Bereich: Reiter „Import/Export“ → Datei wählen → Probelauf → Importieren. Alles oder nichts: "
     "bei einem Fehler wird nichts gespeichert. Importierte Rezepte sind gesperrt.", False),
    ("", False),
    ("Regeln", True),
    ("• Rezeptnummer: leer = nächste freie Nummer. Gibt es die Nummer (sonst der Rezeptname) schon, bekommt das "
     "vorhandene Rezept nach Bestätigung eine neue Version; die bisherige bleibt als „old“ erhalten. Gleicher Inhalt = unverändert. "
     "Archivierte Rezepte müssen zuerst wiederhergestellt werden.", False),
    ("• Namen dürfen nicht mit =, +, - oder @ beginnen (Hinweistext und Notiz schon).", False),
    ("• Hinweis anzeigen: „Beginn“ = am Anfang und am Ende der Verwiegung, „Ende“ = nur am Ende. "
     "Ein leerer Hinweistext erscheint an der Waage nicht.", False),
    ("• Notiz intern: nur im Admin-Bereich sichtbar, nie an der Waage.", False),
    ("• Darf vorproduziert werden / Abwiegezuschlag: Angaben für den Planer (ja/nein; Prozent mit höchstens einer "
     "Nachkommastelle, 0 bis 20). Leer = beim Anlegen nein bzw. kein Zuschlag, bei vorhandenen Rezepten unverändert.", False),
    ("• Toleranz je Zeile ist freiwillig (sonst gilt die des Rohstoffs): Einheit g oder percent, Wert in g bzw. %.", False),
    ("• Chargengröße „Gewicht“ ohne Wert = Gesamtgewicht des Rezepts; „Stück“ braucht Anzahl und Stückgewicht-Bezeichnung.", False),
    ("• „Obergrenze“ = ja: größter Teig für dieses Rezept (Kessel); höchstens eine Chargengröße je Rezept.", False),
    ("• Spalten mit „(Formel)“ dienen nur der Kontrolle in Excel und werden nicht importiert. Die Datei als .xlsx speichern.", False),
    ("• Ohne Microsoft Office: die Datei z. B. in LibreOffice Calc öffnen und beim Speichern das Format "
     "„Excel 2007-365 (.xlsx)“ wählen (nicht .ods).", False),
    ("• Ein Blatt „Umrechnung“ aus älteren Vorlagen wird übergangsweise noch gelesen; neu bitte das Blatt „Rohstoffe“ verwenden.", False),
]


def _style():
    from openpyxl.styles import Font, PatternFill
    return Font(bold=True), PatternFill("solid", fgColor="DDDDDD"), PatternFill("solid", fgColor="FFF2B3")


def _sheet(wb, title, header, rows, widths, muster_fill):
    ws = wb.create_sheet(title)
    bold, head_fill, _ = _style()
    ws.append(header)
    for column, width in enumerate(widths, start=1):
        cell = ws.cell(row=1, column=column)
        cell.font = bold
        cell.fill = head_fill
        ws.column_dimensions[cell.column_letter].width = width
    for row in rows:
        ws.append(row)
        for column in range(1, len(header) + 1):
            cell = ws.cell(row=ws.max_row, column=column)
            cell.fill = muster_fill
            if isinstance(cell.value, str):
                cell.data_type = "s"            # Text bleibt Text (B2)
    ws.freeze_panes = "A2"
    return ws


def _validation(ws, formula: str, cell_range: str) -> None:
    from openpyxl.worksheet.datavalidation import DataValidation
    dv = DataValidation(type="list", formula1=formula, allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(cell_range)


def build_sample() -> bytes:
    """Erzeugt die Mustervorlage als .xlsx."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    _, _, muster = _style()
    wb = Workbook()
    guide = wb.active
    guide.title = "Anleitung"
    for row, (text, bold) in enumerate(GUIDE, start=1):
        cell = guide.cell(row=row, column=1, value=text or None)
        cell.font = Font(bold=bold, size=12 if row == 1 else 10)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    guide.cell(row=len(GUIDE) + 2, column=1,
               value=f"Erstellt am {datetime.now().strftime('%d.%m.%Y')} mit HA-Rezeptbuch {__version__}.")
    guide.column_dimensions["A"].width = 120

    ws_r = _sheet(wb, "Rezepte", RECIPES, SAMPLE_RECIPES, [10, 14, 34, 16, 12, 12, 46, 24, 30, 16, 16, 40], muster)
    lines = []
    for ln in SAMPLE_LINES:
        lines.append([*ln[:8], None, None, *ln[8:]])
    ws_l = _sheet(wb, "Rezeptzeilen", LINES, lines, [10, 9, 16, 14, 26, 12, 12, 14, 12, 12, 14, 12, 8, 44], muster)
    # Kontrollformeln Faktor und Menge g (der Import liest sie nicht); Faktor aus der Umrechnung im Blatt „Rohstoffe“
    for r in range(2, FORMULA_ROWS + 2):
        match = f"MATCH(E{r},Rohstoffe!$B:$B,0)"
        ws_l.cell(row=r, column=9, value=(
            f'=IF(G{r}="","",IF(OR(H{r}="g",H{r}=""),1,IF(H{r}="kg",1000,'
            f'IFERROR(IF(INDEX(Rohstoffe!$I:$I,{match})=H{r},INDEX(Rohstoffe!$J:$J,{match}),""),""))))'))
        ws_l.cell(row=r, column=10, value=f'=IF(OR(G{r}="",I{r}=""),"",ROUND(G{r}*I{r},0))')
        ws_l.cell(row=r, column=9).number_format = "0.00"
    ws_p = _sheet(wb, "Stückgewichte", PIECES, SAMPLE_PIECES, [10, 22, 11, 11, 40], muster)
    ws_b = _sheet(wb, "Chargengrößen", BATCHES, SAMPLE_BATCHES, [10, 22, 14, 14, 26, 11, 14, 40], muster)
    ws_rm = _sheet(wb, "Rohstoffe", RAW, SAMPLE_RAW, [9, 26, 14, 14, 14, 14, 14, 16, 18, 14, 14, 60], muster)
    from openpyxl.comments import Comment
    for column in (9, 10):
        comment = Comment(CONVERSION_NOTE, "HA-Rezeptbuch")
        comment.width, comment.height = 360, 160
        ws_rm.cell(row=1, column=column).comment = comment

    end = FORMULA_ROWS + 1
    _validation(ws_r, '"Beginn,Ende"', f"H2:H{end}")
    _validation(ws_l, '"Rohstoff,Unterrezept"', f"D2:D{end}")
    _validation(ws_l, '"g,kg,ml,Stück,Maß"', f"H2:H{end}")
    _validation(ws_l, '"g,percent"', f"K2:K{end}")
    _validation(ws_l, '"*"', f"M2:M{end}")
    _validation(ws_b, '"Gewicht,Stück"', f"C2:C{end}")
    _validation(ws_rm, '"standard,flour"', f"D2:D{end}")
    _validation(ws_rm, '"g,percent"', f"F2:F{end}")
    _validation(ws_rm, '"0,1"', f"K2:K{end}")
    del ws_p  # nur der Vollständigkeit halber angelegt

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def file_name() -> str:
    return "mustervorlage_rezepte.xlsx"
