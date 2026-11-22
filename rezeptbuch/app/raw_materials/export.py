"""CSV-Export der Rohstoffe (Modul 03, M03-8, docs/rohstoffe.md Abschnitt 6).

Semikolon als Trenner, UTF-8 mit BOM (Excel öffnet die Datei direkt richtig),
Prozent mit Komma. Dasselbe Format dient für den Import (Modul 05). Seit 0.6.2 zwei Spalten
am Ende: „Preis je kg €“ (z. B. „2,35“) und „Preis geändert am“ (VC03-a). Seit Modul 04 Teil C1 ist
der Preis der gültige Preis (aktive Bezugsquelle, M04-14); drei Info-Spalten am Ende (K04-3).
"""

from __future__ import annotations

import csv
import io

from .models import euro_text
from .stock import kg_text

HEADER = [
    "Nummer", "Name", "Kurzname", "Typ", "Toleranz", "Toleranzeinheit",
    "Gebindegröße g", "Gebindebezeichnung", "Herkunft", "archiviert", "geändert am",
    # ab 0.6.2 am Ende (VC03-a, docs/rohstoffe.md 15.5)
    "Preis je kg €", "Preis geändert am",
    # ab VC03-b am Ende (docs/bestand.md B8): kg mit Komma, leer = keine Bestandsführung / kein Meldewert
    "Bestand kg", "Meldewert kg",
    # ab Modul 04 Teil C1 am Ende, nur zur Info – der Import wertet sie nicht aus (K04-3)
    "Händler (aktiv)", "Artikelnummer (aktiv)", "datenlink-ID",
]

TYPE_LABEL = {"standard": "Standard", "flour": "Mehl", "aid": "Hilfs- und Betriebsstoff"}
SOURCE_LABEL = {"own": "eigen", "datenlink": "datenlink"}


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
            euro_text(row["price_cents_per_kg"]) if row["price_cents_per_kg"] is not None else "",
            row["price_changed_at"] or "",
            kg_text(row["stock_g"]),
            kg_text(row["stock_alert_g"]),
            (row.get("active_source") or {}).get("dealer_name") or "",
            (row.get("active_source") or {}).get("article_no") or "",
            row.get("datenlink_id") or "",
        ])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")
