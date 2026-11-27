-- migration: foreign_keys=off
-- Migration 0015 – Handelsware und Pfand, Teil H1 (Modul 03, docs/handelsware.md, K03-85 bis K03-93,
-- entschieden 27.11.2026, Freigabe Michael 27.11.2026, 09:39)
--
-- * raw_material neu aufbauen (CHECK-Regeln), Inhalt unverändert:
--     - Art 'goods' = Handelsware (K03-85); Bestand in Stück, intern 1 Stück = 1000 (wie die VE bei 'aid')
--     - is_deposit: Pfand ja/nein, nur bei Handelsware (K03-92)
--     - register_no: Kassennummer (Vectron-Artikelnummer), nur bei Handelsware, aktiv eindeutig (K03-86)
--     - stock_ref_id + piece_g: Handelsware als Verweis auf einen Rohstoff, der den Bestand führt; Kassenverkäufe
--       buchen dort über das Gewicht je Stück ab (K03-93); der Verweis selbst führt keinen Bestand
-- * stock_movement neu aufbauen: Art 'sale' (Verkauf laut Kasse), Grund 'deposit_return' (Pfand zurück),
--   Spalte sales_import_id
-- * sales_import / sales_import_line: Kassenimport Vectron-Abverkauf, jeder Zeitraum nur einmal (K03-86)
-- * stocktake_line.is_deposit: Zwischensumme Pfand getrennt von Handelsware (K03-88)

CREATE TABLE raw_material_new (
    id                  INTEGER PRIMARY KEY,
    number              INTEGER NOT NULL UNIQUE CHECK (number > 0),
    name                TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    type                TEXT    NOT NULL DEFAULT 'standard' CHECK (type IN ('standard', 'flour', 'aid', 'goods')),
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
    booking_group_id    INTEGER REFERENCES booking_group (id),
    booking_group_checked INTEGER NOT NULL DEFAULT 0 CHECK (booking_group_checked IN (0, 1)),
    substitute_note     TEXT,
    is_deposit          INTEGER NOT NULL DEFAULT 0 CHECK (is_deposit IN (0, 1)),
    register_no         INTEGER CHECK (register_no IS NULL OR (register_no > 0 AND register_no <= 2000000000)),
    stock_ref_id        INTEGER REFERENCES raw_material (id) ON DELETE RESTRICT,
    piece_g             INTEGER CHECK (piece_g IS NULL OR (piece_g > 0 AND piece_g <= 1000000)),
    CHECK ((unit_size_g IS NULL) = (unit_label IS NULL)),
    CHECK ((delivery_pack_g IS NULL) = (delivery_pack_label IS NULL)),
    CHECK (tolerance_unit <> 'percent' OR tolerance_value <= 1000),
    CHECK ((source = 'datenlink') = (datenlink_id IS NOT NULL)),
    -- Hilfs- und Betriebsstoff: immer mit Verpackungseinheit (1 VE = 1000), ohne Toleranz, ohne Liefergebinde
    CHECK (type <> 'aid' OR (unit_size_g = 1000 AND tolerance_value = 0 AND delivery_pack_g IS NULL)),
    -- Handelsware: gezählt in Stück (1 Stück = 1000), ohne Toleranz, ohne Liefergebinde in Gramm
    CHECK (type <> 'goods' OR (unit_size_g = 1000 AND tolerance_value = 0 AND delivery_pack_g IS NULL)),
    CHECK (is_deposit = 0 OR type = 'goods'),
    CHECK (register_no IS NULL OR type = 'goods'),
    -- Verweis (K03-93): nur Handelsware, mit Gewicht je Stück, ohne eigenen Bestand
    CHECK (stock_ref_id IS NULL OR (type = 'goods' AND piece_g IS NOT NULL AND stock_g IS NULL AND stock_ref_id <> id)),
    CHECK (piece_g IS NULL OR stock_ref_id IS NOT NULL),
    CHECK (location2_id IS NULL OR location1_id IS NOT NULL)
);

INSERT INTO raw_material_new (
    id, number, name, type, tolerance_unit, tolerance_value, unit_size_g, unit_label, source, archived,
    created_at, updated_at, display_name, price_cents_per_kg, price_changed_at, stock_g, stock_alert_g,
    datenlink_id, delivery_pack_g, delivery_pack_label, location1_id, location1_label, location2_id, location2_label,
    booking_group_id, booking_group_checked, substitute_note)
SELECT
    id, number, name, type, tolerance_unit, tolerance_value, unit_size_g, unit_label, source, archived,
    created_at, updated_at, display_name, price_cents_per_kg, price_changed_at, stock_g, stock_alert_g,
    datenlink_id, delivery_pack_g, delivery_pack_label, location1_id, location1_label, location2_id, location2_label,
    booking_group_id, booking_group_checked, substitute_note
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
CREATE UNIQUE INDEX idx_raw_material_register_no_active
    ON raw_material (register_no) WHERE archived = 0 AND register_no IS NOT NULL;
CREATE INDEX idx_raw_material_stock_ref ON raw_material (stock_ref_id) WHERE stock_ref_id IS NOT NULL;

