"""Tests Modul 09 Teil C2: Tara an der Waage, Auto-Quittung, Höchstlast, Waagenausfall, Abschluss durch
Abnehmen, Lastprüfung beim „Weiter“, Behälter wiegen/wechseln, Handbetrieb (docs/ablauf.md 6, 9).

Die Waage (FakeHub) tariert und nullt wie die KERN; die Uhr wird von Hand weitergestellt.
"""

import pytest

from app.errors import ConflictError
from app.production import batches, orders
from app.production.automation import tick
from app.production.weigh import Sample, StationWeigh, capacity_warning, zone

from prod_helpers import clock, hub, recipes, rm, runner  # noqa: F401  (Fixtures)

TODAY = "2026-11-20"


def total(recipe_id, grams, **kw):
    data = {"recipe_id": recipe_id, "basis_type": "total", "value": grams, "planned_date": TODAY}
    data.update(kw)
    return data


def st(station=1, **kw):
    return {"station": station, **kw}


ZEROED = 2.4    # Tara, 2 s Pause, Null, Bestätigung


def run(conn, runner, clock, seconds, step=0.2):
    """Hintergrund für ``seconds`` Sekunden laufen lassen."""
    for _ in range(int(round(seconds / step))):
        clock.advance(step)
        tick(conn, runner)


@pytest.fixture
def brot(conn, recipes, runner, hub):
    """Weißbrot 1 620 g gestartet an Waage 1, Behälter 800 g steht schon drauf (Tara beim Start).
    Mindestlast für die Auto-Quittung hier 0 g, damit auch Salz (20 g) automatisch quittiert wird."""
    from app.production.settings import save_settings
    save_settings(conn, {"auto_ack_min_g": 0})
    runner.refresh_settings(conn, force=True)
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 800)
    return batches.start_dough(conn, order["id"], st(), runner, today=TODAY)


def events(conn, kind=None):
    rows = conn.execute("SELECT event_type, weight_g, tare_g, stable, note FROM weighing_event ORDER BY id")
    return [tuple(r) for r in rows if kind is None or r[0] == kind]


# -- weigh.py ohne Datenbank ------------------------------------------------------------------

def test_tare_confirmed_by_scale():
    sw = StationWeigh()
    sw.observe(0, Sample("ok", 0, True, net=False), 3, 5)
    sw.observe(1, Sample("ok", 800, True, net=False), 3, 5)
    assert sw.start_tare(1, Sample("ok", 800, True, net=False)) == 800
    assert sw.taring and sw.actual() == 0
    assert sw.observe(1.5, Sample("ok", 1, True, net=True), 3, 5) == ["tare_confirmed"]
    assert (sw.reference_g, sw.scale_tare_g, sw.taring) == (0, 800, False)      # Nullpunkt 0 netto (B2)
    assert sw.gross(Sample("ok", 501, True, net=True)) == 1301 and sw.tare_total() == 800


def test_tare_timeout_and_late_jump():
    sw = StationWeigh()
    sw.observe(0, Sample("ok", 800, True, net=False), 3, 5)
    sw.start_tare(0, Sample("ok", 800, True, net=False))
    assert sw.observe(1, Sample("ok", 800, True, net=False), 3, 5) == []
    assert sw.observe(3.1, Sample("ok", 900, True, net=False), 3, 5) == ["tare_timeout"]
    assert sw.hint.startswith("Tara an der Waage nicht bestätigt") and sw.actual() == 100
    # Waage tariert doch noch: Anzeige springt um genau 800 g
    assert sw.observe(4, Sample("ok", 100, True, net=True), 3, 5) == ["late_tare"]
    assert sw.actual() == 100 and sw.reference_g == 0 and sw.hint is None


def test_unknown_scale_tare_after_restart():
    sw = StationWeigh()
    sw.observe(0, Sample("ok", 300, True, net=True), 3, 5)       # netto ohne bekannte Tara
    assert sw.gross() is None
    sw.observe(1, Sample("ok", 0, True, net=False), 3, 5)
    assert sw.gross() == 0


