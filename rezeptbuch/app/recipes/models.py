"""Eingabeprüfung für Rezepte (Modul 05, docs/rezepte.md Abschnitt 4).

Reine Python-Prüfung ohne Webserver-Bibliothek, damit der Vorlagen-Import
(Teil C3) dieselben Regeln nutzt. Geprüft werden Form und Wertebereiche;
Regeln, die die Datenbank brauchen (Name eindeutig, Rohstoff vorhanden,
Kreise, Versionen), stehen in ``service.py``.

Ergebnis von ``validate_recipe`` ist ein „sauberes“ Rezept mit Spaltenwerten:
Toleranz in Gramm bzw. Zehntelprozent (K2), Schritte als Liste von Namen,
Zeilen mit lückenloser Reihenfolge (R05-12).
"""

from __future__ import annotations

from ..errors import ValidationError
from ..raw_materials.models import normalize_text, parse_tolerance

MAX_NAME = 100
MAX_STEP_NAME = 60
MAX_LABEL = 30              # Stückgewicht, Chargengröße
MAX_GROUP_NAME = 60
MAX_NOTE = 2000
MAX_GRAMS = 1_000_000       # 1 t je Zeile bzw. Stückgewicht
MAX_PIECES = 100_000
MAX_KNEAD_MIN = 999
MAX_NUMBER = 2_000_000_000
MAX_STEPS = 50
MAX_ITEMS = 300
NOTE_DISPLAY = ("start", "end")
ITEM_TYPES = ("raw_material", "sub_recipe")
BATCH_KINDS = ("weight", "pieces")
VERSION_MODES = ("new", "overwrite")


def text(value, field: str, label: str, *, required: bool, max_len: int) -> str | None:
    """Text ohne Randleerzeichen, doppelte Leerzeichen zusammengezogen; leer = None."""
    if value is None:
        result = ""
    elif isinstance(value, str):
        result = normalize_text(value)
    else:
        raise ValidationError(f"{label} muss ein Text sein.", field=field)
    if not result:
        if required:
            raise ValidationError(f"{label} ist ein Pflichtfeld.", field=field)
        return None
    if len(result) > max_len:
        raise ValidationError(f"{label} darf höchstens {max_len} Zeichen lang sein.", field=field)
    return result


