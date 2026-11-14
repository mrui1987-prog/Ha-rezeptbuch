"""CSV-Export der Rohstoffe (Modul 03, M03-8, docs/rohstoffe.md Abschnitt 6).

Semikolon als Trenner, UTF-8 mit BOM (Excel öffnet die Datei direkt richtig),
Prozent mit Komma. Dasselbe Format dient später für den Import (Modul 05).
"""

from __future__ import annotations

import csv
import io

HEADER = [
    "Nummer", "Name", "Kurzname", "Typ", "Toleranz", "Toleranzeinheit",
    "Gebindegröße g", "Gebindebezeichnung", "Herkunft", "archiviert", "geändert am",
]

TYPE_LABEL = {"standard": "Standard", "flour": "Mehl"}
SOURCE_LABEL = {"own": "eigen", "baeko": "BÄKO"}


def _tolerance(row: dict) -> str:
    if row["tolerance_unit"] == "percent":
        return f"{row['tolerance']:.1f}".replace(".", ",")
    return str(int(row["tolerance"]))


def build_csv(rows: list[dict]) -> bytes:
    """Erzeugt die CSV-Datei aus den Rohstoffen (Format von ``service.list_raw_materials``)."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
    writer.writerow(HEADER)
    for row in rows:
        writer.writerow([
            row["number"],
            row["name"],
            row["display_name"] or "",
            TYPE_LABEL.get(row["type"], row["type"]),
            _tolerance(row),
            "%" if row["tolerance_unit"] == "percent" else "g",
            row["unit_size_g"] if row["unit_size_g"] is not None else "",
            row["unit_label"] or "",
            SOURCE_LABEL.get(row["source"], row["source"]),
            "ja" if row["archived"] else "nein",
            row["updated_at"],
        ])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")