def test_auto_ack_window():
    sw = StationWeigh(reference_g=0)
    sw.observe(0, Sample("ok", 1000, True), 3, 5)
    assert not sw.auto_ack(0, 1000, 1000, 20, 2, 5)
    assert not sw.auto_ack(1, 1003, 1000, 20, 2, 5) and sw.progress == 50
    assert not sw.auto_ack(1.5, 1009, 1000, 20, 2, 5)            # Wanderung 9 g > 5 g: neu
    assert sw.progress == 0
    assert not sw.auto_ack(2.5, 1010, 1000, 20, 2, 5)
    assert sw.auto_ack(3.5, 1008, 1000, 20, 2, 5) and sw.progress == 100
    assert not sw.auto_ack(4, 1100, 1000, 20, 2, 5) and sw.progress == 0        # außerhalb der Toleranz


def test_auto_ack_needs_half_target():
    # Befund B1: Boerol 4 g ± 20 g darf nicht bei 0 g automatisch quittiert werden
    from app.production.weigh import auto_ack_minimum
    assert [auto_ack_minimum(t) for t in (0, 1, 2, 3, 4, 1000)] == [1, 1, 1, 2, 2, 500]
    assert [auto_ack_minimum(t, 70) for t in (4, 30, 100, 1000)] == [70, 70, 70, 500]
    sw = StationWeigh(reference_g=0)
    sw.observe(0, Sample("ok", 0, True), 3, 5)
    assert not sw.auto_ack(0, 0, 4, 20, 2, 5)
    assert not sw.auto_ack(3, 0, 4, 20, 2, 5) and sw.progress == 0
    sw.observe(3, Sample("ok", 2, True), 3, 5)
    assert not sw.auto_ack(3, 2, 4, 20, 2, 5)
    assert sw.auto_ack(5, 2, 4, 20, 2, 5)


def test_tare_executed_with_next_ingredient_on_top():
    # B2: Waage brutto 800 g, Tara-Befehl; noch bevor sie ruhig bei 0 steht, liegen 300 g Mehl drauf
    sw = StationWeigh()
    sw.observe(0, Sample("ok", 800, True, net=False), 3, 5)
    sw.start_tare(0, Sample("ok", 800, True, net=False))
    assert sw.observe(0.5, Sample("ok", 300, False, net=True), 3, 5) == ["tare_confirmed"]
    assert (sw.reference_g, sw.scale_tare_g, sw.taring) == (0, 800, False)
    assert sw.actual() == 300 and sw.gross() == 1100


def test_tare_executed_already_net_by_drop():
    # Waage war schon netto (1 000 g nach Tara); neue Tara, Anzeige fällt um das tarierte Gewicht
    sw = StationWeigh(scale_tare_g=800)
    sw.observe(0, Sample("ok", 1000, True, net=True), 3, 5)
    sw.start_tare(0, Sample("ok", 1000, True, net=True))
    assert sw.observe(0.2, Sample("ok", 1003, False, net=True), 3, 5) == []
    # Tara ausgeführt (Anzeige fällt um 1 000 g auf 3 g, Waage unruhig), danach 40 g Mehl
    assert sw.observe(0.4, Sample("ok", 3, False, net=True), 3, 5) == ["tare_confirmed"]
    assert sw.observe(0.6, Sample("ok", 43, False, net=True), 3, 5) == []
    assert sw.actual() == 43 and sw.scale_tare_g == 1800


def test_late_tare_with_load_on_top():
    sw = StationWeigh()
    sw.observe(0, Sample("ok", 800, True, net=False), 3, 5)
    sw.start_tare(0, Sample("ok", 800, True, net=False))
    sw.observe(3.1, Sample("ok", 900, True, net=False), 3, 5)          # Zeit abgelaufen, Software-Tara
    assert sw.actual() == 100
    assert sw.observe(4, Sample("ok", 150, False, net=True), 3, 5) == ["late_tare"]
    assert sw.actual() == 150 and sw.gross() == 950


def test_zone_and_capacity():
    assert [zone(v, 1000, 20) for v in (979, 980, 1020, 1021, None)] == ["low", "ok", "ok", "high", None]
    assert not capacity_warning(28_000, 500, 30_000, 1000)
    assert capacity_warning(29_000, 500, 30_000, 1000)
    assert capacity_warning(27_000, 500, 30_000, 1000, remaining_g=2_500)
    assert capacity_warning(None, 29_500, 30_000, 1000)            # Tara unbekannt: Anzeige zählt
    assert not capacity_warning(None, None, 30_000, 1000)


