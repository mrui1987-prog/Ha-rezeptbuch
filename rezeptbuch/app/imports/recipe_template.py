"""Rezeptimport aus der Importvorlage .xlsx (Modul 05, Teil C3, docs/rezepte.md Abschnitt 6.2).

Gelesen werden die Blätter **Rohstoffe, Rezepte, Rezeptzeilen, Stückgewichte,
Chargengrößen**. Die Umrechnung von Stück, ml usw. steht seit 0.5.8 im Blatt **Rohstoffe**
(Spalten „Umrechnung Einheit“ und „Gramm je Einheit“, C3-E7); ein altes Blatt **Umrechnung**
wird weiter gelesen (Hinweis „veraltet“, E7a; ToDo Modul 14: entfernen). Spalten werden über die
Überschrift erkannt; ein Zusatz in Klammern zählt nicht („Rezeptnummer (Vorschlag)“ =
„Rezeptnummer“). Spalten mit „(Formel)“ oder „(nicht importieren)“ werden nicht
ausgewertet, ebenso Bemerkungen.

Ablauf (alles oder nichts, M05-11):

1. **Rohstoffe** genau wie der CSV-Import (``raw_materials_csv.apply_rows``): Zuordnung über
   Nummer, sonst Name; vorhandene werden überschrieben (Bestätigung), neue mit leerer
   Toleranz erhalten 0 % (K05-2, M05-13).
2. **Rezepte** je Import-ID. Neue Rezepte starten gesperrt (M05-12). Ein **vorhandenes Rezept**
   (gleiche Nummer, sonst gleicher Name) bekommt auf Bestätigung eine **neue Version**; die bisherige
   wird zur alten Version „old (n)“ (C3-E5, Wunsch Michael 17.11.2026). Gleicher Inhalt = unverändert.
   Archivierte Rezepte werden nicht verändert (Fehler). Gruppe: vorhandene verwenden, sonst anlegen (M05-9).
3. **Rezeptzeilen:** Rohstoff über „Zutat“ (Name), Unterrezept über „Unterrezept Import-ID“
   (nur innerhalb der Datei). **Menge g rechnet der Import selbst** aus Menge Original ×
   Faktor (g = 1, kg = 1 000, sonst Umrechnung des Rohstoffs aus dem Blatt „Rohstoffe“, ml ↔ l
   automatisch × 1 000; ersatzweise altes Blatt „Umrechnung“ nach „Einheit + Zutat“), kaufmännisch
   gerundet (K05-6). Leere Menge = 0 g Handzugabe. „Prüfen“ = „*“ → Prüfmarkierung; **jede
   umgerechnete Zeile bekommt automatisch „*“** (C3-E7). Die Umrechnungen stehen im Bericht
   gesondert unter ``conversions`` (Übersicht vorab, E7d).
4. **Stückgewichte** und 5. **Chargengrößen** je Import-ID.

**Musterdaten** der Mustervorlage (C3-E2) werden übersprungen (C3-E11): die Musterrezepte und
Musterrohstoffe, erkannt an der festen Namensliste in ``exports/sample_template.py``, samt ihren
Zeilen, Stückgewichten und Chargengrößen. Mit ``include_samples`` werden sie wie früher importiert
(zum Ausprobieren der Mustervorlage).

Probelauf und Import führen dieselben Schritte in einer Transaktion aus; der Probelauf
rollt zurück. Alle Regeln prüft die Service-Schicht (keine zweite Regelprüfung).
"""

from __future__ import annotations

import io
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..errors import ConflictError, PayloadTooLargeError, ServiceError, ValidationError
from ..exports.sample_template import SAMPLE_RAW_NAMES, SAMPLE_RECIPE_NAMES
from ..raw_materials import service as rm_service
from ..raw_materials.models import normalize_text
from ..recipes import groups as group_service
from ..recipes import service as recipe_service
from ..recipes.models import validate_batch_sizes, validate_piece_weights
from .raw_materials_csv import HEADERS as RM_HEADERS
from .raw_materials_csv import MAX_BYTES, SourceRow, apply_rows, cell_text
from .raw_materials_csv import _find_target as find_raw_material
from .raw_materials_csv import _parse_number as parse_raw_number
from .report import ImportReport

MAX_ROWS = 5000
MAX_UNPACKED = 100 * 1024 * 1024      # Schutz vor „gepackten Riesen“: entpackt höchstens 100 MB

SHEET_RAW = "Rohstoffe"
SHEET_RECIPES = "Rezepte"
SHEET_LINES = "Rezeptzeilen"
SHEET_PIECES = "Stückgewichte"
SHEET_BATCHES = "Chargengrößen"
SHEET_UNITS = "Umrechnung"

# Überschrift (ohne Klammerzusatz, ohne Groß-/Kleinschreibung) → Feld; None = bekannt, nicht ausgewertet
RECIPE_COLUMNS = {
    "import-id": "import_id", "rezeptnummer": "number", "rezeptname": "name", "rezeptgruppe": "group",
    "knetzeit langsam": "knead_slow", "knetzeit schnell": "knead_fast", "hinweistext": "note",
    "hinweis anzeigen": "note_display", "notiz intern": "internal_note",
    "prüfen": None, "bemerkung": None, "status": None, "version": None,
}
LINE_COLUMNS = {
    "import-id": "import_id", "position": "position", "schritt": "step", "zeilenart": "kind",
    "zutat": "ingredient", "unterrezept import-id": "sub_id", "menge original": "amount",
    "einheit original": "unit", "toleranzeinheit": "tol_unit", "toleranzwert": "tol_value",
    "prüfen": "review", "bemerkung / prüfgrund": None, "bemerkung": None,
}
PIECE_COLUMNS = {
    "import-id": "import_id", "bezeichnung": "label", "gewicht g": "weight", "reihenfolge": "order",
    "prüfen": None, "bemerkung": None,
}
BATCH_COLUMNS = {
    "import-id": "import_id", "bezeichnung": "label", "art": "kind", "wert": "value",
    "stückgewicht-bezeichnung": "piece_label", "reihenfolge": "order", "obergrenze": "is_limit",
    "prüfen": None, "bemerkung": None,
}
UNIT_COLUMNS = {"schlüssel": "key", "gramm je einheit": "factor", "bemerkung": None}
# Umrechnung im Blatt „Rohstoffe“ (C3-E7); wird nicht gespeichert, nur für den Import verwendet (M02-2)
CONVERSION_COLUMNS = {"umrechnung einheit": "conv_unit", "gramm je einheit": "conv_factor"}
CONV_TITLES = {"conv_unit": "Umrechnung Einheit", "conv_factor": "Gramm je Einheit"}

COLUMN_TITLES = {
    SHEET_RECIPES: {"import_id": "Import-ID", "number": "Rezeptnummer", "name": "Rezeptname",
                    "group": "Rezeptgruppe", "knead_slow": "Knetzeit langsam", "knead_fast": "Knetzeit schnell",
                    "note": "Hinweistext", "note_display": "Hinweis anzeigen", "internal_note": "Notiz intern"},
    SHEET_LINES: {"import_id": "Import-ID", "position": "Position", "step": "Schritt", "kind": "Zeilenart",
                  "ingredient": "Zutat", "sub_id": "Unterrezept Import-ID", "amount": "Menge Original",
                  "unit": "Einheit Original", "tol_unit": "Toleranzeinheit", "tol_value": "Toleranzwert",
                  "review": "Prüfen"},
    SHEET_PIECES: {"label": "Bezeichnung", "weight": "Gewicht g", "order": "Reihenfolge"},
    SHEET_BATCHES: {"label": "Bezeichnung", "kind": "Art", "value": "Wert", "piece_label": "Stückgewicht-Bezeichnung",
                    "order": "Reihenfolge", "is_limit": "Obergrenze"},
}

