"""Bericht eines Imports (Modul 05, docs/rezepte.md Abschnitt 6).

Der Bericht ist für Probelauf und Import gleich. Er unterscheidet:

* **Fehler** – Import nicht möglich (Blatt, Zeile, Spalte, Meldung)
* **Änderungen** – vorhandene Rohstoffe, die überschrieben werden („alt → neu“ je Feld, K05-2d)
* **Hinweise** – Import möglich (ähnliche Namen, Typwechsel, nicht ausgewertete Spalten …)
* **Toleranz 0 %** – Rohstoffe, die 0 % erhalten (M05-13b)
* **Rezepte** – beim Vorlagen-Import neu angelegte Rezepte und Gruppen (Teil C3)
* **Umrechnungen** – umgerechnete Rezeptzeilen (Stück, ml …), gesondert für die Übersicht vorab (C3-E7, E7d)
* **Musterdaten** – Anzahl übersprungener Musterrezepte und Musterrohstoffe (C3-E11)
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
        self.recipes: list[dict] = []        # Vorlagen-Import: neu angelegte Rezepte
        self.recipes_updated: list[dict] = []  # Vorlagen-Import: vorhandene Rezepte, die eine neue Version bekommen
        self.groups_created: list[str] = []  # Vorlagen-Import: neu angelegte Gruppen
        self.conversions: list[dict] = []    # Vorlagen-Import: umgerechnete Zeilen (C3-E7)
        self.samples_recipes = 0             # Vorlagen-Import: übersprungene Musterrezepte (C3-E11)
        self.samples_raw_materials = 0       # Vorlagen-Import: übersprungene Musterrohstoffe (C3-E11)
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
        """Rohstoffe überschreiben (K05-2) oder vorhandene Rezepte neue Versionen bekommen (C3-E5): Bestätigung nötig."""
        return self.overwritten > 0 or any(r["action"] == "new_version" for r in self.recipes_updated)

    @property
    def nothing_to_import(self) -> bool:
        """Weder neue noch geänderte Rohstoffe oder Rezepte (z. B. Datei nur mit Musterdaten)."""
        return not (self.created or self.changes or self.recipes
                    or any(r["action"] == "new_version" for r in self.recipes_updated))

    def summary(self) -> str:
        if self.errors:
            n = len(self.errors)
            return f"Import nicht möglich: {n} Fehler. Es wurde nichts gespeichert."
        parts = [f"{len(self.created)} neu", f"{self.overwritten} überschrieben", f"{self.unchanged} unverändert"]
        verb = "importiert" if self.imported else "Probelauf"
        if self.kind == "recipes":
            n = len(self.recipes)
            versions = sum(1 for r in self.recipes_updated if r["action"] == "new_version")
            same = len(self.recipes_updated) - versions
            text = f"{verb}: {n} Rezept{'e' if n != 1 else ''} neu"
            if self.recipes_updated:
                text += f", {versions} neue Version{'en' if versions != 1 else ''}, {same} unverändert"
            return text + "; Rohstoffe " + ", ".join(parts) + "."
        return f"{verb}: " + ", ".join(parts) + "."

    def to_dict(self) -> dict:
        result = self._base_dict()
        if self.kind == "recipes":
            result["counts"].update({
                "recipes": len(self.recipes),
                "recipes_new_version": sum(1 for r in self.recipes_updated if r["action"] == "new_version"),
                "recipes_unchanged": sum(1 for r in self.recipes_updated if r["action"] != "new_version"),
                "groups": len(self.groups_created),
                "review_lines": sum(r.get("review_count", 0) for r in self.recipes),
                "conversions": len(self.conversions),
                "samples_recipes": self.samples_recipes,
                "samples_raw_materials": self.samples_raw_materials,
            })
            result["nothing_to_import"] = self.nothing_to_import
            result["conversions"] = self.conversions
            result["recipes"] = self.recipes
            result["recipes_updated"] = self.recipes_updated
            result["groups_created"] = self.groups_created
        return result

    def _base_dict(self) -> dict:
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