# -- Tara an der Waage --------------------------------------------------------------------------

def test_start_tares_the_scale(conn, brot, runner, hub):
    assert (1, "tare") in hub.commands
    assert brot["scale"]["weight_g"] == 0 and brot["scale"]["taring"] is False
    assert brot["scale"]["gross_g"] == 800


def test_tare_not_confirmed_software_continues(conn, recipes, runner, hub, clock):
    hub.ignore_commands = True                                    # Waage führt Befehle nicht aus
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 800)
    batch = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)
    assert batch["scale"]["taring"] is True
    with pytest.raises(ConflictError) as exc:
        batches.ack_weighed(conn, batch["id"], st(), runner)
    assert exc.value.code == "taring"
    run(conn, runner, clock, 3.2)
    reading = runner.reading(1)
    assert reading.taring is False and reading.hint.startswith("Tara an der Waage nicht bestätigt")
    hub.put(1, 1810)
    batch = batches.ack_weighed(conn, batch["id"], st(), runner)
    assert batch["items"][0]["actual_g"] == 1010


# -- Auto-Quittung ---------------------------------------------------------------------------------

def test_auto_ack_after_two_seconds(conn, brot, runner, hub, clock):
    hub.put(1, 800 + 1005)
    run(conn, runner, clock, 1.6)
    assert batches.get_batch(conn, brot["id"])["items"][0]["done"] is False
    weigh = [e for e in hub.events if e["type"] == "weigh"][-1]
    assert weigh["actual_g"] == 1005 and weigh["zone"] == "ok" and 60 <= weigh["auto_ack_progress"] < 100
    run(conn, runner, clock, 0.6)
    batch = batches.get_batch(conn, brot["id"], runner)
    assert batch["items"][0]["ack_type"] == "auto_stable" and batch["items"][0]["actual_g"] == 1005
    assert batch["current_position"] == 2 and batch["scale"]["actual_g"] == 0
    assert hub.commands.count((1, "tare")) == 2
    assert any(e["type"] == "batch" and e["event"] == "acked" for e in hub.events)


def test_no_auto_ack_when_unstable_or_wandering(conn, brot, runner, hub, clock):
    hub.put(1, 800 + 1005, stable=False)
    run(conn, runner, clock, 3)
    for weight in (1800, 1809, 1800, 1809, 1800, 1809):          # Wanderung 9 g
        hub.put(1, weight)
        run(conn, runner, clock, 0.6)
    assert batches.get_batch(conn, brot["id"])["items"][0]["done"] is False


def test_min_load_default_70(conn, recipes, runner, hub, clock):
    # Standard: Auto-Quittung erst ab 70 g; Salz 20 g von Hand (Michael 15:21)
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)
    batch = batches.select_item(conn, batch["id"], st(position=3), runner)
    hub.put(1, 20)
    run(conn, runner, clock, 3)
    assert batches.get_batch(conn, batch["id"])["items"][2]["done"] is False
    batch = batches.ack_weighed(conn, batch["id"], st(), runner)
    assert batch["items"][2]["ack_type"] == "manual_stable"
    hub.put(1, 20 + 1000)
    run(conn, runner, clock, 2.4)
    assert batches.get_batch(conn, batch["id"])["items"][0]["ack_type"] == "auto_stable"


def test_next_ingredient_during_tare_no_wait(conn, brot, runner, hub, clock):
    # B2 mit Hintergrund: nach der Mehl-Quittung kommt sofort Wasser drauf, Waage tariert verzögert
    hub.put(1, 800 + 1000)
    hub.ignore_commands = True                                    # Waage führt die Tara erst später aus
    run(conn, runner, clock, 2.4)
    assert batches.get_batch(conn, brot["id"])["items"][0]["done"] is True
    hub.put(1, 1800 + 600)                                        # Wasser drauf, Tara noch nicht ausgeführt
    run(conn, runner, clock, 0.4)
    assert runner.reading(1).taring is True
    hub.ignore_commands = False
    hub.offset[1] = 1800                                          # Waage führt die Tara jetzt aus: netto 600 g
    run(conn, runner, clock, 0.2)
    assert runner.reading(1).taring is False and runner.reading(1).actual_g == 600
    run(conn, runner, clock, 2.2)                                 # keine 3 s Sperre, Auto-Quittung nach 2 s
    assert batches.get_batch(conn, brot["id"])["items"][1]["actual_g"] == 600