NOTE_DISPLAY_VALUES = {
    "beginn": "start", "anfang": "start", "start": "start", "am anfang und am ende": "start",
    "ende": "end", "end": "end", "nur am ende": "end",
}
KIND_VALUES = {"rohstoff": "raw_material", "raw_material": "raw_material",
               "unterrezept": "sub_recipe", "sub_recipe": "sub_recipe"}
BATCH_KIND_VALUES = {"gewicht": "weight", "weight": "weight", "stück": "pieces", "stueck": "pieces",
                     "pieces": "pieces", "stückzahl": "pieces"}
TOL_UNIT_VALUES = {"g": "g", "%": "percent", "percent": "percent", "prozent": "percent"}
REVIEW_VALUES = {"*", "x", "ja", "1"}
# Spalte „Obergrenze“ im Blatt Chargengrößen (V06-2, seit 0.6.2): ja = aktiv, leer/nein = nicht aktiv
LIMIT_VALUES = {"ja": True, "x": True, "1": True, "aktiv": True, "nein": False, "0": False}
FIXED_FACTORS = {"g": Decimal(1), "kg": Decimal(1000)}
# ml ↔ l: ist der Faktor für die eine Einheit bekannt, ergibt sich die andere (E7c)
RELATED_UNITS = {"l": ("ml", Decimal(1000)), "ml": ("l", Decimal(1) / Decimal(1000))}

_PAREN = re.compile(r"\s*\([^)]*\)")


def header_key(text) -> str:
    """Überschrift ohne Klammerzusätze, Leerzeichen zusammengezogen, ohne Groß-/Kleinschreibung."""
    return normalize_text(_PAREN.sub("", str(text or ""))).casefold()


def _skipped_header(text: str) -> bool:
    low = str(text or "").casefold()
    return "(formel)" in low or "(nicht importieren)" in low


# -- Lesen der Datei ---------------------------------------------------------------

@dataclass
class Row:
    """Eine Datenzeile eines Blatts: Excel-Zeilennummer, Werte je Feld, Felder mit Formel."""

    line: int
    values: dict = field(default_factory=dict)
    formulas: set = field(default_factory=set)
    cached_grams: object = None        # gespeicherter Wert der Spalte „Menge g (Formel)“

    def text(self, key: str) -> str:
        return cell_text(self.values.get(key))

    def raw(self, key: str):
        return self.values.get(key)


@dataclass
class Sheet:
    name: str
    rows: list[Row]
    columns: set[str]


def _check_package(data: bytes) -> None:
    if len(data) > MAX_BYTES:
        raise PayloadTooLargeError("Die Datei ist zu groß (höchstens 5 MB).", code="file_too_large")
    if not data.strip():
        raise ValidationError("Die Datei ist leer.", code="empty_file")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            names = set(package.namelist())
            unpacked = sum(info.file_size for info in package.infolist())
    except zipfile.BadZipFile:
        raise ValidationError("Datei kann nicht gelesen werden. Erwartet wird eine Excel-Datei (.xlsx).",
                              code="unreadable_file") from None
    if "xl/workbook.bin" in names:
        raise ValidationError("Die Datei ist im Format .xlsb gespeichert. Bitte in Excel als "
                              "„Excel-Arbeitsmappe (.xlsx)“ speichern.", code="unreadable_file")
    if "xl/workbook.xml" not in names:
        raise ValidationError("Datei kann nicht gelesen werden. Erwartet wird eine Excel-Datei (.xlsx).",
                              code="unreadable_file")
    if unpacked > MAX_UNPACKED:
        raise PayloadTooLargeError("Die Datei ist entpackt zu groß.", code="file_too_large")


def _load(data: bytes):
    """Lädt die Mappe zweimal: mit gespeicherten Werten und mit Formeln (Erkennung von Formelzellen)."""
    import openpyxl    # erst hier, damit der Rest des Servers ohne die Bibliothek startet

    _check_package(data)
    try:
        values = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        formulas = openpyxl.load_workbook(io.BytesIO(data), data_only=False, read_only=True)
    except Exception as exc:     # beschädigte Datei: openpyxl meldet viele verschiedene Fehler
        raise ValidationError(f"Datei kann nicht gelesen werden ({type(exc).__name__}).",
                              code="unreadable_file") from None
    return values, formulas


def _find_sheet(workbook, name: str):
    for title in workbook.sheetnames:
        if normalize_text(title).casefold() == name.casefold():
            return workbook[title]
    return None


def _read_sheet(values_wb, formulas_wb, name: str, columns: dict, report: ImportReport,
                *, required: bool) -> Sheet | None:
    ws = _find_sheet(values_wb, name)
    if ws is None:
        if required:
            report.error(f"Das Blatt „{name}“ fehlt.", sheet=name)
        return None
    wf = _find_sheet(formulas_wb, name)
    value_rows = ws.iter_rows(values_only=True)
    formula_rows = wf.iter_rows()
    header = next(value_rows, None) or ()
    next(formula_rows, None)

    targets: list[str | None] = []
    found: set[str] = set()
    for title in header:
        key = header_key(title)
        if not key:
            targets.append(None)
            continue
        if _skipped_header(title):
            # „Menge g (Formel)“: gespeicherter Wert nur für den Vergleich (Hinweis, K05-6)
            targets.append("__cached_grams" if name == SHEET_LINES and key == "menge g" else None)
            continue
        if key not in columns:
            targets.append(None)
            report.hint(f"Spalte „{normalize_text(str(title))}“ wird nicht ausgewertet.", sheet=name)
            continue
        target = columns[key]
        if target is not None and target in found:
            report.error(f"Die Spalte „{normalize_text(str(title))}“ kommt doppelt vor.", sheet=name)
            target = None
        if target is not None:
            found.add(target)
        targets.append(target)

    rows: list[Row] = []
    for line, (vals, cells) in enumerate(zip(value_rows, formula_rows), start=2):
        row = Row(line=line)
        for index, target in enumerate(targets):
            if target is None or index >= len(vals):
                continue
            value = vals[index]
            if isinstance(value, str):
                value = value.strip() or None
            if target == "__cached_grams":
                row.cached_grams = value
                continue
            row.values[target] = value
            cell = cells[index] if index < len(cells) else None
            if cell is not None and getattr(cell, "data_type", None) == "f":
                row.formulas.add(target)
        if not any(v is not None for v in row.values.values()):
            continue                    # leere Zeile
        if _note_row(vals):
            report.hint("Zeile wird als Anmerkung übersprungen.", line=line, sheet=name)
            continue
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise ValidationError(f"Das Blatt „{name}“ hat mehr als {MAX_ROWS} Zeilen.", code="too_many_rows")
    return Sheet(name=name, rows=rows, columns=found)


def _note_row(values) -> bool:
    """Anmerkung unter einer Tabelle: nur die erste Zelle gefüllt, mit einem Satz (z. B. Fußnote der Vorlage)."""
    filled = [i for i, v in enumerate(values) if v is not None and str(v).strip()]
    return filled == [0] and isinstance(values[0], str) and len(values[0].split()) >= 4


