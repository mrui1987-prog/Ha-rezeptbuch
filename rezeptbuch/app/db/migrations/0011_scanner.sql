-- migration: foreign_keys=off
-- Migration 0011 – Strichcode-Scanner, Teil S1 (Modul 03, docs/strichcode.md 8, freigegeben 22.11.2026, 08:09)
--
-- * storage_location: Lagerorte mit optionalem eigenem Code (M03-25)
-- * raw_material neu aufbauen (CHECK-Regeln), Inhalt unverändert:
--     - Art 'aid' = Hilfs- und Betriebsstoff (M03-26); Bestand in Verpackungseinheiten, intern 1 VE = 1000
--       (unit_size_g = 1000, Preis „je kg“ = Preis je VE, H-B)
--     - Liefergebinde delivery_pack_g/delivery_pack_label (F-1), getrennt vom Waagen-Gebinde
--     - Lagerort 1 und optional 2 mit eigener Beschriftung (M03-25)
-- * raw_material_barcode: Codes je Rohstoff, ein Code genau einem Rohstoff (Regel S1)
-- * purchase: Einkauf als Beleg für „+1 Einkauf“ (O-1 geändert: kein +1 ohne Beleg)
-- * stock_movement neu aufbauen: Arten loss (Abgang), return (Rückgabe, W2), correction (Korrektur, PIN),
--   undo (Rückgängig); Spalten reason, purchase_id, device_id, undo_of_id, stocktake_id, receiving_line_id
--
-- Neuaufbau von raw_material und stock_movement einmal hier für S1, I1 und W1 (docs/strichcode.md 8).

