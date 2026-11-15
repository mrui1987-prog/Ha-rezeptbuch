"""Bericht eines Imports (Modul 05, docs/rezepte.md Abschnitt 6).

Der Bericht ist für Probelauf und Import gleich. Er unterscheidet:

* **Fehler** – Import nicht möglich (Blatt, Zeile, Spalte, Meldung)
* **Änderungen** – vorhandene Rohstoffe, die überschrieben werden („alt → neu“ je Feld, K05-2d)
* **Hinweise** – Import möglich (ähnliche Namen, Typwechsel, nicht ausgewertete Spalten …)
* **Toleranz 0 %** – Rohstoffe, die 0 % erhalten (M05-13b)
"""

from __future__ import annotations


class ImportReport:
    def __init__(self, mode: str, kind: str):
        self.mode = mode                 # "check" oder "run"
        self.kind = kind                 # z. B. "raw_materials"
        self.encoding: str | None = None
        self.rows = 0                    # ausgewertete (nicht leere) Datenzeilen
        self.created: list[dict] = []
        self.changes: list[dict] = []
        self.unchanged = 0
        self.errors: list[dict] = []
        self.hints: list[dict] = []
        self.zero_percent: list[dict] = []
        self.imported = False

    # -- Einträge --------------------------------------------------------------

    def error(self, message: str, *, line: int | None = None, column: str | None = None,
              sheet: str | None = None) -> None:
        self.errors.append({"sheet": sheet, "line": line, "column": column, "message": message})

    def hint(self, message: str, *, line: int | None = None, sheet: str | None = None) -> None:
        self.hints.append({"sheet": sheet, "line": line, "message": message})

    # -- Auswertung ------------------------------------------------------------

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def overwritten(self) -> int:
        return len(self.changes)

    @property
    def needs_confirmation(self) -> bool:
        """Werden vorhandene Rohstoffe überschrieben, braucht der Import eine Bestätigung (K05-2)."""
        return self.overwritten > 0

    def summary(self) -> str:
        if self.errors:
            n = len(self.errors)
            return f"Import nicht möglich: {n} Fehler. Es wurde nichts gespeichert."
        parts = [f"{len(self.created)} neu", f"{self.overwritten} überschrieben", f"{self.unchanged} unverändert"]
        verb = "importiert" if self.imported else "Probelauf"
        return f"{verb}: " + ", ".join(parts) + "."

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "mode": self.mode,
            "ok": self.ok,
            "imported": self.imported,
            "needs_confirmation": self.needs_confirmation,
            "encoding": self.encoding,
            "summary": self.summary(),
            "counts": {
                "rows": self.rows,
                "new": len(self.created),
                "overwritten": self.overwritten,
                "unchanged": self.unchanged,
                "errors": len(self.errors),
            },
            "created": self.created,
            "changes": self.changes,
            "errors": self.errors,
            "hints": self.hints,
            "zero_percent": self.zero_percent,
        }