@dataclass
class Conversion:
    """Umrechnung eines Rohstoffs aus dem Blatt „Rohstoffe“ (C3-E7)."""

    line: int
    name: str
    number: str
    unit: str            # wie eingegeben
    factor: Decimal
    only: bool           # Zeile enthält außer Nummer/Name nur die Umrechnung (E7b)
    row: SourceRow


def _raw_material_rows(values_wb, report: ImportReport, *, include_samples: bool = False
                       ) -> tuple[list[SourceRow] | None, list[Conversion]]:
    """Blatt „Rohstoffe“ → Zeilen wie beim CSV-Import (gleiche Spalten wie der CSV-Export) und Umrechnungen.

    Die Spalten „Umrechnung Einheit“ und „Gramm je Einheit“ gehen nicht an den Rohstoff-Import,
    sondern nur in die Umrechnung der Rezeptzeilen. Musterrohstoffe werden übersprungen (C3-E11).
    """
    ws = _find_sheet(values_wb, SHEET_RAW)
    if ws is None:
        return None, []
    iterator = ws.iter_rows(values_only=True)
    header = next(iterator, None) or ()
    targets: list[str | None] = []
    seen: set[str] = set()
    for title in header:
        key = header_key(title)
        if key in CONVERSION_COLUMNS and not _skipped_header(title):
            target = CONVERSION_COLUMNS[key]
        else:
            target = RM_HEADERS.get(key, "?") if key and not _skipped_header(title) else None
        if target == "?":
            report.hint(f"Spalte „{normalize_text(str(title))}“ wird nicht ausgewertet.", sheet=SHEET_RAW)
            target = None
        if target is not None and target in seen:
            report.error(f"Die Spalte „{normalize_text(str(title))}“ kommt doppelt vor.", sheet=SHEET_RAW)
            target = None
        if target is not None:
            seen.add(target)
        targets.append(target)
    if "name" not in seen:
        report.error("Spalte „Name“ fehlt.", sheet=SHEET_RAW)
        return [], []
    rows: list[SourceRow] = []
    conversions: list[Conversion] = []
    for line, vals in enumerate(iterator, start=2):
        values = {}
        conv_raw = {}
        for index, target in enumerate(targets):
            if target is None:
                continue
            cell = vals[index] if index < len(vals) else None
            if target in CONV_TITLES:
                conv_raw[target] = cell
            else:
                values[target] = cell_text(cell)
        if not any(values.values()) and not any(cell_text(v) for v in conv_raw.values()):
            continue
        if _note_row(vals):
            report.hint("Zeile wird als Anmerkung übersprungen.", line=line, sheet=SHEET_RAW)
            continue
        if not include_samples and _key(values.get("name", "")) in SAMPLE_RAW_KEYS:
            report.samples_raw_materials += 1
            continue
        row = SourceRow(line=line, values=values)
        rows.append(row)
        conversion = _conversion(row, conv_raw, report)
        if conversion is not None:
            conversions.append(conversion)
        if len(rows) > MAX_ROWS:
            raise ValidationError(f"Das Blatt „{SHEET_RAW}“ hat mehr als {MAX_ROWS} Zeilen.", code="too_many_rows")
    return rows, conversions


def _conversion(row: SourceRow, conv_raw: dict, report: ImportReport) -> Conversion | None:
    """Prüft „Umrechnung Einheit“ und „Gramm je Einheit“ einer Rohstoffzeile."""
    unit = cell_text(conv_raw.get("conv_unit"))
    factor_cell = conv_raw.get("conv_factor")
    if not unit and not cell_text(factor_cell):
        return None
    try:
        factor = _decimal(factor_cell)
    except ValueError:
        report.error("Gramm je Einheit muss eine Zahl sein.", line=row.line, sheet=SHEET_RAW,
                     column="Gramm je Einheit")
        return None
    if not unit:
        report.error("Umrechnung Einheit fehlt (z. B. „Stück“).", line=row.line, sheet=SHEET_RAW,
                     column="Umrechnung Einheit")
        return None
    if factor is None:
        report.error(f"Gramm je Einheit fehlt für „{unit}“.", line=row.line, sheet=SHEET_RAW,
                     column="Gramm je Einheit")
        return None
    if factor <= 0:
        report.error("Gramm je Einheit muss größer 0 sein.", line=row.line, sheet=SHEET_RAW,
                     column="Gramm je Einheit")
        return None
    if _key(unit) in FIXED_FACTORS:
        report.hint(f"Umrechnung für „{unit}“ ist nicht nötig (g und kg rechnet der Import selbst) und wird "
                    "nicht verwendet.", line=row.line, sheet=SHEET_RAW)
        return None
    only = not any(text for key, text in row.values.items() if key not in ("name", "number"))
    return Conversion(line=row.line, name=row.get("name"), number=row.get("number"), unit=unit, factor=factor,
                      only=only, row=row)


SAMPLE_RAW_KEYS = {normalize_text(n).casefold() for n in SAMPLE_RAW_NAMES}
SAMPLE_RECIPE_KEYS = {normalize_text(n).casefold() for n in SAMPLE_RECIPE_NAMES}


# -- Werte ----------------------------------------------------------------------

def _decimal(value) -> Decimal | None:
    """Zahl aus Zelle (Zahl oder Text mit Komma/Punkt); leer = None; sonst ValueError."""
    if value is None or isinstance(value, bool):
        if isinstance(value, bool):
            raise ValueError
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", text):     # 1.250,5 (deutsche Tausenderpunkte)
        text = text.replace(".", "")
    text = text.replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ValueError from None
    if not number.is_finite():
        raise ValueError
    return number


def _whole(value) -> int | None:
    """Ganze Zahl ≥ 0 oder None; sonst ValueError."""
    number = _decimal(value)
    if number is None:
        return None
    if number < 0 or number != number.to_integral_value():
        raise ValueError
    return int(number)


def _key(text: str) -> str:
    return normalize_text(text or "").casefold()


# -- Planung (ohne Datenbank) -------------------------------------------------------

@dataclass
class PlannedRecipe:
    import_id: str
    line: int
    number: int | None
    name: str
    group: str | None
    data: dict
    lines: list[dict] = field(default_factory=list)      # je Zeile: Eingabe + Fundstelle
    pieces: list[dict] = field(default_factory=list)
    batches: list[dict] = field(default_factory=list)
    broken: bool = False
    existing_id: int | None = None            # vorhandenes Rezept → neue Version statt Anlegen
    # beim Anlegen gefüllt (Reihenfolge wie an die Service-Schicht übergeben, für Fundstellen)
    sorted_lines: list[dict] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    sorted_pieces: list[dict] = field(default_factory=list)
    sorted_batches: list[dict] = field(default_factory=list)


class _Errors:
    """Fehler sammeln mit Blatt, Zeile, Spalte."""

    def __init__(self, report: ImportReport):
        self.report = report

    def add(self, sheet: str, line: int | None, column_key: str | None, message: str) -> None:
        column = COLUMN_TITLES.get(sheet, {}).get(column_key or "", None)
        self.report.error(message, line=line, column=column, sheet=sheet)


def _units(sheet: Sheet | None, report: ImportReport) -> dict[str, Decimal | None]:
    """Blatt „Umrechnung“: „Einheit + Zutat“ → Gramm je Einheit (leer = fehlt)."""
    result: dict[str, Decimal | None] = {}
    if sheet is None:
        return result
    for row in sheet.rows:
        key = _key(row.text("key"))
        if not key:
            continue
        try:
            factor = _decimal(row.raw("factor"))
        except ValueError:
            report.error("Gramm je Einheit muss eine Zahl sein.", line=row.line, sheet=SHEET_UNITS,
                         column="Gramm je Einheit")
            factor = None
        if factor is not None and factor <= 0:
            report.error("Gramm je Einheit muss größer 0 sein.", line=row.line, sheet=SHEET_UNITS,
                         column="Gramm je Einheit")
            factor = None
        result[key] = factor
    return result


