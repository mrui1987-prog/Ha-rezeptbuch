"""API-Tests Modul 09 Teil C1: Aufträge, Chargen, Einstellungen, Live-Nachrichten, Prüfseite
(laufen im GitHub-Testlauf)."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import connect  # noqa: E402
from app.main import app  # noqa: E402

H = "X-Rezeptbuch-Session"
TOPIC = "rezeptbuch/v1/station/{}/scale/state"


def scale(weight, station=1, stable=True, status="ok"):
    return json.dumps({"v": 2, "station": station, "status": status, "weight_g": weight if status == "ok" else None,
                       "stable": stable, "scale_stable": stable, "net": False, "capacity_g": 30000,
                       "resolution_g": 1, "ts": "2026-11-20T08:00:00.000+00:00"}).encode()


async def _stop_connect_task(service):
    task = service._tasks[0]
    task.cancel()
    try:
        await task
    except BaseException:  # noqa: BLE001 – abgebrochen oder schon fertig
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_DB", str(tmp_path / "rezeptbuch.db"))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with TestClient(app) as c:
        c.hub = app.state.scales.hub
        c.portal.call(_stop_connect_task, app.state.scales)
        c.hub.set_publisher(lambda topic, data: True)
        c.portal.call(c.hub.set_mqtt, "connected")
        c.portal.call(c.hub.handle_availability, b"online")
        c.db_path = tmp_path / "rezeptbuch.db"
        yield c


def put(client, weight, station=1, **kw):
    client.portal.call(client.hub.handle_state, TOPIC.format(station), scale(weight, station, **kw))


@pytest.fixture
def auth(client):
    r = client.post("/api/v1/admin/login", json={"pin": "1234"})
    assert r.status_code == 200
    return {H: r.json()["session"]}


@pytest.fixture
def recipe(client, auth):
    """Weißbrot: Mehl 1 000 g (± 20), Wasser 600 g (± 50), Salz 20 g (± 2); entsperrt."""
    ids = []
    for name, kind, tol in (("Weizenmehl 550", "flour", "20"), ("Wasser", "standard", "50"),
                            ("Salz", "standard", "2")):
        r = client.post("/api/v1/admin/raw-materials", headers=auth, json={"name": name, "type": kind,
                                                                             "tolerance": tol})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    r = client.post("/api/v1/admin/recipes", headers=auth, json={
        "name": "Weißbrot", "items": [{"type": "raw_material", "raw_material_id": i, "amount_g": a}
                                      for i, a in zip(ids, (1000, 600, 20))]})
    assert r.status_code == 201, r.text
    recipe_id = r.json()["id"]
    conn = connect(client.db_path)
    conn.execute("UPDATE recipe SET locked = 0 WHERE id = ?", (recipe_id,))
    conn.close()
    return recipe_id


def test_whole_flow_over_rest(client, recipe):
    queue = client.portal.call(_subscribe, client.hub)
    r = client.post("/api/v1/orders", json={"recipe_id": recipe, "basis_type": "total", "value": 1620,
                                            "planned_date": "2026-11-20"})
    assert r.status_code == 201, r.text
    order = r.json()
    assert client.get("/api/v1/orders", params={"date": "2026-11-20"}).json()["orders"][0]["id"] == order["id"]
    put(client, 700)
    r = client.post(f"/api/v1/orders/{order['id']}/start", json={"station": 1})
    assert r.status_code == 201, r.text
    batch = r.json()
    bid = batch["id"]
    assert batch["status"] == "running" and batch["scale"]["actual_g"] == 0
    put(client, 1700)
    r = client.post(f"/api/v1/batches/{bid}/ack", json={"station": 1})
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["actual_g"] == 1000
    put(client, 2500)
    r = client.post(f"/api/v1/batches/{bid}/ack", json={"station": 1})
    assert r.status_code == 409 and r.json()["code"] == "out_of_tolerance"
    put(client, 2300)
    client.post(f"/api/v1/batches/{bid}/ack", json={"station": 1})
    put(client, 2320)
    r = client.post(f"/api/v1/batches/{bid}/ack", json={"station": 1})
    assert r.json()["status"] == "done"
    r = client.post(f"/api/v1/batches/{bid}/finish", json={"station": 1})
    assert r.status_code == 200 and r.json()["finish_ack_at"]
    assert client.get(f"/api/v1/orders/{order['id']}").json()["status"] == "done"
    events = client.portal.call(_drain, queue)
    batch_events = [e["event"] for e in events if e["type"] == "batch"]
    assert batch_events == ["started", "acked", "acked", "finished_dough", "finished"]
    assert any(e["type"] == "orders" for e in events)


async def _subscribe(hub):
    return hub.subscribe()


async def _drain(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def test_errors_and_pause_resume(client, recipe):
    order = client.post("/api/v1/orders", json={"recipe_id": recipe, "basis_type": "total", "value": 1620}).json()
    assert client.post(f"/api/v1/orders/{order['id']}/start", json={"station": 2}).status_code == 409
    assert client.post(f"/api/v1/orders/{order['id']}/start", json={"station": 9}).status_code == 404
    assert client.post(f"/api/v1/orders/{order['id']}/start", json={}).status_code == 400
    put(client, 0)
    bid = client.post(f"/api/v1/orders/{order['id']}/start", json={"station": 1}).json()["id"]
    assert client.post(f"/api/v1/batches/{bid}/pause", json={"station": 1}).json()["status"] == "paused"
    r = client.post(f"/api/v1/batches/{bid}/ack", json={"station": 1})
    assert r.status_code == 409 and r.json()["code"] == "batch_paused"
    listed = client.get("/api/v1/batches").json()["batches"]
    assert listed[0]["status"] == "paused"
    assert client.post(f"/api/v1/batches/{bid}/resume", json={"station": 1}).json()["status"] == "running"
    r = client.post(f"/api/v1/batches/{bid}/cancel", json={"station": 1})
    assert r.status_code == 409 and r.json()["code"] == "confirm_required"
    r = client.post(f"/api/v1/batches/{bid}/cancel", json={"station": 1, "confirm": True})
    assert r.json()["status"] == "cancelled"
    assert client.get("/api/v1/batches/999").status_code == 404


def test_delete_order(client, recipe):
    order = client.post("/api/v1/orders", json={"recipe_id": recipe, "basis_type": "total", "value": 1620}).json()
    assert client.request("DELETE", f"/api/v1/orders/{order['id']}").status_code == 409
    assert client.request("DELETE", f"/api/v1/orders/{order['id']}", json={"confirm": True}).status_code == 204
    assert client.get(f"/api/v1/orders/{order['id']}").status_code == 404


def test_settings_read_free_write_with_pin(client, auth):
    body = client.get("/api/v1/production-settings").json()
    values = {s["key"]: s["value"] for s in body["settings"]}
    assert values == {"auto_ack_seconds": 2, "auto_ack_span_g": 5, "offline_pause_seconds": 45,
                      "capacity_warn_g": 1000, "tare_confirm_seconds": 3, "resume_check_g": 5}
    assert client.put("/api/v1/admin/production-settings", json={"auto_ack_seconds": 3}).status_code == 401
    r = client.put("/api/v1/admin/production-settings", headers=auth, json={"auto_ack_seconds": 3})
    assert r.status_code == 200
    assert {s["key"]: s["value"] for s in r.json()["settings"]}["auto_ack_seconds"] == 3
    r = client.put("/api/v1/admin/production-settings", headers=auth, json={"auto_ack_seconds": 99})
    assert r.status_code == 400 and r.json()["field"] == "auto_ack_seconds"


def test_page(client):
    r = client.get("/admin/ablauf")
    assert r.status_code == 200 and "Ablauf" in r.text
    assert r.headers["cache-control"] == "no-store"