def test_auto_ack_settings(conn, brot, runner, hub, clock):
    from app.production.settings import save_settings
    save_settings(conn, {"auto_ack_seconds": 5})
    runner.refresh_settings(conn, force=True)
    hub.put(1, 800 + 1000)
    run(conn, runner, clock, 3)
    assert batches.get_batch(conn, brot["id"])["items"][0]["done"] is False
    run(conn, runner, clock, 2.2)
    assert batches.get_batch(conn, brot["id"])["items"][0]["done"] is True


def test_whole_dough_auto_and_finish_by_removing(conn, brot, runner, hub, clock):
    for gross in (1810, 2410, 2430):                              # Mehl, Wasser, Salz
        hub.put(1, gross)
        run(conn, runner, clock, 2.4)
    batch = batches.get_batch(conn, brot["id"], runner)
    assert batch["status"] == "done" and batch["finish_ack_at"] is None
    assert [i["actual_g"] for i in batch["items"]] == [1010, 600, 20]
    run(conn, runner, clock, 1)
    assert batches.get_batch(conn, brot["id"])["finish_ack_at"] is None      # Behälter steht noch
    hub.put(1, 0)                                                 # abgenommen: Anzeige -----
    run(conn, runner, clock, 0.4)
    batch = batches.get_batch(conn, brot["id"])
    assert batch["finish_ack_at"] is not None
    assert hub.commands[-1] == (1, "zero") and hub.display(1) == 0
    assert any(e["type"] == "batch" and e["event"] == "finished" for e in hub.events)
    # Protokoll: Tara gesamt je Zutat (Behälter + bisherige Zutaten)
    assert [(e[1], e[2]) for e in events(conn, "weighed")] == [(1010, 800), (600, 1810), (20, 2410)]


# -- Waagenausfall ---------------------------------------------------------------------------------

def test_offline_45_seconds_pauses(conn, brot, runner, hub, clock):
    hub.put(1, None, status="offline")
    run(conn, runner, clock, 44)
    assert batches.get_batch(conn, brot["id"])["status"] == "running"
    run(conn, runner, clock, 1.2)
    batch = batches.get_batch(conn, brot["id"])
    assert (batch["status"], batch["pause_reason"], batch["owner_station"]) == ("paused", "scale_offline", None)
    hub.put(1, 800)                                               # Rückkehr hebt die Pause nicht auf
    run(conn, runner, clock, 1)
    assert batches.get_batch(conn, brot["id"])["status"] == "paused"


def test_offline_short_does_not_pause(conn, brot, runner, hub, clock):
    hub.put(1, None, status="offline")
    run(conn, runner, clock, 30)
    hub.put(1, 800)
    run(conn, runner, clock, 1)
    hub.put(1, None, status="offline")
    run(conn, runner, clock, 30)
    assert batches.get_batch(conn, brot["id"])["status"] == "running"


# -- Höchstlast ------------------------------------------------------------------------------------

def test_capacity_warning_in_weigh_message(conn, recipes, runner, hub, clock):
    # Warnung, wenn Gesamtlast + noch zu wiegende Menge ≥ 30 000 − 1 000 g (M09-7)
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 27_000)                                            # schwerer Behälter: 27 000 + 1 620 < 29 000
    batch = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)
    run(conn, runner, clock, 0.4)
    weigh = [e for e in hub.events if e["type"] == "weigh"][-1]
    assert weigh["gross_g"] == 27_000 and weigh["capacity_warning"] is False
    hub.put(1, 27_000 + 2_100)                                    # viel zu viel Mehl: Gesamtlast 29 100
    run(conn, runner, clock, 0.4)
    weigh = [e for e in hub.events if e["type"] == "weigh"][-1]
    assert weigh["zone"] == "high" and weigh["capacity_warning"] is True
    batches.cancel(conn, batch["id"], st(confirm=True), runner)
    second = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    hub.offset[1] = 0
    hub.put(1, 27_500)                                            # 27 500 + 1 620 ≥ 29 000: schon vorher
    batches.start_dough(conn, second["id"], st(), runner, today=TODAY)
    run(conn, runner, clock, 0.4)
    weigh = [e for e in hub.events if e["type"] == "weigh"][-1]
    assert weigh["capacity_warning"] is True