@dataclass
class Factors:
    """Umrechnungsfaktoren für den Import: Blatt „Rohstoffe“ (je Rohstoff) und altes Blatt „Umrechnung“."""

    by_material: dict[str, tuple[str, Decimal]] = field(default_factory=dict)   # Name-Schlüssel → (Einheit, g)
    old_sheet: dict[str, Decimal | None] = field(default_factory=dict)          # „einheit zutat“ → g

    def lookup(self, unit_key: str, ingredient: str) -> tuple[Decimal | None, str | None, bool]:
        """(Faktor, Quelle, im alten Blatt ohne Wert). Quelle „Rohstoffe“ oder „Umrechnung“."""
        entry = self.by_material.get(rm_service.name_key(ingredient))
        if entry is not None:
            factor = _with_related(unit_key, {entry[0]: entry[1]})
            if factor is not None:
                return factor, SHEET_RAW, False
        old = {}
        for key in (unit_key, RELATED_UNITS.get(unit_key, (None,))[0]):
            if key is not None:
                lookup = f"{key} {_key(ingredient)}".strip()
                if lookup in self.old_sheet:
                    old[key] = self.old_sheet[lookup]
        factor = _with_related(unit_key, {k: v for k, v in old.items() if v is not None})
        if factor is not None:
            return factor, SHEET_UNITS, False
        return None, None, unit_key in old and old[unit_key] is None


def _with_related(unit_key: str, factors: dict[str, Decimal]) -> Decimal | None:
    """Faktor für die Einheit, sonst über ml ↔ l (× 1 000 bzw. ÷ 1 000, E7c)."""
    if unit_key in factors:
        return factors[unit_key]
    related = RELATED_UNITS.get(unit_key)
    if related and related[0] in factors:
        return factors[related[0]] * related[1]
    return None


def _number_text(value: Decimal) -> str:
    """Zahl für den Bericht: ohne unnötige Nullen, Komma als Dezimalzeichen, Tausender mit Leerzeichen."""
    text = format(value.normalize(), "f")
    whole, _, frac = text.partition(".")
    whole = f"{int(whole):,}".replace(",", " ") if whole.lstrip("-").isdigit() else whole
    return whole + ("," + frac if frac else "")


def _plan_recipes(sheet: Sheet, err: _Errors, report: ImportReport, ignored: set[str],
                  include_samples: bool = False) -> dict[str, PlannedRecipe]:
    planned: dict[str, PlannedRecipe] = {}
    names: dict[str, int] = {}
    numbers: dict[int, int] = {}
    for row in sheet.rows:
        import_id = row.text("import_id")
        if not import_id:
            err.add(SHEET_RECIPES, row.line, "import_id", "Import-ID fehlt.")
            continue
        key = import_id.casefold()
        if not include_samples and _key(row.text("name")) in SAMPLE_RECIPE_KEYS:
            ignored.add(key)                    # Musterrezept der Mustervorlage (C3-E11)
            report.samples_recipes += 1
            continue
        if key in planned:
            err.add(SHEET_RECIPES, row.line, "import_id",
                    f"Import-ID „{import_id}“ steht mehrfach (auch Zeile {planned[key].line}).")
            continue
        broken = False
        number = None
        try:
            number = _whole(row.raw("number"))
            if number == 0:
                raise ValueError
        except ValueError:
            err.add(SHEET_RECIPES, row.line, "number", "Rezeptnummer muss eine ganze Zahl größer 0 sein.")
            broken = True
        if number is not None:
            if number in numbers:
                err.add(SHEET_RECIPES, row.line, "number",
                        f"Rezeptnummer {number} steht mehrfach in der Datei (auch Zeile {numbers[number]}).")
                broken = True
            numbers.setdefault(number, row.line)
        name = row.text("name")
        if name:
            if _key(name) in names:
                err.add(SHEET_RECIPES, row.line, "name",
                        f"Rezeptname „{name}“ steht mehrfach in der Datei (auch Zeile {names[_key(name)]}).")
                broken = True
            names.setdefault(_key(name), row.line)
        knead = {}
        for field_key, target in (("knead_slow", "knead_slow_min"), ("knead_fast", "knead_fast_min")):
            try:
                knead[target] = _whole(row.raw(field_key))
            except ValueError:
                err.add(SHEET_RECIPES, row.line, field_key, "Knetzeit muss eine ganze Zahl (Minuten) sein.")
                broken = True
        display_text = _key(row.text("note_display"))
        note_display = NOTE_DISPLAY_VALUES.get(display_text) if display_text else "end"
        if note_display is None:
            err.add(SHEET_RECIPES, row.line, "note_display", "„Hinweis anzeigen“ muss „Beginn“ oder „Ende“ sein.")
            broken = True
        note = row.raw("note")
        internal = row.raw("internal_note")
        data = {
            "number": number,
            "name": name,
            **knead,
            "note": str(note) if note is not None else None,
            "note_display": note_display or "end",
            "internal_note": str(internal) if internal is not None else None,
        }
        group = row.text("group") or None
        planned[key] = PlannedRecipe(import_id=import_id, line=row.line, number=number, name=name,
                                     group=group, data=data, broken=broken)
    return planned


