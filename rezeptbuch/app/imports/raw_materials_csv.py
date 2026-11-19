"""Rohstoff-Import (Modul 05, docs/rezepte.md Abschnitt 6.1; K05-2, M05-13).

Zwei Teile:

* ``parse_csv`` liest die CSV-Datei im Format des Exports (docs/rohstoffe.md Abschnitt 6).
* ``apply_rows`` wendet die Zeilen in einer **bereits offenen** Transaktion an. Dieselbe
  Funktion verwendet später der Vorlagen-Import (Blatt „Rohstoffe“, Teil C3).

``import_raw_materials_csv`` verbindet beides: Probelauf und Import laufen exakt gleich in
einer Transaktion; der Probelauf rollt am Ende zurück. Fehler in einer Zeile verwerfen nur
diese Zeile (Savepoint), damit der Bericht alle Fehler zeigt; ein Fehler verhindert aber
den ganzen Import (alles oder nichts).

Regeln (K05-2a bis K05-2d):

* Zuordnung über die Nummer; ohne Nummer über den Namen (ohne Groß-/Kleinschreibung,
  zuerst aktive, sonst ein eindeutiger archivierter Rohstoff); sonst neu anlegen.
* Vorhandene Rohstoffe werden mit den Werten der Datei **überschrieben**. Leere Toleranz
  bleibt unverändert; leerer Kurzname bzw. leeres Gebinde werden geleert. Leerer Typ,
  leere Toleranzeinheit und leeres „archiviert“ lassen den bisherigen Wert stehen.
  Fehlt eine Spalte ganz, bleibt das Feld unverändert. Nummer und Herkunft ändern sich nie.
* Neue Rohstoffe: leere Toleranz wird **0 %** (M05-13), Herkunft immer „eigen“.
* Spalte „archiviert“: ja → archivieren, nein → wiederherstellen (Namensprüfung R03-10).
  Rohstoffe, die nicht in der Datei stehen, bleiben unverändert.
* Werden vorhandene Rohstoffe überschrieben, läuft der Import nur mit ``confirm_overwrite``.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from dataclasses import dataclass, field

from ..errors import ConflictError, PayloadTooLargeError, ServiceError, ValidationError
from ..raw_materials import service
from ..raw_materials.models import euro_text, normalize_text
from ..raw_materials.stock import inventory_in_tx, kg_text, parse_kg
from .report import ImportReport

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000

# Kopfzeile (wie im Export) → Feld; None = bekannt, wird aber nicht ausgewertet.
# Verglichen wird ohne Groß-/Kleinschreibung (casefold macht aus „ß“ ein „ss“).
_HEADER_LABELS = {
    "Nummer": "number",
    "Name": "name",
    "Kurzname": "display_name",
    "Typ": "type",
    "Toleranz": "tolerance",
    "Toleranzeinheit": "tolerance_unit",
    "Gebindegröße g": "unit_size_g",
    "Gebindebezeichnung": "unit_label",
    "archiviert": "archived",
    "Herkunft": None,
    "geändert am": None,
}

COLUMN_LABEL = {
    "number": "Nummer", "name": "Name", "display_name": "Kurzname", "type": "Typ",
    "tolerance": "Toleranz", "tolerance_unit": "Toleranzeinheit", "unit_size_g": "Gebindegröße g",
    "unit_label": "Gebindebezeichnung", "archived": "archiviert", "price_per_kg": "Preis je kg €",
    "stock_kg": "Bestand kg", "stock_alert_kg": "Meldewert kg",
}

TYPE_VALUES = {"standard": "standard", "mehl": "flour", "flour": "flour"}
UNIT_VALUES = {"g": "g", "%": "percent", "percent": "percent", "prozent": "percent"}
ARCHIVED_VALUES = {"ja": True, "1": True, "nein": False, "0": False}


@dataclass
class SourceRow:
    """Eine Datenzeile: Zeilennummer in der Datei und die Texte der vorhandenen Spalten."""

    line: int
    values: dict[str, str] = field(default_factory=dict)

    def has(self, key: str) -> bool:
        return key in self.values

    def get(self, key: str) -> str:
        return self.values.get(key, "")


@dataclass
class ParsedFile:
    rows: list[SourceRow]
    encoding: str
    ignored_columns: list[str]


# -- Lesen der Datei ---------------------------------------------------------------

def _decode(data: bytes) -> tuple[str, str]:
    """UTF-8 mit oder ohne BOM; sonst Windows-1252 (so speichert Excel „CSV (Trennzeichen-getrennt)“)."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        raise ValidationError("Datei kann nicht gelesen werden (unbekannte Zeichenkodierung).",
                              code="unreadable_file") from None