# -- Lastprüfung beim „Weiter“ (K09-12) -------------------------------------------------------------

def test_resume_load_check_same_station(conn, brot, runner, hub):
    hub.put(1, 1300)                                              # 500 g Mehl drin
    batches.pause(conn, brot["id"], st(), runner)
    assert batches.get_batch(conn, brot["id"])["status"] == "paused"
    assert conn.execute("SELECT pause_load_g FROM batch").fetchone()[0] == 1300
    hub.put(1, 1302)                                              # 2 g Abweichung: in Ordnung
    batch = batches.resume(conn, brot["id"], st(), runner)
    assert batch["status"] == "running"
    batches.pause(conn, brot["id"], st(), runner, reason="hand_scale")
    hub.put(1, 1400)                                              # 98 g mehr
    with pytest.raises(ConflictError) as exc:
        batches.resume(conn, brot["id"], st(), runner)
    assert exc.value.code == "resume_deviation" and exc.value.extra["deviation_g"] == 98
    batch = batches.resume(conn, brot["id"], st(confirm_deviation=True), runner)
    assert batch["status"] == "running"
    assert events(conn, "resume_deviation")[0][1] == 98
    assert "Pause 1302 g, jetzt 1400 g" in events(conn, "resume_deviation")[0][4]


def test_resume_refused_while_scale_invalid(conn, brot, runner, hub):
    # Befund Michael 22:38: Handwaage, Behälter weg, Waage zeigt „-----“ – „Weiter“ ohne Rückfrage war möglich
    hub.put(1, 1300)
    batches.pause(conn, brot["id"], st(), runner, reason="hand_scale")
    hub.put(1, -50)                                               # unter 0: Status invalid
    with pytest.raises(ConflictError) as exc:
        batches.resume(conn, brot["id"], st(), runner)
    assert exc.value.code == "resume_invalid" and "keinen gültigen Wert" in exc.value.message
    with pytest.raises(ConflictError):
        batches.resume(conn, brot["id"], st(confirm_deviation=True), runner)
    assert batches.get_batch(conn, brot["id"])["status"] == "paused"
    hub.put(1, 1300)                                              # Behälter wieder drauf
    assert batches.resume(conn, brot["id"], st(), runner)["status"] == "running"


def test_resume_other_station_no_load_check(conn, brot, runner, hub):
    conn.execute("UPDATE station SET active = 1 WHERE id = 2")
    hub.put(1, 1300)
    batches.pause(conn, brot["id"], st(), runner)
    hub.put(2, 5000)
    batch = batches.resume(conn, brot["id"], st(2), runner)
    assert batch["status"] == "running" and batch["owner_station"] == 2


# -- Behälter wiegen und wechseln (K09-13, K09-14) ----------------------------------------------------

def test_container_weigh_flow(conn, recipes, runner, hub, clock):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)
    batch = batches.container(conn, batch["id"], st(action="weigh"), runner)
    assert batch["scale"]["container_step"] == "empty" and batch["scale"]["hint"] == "Waage leeren"
    with pytest.raises(ConflictError) as exc:
        batches.ack_weighed(conn, batch["id"], st(), runner)
    assert exc.value.code == "container_busy"
    run(conn, runner, clock, 0.2)                                 # Waage ist leer: Tara
    assert hub.commands[-1] == (1, "tare") and runner.flow(1).step == "zeroing"
    assert runner.reading(1).hint == "Waage wird genullt – bitte warten"
    run(conn, runner, clock, 1.8)
    assert hub.commands[-1] == (1, "tare")                        # Pause zwischen Tara und Null
    run(conn, runner, clock, 0.2)
    assert hub.commands[-1] == (1, "zero")
    run(conn, runner, clock, 0.2)                                 # Null bestätigt
    assert runner.flow(1).step == "place"
    hub.put(1, 1250)                                              # Behälter aufstellen
    run(conn, runner, clock, 0.4)
    assert runner.flow(1).step == "final_zero" and hub.commands[-1] == (1, "tare")
    assert runner.reading(1).hint == "Waage wird genullt – bitte warten"
    run(conn, runner, clock, 0.6)                                 # Michael 22:38: ½ s nach der Tara Null
    assert hub.commands[-2:] == [(1, "tare"), (1, "zero")]
    run(conn, runner, clock, 0.6)                                 # neuer Bezug = Anzeige nach Null
    assert runner.flow(1) is None
    batch = batches.get_batch(conn, batch["id"], runner)
    assert batch["container_g"] == 1250 and batch["scale"]["actual_g"] == 0 and batch["scale"]["gross_g"] == 1250
    assert events(conn, "container")[0][1] == 1250 and events(conn, "container")[0][4] == "gewogen"
    batch = batches.container(conn, batch["id"], st(action="set", container_g=1200), runner)
    assert batch["container_g"] == 1200