-- Trigger aus 0009/0011 unverändert neu anlegen (gehörte zur alten Tabelle)
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
-- Kassenimport (Vectron-Abverkauf)
-- ---------------------------------------------------------------------------

CREATE TABLE sales_import (
    id             INTEGER PRIMARY KEY,
    date_from      TEXT    NOT NULL CHECK (date_from GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    date_to        TEXT    NOT NULL CHECK (date_to GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    file_name      TEXT,
    file_sha256    TEXT,
    booked_count   INTEGER NOT NULL DEFAULT 0,
    deposit_cents  INTEGER NOT NULL DEFAULT 0,
    total_cents    INTEGER,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (date_from <= date_to),
    UNIQUE (date_from, date_to)
);

CREATE TABLE sales_import_line (
    id                 INTEGER PRIMARY KEY,
    sales_import_id    INTEGER NOT NULL REFERENCES sales_import (id) ON DELETE CASCADE,
    register_no        INTEGER NOT NULL,
    name               TEXT,
    qty_milli          INTEGER NOT NULL,
    value_cents        INTEGER,
    status             TEXT    NOT NULL CHECK (status IN ('booked', 'collective', 'unassigned', 'no_stock')),
    raw_material_id    INTEGER REFERENCES raw_material (id) ON DELETE RESTRICT,
    booked_qty         INTEGER,
    is_deposit         INTEGER NOT NULL DEFAULT 0 CHECK (is_deposit IN (0, 1)),
    stock_movement_id  INTEGER,
    UNIQUE (sales_import_id, register_no)
);
CREATE INDEX idx_sales_import_line_rm ON sales_import_line (raw_material_id);

-- ---------------------------------------------------------------------------
-- stock_movement neu aufbauen (CHECK-Regeln), Inhalt unverändert
-- ---------------------------------------------------------------------------

CREATE TABLE stock_movement_new (
    id                 INTEGER PRIMARY KEY,
    raw_material_id    INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE CASCADE,
    kind               TEXT    NOT NULL CHECK (kind IN ('receipt', 'inventory', 'consumption', 'reversal',
                                                        'planner', 'planner_return', 'loss', 'return',
                                                        'correction', 'undo', 'sale')),
    delta_g            INTEGER,
    stock_after_g      INTEGER,
    batch_id           INTEGER REFERENCES batch (id) ON DELETE RESTRICT,
    batch_item_id      INTEGER REFERENCES batch_item (id) ON DELETE RESTRICT,
    station_id         INTEGER REFERENCES station (id) ON DELETE RESTRICT,
    source             TEXT    NOT NULL DEFAULT 'admin',
    note               TEXT,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    reason             TEXT    CHECK (reason IS NULL OR reason IN ('breakage', 'spoilage', 'own_use',
                                                                    'merchandise', 'other', 'deposit_return')),
    purchase_id        INTEGER REFERENCES purchase (id) ON DELETE RESTRICT,
    device_id          TEXT,
    undo_of_id         INTEGER REFERENCES stock_movement (id) ON DELETE RESTRICT,
    stocktake_id       INTEGER,
    receiving_line_id  INTEGER,
    attachment         TEXT,
    sales_import_id    INTEGER REFERENCES sales_import (id) ON DELETE SET NULL,
    CHECK (kind <> 'loss' OR reason IS NOT NULL),
    CHECK (kind <> 'undo' OR undo_of_id IS NOT NULL)
);
INSERT INTO stock_movement_new (id, raw_material_id, kind, delta_g, stock_after_g, batch_id, batch_item_id,
                                station_id, source, note, created_at, reason, purchase_id, device_id, undo_of_id,
                                stocktake_id, receiving_line_id, attachment)
    SELECT id, raw_material_id, kind, delta_g, stock_after_g, batch_id, batch_item_id,
           station_id, source, note, created_at, reason, purchase_id, device_id, undo_of_id,
           stocktake_id, receiving_line_id, attachment FROM stock_movement;
DROP TABLE stock_movement;
PRAGMA legacy_alter_table = ON;
ALTER TABLE stock_movement_new RENAME TO stock_movement;
PRAGMA legacy_alter_table = OFF;
CREATE INDEX idx_stock_movement_raw_material ON stock_movement (raw_material_id, id);
CREATE INDEX idx_stock_movement_batch ON stock_movement (batch_id);
CREATE INDEX idx_stock_movement_purchase ON stock_movement (purchase_id);
CREATE UNIQUE INDEX idx_stock_movement_undo ON stock_movement (undo_of_id) WHERE undo_of_id IS NOT NULL;
CREATE INDEX idx_stock_movement_stocktake ON stock_movement (stocktake_id) WHERE stocktake_id IS NOT NULL;
CREATE INDEX idx_stock_movement_sales_import ON stock_movement (sales_import_id) WHERE sales_import_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Inventur: Pfand getrennt
-- ---------------------------------------------------------------------------

ALTER TABLE stocktake_line ADD COLUMN is_deposit INTEGER NOT NULL DEFAULT 0;
