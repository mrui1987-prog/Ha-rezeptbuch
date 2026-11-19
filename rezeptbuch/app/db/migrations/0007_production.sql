-- migration: foreign_keys=off
--
-- Migration 0007 – Produktions- und Wiegeablauf (Modul 09, docs/ablauf.md Abschnitt 12, K09-1)
--
-- * batch_item.ack_type zusätzlich 'sub_done' (Unterrezept gewogen, K09-1) und 'manual_stable'
--   (von Hand quittiert, Waage stabil, K09-2)
-- * weighing_event.event_type zusätzlich 'resume_deviation' (Abweichung beim „Weiter“ bestätigt, K09-12),
--   'container' (Behältergewicht, K09-13) und 'partial' (Teilmenge beim Behälterwechsel, K09-14);
--   neue Spalte note (z. B. Herkunft des Behältergewichts)
-- * batch: pause_reason, paused_at, pause_load_g (K09-12), finish_ack_at (K09-10), container_g (K09-13),
--   current_position (aktuelle Zutat, übersteht einen Neustart)
-- * production_order.sub_modes: Unterrezept „je Teig“ oder „für alle“ je Zeile, bis zum Start gemerkt
-- * Abgeschlossene Charge: nur noch finish_ack_at darf einmal gesetzt werden (Behälter abgenommen)
-- * Einstellungen (docs/ablauf.md Abschnitt 10): Startwerte stehen im Code (app/production/settings.py),
--   in der Tabelle setting nur geänderte Werte
--
-- Die CHECK-Regeln von ack_type und event_type lassen sich nur per Neuaufbau ändern (wie 0006).
-- Bisher gibt es keine Chargen im Betrieb; vorhandene Zeilen werden trotzdem vollständig kopiert.

-- ---------------------------------------------------------------------------
-- Auftrag: Unterrezept-Modus (JSON {"Position": "per_dough"|"all"})
-- ---------------------------------------------------------------------------

ALTER TABLE production_order
    ADD COLUMN sub_modes TEXT CHECK (sub_modes IS NULL OR json_valid(sub_modes));

-- ---------------------------------------------------------------------------
-- Charge: neue Spalten
-- ---------------------------------------------------------------------------

ALTER TABLE batch ADD COLUMN pause_reason TEXT
    CHECK (pause_reason IS NULL OR pause_reason IN ('manual', 'scale_offline', 'restart', 'hand_scale'));
ALTER TABLE batch ADD COLUMN paused_at TEXT;
-- Gesamtlast beim Pausieren in Gramm (Lastprüfung beim „Weiter“, K09-12)
ALTER TABLE batch ADD COLUMN pause_load_g INTEGER;
-- Behälter abgenommen bzw. von Hand abgeschlossen (K09-10)
ALTER TABLE batch ADD COLUMN finish_ack_at TEXT;
-- Behältergewicht in Gramm; leer = unbekannt (K09-13)
ALTER TABLE batch ADD COLUMN container_g INTEGER CHECK (container_g IS NULL OR container_g >= 0);
-- Position der aktuellen Zutat; leer = noch keine gewählt
ALTER TABLE batch ADD COLUMN current_position INTEGER CHECK (current_position IS NULL OR current_position >= 1);

-- Abgeschlossene Chargen bleiben unveränderlich – Ausnahme: finish_ack_at einmal setzen (K09-10)
DROP TRIGGER trg_batch_closed_update;
CREATE TRIGGER trg_batch_closed_update
BEFORE UPDATE ON batch
WHEN OLD.status IN ('done', 'cancelled')
 AND NOT (OLD.status = 'done' AND NEW.status = 'done' AND OLD.finish_ack_at IS NULL
          AND NEW.finish_ack_at IS NOT NULL
          AND NEW.batch_no IS OLD.batch_no AND NEW.order_id IS OLD.order_id
          AND NEW.dough_index IS OLD.dough_index AND NEW.recipe_version_id IS OLD.recipe_version_id
          AND NEW.started_at IS OLD.started_at AND NEW.finished_at IS OLD.finished_at
          AND NEW.container_g IS OLD.container_g)
BEGIN
    SELECT RAISE(ABORT, 'Charge ist abgeschlossen und kann nicht geändert werden');
END;

-- ---------------------------------------------------------------------------
-- batch_item neu aufbauen (ack_type)
-- ---------------------------------------------------------------------------

