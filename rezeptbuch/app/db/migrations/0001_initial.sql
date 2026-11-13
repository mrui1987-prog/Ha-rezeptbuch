-- 0001_initial.sql – Grundschema HA-Rezeptbuch (Modul 02)
--
-- Grundlage: docs/datenmodell.md (freigegeben am 13.11.2026)
-- Regeln:
--   * Gewichte in ganzen Gramm (INTEGER)
--   * Prozentwerte in Zehntelprozent (25 = 2,5 %)
--   * Zeitpunkte als Text ISO 8601 in UTC, z. B. 2026-11-13T17:30:00Z
--   * Diese Datei wird nach der Auslieferung nie mehr geändert.
--     Änderungen kommen als neue Migration (0002_..., 0003_...).

-- ---------------------------------------------------------------------------
-- Stammdaten
-- ---------------------------------------------------------------------------

CREATE TABLE station (
    id      INTEGER PRIMARY KEY CHECK (id >= 1),
    name    TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    active  INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

-- Waage 2 ist vorbereitet, aber erst nach Einrichtung aktiv
INSERT INTO station (id, name, active) VALUES (1, 'Waage 1', 1), (2, 'Waage 2', 0);

CREATE TABLE raw_material (
    id               INTEGER PRIMARY KEY,
    number           INTEGER NOT NULL UNIQUE CHECK (number > 0),
    name             TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    type             TEXT    NOT NULL DEFAULT 'standard' CHECK (type IN ('standard', 'flour')),
    tolerance_unit   TEXT    NOT NULL DEFAULT 'g' CHECK (tolerance_unit IN ('g', 'percent')),
    tolerance_value  INTEGER NOT NULL CHECK (tolerance_value >= 0),
    unit_size_g      INTEGER CHECK (unit_size_g IS NULL OR unit_size_g > 0),
    unit_label       TEXT    CHECK (unit_label IS NULL OR length(trim(unit_label)) > 0),
    source           TEXT    NOT NULL DEFAULT 'own' CHECK (source IN ('baeko', 'own')),
    archived         INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- Gebinde-/Stückgröße und Bezeichnung nur gemeinsam (z. B. 55 g „Ei“)
    CHECK ((unit_size_g IS NULL) = (unit_label IS NULL)),
    -- Prozent-Toleranz höchstens 100,0 %
    CHECK (tolerance_unit <> 'percent' OR tolerance_value <= 1000)
);

-- ---------------------------------------------------------------------------
-- Rezepte
-- ---------------------------------------------------------------------------

CREATE TABLE recipe_group (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE recipe (
    id                  INTEGER PRIMARY KEY,
    number              INTEGER NOT NULL UNIQUE CHECK (number > 0),
    group_id            INTEGER REFERENCES recipe_group (id) ON DELETE RESTRICT,
    -- NO ACTION statt RESTRICT: wird erst am Ende der Anweisung geprüft,
    -- damit ein nie verwendetes Rezept samt Versionen gelöscht werden kann
    current_version_id  INTEGER REFERENCES recipe_version (id) ON DELETE NO ACTION,
    locked              INTEGER NOT NULL CHECK (locked IN (0, 1)),
    archived            INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE recipe_version (
    id              INTEGER PRIMARY KEY,
    recipe_id       INTEGER NOT NULL REFERENCES recipe (id) ON DELETE CASCADE,
    version_no      INTEGER NOT NULL CHECK (version_no >= 1),
    name            TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    piece_weight_g  INTEGER CHECK (piece_weight_g IS NULL OR piece_weight_g > 0),
    note            TEXT,
    note_display    TEXT    NOT NULL DEFAULT 'end' CHECK (note_display IN ('start', 'end')),
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- gesetzt, sobald die Version in einem Auftrag fixiert wurde (danach unveränderlich)
    frozen_at       TEXT,
    UNIQUE (recipe_id, version_no)
);

CREATE TABLE recipe_version_step (
    id                 INTEGER PRIMARY KEY,
    recipe_version_id  INTEGER NOT NULL REFERENCES recipe_version (id) ON DELETE CASCADE,
    step_no            INTEGER NOT NULL CHECK (step_no >= 1),
    name               TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    UNIQUE (recipe_version_id, step_no)
);

CREATE TABLE recipe_item (
    id                 INTEGER PRIMARY KEY,
    recipe_version_id  INTEGER NOT NULL REFERENCES recipe_version (id) ON DELETE CASCADE,
    position           INTEGER NOT NULL CHECK (position >= 1),
    item_type          TEXT    NOT NULL CHECK (item_type IN ('raw_material', 'sub_recipe')),
    raw_material_id    INTEGER REFERENCES raw_material (id) ON DELETE RESTRICT,
    sub_recipe_id      INTEGER REFERENCES recipe (id) ON DELETE RESTRICT,
    amount_g           INTEGER NOT NULL CHECK (amount_g > 0),
    -- überschreibt die Rohstoff-Toleranz (± ein Wert), beide leer = Rohstoff-Toleranz
    tolerance_unit     TEXT    CHECK (tolerance_unit IS NULL OR tolerance_unit IN ('g', 'percent')),
    tolerance_value    INTEGER CHECK (tolerance_value IS NULL OR tolerance_value >= 0),
    step_no            INTEGER,
    UNIQUE (recipe_version_id, position),
    FOREIGN KEY (recipe_version_id, step_no)
        REFERENCES recipe_version_step (recipe_version_id, step_no) ON DELETE NO ACTION,
    CHECK (
        (item_type = 'raw_material' AND raw_material_id IS NOT NULL AND sub_recipe_id IS NULL)
        OR (item_type = 'sub_recipe' AND sub_recipe_id IS NOT NULL AND raw_material_id IS NULL)
    ),
    CHECK ((tolerance_unit IS NULL) = (tolerance_value IS NULL)),
    CHECK (tolerance_unit IS NOT 'percent' OR tolerance_value <= 1000)
);

CREATE INDEX idx_recipe_item_raw_material ON recipe_item (raw_material_id);
CREATE INDEX idx_recipe_item_sub_recipe ON recipe_item (sub_recipe_id);

CREATE TABLE recipe_batch_size (
    id          INTEGER PRIMARY KEY,
    recipe_id   INTEGER NOT NULL REFERENCES recipe (id) ON DELETE CASCADE,
    label       TEXT    NOT NULL CHECK (length(trim(label)) > 0),
    kind        TEXT    NOT NULL CHECK (kind IN ('weight', 'pieces')),
    value       INTEGER NOT NULL CHECK (value > 0),
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_recipe_batch_size_recipe ON recipe_batch_size (recipe_id);

-- ---------------------------------------------------------------------------
-- Produktion
-- ---------------------------------------------------------------------------

CREATE TABLE production_order (
    id                     INTEGER PRIMARY KEY,
    recipe_id              INTEGER NOT NULL REFERENCES recipe (id) ON DELETE RESTRICT,
    -- beim Start des ersten Teigs einmal für den ganzen Auftrag fixiert (R2, K6)
    recipe_version_id      INTEGER REFERENCES recipe_version (id) ON DELETE RESTRICT,
    parent_order_id        INTEGER REFERENCES production_order (id) ON DELETE RESTRICT,
    parent_item_position   INTEGER,
    basis_type             TEXT    NOT NULL
        CHECK (basis_type IN ('total', 'pieces', 'batch_size', 'raw_material', 'flour_total')),
    basis_value            INTEGER NOT NULL CHECK (basis_value > 0),
    basis_raw_material_id  INTEGER REFERENCES raw_material (id) ON DELETE RESTRICT,
    basis_input_unit       TEXT    NOT NULL DEFAULT 'g' CHECK (basis_input_unit IN ('g', 'kg', 'l', 'pcs')),
    batch_size_id          INTEGER REFERENCES recipe_batch_size (id) ON DELETE SET NULL,
    dough_count            INTEGER NOT NULL DEFAULT 1 CHECK (dough_count >= 1),
    fixed_station_id       INTEGER REFERENCES station (id) ON DELETE RESTRICT,
    planned_date           TEXT,
    list_position          INTEGER,
    status                 TEXT    NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'in_progress', 'done', 'cancelled')),
    created_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finished_at            TEXT,
    -- Leitrohstoff nur bei basis_type 'raw_material', dort Pflicht
    CHECK ((basis_type = 'raw_material') = (basis_raw_material_id IS NOT NULL)),
    -- Liter-Eingabe nur beim Leitrohstoff (M02-1e)
    CHECK (basis_input_unit <> 'l' OR basis_type = 'raw_material'),
    CHECK ((parent_order_id IS NULL) = (parent_item_position IS NULL)),
    CHECK (status = 'open' OR status = 'cancelled' OR recipe_version_id IS NOT NULL)
);

CREATE INDEX idx_production_order_list ON production_order (status, planned_date, list_position);
CREATE INDEX idx_production_order_parent ON production_order (parent_order_id);

CREATE TABLE order_item_override (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES production_order (id) ON DELETE CASCADE,
    item_position  INTEGER NOT NULL CHECK (item_position >= 1),
    amount_g       INTEGER NOT NULL CHECK (amount_g >= 0),
    UNIQUE (order_id, item_position)
);

CREATE TABLE batch (
    id                 INTEGER PRIMARY KEY,
    batch_no           TEXT    NOT NULL UNIQUE CHECK (length(trim(batch_no)) > 0),
    order_id           INTEGER NOT NULL REFERENCES production_order (id) ON DELETE RESTRICT,
    dough_index        INTEGER NOT NULL CHECK (dough_index >= 1),
    recipe_version_id  INTEGER REFERENCES recipe_version (id) ON DELETE RESTRICT,
    status             TEXT    NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'running', 'paused', 'done', 'cancelled')),
    owner_station_id   INTEGER REFERENCES station (id) ON DELETE RESTRICT,
    started_at         TEXT,
    finished_at        TEXT,
    UNIQUE (order_id, dough_index),
    CHECK (status IN ('open', 'cancelled') OR recipe_version_id IS NOT NULL)
);