def _header_key(text: str) -> str:
    return normalize_text(text.replace("\ufeff", "")).casefold()


HEADERS = {_header_key(label): target for label, target in _HEADER_LABELS.items()}

# Preis je kg nur im CSV-Import, nicht in der Importvorlage .xlsx (VC03-a, K03-7; docs/rohstoffe.md 15.6).
# „Preis geändert am“ ist bekannt, wird aber nicht ausgewertet (setzt der Rezeptserver, R03-14).
_PRICE_LABELS = {
    "Preis je kg €": "price_per_kg", "Preis je kg": "price_per_kg", "Preis €/kg": "price_per_kg",
    "Preis/kg": "price_per_kg", "Preis geändert am": None,
    # Bestand und Meldewert (VC03-b, docs/bestand.md B8): leer = Führung beenden bzw. kein Meldewert,
    # fehlt die Spalte, bleibt der Wert. Ein geänderter Bestand wird als Inventur gebucht.
    "Bestand kg": "stock_kg", "Bestand": "stock_kg", "Meldewert kg": "stock_alert_kg", "Meldewert": "stock_alert_kg",
}
CSV_HEADERS = {**HEADERS, **{_header_key(label): target for label, target in _PRICE_LABELS.items()}}


def cell_text(value) -> str:
    """Zellwert als Text (für CSV schon Text; für .xlsx auch Zahlen, Teil C3)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return normalize_text(str(value))


def parse_csv(data: bytes) -> ParsedFile:
    """Liest die CSV-Datei. Semikolon (Export, deutsches Excel), sonst Tabulator oder Komma."""
    if len(data) > MAX_BYTES:
        raise PayloadTooLargeError("Die Datei ist zu groß (höchstens 5 MB).", code="file_too_large")
    if not data.strip():
        raise ValidationError("Die Datei ist leer.", code="empty_file")
    text, encoding = _decode(data)
    if "\x00" in text:
        raise ValidationError("Datei kann nicht gelesen werden (keine CSV-Datei).", code="unreadable_file")

    first_line = text.splitlines()[0] if text.splitlines() else ""
    delimiter = ";" if ";" in first_line else "\t" if "\t" in first_line else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except (StopIteration, csv.Error):
        raise ValidationError("Datei kann nicht gelesen werden.", code="unreadable_file") from None

    columns: list[str | None] = []
    seen: set[str] = set()
    ignored: list[str] = []
    for raw in header:
        key = _header_key(raw)
        target = CSV_HEADERS.get(key, "?")
        if target == "?":
            columns.append(None)
            if key:
                ignored.append(normalize_text(raw))
            continue
        if target is not None and target in seen:
            raise ValidationError(f"Die Spalte „{COLUMN_LABEL[target]}“ kommt doppelt vor.", code="bad_header")
        if target is not None:
            seen.add(target)
        columns.append(target)
    if "name" not in seen:
        raise ValidationError(
            "Die Kopfzeile ist nicht erkennbar: Spalte „Name“ fehlt. Erwartet wird das Format "
            "des CSV-Exports (Nummer;Name;Kurzname;Typ;Toleranz;…).", code="bad_header")

    rows: list[SourceRow] = []
    try:
        for record in reader:
            values = {}
            for index, target in enumerate(columns):
                if target is None:
                    continue
                values[target] = normalize_text(record[index]) if index < len(record) else ""
            if not any(values.values()):
                continue                       # leere Zeile (z. B. am Ende aus Excel)
            rows.append(SourceRow(line=reader.line_num, values=values))
            if len(rows) > MAX_ROWS:
                raise ValidationError(f"Die Datei hat mehr als {MAX_ROWS} Zeilen.", code="too_many_rows")
    except csv.Error as exc:
        raise ValidationError(f"Datei kann nicht gelesen werden (Zeile {reader.line_num}): {exc}",
                              code="unreadable_file") from None
    return ParsedFile(rows=rows, encoding=encoding, ignored_columns=ignored)


# -- Werte einer Zeile -------------------------------------------------------------

_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+$")
_TRAILING_ZERO = re.compile(r"^(\d+)[.,]0+$")


def _int_text(text: str) -> str:
    """Ganze Zahl aus Excel-Schreibweisen: „25.000“ → 25000, „55,0“ → 55. Prüfung danach im Modell."""
    text = text.replace(" ", "").replace("\u00a0", "")
    if _THOUSANDS.match(text):
        return text.replace(".", "")
    match = _TRAILING_ZERO.match(text)
    return match.group(1) if match else text


def _choice(text: str, table: dict, field_name: str, message: str):
    value = table.get(text.casefold())
    if value is None:
        raise ValidationError(message, field=field_name)
    return value


def _row_input(row: SourceRow, existing: bool) -> tuple[dict, bool | None, bool]:
    """Zeile → Eingabe für ``raw_materials.service`` und gewünschter Archivstatus.

    Liefert (Daten, archiviert oder None = unverändert, Toleranz leer → 0 %).
    """
    data: dict = {}
    zero_from_empty = False
    for key in ("name", "display_name", "unit_label"):
        if row.has(key):
            data[key] = row.get(key) or None
    if row.has("price_per_kg"):
        # K03-5: leere Zelle löscht den Preis; fehlt die Spalte ganz, bleibt er unverändert
        data["price_per_kg"] = row.get("price_per_kg") or None
    if row.has("stock_alert_kg"):
        data["stock_alert_kg"] = row.get("stock_alert_kg") or None
    if row.has("unit_size_g"):
        data["unit_size_g"] = _int_text(row.get("unit_size_g")) or None
    if row.get("type"):
        data["type"] = _choice(row.get("type"), TYPE_VALUES, "type", "Typ muss „Standard“ oder „Mehl“ sein.")
    if row.get("tolerance_unit"):
        data["tolerance_unit"] = _choice(row.get("tolerance_unit"), UNIT_VALUES, "tolerance_unit",
                                         "Toleranzeinheit muss „g“ oder „%“ sein.")
    if row.get("tolerance"):
        data["tolerance"] = row.get("tolerance")
    elif not existing:
        # M05-13: leere Toleranz bei neuem Rohstoff = 0 % (wird gewogen, mindestens ±1 g)
        data["tolerance"] = "0"
        data["tolerance_unit"] = "percent"
        zero_from_empty = True
    archived = None
    if row.get("archived"):
        archived = _choice(row.get("archived"), ARCHIVED_VALUES, "archived",
                           "„archiviert“ muss „ja“ oder „nein“ sein.")
    return data, archived, zero_from_empty


# -- Anzeige für den Bericht -------------------------------------------------------

def _show(item: dict) -> dict:
    """Anzeigewerte eines Rohstoffs für „alt → neu“."""
    if item["tolerance_unit"] == "percent":
        tolerance = f"{item['tolerance']:.1f}".replace(".", ",") + " %"
    else:
        tolerance = f"{item['tolerance']} g" + (" (Handzugabe)" if item["tolerance"] == 0 else "")
    return {
        "Name": item["name"],
        "Kurzname": item["display_name"] or "(leer)",
        "Typ": "Mehl" if item["type"] == "flour" else "Standard",
        "Toleranz": tolerance,
        "Gebinde": f"{item['unit_size_g']} g {item['unit_label']}" if item["unit_size_g"] else "(leer)",
        "archiviert": "ja" if item["archived"] else "nein",
        "Preis je kg": (euro_text(item["price_cents_per_kg"]) + " €"
                        if item["price_cents_per_kg"] is not None else "(leer)"),
        "Bestand": kg_text(item["stock_g"]) + " kg" if item["stock_g"] is not None else "(keine Führung)",
        "Meldewert": kg_text(item["stock_alert_g"]) + " kg" if item["stock_alert_g"] is not None else "(leer)",
    }


def _price_hints(report: ImportReport, warnings: list, row: SourceRow, sheet: str | None) -> None:
    """Gerundeter Preis (K03-8): Import möglich, Hinweis mit Zeile im Bericht."""
    for warning in warnings:
        report.hint(warning["detail"], line=row.line, sheet=sheet)


def _apply_stock(conn: sqlite3.Connection, raw_material_id: int, row: SourceRow) -> None:
    """Bestand aus der Datei als Inventur buchen, wenn er sich ändert (B8)."""
    if not row.has("stock_kg"):
        return
    grams = parse_kg(row.get("stock_kg"), "stock_kg", allow_empty=True)
    current = conn.execute("SELECT stock_g FROM raw_material WHERE id = ?", (raw_material_id,)).fetchone()[0]
    if grams != current:
        inventory_in_tx(conn, raw_material_id, grams, note="CSV-Import", source="import")


def _is_zero_percent(item: dict) -> bool:
    return item["tolerance_unit"] == "percent" and item["tolerance"] == 0


# -- Zuordnung -------------------------------------------------------------------

def _find_target(conn: sqlite3.Connection, number: int | None, name: str):
    """Vorhandener Rohstoff zur Zeile (K05-2a) oder None."""
    if number is not None:
        row = conn.execute("SELECT id FROM raw_material WHERE number = ?", (number,)).fetchone()
        return row["id"] if row else None
    key = service.name_key(name)
    active, archived = [], []
    for row in conn.execute("SELECT id, name, archived FROM raw_material"):
        if service.name_key(row["name"]) == key:
            (archived if row["archived"] else active).append(row["id"])
    if active:
        return active[0]
    if len(archived) == 1:
        return archived[0]
    if len(archived) > 1:
        raise ValidationError(
            f"Mehrere archivierte Rohstoffe heißen „{name}“. Bitte die Nummer angeben.", field="number")
    return None


def _parse_number(row: SourceRow) -> int | None:
    text = _int_text(row.get("number"))
    if not text:
        return None
    if not (text.isascii() and text.isdigit()) or int(text) <= 0:
        raise ValidationError("Nummer muss eine ganze Zahl größer 0 sein.", field="number")
    return int(text)


def _duplicates_in_file(rows: list[SourceRow], report: ImportReport, sheet: str | None) -> set[int]:
    """Doppelte Nummern und doppelte Namen innerhalb der Datei (ohne archivierte Zeilen)."""
    bad: set[int] = set()
    numbers: dict[str, int] = {}
    names: dict[str, int] = {}
    for row in rows:
        number = _int_text(row.get("number"))
        if number:
            if number in numbers:
                report.error(f"Nummer {number} steht mehrfach in der Datei (auch Zeile {numbers[number]}).",
                             line=row.line, column="Nummer", sheet=sheet)
                bad.add(row.line)
            else:
                numbers[number] = row.line
        if ARCHIVED_VALUES.get(row.get("archived").casefold()) is True or not row.get("name"):
            continue
        key = service.name_key(row.get("name"))
        if key in names:
            report.error(f"Name „{row.get('name')}“ steht mehrfach in der Datei (auch Zeile {names[key]}).",
                         line=row.line, column="Name", sheet=sheet)
            bad.add(row.line)
        else:
            names[key] = row.line
    return bad


# -- Anwenden ------------------------------------------------------------------

def _apply_one(conn: sqlite3.Connection, row: SourceRow, report: ImportReport, sheet: str | None) -> None:
    number = _parse_number(row)
    target = _find_target(conn, number, row.get("name"))

    if target is None:
        data, archived, zero_from_empty = _row_input(row, existing=False)
        if number is not None:
            data["number"] = number
        warnings: list = []
        new_id = service.create_in_tx(conn, data, source="import", warnings=warnings)
        _apply_stock(conn, new_id, row)
        _price_hints(report, warnings, row, sheet)
        if archived:
            service.archive_in_tx(conn, new_id, source="import")
        item = service.get_raw_material(conn, new_id)
        report.created.append({"sheet": sheet, "line": row.line, "number": item["number"], "name": item["name"]})
        if _is_zero_percent(item):
            report.zero_percent.append({
                "sheet": sheet, "line": row.line, "number": item["number"], "name": item["name"],
                "reason": "Toleranz leer → 0 %" if zero_from_empty else "Toleranz 0 %"})
        similar = service.similar_names(conn, item["name"], exclude_id=new_id)
        if similar:
            report.hint(f"„{item['name']}“ ist neu; ähnliche Rohstoffe gibt es schon: "
                        + ", ".join(f"{s['name']} (Nr. {s['number']})" for s in similar),
                        line=row.line, sheet=sheet)
        return

    before = service.get_raw_material(conn, target)
    data, archived, _ = _row_input(row, existing=True)
    warnings: list = []
    if archived is True and not before["archived"]:
        service.archive_in_tx(conn, target, source="import")
        changed = service.update_in_tx(conn, target, data, confirm_type_change=True, source="import",
                                       warnings=warnings)
    else:
        changed = service.update_in_tx(conn, target, data, confirm_type_change=True, source="import",
                                       warnings=warnings)
        if archived is False and before["archived"]:
            service.restore_in_tx(conn, target, source="import")
    _apply_stock(conn, target, row)
    after = service.get_raw_material(conn, target)
    _price_hints(report, warnings, row, sheet)

    old, new = _show(before), _show(after)
    fields = [{"field": key, "old": old[key], "new": new[key]} for key in old if old[key] != new[key]]
    if not fields:
        report.unchanged += 1
        return
    entry = {"sheet": sheet, "line": row.line, "number": after["number"], "name": after["name"],
             "fields": fields, "type_change_recipes": 0}
    if "type" in changed and before["usage"]["recipes"]:
        n = before["usage"]["recipes"]
        entry["type_change_recipes"] = n
        report.hint(f"Typwechsel bei „{after['name']}“ ({old['Typ']} → {new['Typ']}) betrifft "
                    f"{n} Rezept{'e' if n != 1 else ''}: „Mehl gesamt“ ändert sich dort.",
                    line=row.line, sheet=sheet)
    report.changes.append(entry)
    if _is_zero_percent(after) and not _is_zero_percent(before):
        report.zero_percent.append({"sheet": sheet, "line": row.line, "number": after["number"],
                                    "name": after["name"], "reason": "Toleranz 0 %"})


def apply_rows(conn: sqlite3.Connection, rows: list[SourceRow], report: ImportReport,
               sheet: str | None = None) -> None:
    """Wendet alle Zeilen an. Erwartet eine offene Transaktion; schreibt Fehler in den Bericht."""
    report.rows += len(rows)
    skip = _duplicates_in_file(rows, report, sheet)
    for row in rows:
        if row.line in skip:
            continue
        conn.execute("SAVEPOINT import_row")
        try:
            _apply_one(conn, row, report, sheet)
        except ServiceError as exc:
            conn.execute("ROLLBACK TO import_row")
            report.error(exc.message, line=row.line, column=COLUMN_LABEL.get(exc.field or ""), sheet=sheet)
        except sqlite3.IntegrityError as exc:
            conn.execute("ROLLBACK TO import_row")
            report.error(f"Konnte nicht gespeichert werden: {exc}", line=row.line, sheet=sheet)
        finally:
            conn.execute("RELEASE import_row")


def import_raw_materials_csv(conn: sqlite3.Connection, data: bytes, *, mode: str = "check",
                             confirm_overwrite: bool = False) -> dict:
    """Probelauf (``mode="check"``) oder Import (``mode="run"``) einer Rohstoff-CSV.

    Probelauf: liefert immer den Bericht, ändert nichts.
    Import: speichert nur, wenn es keine Fehler gibt und – falls vorhandene Rohstoffe
    überschrieben werden – ``confirm_overwrite`` gesetzt ist. Sonst wird nichts gespeichert
    und ein Fehler mit dem Bericht ausgelöst.
    """
    if mode not in ("check", "run"):
        raise ValidationError("mode muss „check“ oder „run“ sein.", field="mode")
    parsed = parse_csv(data)
    report = ImportReport(mode, "raw_materials")
    report.encoding = parsed.encoding
    if parsed.encoding != "utf-8":
        report.hint("Die Datei war nicht in UTF-8 gespeichert und wurde als Windows-Zeichensatz gelesen. "
                    "Bitte Umlaute im Bericht prüfen.")
    for column in parsed.ignored_columns:
        report.hint(f"Spalte „{column}“ wird nicht ausgewertet.")

    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_rows(conn, parsed.rows, report)
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

    if mode == "run" and not report.ok:
        raise ValidationError(report.summary(), code="import_failed", report=report.to_dict())
    if mode == "run" and not report.imported:
        n = report.overwritten
        raise ConflictError(
            f"{n} Rohstoff{'e werden' if n != 1 else ' wird'} überschrieben. Bitte bestätigen.",
            code="overwrite_confirmation_required", report=report.to_dict())
    return report.to_dict()
