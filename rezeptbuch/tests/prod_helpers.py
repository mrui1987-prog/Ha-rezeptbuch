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
    net: bool = False
    capacity_g: int = 30000


class FakeHub:
    """Steht für Mittelsmann und Waage: ``put`` setzt das Bruttogewicht; ``tare``/``zero`` wirken wie an der
    KERN (Tara merkt die Anzeige, Anzeige darunter = ``-----``, Null nur bis ±50 g oder bei ``-----``)."""

    def __init__(self):
        self.gross: dict[int, int | None] = {}
        self.offset: dict[int, int] = {}
        self.stable: dict[int, bool] = {}
        self.status: dict[int, str] = {}
        self.events: list[dict] = []
        self.commands: list[tuple[int, str]] = []
        self.ignore_commands = False

    def put(self, station: int, weight_g: int | None, stable: bool = True, status: str = "ok") -> None:
        self.gross[station] = weight_g
        self.stable[station] = stable
        self.status[station] = status
        self.offset.setdefault(station, 0)

    @property
    def states(self):
        return {n: self.current_state(n) for n in self.gross}

    def known_stations(self):
        return sorted(self.gross)

    def display(self, station):
        gross = self.gross.get(station)
        return None if gross is None else gross - self.offset.get(station, 0)

    def current_state(self, station: int):
        if station not in self.gross:
            return None
        status = self.status[station]
        shown = self.display(station)
        if status == "ok" and (shown is None or shown < 0):
            status = "invalid"
        weight = shown if status == "ok" else None
        return FakeState(status, weight, self.stable[station] if status == "ok" else False,
                         net=self.offset.get(station, 0) > 0)

    def send_command(self, station: int, cmd: str) -> str:
        self.commands.append((station, cmd))
        if self.status.get(station) == "offline":
            return "offline"
        if self.ignore_commands:
            return "sent"
        shown = self.display(station)
        if cmd == "tare" and shown is not None and shown > 0 and self.status[station] == "ok":
            self.offset[station] = self.offset.get(station, 0) + shown
        elif cmd == "zero" and (shown is None or shown < 0 or abs(shown) <= 50):
            self.offset[station] = 0
        return "sent"

    def broadcast(self, event: dict) -> None:
        self.events.append(event)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def item(raw_material_id, amount):
    return {"type": "raw_material", "raw_material_id": raw_material_id, "amount_g": amount}


@pytest.fixture
def hub():
    return FakeHub()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def runner(hub, clock):
    return ProductionRunner(hub, clock=clock)


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
