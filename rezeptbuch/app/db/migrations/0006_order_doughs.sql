-- migration: foreign_keys=off
--
-- Migration 0006 – Kombinieren, Faktor, Obergrenze, Teige; Preis je kg
-- (Modul 06 Teil C3, docs/berechnung.md Abschnitt 17.9, K06-11; Modul 03 VC03-a, docs/rohstoffe.md 15.2)
--
-- * recipe_batch_size.is_limit: Haken „aktiv (Obergrenze)“, höchstens einer je Rezept (R06-27)
-- * production_order: basis_type zusätzlich 'factor' und 'combined'; neue Spalten total_part_g,
--   factor_hundredths, limit_g, limit_source, split_mode, parent_dough_index
-- * neue Tabellen order_batch_size (Chargengrößen mit Anzahl) und order_dough (Sollgröße je Teig)
-- * raw_material.price_cents_per_kg und price_changed_at (VC03-a)
--
-- Die CHECK-Regel von basis_type lässt sich in SQLite nicht mit ALTER TABLE ändern. Deshalb wird
-- production_order nach dem Vorgehen der SQLite-Dokumentation neu aufgebaut (neue Tabelle anlegen,
-- Daten kopieren, alte löschen, umbenennen, Indizes und Trigger neu anlegen). Dafür läuft diese
-- Migration mit ausgeschalteten Fremdschlüsseln (erste Zeile); migrate.py prüft vor dem COMMIT mit
-- PRAGMA foreign_key_check und schaltet die Fremdschlüssel danach wieder ein.
-- Vorhandene Werte bleiben unverändert (bisher gibt es keine Aufträge im Betrieb).

-- ---------------------------------------------------------------------------
-- Rohstoff: Preis je kg (VC03-a, R03-13 bis R03-17)
-- ---------------------------------------------------------------------------

-- Cent je kg als ganze Zahl (235 = 2,35 €), leer = kein Preis; 0 bis 9 999,99 €
ALTER TABLE raw_material
    ADD COLUMN price_cents_per_kg INTEGER
        CHECK (price_cents_per_kg IS NULL OR (price_cents_per_kg >= 0 AND price_cents_per_kg <= 999999));

-- Zeitpunkt der letzten Preisänderung (setzt der Rezeptserver, R03-14)
ALTER TABLE raw_material
    ADD COLUMN price_changed_at TEXT;

-- ---------------------------------------------------------------------------
-- Chargengröße als Obergrenze (V06-2, R06-27)
-- ---------------------------------------------------------------------------

ALTER TABLE recipe_batch_size
    ADD COLUMN is_limit INTEGER NOT NULL DEFAULT 0 CHECK (is_limit IN (0, 1));

CREATE UNIQUE INDEX idx_recipe_batch_size_limit ON recipe_batch_size (recipe_id) WHERE is_limit = 1;

-- ---------------------------------------------------------------------------
-- Auftrag neu aufbauen
-- ---------------------------------------------------------------------------