def _plan_lines(sheet: Sheet, planned: dict[str, PlannedRecipe], factors: Factors, err: _Errors,
                report: ImportReport, ignored: set[str]) -> None:
    for order, row in enumerate(sheet.rows):
        import_id = row.text("import_id")
        if import_id and import_id.casefold() in ignored:
            continue
        recipe = planned.get(import_id.casefold()) if import_id else None
        if recipe is None:
            err.add(SHEET_LINES, row.line, "import_id",
                    f"Import-ID „{import_id}“ gibt es im Blatt „Rezepte“ nicht." if import_id else "Import-ID fehlt.")
            continue
        ok = True
        ingredient = row.text("ingredient")
        sub_id = row.text("sub_id")
        kind_text = _key(row.text("kind"))
        kind = KIND_VALUES.get(kind_text) if kind_text else ("sub_recipe" if sub_id and not ingredient else "raw_material")
        if kind is None:
            err.add(SHEET_LINES, row.line, "kind", "Zeilenart muss „Rohstoff“ oder „Unterrezept“ sein.")
            ok = False
        if kind == "raw_material" and not ingredient:
            err.add(SHEET_LINES, row.line, "ingredient", "Zutat fehlt.")
            ok = False
        if kind == "sub_recipe" and not sub_id:
            err.add(SHEET_LINES, row.line, "sub_id", "Unterrezept Import-ID fehlt.")
            ok = False

        position = None
        try:
            position = _whole(row.raw("position"))
        except ValueError:
            err.add(SHEET_LINES, row.line, "position", "Position muss eine ganze Zahl sein.")
            ok = False

        # Menge g = Menge Original × Faktor, kaufmännisch gerundet (K05-6)
        grams = None
        converted = False
        try:
            amount = _decimal(row.raw("amount"))
        except ValueError:
            err.add(SHEET_LINES, row.line, "amount", "Menge Original muss eine Zahl sein.")
            amount, ok = None, False
        else:
            if amount is not None and amount < 0:
                err.add(SHEET_LINES, row.line, "amount", "Menge Original darf nicht negativ sein.")
                ok = False
            unit = _key(row.text("unit")) or "g"
            if amount is None:
                grams = 0                                  # leere Menge = Handzugabe (M02-15)
            elif ok:
                factor = FIXED_FACTORS.get(unit)
                source = None
                if factor is None:
                    factor, source, empty = factors.lookup(unit, ingredient or "")
                    if factor is None:
                        shown_unit = row.text("unit")
                        if empty:
                            message = (f"Umrechnung „{shown_unit} {ingredient}“ ohne Wert "
                                       "(Blatt „Umrechnung“, Gramm je Einheit).")
                        else:
                            message = (f"Umrechnung für „{shown_unit}“ bei „{ingredient}“ fehlt: im Blatt „Rohstoffe“ "
                                       f"beim Rohstoff „{ingredient}“ „Umrechnung Einheit“ = {shown_unit} und "
                                       "„Gramm je Einheit“ eintragen.")
                        err.add(SHEET_LINES, row.line, "unit", message)
                        ok = False
                if factor is not None:
                    grams = int((amount * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))
                    if source is not None:
                        converted = True        # jede Umrechnung bekommt „*“ (C3-E7)
                        report.conversions.append({
                            "sheet": SHEET_LINES, "line": row.line, "recipe": recipe.name or recipe.import_id,
                            "import_id": recipe.import_id, "ingredient": ingredient, "source": source,
                            "text": f"{_number_text(amount)} {row.text('unit')} × {_number_text(factor)} g = "
                                    f"{_number_text(Decimal(grams))} g",
                            "amount": float(amount), "unit": row.text("unit"), "factor": float(factor),
                            "grams": grams})
            if grams is not None and row.cached_grams is not None:
                try:
                    cached = _decimal(row.cached_grams)
                except ValueError:
                    cached = None
                if cached is not None and cached != grams:
                    report.hint(f"Menge g berechnet {grams} g, in der Datei stand {cell_text(row.cached_grams)} g. "
                                "Übernommen wird der berechnete Wert.", line=row.line, sheet=SHEET_LINES)

        tol_value_text = row.text("tol_value")
        tol_unit_text = _key(row.text("tol_unit"))
        tolerance = tolerance_unit = None
        if tol_value_text:
            tolerance_unit = TOL_UNIT_VALUES.get(tol_unit_text or "g")
            if tolerance_unit is None:
                err.add(SHEET_LINES, row.line, "tol_unit", "Toleranzeinheit muss „g“ oder „percent“ sein.")
                ok = False
            tolerance = tol_value_text
        elif tol_unit_text:
            err.add(SHEET_LINES, row.line, "tol_value", "Toleranzeinheit ohne Toleranzwert – bitte Wert angeben.")
            ok = False

        if not ok:
            recipe.broken = True
            continue
        recipe.lines.append({
            "line": row.line, "order": order, "position": position, "kind": kind,
            "ingredient": ingredient, "sub_id": sub_id, "amount_g": grams,
            "tolerance": tolerance, "tolerance_unit": tolerance_unit,
            "step": row.text("step") or None,
            "review": _key(row.text("review")) in REVIEW_VALUES or converted,
        })


def _plan_pieces(sheet: Sheet | None, planned: dict[str, PlannedRecipe], err: _Errors, ignored: set[str]) -> None:
    if sheet is None:
        return
    for order, row in enumerate(sheet.rows):
        import_id = row.text("import_id")
        if import_id and import_id.casefold() in ignored:
            continue
        recipe = planned.get(import_id.casefold()) if import_id else None
        if recipe is None:
            err.add(SHEET_PIECES, row.line, "import_id",
                    f"Import-ID „{import_id}“ gibt es im Blatt „Rezepte“ nicht." if import_id else "Import-ID fehlt.")
            continue
        try:
            sort = _whole(row.raw("order"))
            weight = _whole(row.raw("weight"))
        except ValueError:
            err.add(SHEET_PIECES, row.line, "weight", "Gewicht und Reihenfolge müssen ganze Zahlen sein.")
            recipe.broken = True
            continue
        recipe.pieces.append({"line": row.line, "sort": (sort if sort is not None else 10**9, order),
                              "label": row.text("label"), "weight_g": weight})


def _plan_batches(sheet: Sheet | None, planned: dict[str, PlannedRecipe], err: _Errors, ignored: set[str]) -> None:
    if sheet is None:
        return
    for order, row in enumerate(sheet.rows):
        import_id = row.text("import_id")
        if import_id and import_id.casefold() in ignored:
            continue
        recipe = planned.get(import_id.casefold()) if import_id else None
        if recipe is None:
            err.add(SHEET_BATCHES, row.line, "import_id",
                    f"Import-ID „{import_id}“ gibt es im Blatt „Rezepte“ nicht." if import_id else "Import-ID fehlt.")
            continue
        kind = BATCH_KIND_VALUES.get(_key(row.text("kind")))
        if kind is None:
            err.add(SHEET_BATCHES, row.line, "kind", "Art muss „Gewicht“ oder „Stück“ sein.")
            recipe.broken = True
            continue
        try:
            sort = _whole(row.raw("order"))
            # Art „Gewicht“: Formel oder leer = Gesamtgewicht des Rezepts (wird beim Anlegen eingesetzt)
            value = None if (kind == "weight" and "value" in row.formulas) else _whole(row.raw("value"))
        except ValueError:
            err.add(SHEET_BATCHES, row.line, "value", "Wert und Reihenfolge müssen ganze Zahlen sein.")
            recipe.broken = True
            continue
        is_limit = None                                  # Spalte fehlt: bisheriger Haken bleibt
        if "is_limit" in sheet.columns:
            text = _key(row.text("is_limit"))
            is_limit = LIMIT_VALUES.get(text, None) if text else False
            if is_limit is None:
                err.add(SHEET_BATCHES, row.line, "is_limit", "Obergrenze muss „ja“ oder leer sein.")
                recipe.broken = True
                continue
        recipe.batches.append({"line": row.line, "sort": (sort if sort is not None else 10**9, order),
                               "label": row.text("label"), "kind": kind, "value": value,
                               "piece_label": row.text("piece_label") or None, "is_limit": is_limit})


def _order(planned: dict[str, PlannedRecipe], err: _Errors, ignored: set[str] = frozenset()) -> list[PlannedRecipe]:
    """Reihenfolge zum Anlegen: Unterrezepte zuerst. Kreise und unbekannte Verweise sind Fehler (R05-10)."""
    edges: dict[str, list[tuple[str, int]]] = {}
    for key, recipe in planned.items():
        for line in recipe.lines:
            if line["kind"] != "sub_recipe":
                continue
            target = line["sub_id"].casefold()
            if target in ignored:
                err.add(SHEET_LINES, line["line"], "sub_id",
                        f"Unterrezept „{line['sub_id']}“ ist ein Musterrezept der Mustervorlage und wird nicht "
                        "importiert.")
                recipe.broken = True
                continue
            if target not in planned:
                err.add(SHEET_LINES, line["line"], "sub_id",
                        f"Unterrezept „{line['sub_id']}“ gibt es im Blatt „Rezepte“ nicht.")
                recipe.broken = True
                continue
            edges.setdefault(key, []).append((target, line["line"]))

    result: list[PlannedRecipe] = []
    state: dict[str, int] = {}          # 1 = in Arbeit, 2 = fertig
    reported: set[frozenset] = set()

    def visit(key: str, path: list[str]) -> None:
        if state.get(key) == 2:
            return
        if state.get(key) == 1:
            cycle = path[path.index(key):] + [key]
            ident = frozenset(cycle)
            if ident not in reported:
                reported.add(ident)
                names = " → ".join(planned[k].name or planned[k].import_id for k in cycle)
                first = planned[cycle[0]]
                err.add(SHEET_LINES, next((ln for t, ln in edges.get(cycle[0], []) if t == cycle[1]), None),
                        "sub_id", f"Kreis bei Unterrezepten: {names}")
                for k in cycle:
                    planned[k].broken = True
                first.broken = True
            return
        state[key] = 1
        for target, _line in edges.get(key, []):
            visit(target, [*path, key])
        state[key] = 2
        result.append(planned[key])

    for key in planned:
        visit(key, [])
    return result


