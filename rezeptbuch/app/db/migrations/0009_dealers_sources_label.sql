-- migration: foreign_keys=off
-- Migration 0009 – Händler, Bezugsquellen, Kennzeichnungspass (Modul 04, docs/kennzeichnungspass-import.md 3)
--
-- * raw_material: Herkunft 'own' / 'datenlink' statt 'own' / 'baeko' (M04-4, M04-18), datenlink_id (M04-16)
--   → Neuaufbau der Tabelle (CHECK-Regel), Inhalt unverändert; 'baeko' gab es im Betrieb nie, würde zu 'own'
-- * dealer: Händlerliste (M04-5)
-- * raw_material_source: Bezugsquellen mit Preis je kg (M04-14), höchstens eine aktiv,
--   dazu „g je Mengeneinheit“ und Warengruppe für den Beleg-Import (K03-19, K03-24, M04-24)
-- * raw_material_label, allergen, raw_material_allergen, raw_material_nutrient: Pass-Daten (für Teil C2)
--
-- Eine Migration für Modul 04 (M04-11, Nummer nach K04-5/K03-11: 0009).

-- ---------------------------------------------------------------------------
-- raw_material neu aufbauen
-- ---------------------------------------------------------------------------

CREATE TABLE raw_material_new (
    id                  INTEGER PRIMARY KEY,
    number              INTEGER NOT NULL UNIQUE CHECK (number > 0),
    name                TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    type                TEXT    NOT NULL DEFAULT 'standard' CHECK (type IN ('standard', 'flour')),
    tolerance_unit      TEXT    NOT NULL DEFAULT 'g' CHECK (tolerance_unit IN ('g', 'percent')),
    tolerance_value     INTEGER NOT NULL CHECK (tolerance_value >= 0),
    unit_size_g         INTEGER CHECK (unit_size_g IS NULL OR unit_size_g > 0),
    unit_label          TEXT    CHECK (unit_label IS NULL OR length(trim(unit_label)) > 0),
    source              TEXT    NOT NULL DEFAULT 'own' CHECK (source IN ('own', 'datenlink')),
    archived            INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    display_name        TEXT    CHECK (display_name IS NULL OR length(trim(display_name)) > 0),
    -- gültiger Preis: Preis der aktiven Bezugsquelle, ohne Bezugsquelle eigener Preis (M04-14, K04-4)
    price_cents_per_kg  INTEGER
        CHECK (price_cents_per_kg IS NULL OR (price_cents_per_kg >= 0 AND price_cents_per_kg <= 999999)),
    price_changed_at    TEXT,
    stock_g             INTEGER,
    stock_alert_g       INTEGER CHECK (stock_alert_g IS NULL OR stock_alert_g >= 0),
    datenlink_id        TEXT    CHECK (datenlink_id IS NULL OR length(trim(datenlink_id)) > 0),
    CHECK ((unit_size_g IS NULL) = (unit_label IS NULL)),
    CHECK (tolerance_unit <> 'percent' OR tolerance_value <= 1000),
    -- Herkunft 'datenlink' genau dann, wenn ein Pass zugeordnet ist (R04-2)
    CHECK ((source = 'datenlink') = (datenlink_id IS NOT NULL))
);

INSERT INTO raw_material_new (
    id, number, name, type, tolerance_unit, tolerance_value, unit_size_g, unit_label, source, archived,
    created_at, updated_at, display_name, price_cents_per_kg, price_changed_at, stock_g, stock_alert_g)
SELECT
    id, number, name, type, tolerance_unit, tolerance_value, unit_size_g, unit_label, 'own', archived,
    created_at, updated_at, display_name, price_cents_per_kg, price_changed_at, stock_g, stock_alert_g
FROM raw_material;

DROP TABLE raw_material;

PRAGMA legacy_alter_table = ON;
ALTER TABLE raw_material_new RENAME TO raw_material;
PRAGMA legacy_alter_table = OFF;

CREATE INDEX idx_raw_material_name ON raw_material (name);

-- datenlink-ID eindeutig unter den nicht archivierten Rohstoffen (M04-16, R04-3)
CREATE UNIQUE INDEX idx_raw_material_datenlink_active
    ON raw_material (datenlink_id) WHERE archived = 0 AND datenlink_id IS NOT NULL;

-- Trigger aus 0002 unverändert neu anlegen (gehörte zur alten Tabelle)
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
-- Händler und Bezugsquellen (M04-5, M04-14, K04-11)
-- ---------------------------------------------------------------------------

