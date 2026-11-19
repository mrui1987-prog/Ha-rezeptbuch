"""Hilfen für die Tests des Wiegeablaufs (Modul 09): Rezepte, Waage zum Einstellen."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.production.runner import ProductionRunner
from app.raw_materials import create_raw_material
from app.recipes import create_recipe, set_batch_sizes


@dataclass(frozen=True)
class FakeState:
    status: str
    weight_g: int | None
    stable: bool


class FakeHub:
    """Steht für den Mittelsmann: Werte je Station von Hand setzen, Nachrichten werden gesammelt."""

    def __init__(self):
        self.states: dict[int, FakeState] = {}
        self.events: list[dict] = []

    def put(self, station: int, weight_g: int | None, stable: bool = True, status: str = "ok") -> None:
        self.states[station] = FakeState(status, weight_g if status == "ok" else None, stable)

    def current_state(self, station: int):
        return self.states.get(station)

    def broadcast(self, event: dict) -> None:
        self.events.append(event)


def item(raw_material_id, amount):
    return {"type": "raw_material", "raw_material_id": raw_material_id, "amount_g": amount}


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture
def runner(hub):
    return ProductionRunner(hub)


@pytest.fixture
def rm(conn):
    def make(name, **kw):
        data = {"name": name, "tolerance": "10"}
        data.update(kw)
        return create_raw_material(conn, data)["id"]
    return {
        "mehl": make("Weizenmehl 550", type="flour", tolerance="20"),
        "roggen": make("Roggenmehl 1150", type="flour", tolerance="20"),
        "wasser": make("Wasser", tolerance="50"),
        "salz": make("Speisesalz", display_name="Salz", tolerance="2"),
        "ei": make("Vollei", unit_size_g="55", unit_label="Ei", tolerance="5"),
        "vanille": make("Vanille", tolerance="0"),
        "hefe": make("Hefe frisch", tolerance="0"),
    }


def unlock(conn, recipe_id):
    conn.execute("UPDATE recipe SET locked = 0 WHERE id = ?", (recipe_id,))


@pytest.fixture
def recipes(conn, rm):
    """Brot (1 000 g Mehl, 600 g Wasser, 20 g Salz), Vorteig-Brot mit Unterrezept, Kuchen mit Eiern/Hand."""
    brot = create_recipe(conn, {"name": "Weißbrot", "knead_slow_min": 5, "knead_fast_min": 6,
                                "note": "Teig 10 min ruhen lassen", "note_display": "end",
                                "items": [item(rm["mehl"], 1000), item(rm["wasser"], 600), item(rm["salz"], 20)]})
    vorteig = create_recipe(conn, {"name": "Vorteig", "items": [item(rm["roggen"], 500), item(rm["wasser"], 500)]})
    misch = create_recipe(conn, {"name": "Mischbrot", "items": [
        {"type": "sub_recipe", "sub_recipe_id": vorteig["id"], "amount_g": 1000},
        item(rm["mehl"], 1000), item(rm["wasser"], 500)]})
    misch = set_batch_sizes(conn, misch["id"], [{"label": "Kessel", "kind": "weight", "value": 2500}])
    kuchen = create_recipe(conn, {"name": "Kuchen", "items": [
        item(rm["mehl"], 1000), item(rm["ei"], 1160), item(rm["vanille"], 0), item(rm["hefe"], 30)]})
    for r in (brot, misch, kuchen):
        unlock(conn, r["id"])
    return {"brot": brot["id"], "vorteig": vorteig["id"], "misch": misch["id"], "kuchen": kuchen["id"]}