# -- Anlegen -----------------------------------------------------------------------

def _locate(recipe: PlannedRecipe, exc: ServiceError) -> tuple[str, int | None, str | None]:
    """Fundstelle (Blatt, Zeile, Spalte) zu einer Meldung der Service-Schicht."""
    fld = exc.field or ""
    parts = fld.split(".")
    if parts[0] == "items" and len(parts) > 1 and parts[1].isdigit():
        index = int(parts[1]) - 1
        if 0 <= index < len(recipe.sorted_lines):
            sub = parts[2] if len(parts) > 2 else ""
            column = {"amount_g": "Menge Original", "tolerance": "Toleranzwert", "tolerance_unit": "Toleranzeinheit",
                      "raw_material_id": "Zutat", "sub_recipe_id": "Unterrezept Import-ID"}.get(sub)
            return SHEET_LINES, recipe.sorted_lines[index]["line"], column
    if parts[0] == "steps" and len(parts) > 1 and parts[1].isdigit():
        name = recipe.steps[int(parts[1]) - 1] if int(parts[1]) - 1 < len(recipe.steps) else None
        line = next((ln["line"] for ln in recipe.sorted_lines if ln["step"] == name), recipe.line)
        return SHEET_LINES, line, "Schritt"
    if parts[0] == "piece_weights" and len(parts) > 1 and parts[1].isdigit():
        index = int(parts[1]) - 1
        if 0 <= index < len(recipe.sorted_pieces):
            return SHEET_PIECES, recipe.sorted_pieces[index]["line"], "Bezeichnung"
    if parts[0] == "batch_sizes" and len(parts) > 1 and parts[1].isdigit():
        index = int(parts[1]) - 1
        if 0 <= index < len(recipe.sorted_batches):
            return SHEET_BATCHES, recipe.sorted_batches[index]["line"], None
    column = {"number": "Rezeptnummer", "name": "Rezeptname", "group_id": "Rezeptgruppe",
              "knead_slow_min": "Knetzeit langsam", "knead_fast_min": "Knetzeit schnell", "note": "Hinweistext",
              "internal_note": "Notiz intern"}.get(fld)
    return SHEET_RECIPES, recipe.line, column


def _raw_material_id(conn: sqlite3.Connection, name: str, kept: frozenset[int] = frozenset()) -> int:
    """Aktiver Rohstoff mit diesem Namen (ohne Groß-/Kleinschreibung), nach Schritt 1.

    ``kept``: archivierte Rohstoffe, die das vorhandene Rezept in seiner aktuellen Version schon verwendet;
    sie bleiben dort erlaubt (wie beim Speichern, R05-8), sonst wäre Export → Re-Import nicht möglich.
    """
    key = rm_service.name_key(name)
    archived = False
    kept_id = None
    for row in conn.execute("SELECT id, name, archived FROM raw_material"):
        if rm_service.name_key(row["name"]) == key:
            if not row["archived"]:
                return row["id"]
            archived = True
            if row["id"] in kept and kept_id is None:
                kept_id = row["id"]
    if kept_id is not None:
        return kept_id
    if archived:
        raise ValidationError(f"Der Rohstoff „{name}“ ist archiviert und kann nicht verwendet werden.",
                              field="items.0.raw_material_id", code="raw_material_archived")
    raise ValidationError(f"Den Rohstoff „{name}“ gibt es nicht. Bitte im Blatt „Rohstoffe“ ergänzen.",
                          field="items.0.raw_material_id", code="raw_material_missing")


def _group_id(conn: sqlite3.Connection, name: str | None, report: ImportReport) -> int | None:
    if not name:
        return None
    key = _key(name)
    for row in conn.execute("SELECT id, name FROM recipe_group"):
        if _key(row["name"]) == key:
            return row["id"]
    group_id = group_service.create_in_tx(conn, name, source="import")
    report.groups_created.append(normalize_text(name))
    return group_id


def _prepare(recipe: PlannedRecipe) -> None:
    recipe.sorted_lines = sorted(recipe.lines, key=lambda ln: (ln["position"] if ln["position"] is not None
                                                                else 10**9, ln["order"]))
    recipe.steps = []
    for line in recipe.sorted_lines:
        if line["step"] and line["step"] not in recipe.steps:
            recipe.steps.append(line["step"])        # Schritte in Reihenfolge des ersten Auftretens
    recipe.sorted_pieces = sorted(recipe.pieces, key=lambda p: p["sort"])
    recipe.sorted_batches = sorted(recipe.batches, key=lambda b: b["sort"])


def _items(conn: sqlite3.Connection, recipe: PlannedRecipe, created: dict[str, int]) -> list[dict]:
    items = []
    kept: frozenset[int] = frozenset()
    if recipe.existing_id is not None:
        kept = frozenset(r[0] for r in conn.execute(
            "SELECT i.raw_material_id FROM recipe r JOIN recipe_item i ON i.recipe_version_id = r.current_version_id "
            "WHERE r.id = ? AND i.raw_material_id IS NOT NULL", (recipe.existing_id,)))
    for index, line in enumerate(recipe.sorted_lines, start=1):
        item = {"type": line["kind"], "amount_g": line["amount_g"], "needs_review": line["review"],
                "step_no": recipe.steps.index(line["step"]) + 1 if line["step"] else None}
        if line["tolerance"] is not None:
            item["tolerance"] = line["tolerance"]
            item["tolerance_unit"] = line["tolerance_unit"]
        if line["kind"] == "raw_material":
            try:
                item["raw_material_id"] = _raw_material_id(conn, line["ingredient"], kept)
            except ValidationError as exc:
                exc.field = f"items.{index}.raw_material_id"
                raise
        else:
            item["sub_recipe_id"] = created[line["sub_id"].casefold()]
        items.append(item)
    return items


def _portions(conn: sqlite3.Connection, recipe: PlannedRecipe, recipe_id: int, items: list[dict]) -> None:
    """Stückgewichte und Chargengrößen aus der Datei. Bei einem vorhandenen Rezept werden gleich bezeichnete
    Einträge fortgeführt (Bezeichnung = Schlüssel); Rezepte ohne Einträge in der Datei bleiben unverändert."""
    if recipe.sorted_pieces:
        pieces = validate_piece_weights([{"label": p["label"], "weight_g": p["weight_g"]}
                                         for p in recipe.sorted_pieces])
        if recipe.existing_id is not None:
            old = {r["label"].casefold(): r["id"] for r in conn.execute(
                "SELECT id, label FROM recipe_piece_weight WHERE recipe_id = ?", (recipe_id,))}
            for p in pieces:
                p["id"] = old.get(p["label"].casefold())
        recipe_service.set_piece_weights_in_tx(conn, recipe_id, pieces, confirm_delete_batch_sizes=True,
                                               source="import")
    if recipe.sorted_batches:
        total = sum(i["amount_g"] for i in items)
        batches = validate_batch_sizes([{
            "label": b["label"], "kind": b["kind"],
            "value": b["value"] if b["value"] is not None or b["kind"] == "pieces" else total,
            "piece_weight_label": b["piece_label"], "is_limit": b["is_limit"]} for b in recipe.sorted_batches])
        if recipe.existing_id is not None:
            old = {r["label"].casefold(): r["id"] for r in conn.execute(
                "SELECT id, label FROM recipe_batch_size WHERE recipe_id = ?", (recipe_id,))}
            for b in batches:
                b["id"] = old.get(b["label"].casefold())
        recipe_service.set_batch_sizes_in_tx(conn, recipe_id, batches, source="import")