CREATE TABLE batch_item (
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
               ('auto_stable', 'manual_unstable', 'hand', 'sub_checked', 'skipped')),
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

CREATE TABLE weighing_event (
    id             INTEGER PRIMARY KEY,
    batch_item_id  INTEGER NOT NULL REFERENCES batch_item (id) ON DELETE RESTRICT,
    event_type     TEXT    NOT NULL
        CHECK (event_type IN ('units_ack', 'weighed', 'hand', 'sub_checked', 'skipped', 'tare_set')),
    units          INTEGER CHECK (units IS NULL OR units >= 0),
    weight_g       INTEGER,
    tare_g         INTEGER,
    stable         INTEGER CHECK (stable IS NULL OR stable IN (0, 1)),
    station_id     INTEGER NOT NULL REFERENCES station (id) ON DELETE RESTRICT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (event_type <> 'units_ack' OR units IS NOT NULL),
    CHECK (event_type <> 'weighed' OR weight_g IS NOT NULL)
);

CREATE INDEX idx_weighing_event_item ON weighing_event (batch_item_id);

-- ---------------------------------------------------------------------------
-- System
-- ---------------------------------------------------------------------------

CREATE TABLE setting (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE change_log (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    source      TEXT    NOT NULL CHECK (source IN ('admin', 'station_1', 'station_2', 'import', 'system')),
    entity      TEXT    NOT NULL,
    entity_id   INTEGER NOT NULL,
    action      TEXT    NOT NULL
        CHECK (action IN ('create', 'update', 'archive', 'restore', 'delete', 'new_version')),
    old_values  TEXT CHECK (old_values IS NULL OR json_valid(old_values)),
    new_values  TEXT CHECK (new_values IS NULL OR json_valid(new_values))
);

CREATE INDEX idx_change_log_entity ON change_log (entity, entity_id);

CREATE TABLE migration_log (
    version      INTEGER PRIMARY KEY,
    file_name    TEXT NOT NULL,
    applied_at   TEXT NOT NULL,
    backup_file  TEXT
);

-- ---------------------------------------------------------------------------
-- Trigger: Datenintegrität
-- ---------------------------------------------------------------------------

-- Aktuelle Version muss zum Rezept gehören
CREATE TRIGGER trg_recipe_current_version_check
BEFORE UPDATE OF current_version_id ON recipe
WHEN NEW.current_version_id IS NOT NULL
 AND (SELECT recipe_id FROM recipe_version WHERE id = NEW.current_version_id) IS NOT NEW.id
BEGIN
    SELECT RAISE(ABORT, 'Die Version gehört nicht zu diesem Rezept');
END;

-- Rezept darf sich nicht direkt selbst als Unterrezept enthalten
-- (Umwege über andere Rezepte prüft der Rezeptserver, Modul 05)
CREATE TRIGGER trg_recipe_item_no_self_insert
BEFORE INSERT ON recipe_item
WHEN NEW.sub_recipe_id IS NOT NULL
 AND NEW.sub_recipe_id = (SELECT recipe_id FROM recipe_version WHERE id = NEW.recipe_version_id)
BEGIN
    SELECT RAISE(ABORT, 'Ein Rezept kann sich nicht selbst als Unterrezept enthalten');
END;

CREATE TRIGGER trg_recipe_item_no_self_update
BEFORE UPDATE ON recipe_item
WHEN NEW.sub_recipe_id IS NOT NULL
 AND NEW.sub_recipe_id = (SELECT recipe_id FROM recipe_version WHERE id = NEW.recipe_version_id)
BEGIN
    SELECT RAISE(ABORT, 'Ein Rezept kann sich nicht selbst als Unterrezept enthalten');
END;

-- Fixierte Versionen sind unveränderlich (K4)
CREATE TRIGGER trg_recipe_version_frozen_update
BEFORE UPDATE ON recipe_version
WHEN OLD.frozen_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Version ist in Produktion verwendet – bitte neue Version speichern');
END;

CREATE TRIGGER trg_recipe_version_frozen_delete
BEFORE DELETE ON recipe_version
WHEN OLD.frozen_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Version ist in Produktion verwendet und kann nicht gelöscht werden');
END;

CREATE TRIGGER trg_recipe_item_frozen_insert
BEFORE INSERT ON recipe_item
WHEN (SELECT frozen_at FROM recipe_version WHERE id = NEW.recipe_version_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Version ist in Produktion verwendet – bitte neue Version speichern');
END;

CREATE TRIGGER trg_recipe_item_frozen_update
BEFORE UPDATE ON recipe_item
WHEN (SELECT frozen_at FROM recipe_version WHERE id = OLD.recipe_version_id) IS NOT NULL
  OR (SELECT frozen_at FROM recipe_version WHERE id = NEW.recipe_version_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Version ist in Produktion verwendet – bitte neue Version speichern');
END;

CREATE TRIGGER trg_recipe_item_frozen_delete
BEFORE DELETE ON recipe_item
WHEN (SELECT frozen_at FROM recipe_version WHERE id = OLD.recipe_version_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Version ist in Produktion verwendet – bitte neue Version speichern');
END;

CREATE TRIGGER trg_recipe_step_frozen_insert
BEFORE INSERT ON recipe_version_step
WHEN (SELECT frozen_at FROM recipe_version WHERE id = NEW.recipe_version_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Version ist in Produktion verwendet – bitte neue Version speichern');
END;

CREATE TRIGGER trg_recipe_step_frozen_update
BEFORE UPDATE ON recipe_version_step
WHEN (SELECT frozen_at FROM recipe_version WHERE id = OLD.recipe_version_id) IS NOT NULL
  OR (SELECT frozen_at FROM recipe_version WHERE id = NEW.recipe_version_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Version ist in Produktion verwendet – bitte neue Version speichern');
END;

CREATE TRIGGER trg_recipe_step_frozen_delete
BEFORE DELETE ON recipe_version_step
WHEN (SELECT frozen_at FROM recipe_version WHERE id = OLD.recipe_version_id) IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Version ist in Produktion verwendet – bitte neue Version speichern');
END;

-- Auftrag: Version muss zum Rezept gehören und bleibt nach dem Fixieren gleich (K6)
CREATE TRIGGER trg_order_version_insert
BEFORE INSERT ON production_order
WHEN NEW.recipe_version_id IS NOT NULL
 AND (SELECT recipe_id FROM recipe_version WHERE id = NEW.recipe_version_id) IS NOT NEW.recipe_id
BEGIN
    SELECT RAISE(ABORT, 'Die Version gehört nicht zum Rezept des Auftrags');
END;

CREATE TRIGGER trg_order_version_update
BEFORE UPDATE OF recipe_version_id, recipe_id ON production_order
BEGIN
    SELECT RAISE(ABORT, 'Die Rezeptversion des Auftrags ist bereits fixiert')
    WHERE OLD.recipe_version_id IS NOT NULL
      AND (NEW.recipe_version_id IS NOT OLD.recipe_version_id OR NEW.recipe_id IS NOT OLD.recipe_id);
    SELECT RAISE(ABORT, 'Die Version gehört nicht zum Rezept des Auftrags')
    WHERE NEW.recipe_version_id IS NOT NULL
      AND (SELECT recipe_id FROM recipe_version WHERE id = NEW.recipe_version_id) IS NOT NEW.recipe_id;
END;

-- Fixieren im Auftrag sperrt die Version automatisch
CREATE TRIGGER trg_order_freeze_version_insert
AFTER INSERT ON production_order
WHEN NEW.recipe_version_id IS NOT NULL
BEGIN
    UPDATE recipe_version SET frozen_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = NEW.recipe_version_id AND frozen_at IS NULL;
END;

CREATE TRIGGER trg_order_freeze_version_update
AFTER UPDATE OF recipe_version_id ON production_order
WHEN NEW.recipe_version_id IS NOT NULL
BEGIN
    UPDATE recipe_version SET frozen_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = NEW.recipe_version_id AND frozen_at IS NULL;
END;

-- Charge: Version immer gleich der des Auftrags (K6)
CREATE TRIGGER trg_batch_version_insert
BEFORE INSERT ON batch
WHEN NEW.recipe_version_id IS NOT NULL
 AND NEW.recipe_version_id IS NOT (SELECT recipe_version_id FROM production_order WHERE id = NEW.order_id)
BEGIN
    SELECT RAISE(ABORT, 'Die Charge muss die Version des Auftrags verwenden');
END;

CREATE TRIGGER trg_batch_version_update
BEFORE UPDATE ON batch
WHEN NEW.recipe_version_id IS NOT NULL
 AND NEW.recipe_version_id IS NOT (SELECT recipe_version_id FROM production_order WHERE id = NEW.order_id)
BEGIN
    SELECT RAISE(ABORT, 'Die Charge muss die Version des Auftrags verwenden');
END;

-- Abgeschlossene Chargen sind unveränderlich
CREATE TRIGGER trg_batch_closed_update
BEFORE UPDATE ON batch
WHEN OLD.status IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Charge ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_batch_closed_delete
BEFORE DELETE ON batch
WHEN OLD.status IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Charge ist abgeschlossen und kann nicht gelöscht werden');
END;

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

-- Wiegeprotokoll: nur anhängen, nie ändern oder löschen
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

-- Änderungsprotokoll: nur anhängen
CREATE TRIGGER trg_change_log_no_update
BEFORE UPDATE ON change_log
BEGIN
    SELECT RAISE(ABORT, 'Änderungsprotokoll kann nicht geändert werden');
END;

CREATE TRIGGER trg_change_log_no_delete
BEFORE DELETE ON change_log
BEGIN
    SELECT RAISE(ABORT, 'Änderungsprotokoll kann nicht gelöscht werden');
END;

-- Mengenänderungen im Auftrag nur, solange er nicht abgeschlossen ist
CREATE TRIGGER trg_override_closed_insert
BEFORE INSERT ON order_item_override
WHEN (SELECT status FROM production_order WHERE id = NEW.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_override_closed_update
BEFORE UPDATE ON order_item_override
WHEN (SELECT status FROM production_order WHERE id = OLD.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_override_closed_delete
BEFORE DELETE ON order_item_override
WHEN (SELECT status FROM production_order WHERE id = OLD.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;