CREATE TABLE storage_location (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    code        TEXT    CHECK (code IS NULL OR length(code) > 0),
    sort        INTEGER NOT NULL DEFAULT 0,
    archived    INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE UNIQUE INDEX idx_storage_location_name ON storage_location (lower(trim(name)));
CREATE UNIQUE INDEX idx_storage_location_code ON storage_location (code) WHERE code IS NOT NULL;

-- ---------------------------------------------------------------------------
-- raw_material neu aufbauen
-- ---------------------------------------------------------------------------

CREATE TABLE raw_material_new (
    id                  INTEGER PRIMARY KEY,
    number              INTEGER NOT NULL UNIQUE CHECK (number > 0),
    name                TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    type                TEXT    NOT NULL DEFAULT 'standard' CHECK (type IN ('standard', 'flour', 'aid')),
    tolerance_unit      TEXT    NOT NULL DEFAULT 'g' CHECK (tolerance_unit IN ('g', 'percent')),
    tolerance_value     INTEGER NOT NULL CHECK (tolerance_value >= 0),
    unit_size_g         INTEGER CHECK (unit_size_g IS NULL OR unit_size_g > 0),
    unit_label          TEXT    CHECK (unit_label IS NULL OR length(trim(unit_label)) > 0),
    source              TEXT    NOT NULL DEFAULT 'own' CHECK (source IN ('own', 'datenlink')),
    archived            INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    display_name        TEXT    CHECK (display_name IS NULL OR length(trim(display_name)) > 0),
    price_cents_per_kg  INTEGER
        CHECK (price_cents_per_kg IS NULL OR (price_cents_per_kg >= 0 AND price_cents_per_kg <= 999999)),
    price_changed_at    TEXT,
    stock_g             INTEGER,
    stock_alert_g       INTEGER CHECK (stock_alert_g IS NULL OR stock_alert_g >= 0),
    datenlink_id        TEXT    CHECK (datenlink_id IS NULL OR length(trim(datenlink_id)) > 0),
    delivery_pack_g     INTEGER CHECK (delivery_pack_g IS NULL OR delivery_pack_g > 0),
    delivery_pack_label TEXT    CHECK (delivery_pack_label IS NULL OR length(trim(delivery_pack_label)) > 0),
    location1_id        INTEGER REFERENCES storage_location (id) ON DELETE SET NULL,
    location1_label     TEXT    CHECK (location1_label IS NULL OR length(trim(location1_label)) > 0),
    location2_id        INTEGER REFERENCES storage_location (id) ON DELETE SET NULL,
    location2_label     TEXT    CHECK (location2_label IS NULL OR length(trim(location2_label)) > 0),
    CHECK ((unit_size_g IS NULL) = (unit_label IS NULL)),
    CHECK ((delivery_pack_g IS NULL) = (delivery_pack_label IS NULL)),
    CHECK (tolerance_unit <> 'percent' OR tolerance_value <= 1000),
    CHECK ((source = 'datenlink') = (datenlink_id IS NOT NULL)),
    -- Hilfs- und Betriebsstoff: immer mit Verpackungseinheit (1 VE = 1000), ohne Toleranz, ohne Liefergebinde
    CHECK (type <> 'aid' OR (unit_size_g = 1000 AND tolerance_value = 0 AND delivery_pack_g IS NULL)),
    CHECK (location2_id IS NULL OR location1_id IS NOT NULL)
);

INSERT INTO raw_material_new (
    id, number, name, type, tolerance_unit, tolerance_value, unit_size_g, unit_label, source, archived,
    created_at, updated_at, display_name, price_cents_per_kg, price_changed_at, stock_g, stock_alert_g,
    datenlink_id)
SELECT
    id, number, name, type, tolerance_unit, tolerance_value, unit_size_g, unit_label, source, archived,
    created_at, updated_at, display_name, price_cents_per_kg, price_changed_at, stock_g, stock_alert_g,
    datenlink_id
FROM raw_material;

DROP TABLE raw_material;

PRAGMA legacy_alter_table = ON;
ALTER TABLE raw_material_new RENAME TO raw_material;
PRAGMA legacy_alter_table = OFF;

CREATE INDEX idx_raw_material_name ON raw_material (name);
CREATE UNIQUE INDEX idx_raw_material_datenlink_active
    ON raw_material (datenlink_id) WHERE archived = 0 AND datenlink_id IS NOT NULL;
CREATE INDEX idx_raw_material_location1 ON raw_material (location1_id);
CREATE INDEX idx_raw_material_location2 ON raw_material (location2_id);

-- Trigger aus 0009 unverändert neu anlegen (gehörte zur alten Tabelle)
CREATE TRIGGER trg_raw_material_number_locked
BEFORE UPDATE OF number ON raw_material
WHEN NEW.number <> OLD.number
 AND (   EXISTS (SELECT 1 FROM recipe_item WHERE raw_material_id = OLD.id)
      OR EXISTS (SELECT 1 FROM production_order WHERE basis_raw_material_id = OLD.id)
      OR EXISTS (SELECT 1 FROM batch_item WHERE raw_material_id = OLD.id))
BEGIN
    SELECT RAISE(ABORT, 'Rohstoffnummer ist in Rezepten verwendet und kann nicht mehr geändert werden');
END;

-- ---------------------------------------------------------------------------
-- Codes und Einkäufe
-- ---------------------------------------------------------------------------

CREATE TABLE raw_material_barcode (
    id               INTEGER PRIMARY KEY,
    raw_material_id  INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE CASCADE,
    code             TEXT    NOT NULL UNIQUE CHECK (length(code) > 0 AND length(code) <= 100),
    format           TEXT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX idx_raw_material_barcode_rm ON raw_material_barcode (raw_material_id);

CREATE TABLE purchase (
    id             INTEGER PRIMARY KEY,
    label          TEXT    NOT NULL CHECK (length(trim(label)) > 0),
    purchase_date  TEXT    NOT NULL CHECK (purchase_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    device_id      TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX idx_purchase_date ON purchase (purchase_date);

-- ---------------------------------------------------------------------------
-- stock_movement neu aufbauen (CHECK-Regel), Inhalt unverändert
-- ---------------------------------------------------------------------------

CREATE TABLE stock_movement_new (
    id                 INTEGER PRIMARY KEY,
    raw_material_id    INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE CASCADE,
    kind               TEXT    NOT NULL CHECK (kind IN ('receipt', 'inventory', 'consumption', 'reversal',
                                                        'planner', 'planner_return', 'loss', 'return',
                                                        'correction', 'undo')),
    delta_g            INTEGER,
    stock_after_g      INTEGER,
    batch_id           INTEGER REFERENCES batch (id) ON DELETE RESTRICT,
    batch_item_id      INTEGER REFERENCES batch_item (id) ON DELETE RESTRICT,
    station_id         INTEGER REFERENCES station (id) ON DELETE RESTRICT,
    source             TEXT    NOT NULL DEFAULT 'admin',
    note               TEXT,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    reason             TEXT    CHECK (reason IS NULL OR reason IN ('breakage', 'spoilage', 'own_use',
                                                                    'merchandise', 'other')),
    purchase_id        INTEGER REFERENCES purchase (id) ON DELETE RESTRICT,
    device_id          TEXT,
    undo_of_id         INTEGER REFERENCES stock_movement (id) ON DELETE RESTRICT,
    stocktake_id       INTEGER,
    receiving_line_id  INTEGER,
    CHECK (kind <> 'loss' OR reason IS NOT NULL),
    CHECK (kind <> 'undo' OR undo_of_id IS NOT NULL)
);
INSERT INTO stock_movement_new (id, raw_material_id, kind, delta_g, stock_after_g, batch_id, batch_item_id,
                                station_id, source, note, created_at)
    SELECT id, raw_material_id, kind, delta_g, stock_after_g, batch_id, batch_item_id,
           station_id, source, note, created_at FROM stock_movement;
DROP TABLE stock_movement;
PRAGMA legacy_alter_table = ON;
ALTER TABLE stock_movement_new RENAME TO stock_movement;
PRAGMA legacy_alter_table = OFF;
CREATE INDEX idx_stock_movement_raw_material ON stock_movement (raw_material_id, id);
CREATE INDEX idx_stock_movement_batch ON stock_movement (batch_id);
CREATE INDEX idx_stock_movement_purchase ON stock_movement (purchase_id);
CREATE UNIQUE INDEX idx_stock_movement_undo ON stock_movement (undo_of_id) WHERE undo_of_id IS NOT NULL;