def _create(conn: sqlite3.Connection, recipe: PlannedRecipe, created: dict[str, int], report: ImportReport) -> None:
    _prepare(recipe)
    items = _items(conn, recipe, created)

    data = dict(recipe.data)
    data["group_id"] = _group_id(conn, recipe.group, report)
    data["steps"] = recipe.steps
    data["items"] = items
    recipe_id = recipe_service.create_in_tx(conn, data, source="import")
    _portions(conn, recipe, recipe_id, items)

    created[recipe.import_id.casefold()] = recipe_id
    info = recipe_service.get_recipe(conn, recipe_id)
    review = info["review_count"]
    report.recipes.append({"sheet": SHEET_RECIPES, "line": recipe.line, "import_id": recipe.import_id,
                           "number": info["number"], "name": info["name"], "lines": len(items),
                           "total_g": info["sums"]["total_g"], "review_count": review})
    if not items:
        report.hint(f"Rezept „{info['name']}“ hat keine Zeilen (Entwurf).", line=recipe.line, sheet=SHEET_RECIPES)


def _update(conn: sqlite3.Connection, recipe: PlannedRecipe, created: dict[str, int], report: ImportReport) -> None:
    """Vorhandenes Rezept: neue Version mit dem Inhalt der Datei; die bisherige bleibt als „old (n)“ (C3-E5)."""
    _prepare(recipe)
    recipe_id = recipe.existing_id
    before = recipe_service.get_recipe(conn, recipe_id)
    items = _items(conn, recipe, created)

    data = dict(recipe.data)
    data["number"] = before["number"]                    # Nummer ändert der Import nie
    data["group_id"] = _group_id(conn, recipe.group, report) if recipe.group else before["group_id"]
    if not (recipe.data.get("internal_note") or "").strip():
        data.pop("internal_note", None)                  # leere Notiz in der Datei löscht die vorhandene nicht
    data["steps"] = recipe.steps
    data["items"] = items
    row = conn.execute("SELECT revision FROM recipe WHERE id = ?", (recipe_id,)).fetchone()
    outcome = recipe_service.save_in_tx(conn, recipe_id, data, revision=row["revision"], version_mode="new",
                                        source="import")
    _portions(conn, recipe, recipe_id, items)

    created[recipe.import_id.casefold()] = recipe_id
    info = recipe_service.get_recipe(conn, recipe_id)
    action = "new_version" if outcome["result"] == "new_version" else "unchanged"
    entry = {"sheet": SHEET_RECIPES, "line": recipe.line, "import_id": recipe.import_id, "number": info["number"],
             "name": info["name"], "lines": len(items), "total_g": info["sums"]["total_g"],
             "review_count": info["review_count"], "action": action,
             "old_version": before["version_no"], "new_version": info["version_no"]}
    report.recipes_updated.append(entry)
    if action == "new_version" and info["review_count"] and not info["locked"]:
        recipe_service.lock_in_tx(conn, recipe_id, source="import")     # zu prüfende Zeilen: wie beim Anlegen sperren
        report.hint(f"Rezept „{info['name']}“ ist wegen „*“ gesperrt worden (bitte prüfen und freischalten).",
                    line=recipe.line, sheet=SHEET_RECIPES)
    if not items:
        report.hint(f"Rezept „{info['name']}“ hat keine Zeilen.", line=recipe.line, sheet=SHEET_RECIPES)


def _match_existing(conn: sqlite3.Connection, planned: dict[str, PlannedRecipe], err: _Errors,
                    report: ImportReport) -> None:
    """Ordnet Rezepte der Datei vorhandenen zu: Nummer, sonst Name (nicht archiviert)."""
    for recipe in planned.values():
        by_number = None
        if recipe.number is not None:
            by_number = conn.execute(
                "SELECT r.id, r.number, r.archived, v.name FROM recipe r JOIN recipe_version v "
                "ON v.id = r.current_version_id WHERE r.number = ?", (recipe.number,)).fetchone()
        by_name = recipe_service._find_active_with_name(conn, recipe.name) if recipe.name else None
        if by_number is not None:
            if by_number["archived"]:
                err.add(SHEET_RECIPES, recipe.line, "number",
                        f"Das Rezept Nr. {by_number['number']} „{by_number['name']}“ ist archiviert. "
                        "Bitte zuerst wiederherstellen.")
                recipe.broken = True
                continue
            if by_name is not None and by_name["id"] != by_number["id"]:
                err.add(SHEET_RECIPES, recipe.line, "name",
                        f"Nummer {recipe.number} gehört zu „{by_number['name']}“, der Name „{recipe.name}“ aber zu "
                        f"Rezept Nr. {by_name['number']}. Bitte eindeutig machen.")
                recipe.broken = True
                continue
            recipe.existing_id = by_number["id"]
        elif by_name is not None:
            recipe.existing_id = by_name["id"]
            if recipe.number is not None:
                report.hint(f"Rezept „{recipe.name}“: Nummer {recipe.number} aus der Datei wird nicht übernommen "
                            f"(vorhandenes Rezept hat Nummer {by_name['number']}).", line=recipe.line,
                            sheet=SHEET_RECIPES)


def _assign_numbers(conn: sqlite3.Connection, planned: dict) -> None:
    """Leere Rezeptnummern: nach der höchsten vorhandenen bzw. in der Datei genannten Nummer vergeben."""
    highest = conn.execute("SELECT COALESCE(MAX(number), 0) FROM recipe").fetchone()[0]
    highest = max([highest, *(r.number for r in planned.values() if r.number is not None)])
    for recipe in sorted(planned.values(), key=lambda r: r.line):
        if recipe.number is None and recipe.existing_id is None:
            highest += 1
            recipe.data["number"] = highest


def _apply_raw_materials(conn: sqlite3.Connection, raw_rows: list[SourceRow], conversions: list[Conversion],
                         report: ImportReport) -> Factors:
    """Schritt 1: Rohstoffe wie der CSV-Import; danach die Umrechnungen je Rohstoff (C3-E7)."""
    only_conversion = {c.line for c in conversions if c.only}
    apply_list = []
    for row in raw_rows:
        if row.line in only_conversion:
            # E7b: nur Name/Nummer + Umrechnung → vorhandenen Rohstoff nicht ändern (sonst würden leere Felder geleert)
            try:
                target = find_raw_material(conn, parse_raw_number(row), row.get("name"))
            except ServiceError:
                target = None
            if target is not None:
                report.unchanged += 1
                report.rows += 1
                continue
        apply_list.append(row)
    if apply_list:
        apply_rows(conn, apply_list, report, sheet=SHEET_RAW)

    factors = Factors()
    for conv in conversions:
        name = conv.name
        if not name and conv.number:
            found = conn.execute("SELECT name FROM raw_material WHERE number = ?", (conv.number,)).fetchone()
            name = found["name"] if found else ""
        if name:
            factors.by_material[rm_service.name_key(name)] = (_key(conv.unit), conv.factor)
    return factors