CREATE TABLE production_order_new (
    id                     INTEGER PRIMARY KEY,
    recipe_id              INTEGER NOT NULL REFERENCES recipe (id) ON DELETE RESTRICT,
    -- beim Start des ersten Teigs einmal für den ganzen Auftrag fixiert (R2, K6)
    recipe_version_id      INTEGER REFERENCES recipe_version (id) ON DELETE RESTRICT,
    parent_order_id        INTEGER REFERENCES production_order (id) ON DELETE RESTRICT,
    parent_item_position   INTEGER,
    -- 'factor' = Faktor × Grundrezept allein, 'combined' = mehr als eine Bezugsangabe (V06-1, VC06-e)
    basis_type             TEXT    NOT NULL
        CHECK (basis_type IN ('total', 'pieces', 'batch_size', 'raw_material', 'flour_total',
                              'factor', 'combined')),
    -- Gramm; bei 'pieces' die Summe aus order_piece; bei 'combined'/'factor' der Gesamtbedarf B (R06-22)
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
    -- Migration 0005: gewählte Rezeptzeile beim Leitrohstoff „je Zeile“
    basis_item_position    INTEGER CHECK (basis_item_position IS NULL OR basis_item_position >= 1),
    -- Migration 0006: Gesamtteig-Anteil in Gramm (nur 'total'/'combined')
    total_part_g           INTEGER CHECK (total_part_g IS NULL OR total_part_g > 0),
    -- Faktor in Hundertsteln (150 = 1,5), 0,01 bis 100 (R06-24, R06-26)
    factor_hundredths      INTEGER CHECK (factor_hundredths IS NULL
                                          OR (factor_hundredths >= 1 AND factor_hundredths <= 10000)),
    -- genutzte Obergrenze in Gramm (Kopie), Herkunft und Teilungsart (V06-2, R06-31)
    limit_g                INTEGER CHECK (limit_g IS NULL OR (limit_g > 0 AND limit_g <= 1000000)),
    limit_source           TEXT    CHECK (limit_source IS NULL OR limit_source IN ('recipe', 'order')),
    split_mode             TEXT    CHECK (split_mode IS NULL OR split_mode IN ('fill', 'even')),
    -- Unterrezept-Auftrag: Teig des Hauptauftrags; leer = „für alle“ (R06-45, R06-46)
    parent_dough_index     INTEGER CHECK (parent_dough_index IS NULL OR parent_dough_index >= 1),
    -- Leitrohstoff nur bei basis_type 'raw_material', dort Pflicht
    CHECK ((basis_type = 'raw_material') = (basis_raw_material_id IS NOT NULL)),
    -- Liter-Eingabe nur beim Leitrohstoff (M02-1e)
    CHECK (basis_input_unit <> 'l' OR basis_type = 'raw_material'),
    CHECK ((parent_order_id IS NULL) = (parent_item_position IS NULL)),
    CHECK (status = 'open' OR status = 'cancelled' OR recipe_version_id IS NOT NULL),
    -- neue Angaben nur bei passender Bezugsart
    CHECK (total_part_g IS NULL OR basis_type IN ('total', 'combined')),
    CHECK (factor_hundredths IS NULL OR basis_type IN ('factor', 'combined')),
    CHECK (basis_type <> 'factor' OR factor_hundredths IS NOT NULL),
    CHECK ((limit_g IS NULL) = (limit_source IS NULL)),
    CHECK (split_mode IS NULL OR limit_g IS NOT NULL),
    CHECK (parent_dough_index IS NULL OR parent_order_id IS NOT NULL)
);

INSERT INTO production_order_new (
    id, recipe_id, recipe_version_id, parent_order_id, parent_item_position, basis_type, basis_value,
    basis_raw_material_id, basis_input_unit, batch_size_id, dough_count, fixed_station_id, planned_date,
    list_position, status, created_at, finished_at, basis_item_position)
SELECT
    id, recipe_id, recipe_version_id, parent_order_id, parent_item_position, basis_type, basis_value,
    basis_raw_material_id, basis_input_unit, batch_size_id, dough_count, fixed_station_id, planned_date,
    list_position, status, created_at, finished_at, basis_item_position
FROM production_order;

DROP TABLE production_order;

-- Trigger anderer Tabellen (z. B. batch) nennen production_order beim Namen; ohne diesen Schalter
-- würde SQLite sie beim Umbenennen neu prüfen, während die Tabelle kurz fehlt.
PRAGMA legacy_alter_table = ON;
ALTER TABLE production_order_new RENAME TO production_order;
PRAGMA legacy_alter_table = OFF;

CREATE INDEX idx_production_order_list ON production_order (status, planned_date, list_position);
CREATE INDEX idx_production_order_parent ON production_order (parent_order_id);

-- Trigger aus 0001 und 0005 unverändert neu anlegen (sie gehörten zur alten Tabelle)

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

