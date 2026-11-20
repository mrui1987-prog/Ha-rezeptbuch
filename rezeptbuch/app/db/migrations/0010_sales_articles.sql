-- Migration 0010 – Verkaufsartikel und Stückliste für den Produktionsplaner (Modul 10, Teil P-A, docs/planer.md 3)
--
-- * sales_article: Verkaufsartikel aus der Vectron-Artikelliste (K10-P1 bis K10-P4, K10-P15)
-- * sales_article_line: Stückliste je Artikel – Zeilen Rezept oder Rohstoff (M10-19, K10-P6)
-- * recipe.preproduce: „darf vorproduziert werden“ (K10-P17: Schild „vorproduzierbar“, Startwert Aufrunden)
-- * recipe.weigh_surcharge_tenths: Abwiegezuschlag in Zehntelprozent, Vorgabe für die Plus-Taste (K10-P21)
--
-- Pläne, Planläufe und Abbuchungen kommen mit Teil P-B (eigene Migration).

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