def apply_template(conn: sqlite3.Connection, values_wb, formulas_wb, report: ImportReport, *,
                   include_samples: bool = False) -> None:
    """Wendet die Vorlage an. Erwartet eine offene Transaktion; schreibt Fehler in den Bericht."""
    err = _Errors(report)

    # 1 Rohstoffe (wie CSV-Import) und Umrechnungen aus dem Blatt „Rohstoffe“
    raw_rows, conversions = _raw_material_rows(values_wb, report, include_samples=include_samples)
    factors = _apply_raw_materials(conn, raw_rows or [], conversions, report)

    # 2–5 Rezepte planen
    recipes_sheet = _read_sheet(values_wb, formulas_wb, SHEET_RECIPES, RECIPE_COLUMNS, report, required=True)
    lines_sheet = _read_sheet(values_wb, formulas_wb, SHEET_LINES, LINE_COLUMNS, report, required=True)
    pieces_sheet = _read_sheet(values_wb, formulas_wb, SHEET_PIECES, PIECE_COLUMNS, report, required=False)
    batches_sheet = _read_sheet(values_wb, formulas_wb, SHEET_BATCHES, BATCH_COLUMNS, report, required=False)
    units_sheet = _read_sheet(values_wb, formulas_wb, SHEET_UNITS, UNIT_COLUMNS, report, required=False)
    if recipes_sheet is None or lines_sheet is None:
        return
    for sheet, needed in ((recipes_sheet, ("import_id", "name")), (lines_sheet, ("import_id", "amount"))):
        for key in needed:
            if key not in sheet.columns:
                report.error(f"Spalte „{COLUMN_TITLES[sheet.name][key]}“ fehlt.", sheet=sheet.name)
                return

    factors.old_sheet = _units(units_sheet, report)
    if units_sheet is not None and units_sheet.rows:
        report.hint("Das Blatt „Umrechnung“ ist veraltet und wird nur noch übergangsweise gelesen. Bitte die "
                    "Umrechnung im Blatt „Rohstoffe“ eintragen (Spalten „Umrechnung Einheit“ und „Gramm je Einheit“).",
                    sheet=SHEET_UNITS)
    ignored: set[str] = set()
    planned = _plan_recipes(recipes_sheet, err, report, ignored, include_samples)
    _plan_lines(lines_sheet, planned, factors, err, report, ignored)
    _plan_pieces(pieces_sheet, planned, err, ignored)
    _plan_batches(batches_sheet, planned, err, ignored)
    ordered = _order(planned, err, ignored)
    _match_existing(conn, planned, err, report)
    _assign_numbers(conn, planned)
    report.rows += len(recipes_sheet.rows)

    created: dict[str, int] = {}
    failed: set[str] = set()
    for recipe in ordered:
        key = recipe.import_id.casefold()
        missing_sub = [ln["sub_id"] for ln in recipe.lines
                       if ln["kind"] == "sub_recipe" and ln["sub_id"].casefold() in failed]
        if recipe.broken or missing_sub:
            failed.add(key)
            if missing_sub and not recipe.broken:
                err.add(SHEET_RECIPES, recipe.line, None,
                        f"Rezept „{recipe.name or recipe.import_id}“ wird nicht angelegt: Unterrezept "
                        + ", ".join(f"„{s}“" for s in missing_sub) + " hat Fehler.")
            continue
        conn.execute("SAVEPOINT import_recipe")
        try:
            if recipe.existing_id is not None:
                _update(conn, recipe, created, report)
            else:
                _create(conn, recipe, created, report)
        except ServiceError as exc:
            conn.execute("ROLLBACK TO import_recipe")
            failed.add(key)
            sheet, line, column = _locate(recipe, exc)
            prefix = "" if sheet == SHEET_RECIPES else f"Rezept {recipe.import_id}: "
            report.error(prefix + exc.message, line=line, column=column, sheet=sheet)
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK TO import_recipe")
            failed.add(key)
            report.error(f"Konnte nicht gespeichert werden: {exc}", line=recipe.line, sheet=SHEET_RECIPES)
        finally:
            conn.execute("RELEASE import_recipe")

    review = sum(r["review_count"] for r in report.recipes)
    if review:
        n = sum(1 for r in report.recipes if r["review_count"])
        report.hint(f"{review} Zeile{'n' if review != 1 else ''} mit „*“ in {n} Rezept{'en' if n != 1 else ''}: "
                    "bitte nach dem Import prüfen. Importierte Rezepte sind gesperrt.")
    if report.conversions:
        n = len(report.conversions)
        report.hint(f"{n} Zeile{'n' if n != 1 else ''} umgerechnet (Stück, ml …); jede umgerechnete Zeile hat „*“ "
                    "zum Prüfen. Liste: „Umrechnungen anzeigen“.")
    if report.samples_recipes or report.samples_raw_materials:
        r, m = report.samples_recipes, report.samples_raw_materials
        report.hint(f"Musterdaten der Mustervorlage ignoriert: {r} Musterrezept{'e' if r != 1 else ''} und "
                    f"{m} Musterrohstoff{'e' if m != 1 else ''}.")
        if report.nothing_to_import and not planned and not raw_rows:
            report.hint("Die Datei enthält nur Musterdaten – es gibt nichts zu importieren.")


def import_recipe_template(conn: sqlite3.Connection, data: bytes, *, mode: str = "check",
                           confirm_overwrite: bool = False, include_samples: bool = False) -> dict:
    """Probelauf (``mode="check"``) oder Import (``mode="run"``) der Importvorlage.

    Wie der Rohstoff-Import: Probelauf liefert immer den Bericht und ändert nichts. Der
    Import speichert nur ohne Fehler und – wenn vorhandene Rohstoffe überschrieben werden –
    mit ``confirm_overwrite``. Sonst wird nichts gespeichert und ein Fehler mit Bericht ausgelöst.
    ``include_samples``: Musterdaten der Mustervorlage mit importieren (sonst übersprungen, C3-E11).
    """
    if mode not in ("check", "run"):
        raise ValidationError("mode muss „check“ oder „run“ sein.", field="mode")
    values_wb, formulas_wb = _load(data)
    report = ImportReport(mode, "recipes")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            apply_template(conn, values_wb, formulas_wb, report, include_samples=include_samples)
            commit = mode == "run" and report.ok and (confirm_overwrite or not report.needs_confirmation)
            if commit:
                conn.execute("COMMIT")
                report.imported = True
            else:
                conn.execute("ROLLBACK")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        values_wb.close()
        formulas_wb.close()

    if mode == "run" and not report.ok:
        raise ValidationError(report.summary(), code="import_failed", report=report.to_dict())
    if mode == "run" and not report.imported:
        n = report.overwritten
        v = sum(1 for r in report.recipes_updated if r["action"] == "new_version")
        parts = []
        if n:
            parts.append(f"{n} Rohstoff{'e werden' if n != 1 else ' wird'} überschrieben")
        if v:
            parts.append(f"{v} vorhandene{'s Rezept bekommt' if v == 1 else ' Rezepte bekommen'} eine neue Version")
        raise ConflictError(
            "; ".join(parts) + ". Bitte bestätigen.",
            code="overwrite_confirmation_required", report=report.to_dict())
    return report.to_dict()
