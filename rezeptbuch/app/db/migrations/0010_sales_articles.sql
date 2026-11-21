-- Migration 0010 – Produktionsplaner (Modul 10 C2, docs/planer.md 3): alle Tabellen für P-A und P-B
--
-- Teil P-A:
-- * sales_article: Verkaufsartikel aus der Vectron-Artikelliste (K10-P1 bis K10-P4, K10-P15)
-- * sales_article_line: Stückliste je Artikel – Zeilen Rezept oder Rohstoff (M10-19, K10-P6)
-- * recipe.preproduce: „darf vorproduziert werden“ (K10-P17: Schild „vorproduzierbar“, Startwert Aufrunden)
-- * recipe.weigh_surcharge_tenths: Abwiegezuschlag in Zehntelprozent, Vorgabe für die Plus-Taste (K10-P21)
--
-- Teil P-B (Tabellen schon jetzt angelegt, H1 – Michael 21.11.2026, 07:08: eine Migration):
-- * sales_plan, sales_plan_line: Plan je Tag mit Auftragsnummer je Zeile (K10-P15)
-- * plan_run, plan_run_order: Planlauf („Jetzt planen“) mit Vorschau-Wahl und angelegten Aufträgen (K10-P10)
-- * order_article_source: woraus ein Planer-Auftrag besteht (K10-P20, K10-P22)
-- * production_order.surcharge_tenths/surcharge_g/carryover_of_order_id: nur Anzeige (K10-P21, K10-P23)
-- * plan_stock_booking und Buchungsarten „planner“/„planner_return“ in stock_movement (K10-P12)
-- * Einstellung planner_in_preselection (K10-P5) in setting, ohne Eintrag = 1

