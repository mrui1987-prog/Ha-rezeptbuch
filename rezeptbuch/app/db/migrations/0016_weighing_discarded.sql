-- migration: foreign_keys=off
--
-- Migration 0016 – Verworfene Menge im Wiegeprotokoll (Modul 09, M09-20, Michael 24.11.2026, 14:18)
--
-- * weighing_event.event_type zusätzlich 'discarded': beim „Behälter wechseln“ über Soll + Toleranz gewählt
--   „Verwerfen – Zutat neu wiegen“; weight_g = verworfene Menge (Pflicht). Die Ware wird bei
--   bestandsgeführten Rohstoffen als Abgang (Grund „other“, Vermerk „beim Wiegen verworfen“) gebucht.
-- Die CHECK-Regel lässt sich nur per Neuaufbau ändern (wie 0007); Zeilen, Index und Trigger bleiben gleich.

CREATE TABLE weighing_event_new (
    id             INTEGER PRIMARY KEY,
    batch_item_id  INTEGER NOT NULL REFERENCES batch_item (id) ON DELETE RESTRICT,
    event_type     TEXT    NOT NULL
        CHECK (event_type IN ('units_ack', 'weighed', 'hand', 'sub_checked', 'skipped', 'tare_set',
                              'resume_deviation', 'container', 'partial', 'discarded')),
    units          INTEGER CHECK (units IS NULL OR units >= 0),
    weight_g       INTEGER,
    tare_g         INTEGER,
    stable         INTEGER CHECK (stable IS NULL OR stable IN (0, 1)),
    station_id     INTEGER NOT NULL REFERENCES station (id) ON DELETE RESTRICT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    note           TEXT,
    CHECK (event_type <> 'units_ack' OR units IS NOT NULL),
    CHECK (event_type NOT IN ('weighed', 'resume_deviation', 'container', 'partial', 'discarded')
           OR weight_g IS NOT NULL)
);

INSERT INTO weighing_event_new (
    id, batch_item_id, event_type, units, weight_g, tare_g, stable, station_id, created_at, note)
SELECT id, batch_item_id, event_type, units, weight_g, tare_g, stable, station_id, created_at, note
FROM weighing_event;

DROP TABLE weighing_event;

PRAGMA legacy_alter_table = ON;
ALTER TABLE weighing_event_new RENAME TO weighing_event;
PRAGMA legacy_alter_table = OFF;

CREATE INDEX idx_weighing_event_item ON weighing_event (batch_item_id);

CREATE TRIGGER trg_weighing_event_closed_insert
BEFORE INSERT ON weighing_event
WHEN (SELECT b.status FROM batch_item bi JOIN batch b ON b.id = bi.batch_id
      WHERE bi.id = NEW.batch_item_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Charge ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_weighing_event_no_update
BEFORE UPDATE ON weighing_event
BEGIN
    SELECT RAISE(ABORT, 'Wiegeprotokoll kann nicht geändert werden');
END;

CREATE TRIGGER trg_weighing_event_no_delete
BEFORE DELETE ON weighing_event
BEGIN
    SELECT RAISE(ABORT, 'Wiegeprotokoll kann nicht gelöscht werden');
END;