CREATE TRIGGER trg_order_closed_status
BEFORE UPDATE OF status ON production_order
WHEN OLD.status IN ('done', 'cancelled') AND NEW.status IS NOT OLD.status
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht wieder geöffnet werden');
END;

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

CREATE TRIGGER trg_order_basis_item_position_insert
BEFORE INSERT ON production_order
WHEN NEW.basis_item_position IS NOT NULL AND NEW.basis_type <> 'raw_material'
BEGIN
    SELECT RAISE(ABORT, 'Eine Rezeptzeile als Bezug gibt es nur beim Leitrohstoff');
END;

CREATE TRIGGER trg_order_basis_item_position_update
BEFORE UPDATE OF basis_item_position, basis_type ON production_order
WHEN NEW.basis_item_position IS NOT NULL AND NEW.basis_type <> 'raw_material'
BEGIN
    SELECT RAISE(ABORT, 'Eine Rezeptzeile als Bezug gibt es nur beim Leitrohstoff');
END;

-- ---------------------------------------------------------------------------
-- Chargengrößen im Auftrag (V06-1: mehrere, dieselbe auch mehrmals), wie order_piece
-- ---------------------------------------------------------------------------

CREATE TABLE order_batch_size (
    id               INTEGER PRIMARY KEY,
    order_id         INTEGER NOT NULL REFERENCES production_order (id) ON DELETE CASCADE,
    batch_size_id    INTEGER REFERENCES recipe_batch_size (id) ON DELETE SET NULL,
    label            TEXT    NOT NULL CHECK (length(trim(label)) > 0),
    kind             TEXT    NOT NULL CHECK (kind IN ('weight', 'pieces')),
    value            INTEGER NOT NULL CHECK (value > 0),
    -- Kopie des Stückgewichts bei Chargengröße „Stück“
    piece_weight_g   INTEGER CHECK (piece_weight_g IS NULL OR piece_weight_g > 0),
    batch_count      INTEGER NOT NULL CHECK (batch_count > 0),
    CHECK ((kind = 'pieces') = (piece_weight_g IS NOT NULL))
);

CREATE INDEX idx_order_batch_size_order ON order_batch_size (order_id);

-- ---------------------------------------------------------------------------
-- Sollgröße je Teig (V06-2: Teige eines Auftrags auch unterschiedlich groß)
-- ---------------------------------------------------------------------------

CREATE TABLE order_dough (
    id           INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES production_order (id) ON DELETE CASCADE,
    dough_index  INTEGER NOT NULL CHECK (dough_index >= 1),
    target_g     INTEGER NOT NULL CHECK (target_g > 0 AND target_g <= 1000000),
    UNIQUE (order_id, dough_index)
);

-- Abgeschlossene Aufträge: Chargengrößen und Teige bleiben unverändert (wie order_piece)

CREATE TRIGGER trg_order_batch_size_closed_insert
BEFORE INSERT ON order_batch_size
WHEN (SELECT status FROM production_order WHERE id = NEW.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_order_batch_size_closed_update
BEFORE UPDATE ON order_batch_size
WHEN (SELECT status FROM production_order WHERE id = OLD.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_order_batch_size_closed_delete
BEFORE DELETE ON order_batch_size
WHEN (SELECT status FROM production_order WHERE id = OLD.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_order_dough_closed_insert
BEFORE INSERT ON order_dough
WHEN (SELECT status FROM production_order WHERE id = NEW.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_order_dough_closed_update
BEFORE UPDATE ON order_dough
WHEN (SELECT status FROM production_order WHERE id = OLD.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;

CREATE TRIGGER trg_order_dough_closed_delete
BEFORE DELETE ON order_dough
WHEN (SELECT status FROM production_order WHERE id = OLD.order_id) IN ('done', 'cancelled')
BEGIN
    SELECT RAISE(ABORT, 'Auftrag ist abgeschlossen und kann nicht geändert werden');
END;