def whole_number(value, field: str, label: str, *, minimum: int = 0, maximum: int = MAX_NUMBER,
                 required: bool = False) -> int | None:
    """Ganze Zahl aus Zahl oder Ziffern-Text (nur 0–9, wie Modul 03); leer = None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(f"{label} ist ein Pflichtfeld.", field=field)
        return None
    number = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.isascii() and stripped.isdigit():
            number = int(stripped)
    if number is None:
        raise ValidationError(f"{label} muss eine ganze Zahl sein.", field=field)
    if number < minimum:
        raise ValidationError(f"{label} muss mindestens {minimum} sein.", field=field)
    if number > maximum:
        raise ValidationError(f"{label} darf höchstens {maximum} sein.", field=field)
    return number


def _id(value, field: str, label: str) -> int:
    return whole_number(value, field, label, minimum=1, required=True)


def _flag(value) -> bool:
    return value is True or value == 1 or (isinstance(value, str) and value.strip().lower() in ("1", "true", "ja"))


def _item(raw, index: int, step_count: int) -> dict:
    """Prüft eine Zeile. ``index`` ist die Position (1, 2, 3 …) für Meldungen."""
    where = f"Zeile {index}"
    if not isinstance(raw, dict):
        raise ValidationError(f"{where}: ungültige Angabe.", field=f"items.{index}")
    item_type = raw.get("type") or raw.get("item_type") or "raw_material"
    if item_type not in ITEM_TYPES:
        raise ValidationError(f"{where}: Art muss Rohstoff oder Unterrezept sein.", field=f"items.{index}.type")

    if item_type == "raw_material":
        ref = _id(raw.get("raw_material_id"), f"items.{index}.raw_material_id", f"{where}: Rohstoff")
        amount = whole_number(raw.get("amount_g"), f"items.{index}.amount_g", f"{where}: Menge",
                              minimum=0, maximum=MAX_GRAMS, required=True)
    else:
        ref = _id(raw.get("sub_recipe_id"), f"items.{index}.sub_recipe_id", f"{where}: Unterrezept")
        amount = whole_number(raw.get("amount_g"), f"items.{index}.amount_g", f"{where}: Menge",
                              minimum=1, maximum=MAX_GRAMS, required=True)

    # Toleranz je Zeile: leer = Toleranz des Rohstoffs (R05-11)
    tol_raw = raw.get("tolerance")
    tol_empty = tol_raw is None or (isinstance(tol_raw, str) and not tol_raw.strip())
    tolerance_unit = tolerance_value = None
    if not tol_empty:
        if item_type == "sub_recipe":
            raise ValidationError(f"{where}: Ein Unterrezept hat keine eigene Toleranz.",
                                  field=f"items.{index}.tolerance")
        tolerance_unit = raw.get("tolerance_unit") or "g"
        if tolerance_unit not in ("g", "percent"):
            raise ValidationError(f"{where}: Toleranzeinheit muss „g“ oder „percent“ sein.",
                                  field=f"items.{index}.tolerance_unit")
        try:
            tolerance_value = parse_tolerance(tol_raw, tolerance_unit)
        except ValidationError as exc:
            raise ValidationError(f"{where}: {exc.message}", field=f"items.{index}.tolerance") from None

    step_no = whole_number(raw.get("step_no"), f"items.{index}.step_no", f"{where}: Schritt", minimum=1,
                           maximum=MAX_STEPS)
    if step_no is not None and step_no > step_count:
        raise ValidationError(f"{where}: Schritt {step_no} gibt es nicht.", field=f"items.{index}.step_no")

    original_id = raw.get("id")
    original_id = original_id if isinstance(original_id, int) and not isinstance(original_id, bool) else None

    return {
        "position": index,
        "item_type": item_type,
        "raw_material_id": ref if item_type == "raw_material" else None,
        "sub_recipe_id": ref if item_type == "sub_recipe" else None,
        "amount_g": amount,
        "tolerance_unit": tolerance_unit,
        "tolerance_value": tolerance_value,
        "step_no": step_no,
        # Wunsch der Seite; der Dienst lässt „*“ nur stehen, wenn die Zeile unverändert ist (R05-14)
        "needs_review": _flag(raw.get("needs_review")),
        "original_id": original_id,
    }


def validate_recipe(data: dict) -> dict:
    """Prüft Kopf, Schritte und Zeilen eines Rezepts (R05-1 bis R05-13).

    Die Sperre B2 (Namen mit =, +, -, @) prüft der Dienst, weil sie nur für neue oder
    geänderte Namen gilt.
    """
    if not isinstance(data, dict):
        raise ValidationError("Ungültige Eingabe.")

    number = whole_number(data.get("number"), "number", "Nummer", minimum=1)
    name = text(data.get("name"), "name", "Name", required=True, max_len=MAX_NAME)
    group_id = whole_number(data.get("group_id"), "group_id", "Gruppe", minimum=1)
    knead_slow = whole_number(data.get("knead_slow_min"), "knead_slow_min", "Knetzeit langsam",
                              maximum=MAX_KNEAD_MIN)
    knead_fast = whole_number(data.get("knead_fast_min"), "knead_fast_min", "Knetzeit schnell",
                              maximum=MAX_KNEAD_MIN)

    note_raw = data.get("note")
    if note_raw is not None and not isinstance(note_raw, str):
        raise ValidationError("Hinweistext muss ein Text sein.", field="note")
    note = note_raw.strip() if isinstance(note_raw, str) else ""
    if len(note) > MAX_NOTE:
        raise ValidationError(f"Hinweistext darf höchstens {MAX_NOTE} Zeichen lang sein.", field="note")
    note_display = data.get("note_display") or "end"
    if note_display not in NOTE_DISPLAY:
        raise ValidationError("Anzeige des Hinweistexts muss „start“ oder „end“ sein.", field="note_display")

    steps_raw = data.get("steps") or []
    if not isinstance(steps_raw, list):
        raise ValidationError("Schritte müssen eine Liste sein.", field="steps")
    if len(steps_raw) > MAX_STEPS:
        raise ValidationError(f"Höchstens {MAX_STEPS} Schritte je Rezept.", field="steps")
    steps = []
    for index, step in enumerate(steps_raw, start=1):
        value = step.get("name") if isinstance(step, dict) else step
        steps.append(text(value, f"steps.{index}.name", f"Schritt {index}: Name", required=True,
                          max_len=MAX_STEP_NAME))

    items_raw = data.get("items") or []
    if not isinstance(items_raw, list):
        raise ValidationError("Zeilen müssen eine Liste sein.", field="items")
    if len(items_raw) > MAX_ITEMS:
        raise ValidationError(f"Höchstens {MAX_ITEMS} Zeilen je Rezept.", field="items")
    items = [_item(raw, index, len(steps)) for index, raw in enumerate(items_raw, start=1)]

    return {
        "number": number,
        "name": name,
        "group_id": group_id,
        "knead_slow_min": knead_slow,
        "knead_fast_min": knead_fast,
        "note": note or None,
        "note_display": note_display,
        "steps": steps,
        "items": items,
    }


def validate_piece_weights(data) -> list[dict]:
    """Stückgewichte (R05-20): Bezeichnung Pflicht, höchstens 30 Zeichen, eindeutig; Gewicht > 0."""
    if not isinstance(data, list):
        raise ValidationError("Stückgewichte müssen eine Liste sein.", field="piece_weights")
    result, seen = [], {}
    for index, raw in enumerate(data, start=1):
        where = f"Stückgewicht {index}"
        if not isinstance(raw, dict):
            raise ValidationError(f"{where}: ungültige Angabe.", field=f"piece_weights.{index}")
        label = text(raw.get("label"), f"piece_weights.{index}.label", f"{where}: Bezeichnung",
                     required=True, max_len=MAX_LABEL)
        weight = whole_number(raw.get("weight_g"), f"piece_weights.{index}.weight_g", f"{where}: Gewicht",
                              minimum=1, maximum=MAX_GRAMS, required=True)
        key = label.casefold()
        if key in seen:
            raise ValidationError(f"{where}: Die Bezeichnung „{label}“ steht schon bei Stückgewicht {seen[key]}.",
                                  field=f"piece_weights.{index}.label", code="label_taken")
        seen[key] = index
        pw_id = raw.get("id")
        result.append({"id": pw_id if isinstance(pw_id, int) and not isinstance(pw_id, bool) else None,
                       "label": label, "weight_g": weight})
    return result


def validate_batch_sizes(data) -> list[dict]:
    """Chargengrößen (R05-20): Bezeichnung Pflicht; Art Gewicht (g) oder Stückzahl mit Stückgewicht."""
    if not isinstance(data, list):
        raise ValidationError("Chargengrößen müssen eine Liste sein.", field="batch_sizes")
    result = []
    for index, raw in enumerate(data, start=1):
        where = f"Chargengröße {index}"
        if not isinstance(raw, dict):
            raise ValidationError(f"{where}: ungültige Angabe.", field=f"batch_sizes.{index}")
        label = text(raw.get("label"), f"batch_sizes.{index}.label", f"{where}: Bezeichnung",
                     required=True, max_len=MAX_LABEL)
        kind = raw.get("kind") or "weight"
        if kind not in BATCH_KINDS:
            raise ValidationError(f"{where}: Art muss „weight“ (Gewicht) oder „pieces“ (Stückzahl) sein.",
                                  field=f"batch_sizes.{index}.kind")
        value = whole_number(raw.get("value"), f"batch_sizes.{index}.value",
                             f"{where}: {'Gewicht' if kind == 'weight' else 'Stückzahl'}",
                             minimum=1, maximum=MAX_GRAMS if kind == "weight" else MAX_PIECES, required=True)
        piece_id = piece_label = None
        if kind == "pieces":
            pid = raw.get("piece_weight_id")
            piece_id = pid if isinstance(pid, int) and not isinstance(pid, bool) else None
            piece_label = text(raw.get("piece_weight_label"), f"batch_sizes.{index}.piece_weight_label",
                               f"{where}: Stückgewicht", required=False, max_len=MAX_LABEL)
            if piece_id is None and piece_label is None:
                raise ValidationError(f"{where}: Bitte das Stückgewicht wählen.",
                                      field=f"batch_sizes.{index}.piece_weight_id")
        bs_id = raw.get("id")
        result.append({"id": bs_id if isinstance(bs_id, int) and not isinstance(bs_id, bool) else None,
                       "label": label, "kind": kind, "value": value,
                       "piece_weight_id": piece_id, "piece_weight_label": piece_label})
    return result


def validate_group_name(value) -> str:
    """Name einer Rezeptgruppe (R05-26): Pflicht, höchstens 60 Zeichen."""
    return text(value, "name", "Name der Gruppe", required=True, max_len=MAX_GROUP_NAME)