def test_container_weigh_mid_ingredient_starts_at_zero(conn, brot, runner, hub, clock):
    # Michael 16:18: „Behälter wiegen“ mitten in der Zutat – im neuen Behälter wieder bei 0, keine Teilmenge
    hub.put(1, 800 + 400)                                         # 400 g Mehl im alten Behälter
    batch = batches.container(conn, brot["id"], st(action="weigh"), runner)
    assert batch["partial_saved_g"] == 0 and batch["items"][0]["partial_g"] == 0
    hub.put(1, 0)                                                 # alter Behälter weg
    run(conn, runner, clock, ZEROED)
    hub.put(1, 950)                                               # neuer Behälter
    run(conn, runner, clock, 2.2)
    assert runner.flow(1) is None
    batch = batches.get_batch(conn, brot["id"], runner)
    assert batch["container_g"] == 950 and batch["scale"]["actual_g"] == 0
    assert batch["items"][0]["done"] is False and events(conn, "partial") == []


def test_container_weigh_without_container(conn, brot, runner, hub, clock):
    hub.put(1, 0)                                                 # Behälter weg: -----
    batches.container(conn, brot["id"], st(action="weigh"), runner)
    run(conn, runner, clock, ZEROED)
    assert runner.flow(1).step == "place"
    batch = batches.container(conn, brot["id"], st(action="none"), runner)
    assert batch["container_g"] == 0 and runner.flow(1) is None
    hub.put(1, 1000)
    assert batches.get_batch(conn, brot["id"], runner)["scale"]["actual_g"] == 1000


def test_container_weigh_refuses_tared_container(conn, brot, runner, hub, clock):
    # Behälter (800 g, tariert) steht noch: Anzeige 0, aber Gesamtlast 800 g → nicht leer
    batches.container(conn, brot["id"], st(action="weigh"), runner)
    run(conn, runner, clock, 1)
    assert runner.flow(1).step == "empty"
    batches.container(conn, brot["id"], st(action="cancel"), runner)
    assert runner.flow(1) is None


def test_container_change_with_partial(conn, recipes, runner, hub, clock):
    # Mehl 1 000 g passt nicht auf einmal: 700 g, wechseln, Rest 310 g
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 800)
    batch = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)
    batches.container(conn, batch["id"], st(action="weigh"), runner)  # erst Behälter kennen
    hub.put(1, 0)
    run(conn, runner, clock, ZEROED)
    hub.put(1, 800)
    run(conn, runner, clock, 2.2)
    assert batches.get_batch(conn, batch["id"])["container_g"] == 800
    hub.put(1, 800 + 700)
    batch = batches.container(conn, batch["id"], st(action="change"), runner)
    assert batch["partial_saved_g"] == 700 and batch["items"][0]["partial_g"] == 700
    assert batch["scale"]["hint"] == "Behälter abnehmen und ausleeren"
    hub.put(1, 0)                                                 # abgenommen: -----
    run(conn, runner, clock, ZEROED)
    assert hub.commands[-2:] == [(1, "tare"), (1, "zero")] and runner.flow(1).step == "place"
    hub.put(1, 803)                                               # leerer Behälter wieder drauf (3 g Abweichung)
    run(conn, runner, clock, 2.2)
    assert runner.flow(1) is None
    hub.put(1, 803 + 310)
    reading = batches.get_batch(conn, batch["id"], runner)
    assert reading["items"][0]["done"] is False
    run(conn, runner, clock, 2.2)                                 # Auto-Quittung mit Teilmengen
    batch = batches.get_batch(conn, batch["id"], runner)
    assert batch["items"][0]["actual_g"] == 1010 and batch["items"][0]["ack_type"] == "auto_stable"
    weighed = events(conn, "weighed")[0]
    assert weighed[1] == 1010 and weighed[4] == "mit Teilmengen 700 g"
    assert events(conn, "partial")[0][1] == 700