CREATE TABLE sales_article (
    id               INTEGER PRIMARY KEY,
    register_no      INTEGER NOT NULL UNIQUE CHECK (register_no > 0),
    name             TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    register_group   INTEGER CHECK (register_group IS NULL OR register_group >= 0),
    pieces_per_whole INTEGER CHECK (pieces_per_whole IS NULL OR (pieces_per_whole > 0 AND pieces_per_whole <= 1000)),
    plan_enabled     INTEGER NOT NULL DEFAULT 1 CHECK (plan_enabled IN (0, 1)),
    in_register      INTEGER NOT NULL DEFAULT 1 CHECK (in_register IN (0, 1)),
    last_order_no    INTEGER NOT NULL DEFAULT 1 CHECK (last_order_no >= 1),
    note             TEXT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE sales_article_line (
    id               INTEGER PRIMARY KEY,
    article_id       INTEGER NOT NULL REFERENCES sales_article (id) ON DELETE CASCADE,
    position         INTEGER NOT NULL CHECK (position >= 1),
    kind             TEXT    NOT NULL CHECK (kind IN ('recipe', 'raw')),
    recipe_id        INTEGER REFERENCES recipe (id) ON DELETE RESTRICT,
    piece_weight_id  INTEGER REFERENCES recipe_piece_weight (id) ON DELETE RESTRICT,
    raw_material_id  INTEGER REFERENCES raw_material (id) ON DELETE RESTRICT,
    amount_g         INTEGER CHECK (amount_g IS NULL OR (amount_g > 0 AND amount_g <= 1000000)),
    amount_pieces    INTEGER CHECK (amount_pieces IS NULL OR (amount_pieces > 0 AND amount_pieces <= 10000)),
    UNIQUE (article_id, position),
    -- Rezeptzeile: Rezept, kein Rohstoff, Menge in g oder Stückgewicht; Rohstoffzeile: Rohstoff, g oder Stück
    CHECK (kind <> 'recipe' OR (recipe_id IS NOT NULL AND raw_material_id IS NULL AND amount_pieces IS NULL
                                AND ((amount_g IS NULL) <> (piece_weight_id IS NULL)))),
    CHECK (kind <> 'raw' OR (raw_material_id IS NOT NULL AND recipe_id IS NULL AND piece_weight_id IS NULL
                             AND ((amount_g IS NULL) <> (amount_pieces IS NULL))))
);

CREATE INDEX idx_sales_article_line_article ON sales_article_line (article_id);
CREATE INDEX idx_sales_article_line_recipe ON sales_article_line (recipe_id);
CREATE INDEX idx_sales_article_line_raw ON sales_article_line (raw_material_id);

-- Das Stückgewicht muss zum Rezept der Zeile gehören (K10-P6)
CREATE TRIGGER trg_sales_article_line_piece_ins
BEFORE INSERT ON sales_article_line
WHEN NEW.piece_weight_id IS NOT NULL
 AND (SELECT recipe_id FROM recipe_piece_weight WHERE id = NEW.piece_weight_id) IS NOT NEW.recipe_id
BEGIN
    SELECT RAISE(ABORT, 'piece_weight_of_other_recipe');
END;

CREATE TRIGGER trg_sales_article_line_piece_upd
BEFORE UPDATE ON sales_article_line
WHEN NEW.piece_weight_id IS NOT NULL
 AND (SELECT recipe_id FROM recipe_piece_weight WHERE id = NEW.piece_weight_id) IS NOT NEW.recipe_id
BEGIN
    SELECT RAISE(ABORT, 'piece_weight_of_other_recipe');
END;

ALTER TABLE recipe ADD COLUMN preproduce INTEGER NOT NULL DEFAULT 0 CHECK (preproduce IN (0, 1));
ALTER TABLE recipe ADD COLUMN weigh_surcharge_tenths INTEGER
    CHECK (weigh_surcharge_tenths IS NULL OR (weigh_surcharge_tenths >= 0 AND weigh_surcharge_tenths <= 200));

-- ---- Teil P-B -------------------------------------------------------------------------

CREATE TABLE sales_plan (
    id          INTEGER PRIMARY KEY,
    plan_date   TEXT    NOT NULL UNIQUE CHECK (plan_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    note        TEXT,
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE sales_plan_line (
    id          INTEGER PRIMARY KEY,
    plan_id     INTEGER NOT NULL REFERENCES sales_plan (id) ON DELETE CASCADE,
    article_id  INTEGER NOT NULL REFERENCES sales_article (id) ON DELETE RESTRICT,
    order_no    INTEGER NOT NULL CHECK (order_no >= 1 AND order_no <= 99),
    pieces      INTEGER NOT NULL DEFAULT 0 CHECK (pieces >= 0 AND pieces <= 100000),
    halves      INTEGER NOT NULL DEFAULT 0 CHECK (halves >= 0 AND halves <= 10000),
    wholes      INTEGER NOT NULL DEFAULT 0 CHECK (wholes >= 0 AND wholes <= 10000),
    UNIQUE (plan_id, article_id, order_no),
    CHECK (pieces > 0 OR halves > 0 OR wholes > 0)
);

CREATE INDEX idx_sales_plan_line_article ON sales_plan_line (article_id);

CREATE TABLE plan_run (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    dates       TEXT    NOT NULL,                       -- JSON-Liste der Tage
    status      TEXT    NOT NULL DEFAULT 'preview' CHECK (status IN ('preview', 'done')),
    mode        TEXT    CHECK (mode IS NULL OR mode IN ('replace', 'delta')),
    choices     TEXT,                                   -- JSON: Wahl, Zusammenfassungen, Zuschläge, Überträge, Tage
    done_at     TEXT
);

CREATE TABLE plan_run_order (
    run_id      INTEGER NOT NULL REFERENCES plan_run (id) ON DELETE CASCADE,
    order_id    INTEGER NOT NULL REFERENCES production_order (id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, order_id)
);

CREATE INDEX idx_plan_run_order_order ON plan_run_order (order_id);

CREATE TABLE order_article_source (
    id             INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES production_order (id) ON DELETE CASCADE,
    article_id     INTEGER REFERENCES sales_article (id) ON DELETE SET NULL,
    article_name   TEXT    NOT NULL,
    register_no    INTEGER,
    plan_date      TEXT,
    order_no       INTEGER CHECK (order_no IS NULL OR order_no >= 1),
    quantity_text  TEXT,
    amount_g       INTEGER CHECK (amount_g IS NULL OR amount_g >= 0),
    carryover      INTEGER NOT NULL DEFAULT 0 CHECK (carryover IN (0, 1))   -- 1 = Artikel des Ursprungsauftrags
);

CREATE INDEX idx_order_article_source_order ON order_article_source (order_id);

ALTER TABLE production_order ADD COLUMN surcharge_tenths INTEGER
    CHECK (surcharge_tenths IS NULL OR (surcharge_tenths >= 0 AND surcharge_tenths <= 200));
ALTER TABLE production_order ADD COLUMN surcharge_g INTEGER
    CHECK (surcharge_g IS NULL OR (surcharge_g >= 0 AND surcharge_g <= 1000000));
ALTER TABLE production_order ADD COLUMN carryover_of_order_id INTEGER
    REFERENCES production_order (id) ON DELETE SET NULL;

-- Buchungsarten „planner“ (Abgang aus dem Planer) und „planner_return“ (Zurückbuchen): Tabelle neu aufbauen,
-- weil SQLite eine CHECK-Regel nicht ändern kann; Inhalt unverändert
CREATE TABLE stock_movement_new (
    id               INTEGER PRIMARY KEY,
    raw_material_id  INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE CASCADE,
    kind             TEXT    NOT NULL CHECK (kind IN ('receipt', 'inventory', 'consumption', 'reversal',
                                                      'planner', 'planner_return')),
    delta_g          INTEGER,
    stock_after_g    INTEGER,
    batch_id         INTEGER REFERENCES batch (id) ON DELETE RESTRICT,
    batch_item_id    INTEGER REFERENCES batch_item (id) ON DELETE RESTRICT,
    station_id       INTEGER REFERENCES station (id) ON DELETE RESTRICT,
    source           TEXT    NOT NULL DEFAULT 'admin',
    note             TEXT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
INSERT INTO stock_movement_new (id, raw_material_id, kind, delta_g, stock_after_g, batch_id, batch_item_id,
                                station_id, source, note, created_at)
    SELECT id, raw_material_id, kind, delta_g, stock_after_g, batch_id, batch_item_id,
           station_id, source, note, created_at FROM stock_movement;
DROP TABLE stock_movement;
ALTER TABLE stock_movement_new RENAME TO stock_movement;
CREATE INDEX idx_stock_movement_raw_material ON stock_movement (raw_material_id, id);
CREATE INDEX idx_stock_movement_batch ON stock_movement (batch_id);

CREATE TABLE plan_stock_booking (
    id                 INTEGER PRIMARY KEY,
    production_date    TEXT    NOT NULL,
    raw_material_id    INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE RESTRICT,
    amount_g           INTEGER NOT NULL CHECK (amount_g > 0),
    stock_movement_id  INTEGER REFERENCES stock_movement (id) ON DELETE SET NULL,
    booked_at          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    reversed_at        TEXT
);

CREATE INDEX idx_plan_stock_booking_day ON plan_stock_booking (production_date, raw_material_id);

-- Einstellung planner_in_preselection: kein Eintrag nötig, fehlt er, gilt 1 (Planer in der Vorwahl anzeigen)