CREATE TABLE dealer (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    archived    INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Name eindeutig ohne Groß-/Kleinschreibung (ASCII); Umlaute prüft zusätzlich der Rezeptserver
CREATE UNIQUE INDEX idx_dealer_name ON dealer (lower(trim(name)));

CREATE TABLE raw_material_source (
    id                  INTEGER PRIMARY KEY,
    raw_material_id     INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE CASCADE,
    dealer_id           INTEGER NOT NULL REFERENCES dealer (id) ON DELETE RESTRICT,
    article_no          TEXT    CHECK (article_no IS NULL OR length(trim(article_no)) > 0),
    note                TEXT    CHECK (note IS NULL OR length(trim(note)) > 0),
    price_cents_per_kg  INTEGER
        CHECK (price_cents_per_kg IS NULL OR (price_cents_per_kg >= 0 AND price_cents_per_kg <= 999999)),
    price_changed_at    TEXT,
    -- Umrechnung der Mengeneinheit auf dem Beleg in Gramm (K03-19, M04-24), z. B. 1 L Milch = 1030 g
    grams_per_unit      INTEGER CHECK (grams_per_unit IS NULL OR grams_per_unit > 0),
    -- Mengeneinheit, für die grams_per_unit gilt (L, BT, DS, ST …), leer = nicht festgelegt
    unit_code           TEXT    CHECK (unit_code IS NULL OR length(trim(unit_code)) > 0),
    -- Warengruppe des Händlers (BÄKO WG, K03-24), Text
    commodity_group     TEXT    CHECK (commodity_group IS NULL OR length(trim(commodity_group)) > 0),
    is_active           INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    created_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (raw_material_id, dealer_id)
);

CREATE UNIQUE INDEX idx_raw_material_source_active
    ON raw_material_source (raw_material_id) WHERE is_active = 1;
CREATE INDEX idx_raw_material_source_dealer ON raw_material_source (dealer_id);
CREATE INDEX idx_raw_material_source_article ON raw_material_source (dealer_id, article_no);

-- ---------------------------------------------------------------------------
-- Kennzeichnungspass (Teil C2; Tabellen schon jetzt, M04-11)
-- ---------------------------------------------------------------------------

CREATE TABLE raw_material_label (
    raw_material_id             INTEGER PRIMARY KEY REFERENCES raw_material (id) ON DELETE CASCADE,
    data_source                 TEXT    NOT NULL CHECK (data_source IN ('datenlink', 'gdsn')),
    manufacturer_name           TEXT,
    manufacturer_city           TEXT,
    manufacturer_country        TEXT,
    product_no                  TEXT,
    gtin                        TEXT,
    product_name                TEXT,
    valid_from                  TEXT,
    ingredients_state           TEXT    NOT NULL CHECK (ingredients_state IN ('text', 'none')),
    ingredients_text            TEXT,
    allergens_contained_state   TEXT    NOT NULL CHECK (allergens_contained_state IN ('known', 'none')),
    allergens_cross_state       TEXT    NOT NULL CHECK (allergens_cross_state IN ('known', 'none')),
    nutrition_basis             TEXT    CHECK (nutrition_basis IS NULL OR nutrition_basis IN ('100g', '100ml')),
    nutrition_preparation       TEXT    CHECK (nutrition_preparation IS NULL
                                               OR nutrition_preparation IN ('unprepared', 'prepared')),
    plausibility                TEXT,
    file_name                   TEXT,
    file_sha256                 TEXT,
    imported_at                 TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK ((ingredients_state = 'text') = (ingredients_text IS NOT NULL))
);

CREATE TABLE allergen (
    code         TEXT    PRIMARY KEY,
    name         TEXT    NOT NULL,
    parent_code  TEXT    REFERENCES allergen (code) ON DELETE RESTRICT,
    sort_order   INTEGER NOT NULL
);

-- 26 Zeilen wie im Pass und im Leser (tools/kennzeichnungspass, Schlüssel gleich)
INSERT INTO allergen (code, name, parent_code, sort_order) VALUES
    ('gluten', 'Glutenhaltiges Getreide', NULL, 1),
    ('weizen', 'Weizen', 'gluten', 2),
    ('roggen', 'Roggen', 'gluten', 3),
    ('gerste', 'Gerste', 'gluten', 4),
    ('hafer', 'Hafer', 'gluten', 5),
    ('krebstiere', 'Krebstiere', NULL, 6),
    ('eier', 'Eier', NULL, 7),
    ('fische', 'Fische', NULL, 8),
    ('erdnuesse', 'Erdnüsse', NULL, 9),
    ('soja', 'Soja', NULL, 10),
    ('milch', 'Milch (einschl. Laktose)', NULL, 11),
    ('schalenfruechte', 'Schalenfrüchte', NULL, 12),
    ('mandeln', 'Mandeln', 'schalenfruechte', 13),
    ('haselnuesse', 'Haselnüsse', 'schalenfruechte', 14),
    ('walnuesse', 'Walnüsse', 'schalenfruechte', 15),
    ('kaschunuesse', 'Kaschunüsse', 'schalenfruechte', 16),
    ('pecannuesse', 'Pecannüsse', 'schalenfruechte', 17),
    ('paranuesse', 'Paranüsse', 'schalenfruechte', 18),
    ('pistazien', 'Pistazien', 'schalenfruechte', 19),
    ('makadamianuesse', 'Makadamianüsse', 'schalenfruechte', 20),
    ('sellerie', 'Sellerie', NULL, 21),
    ('senf', 'Senf', NULL, 22),
    ('sesam', 'Sesamsamen', NULL, 23),
    ('sulfit', 'Schwefeldioxid und Sulfite', NULL, 24),
    ('lupinen', 'Lupinen', NULL, 25),
    ('weichtiere', 'Weichtiere', NULL, 26);

CREATE TABLE raw_material_allergen (
    raw_material_id    INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE CASCADE,
    kind               TEXT    NOT NULL CHECK (kind IN ('contained', 'cross')),
    allergen_code      TEXT    NOT NULL REFERENCES allergen (code) ON DELETE RESTRICT,
    parent_not_marked  INTEGER NOT NULL DEFAULT 0 CHECK (parent_not_marked IN (0, 1)),
    PRIMARY KEY (raw_material_id, kind, allergen_code)
);

CREATE TABLE raw_material_nutrient (
    raw_material_id  INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE CASCADE,
    nutrient_code    TEXT    NOT NULL CHECK (nutrient_code IN ('energy_kj', 'energy_kcal', 'fat', 'saturates',
                                                               'carbohydrate', 'sugars', 'fibre', 'protein', 'salt')),
    state            TEXT    NOT NULL CHECK (state IN ('value', 'none')),
    value_milli      INTEGER CHECK (value_milli IS NULL OR value_milli >= 0),
    less_than        INTEGER NOT NULL DEFAULT 0 CHECK (less_than IN (0, 1)),
    PRIMARY KEY (raw_material_id, nutrient_code),
    CHECK ((state = 'value') = (value_milli IS NOT NULL))
);