CREATE TABLE batch_item_new (
    id                   INTEGER PRIMARY KEY,
    batch_id             INTEGER NOT NULL REFERENCES batch (id) ON DELETE RESTRICT,
    position             INTEGER NOT NULL CHECK (position >= 1),
    recipe_item_id       INTEGER REFERENCES recipe_item (id) ON DELETE RESTRICT,
    item_type            TEXT    NOT NULL CHECK (item_type IN ('raw_material', 'sub_recipe')),
    raw_material_id      INTEGER REFERENCES raw_material (id) ON DELETE RESTRICT,
    -- Kopie zum Zeitpunkt der Produktion
    raw_material_number  INTEGER,
    raw_material_name    TEXT,
    sub_order_id         INTEGER REFERENCES production_order (id) ON DELETE RESTRICT,
    target_g             INTEGER NOT NULL CHECK (target_g >= 0),
    -- Toleranz ± in Gramm, gilt für die Restmenge (M02-2d, K1)
    tolerance_g          INTEGER NOT NULL CHECK (tolerance_g >= 0),
    unit_size_g          INTEGER CHECK (unit_size_g IS NULL OR unit_size_g > 0),
    unit_label           TEXT,
    units_target         INTEGER NOT NULL DEFAULT 0 CHECK (units_target >= 0),
    rest_target_g        INTEGER NOT NULL CHECK (rest_target_g >= 0),
    actual_g             INTEGER,
    ack_type             TEXT
        CHECK (ack_type IS NULL OR ack_type IN
               ('auto_stable', 'manual_stable', 'manual_unstable', 'hand', 'sub_checked', 'sub_done',
                'skipped')),
    station_id           INTEGER REFERENCES station (id) ON DELETE RESTRICT,
    acknowledged_at      TEXT,
    UNIQUE (batch_id, position),
    -- Sollmenge = ganze Einheiten × Größe + Rest (M02-2c)
    CHECK (
        (unit_size_g IS NULL AND units_target = 0 AND rest_target_g = target_g)
        OR (unit_size_g IS NOT NULL AND units_target * unit_size_g + rest_target_g = target_g)
    ),
    CHECK ((unit_size_g IS NULL) = (unit_label IS NULL)),
    CHECK ((ack_type IS NULL) = (acknowledged_at IS NULL)),
    CHECK (item_type <> 'raw_material'
           OR (raw_material_id IS NOT NULL AND raw_material_number IS NOT NULL AND raw_material_name IS NOT NULL))
);

INSERT INTO batch_item_new (
    id, batch_id, position, recipe_item_id, item_type, raw_material_id, raw_material_number, raw_material_name,
    sub_order_id, target_g, tolerance_g, unit_size_g, unit_label, units_target, rest_target_g, actual_g,
    ack_type, station_id, acknowledged_at)
SELECT
    id, batch_id, position, recipe_item_id, item_type, raw_material_id, raw_material_number, raw_material_name,
    sub_order_id, target_g, tolerance_g, unit_size_g, unit_label, units_target, rest_target_g, actual_g,
    ack_type, station_id, acknowledged_at
FROM batch_item;

DROP TABLE batch_item;

PRAGMA legacy_alter_table = ON;
ALTER TABLE batch_item_new RENAME TO batch_item;
PRAGMA legacy_alter_table = OFF;

-- Trigger aus 0001 und 0005 unverändert neu anlegen
CREATE TRIGGER trg_batch_item_closed_insert
BEFORE INSERT ON batch_item
WHEN (SELECT status FROM batch WHERE id = NEW.batch_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Charge ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_batch_item_closed_update
BEFORE UPDATE ON batch_item
WHEN (SELECT status FROM batch WHERE id = OLD.batch_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Charge ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_batch_item_closed_delete
BEFORE DELETE ON batch_item
WHEN (SELECT status FROM batch WHERE id = OLD.batch_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Charge ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_batch_item_version_insert
BEFORE INSERT ON batch_item
WHEN NEW.recipe_item_id IS NOT NULL
 AND (SELECT recipe_version_id FROM recipe_item WHERE id = NEW.recipe_item_id)
     IS NOT (SELECT recipe_version_id FROM batch WHERE id = NEW.batch_id)
BEGIN
    SELECT RAISE(ABORT, 'Die Rezeptzeile gehört nicht zur Version der Charge');
END;

CREATE TRIGGER trg_batch_item_version_update
BEFORE UPDATE OF recipe_item_id, batch_id ON batch_item
WHEN NEW.recipe_item_id IS NOT NULL
 AND (SELECT recipe_version_id FROM recipe_item WHERE id = NEW.recipe_item_id)
     IS NOT (SELECT recipe_version_id FROM batch WHERE id = NEW.batch_id)
BEGIN
    SELECT RAISE(ABORT, 'Die Rezeptzeile gehört nicht zur Version der Charge');
END;

-- ---------------------------------------------------------------------------
-- weighing_event neu aufbauen (event_type, Spalte note)
-- ---------------------------------------------------------------------------

CREATE TABLE weighing_event_new (
    id             INTEGER PRIMARY KEY,
    batch_item_id  INTEGER NOT NULL REFERENCES batch_item (id) ON DELETE RESTRICT,
    event_type     TEXT    NOT NULL
        CHECK (event_type IN ('units_ack', 'weighed', 'hand', 'sub_checked', 'skipped', 'tare_set',
                              'resume_deviation', 'container', 'partial')),
    units          INTEGER CHECK (units IS NULL OR units >= 0),
    weight_g       INTEGER,
    tare_g         INTEGER,
    stable         INTEGER CHECK (stable IS NULL OR stable IN (0, 1)),
    station_id     INTEGER NOT NULL REFERENCES station (id) ON DELETE RESTRICT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- Migration 0007: kurzer Vermerk (z. B. Herkunft des Behältergewichts, Auswahl beim „Weiter“)
    note           TEXT,
    CHECK (event_type <> 'units_ack' OR units IS NOT NULL),
    CHECK (event_type NOT IN ('weighed', 'resume_deviation', 'container', 'partial') OR weight_g IS NOT NULL)
);

INSERT INTO weighing_event_new (
    id, batch_item_id, event_type, units, weight_g, tare_g, stable, station_id, created_at)
SELECT id, batch_item_id, event_type, units, weight_g, tare_g, stable, station_id, created_at
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

-- ---------------------------------------------------------------------------
-- Eine laufende Charge je Station (M09-11)
-- ---------------------------------------------------------------------------

CREATE UNIQUE INDEX idx_batch_running_station ON batch (owner_station_id) WHERE status = 'running';