def test_container_change_other_container_needs_confirm(conn, recipes, runner, hub, clock):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)
    batches.container(conn, batch["id"], st(action="set", container_g=800), runner)
    hub.put(1, 500)                                               # 500 g Mehl (ohne Behälterdaten tariert bei 0)
    batches.container(conn, batch["id"], st(action="change"), runner)
    hub.put(1, 0)                                                 # Behälter abgenommen
    run(conn, runner, clock, ZEROED)
    hub.put(1, 1200)                                              # anderer Behälter
    run(conn, runner, clock, 2.2)
    assert runner.flow(1).step == "confirm"
    batch = batches.container(conn, batch["id"], st(action="confirm"), runner)
    assert batch["container_g"] == 1200 and runner.flow(1).step == "final_zero"
    run(conn, runner, clock, 1.4)
    assert runner.flow(1) is None and hub.commands[-1] == (1, "zero")
    assert batches.get_batch(conn, batch["id"], runner)["scale"]["actual_g"] == 0
    assert events(conn, "container")[-1][4] == "gewogen, Abweichung bestätigt"


def test_container_zero_repeated(conn, brot, runner, hub, clock):
    # Michael 17:14: Null wird nicht immer angenommen – bis zu zweimal wiederholen
    hub.put(1, 0)
    hub.zero_misses = 2
    batches.container(conn, brot["id"], st(action="weigh"), runner)
    run(conn, runner, clock, ZEROED)
    assert runner.flow(1).step == "zeroing" and hub.commands.count((1, "zero")) == 1
    run(conn, runner, clock, 2.0)
    assert hub.commands.count((1, "zero")) == 2 and runner.flow(1).step == "zeroing"
    run(conn, runner, clock, 2.2)
    assert hub.commands.count((1, "zero")) == 3 and runner.flow(1).step == "place"


def test_container_zero_fails_then_by_hand(conn, brot, runner, hub, clock):
    hub.put(1, 0)
    hub.zero_misses = 5
    batches.container(conn, brot["id"], st(action="weigh"), runner)
    run(conn, runner, clock, ZEROED + 6.4)
    assert hub.commands.count((1, "zero")) == 3                  # einmal + zwei Wiederholungen
    assert runner.flow(1).step == "zeroing"
    assert runner.reading(1).hint == "Waage leer lassen und an der Waage Null drücken"
    run(conn, runner, clock, 4)
    assert hub.commands.count((1, "zero")) == 3                  # keine weiteren Befehle
    hub.offset[1] = 0                                             # Null von Hand an der Waage
    run(conn, runner, clock, 0.2)
    assert runner.flow(1).step == "place"


def test_pause_refused_during_container_step(conn, brot, runner, hub):
    batches.container(conn, brot["id"], st(action="weigh"), runner)
    with pytest.raises(ConflictError) as exc:
        batches.pause(conn, brot["id"], st(), runner)
    assert exc.value.code == "container_busy"


# -- Handbetrieb (M09-13) -----------------------------------------------------------------------------

def test_hand_tare(conn, brot, runner, hub):
    with pytest.raises(ConflictError) as exc:
        batches.hand_tare(conn, 1, runner)
    assert exc.value.code == "batch_running"
    batches.pause(conn, brot["id"], st(), runner, reason="hand_scale")
    hub.put(1, 1500)
    reading = batches.hand_tare(conn, 1, runner)
    assert reading["actual_g"] == 0
    hub.put(1, 1750)
    assert runner.reading(1).actual_g == 250


def test_weigh_message_without_batch(conn, runner, hub, clock):
    hub.put(1, 0)
    batches.hand_tare(conn, 1, runner)
    hub.put(1, 120)
    run(conn, runner, clock, 0.2)
    weigh = [e for e in hub.events if e["type"] == "weigh"][-1]
    assert weigh["batch_id"] is None and weigh["actual_g"] == 120 and weigh["station"] == 1
