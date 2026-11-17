-- Migration 0005 – Rezeptberechnung (Modul 06, docs/berechnung.md Abschnitt 3)
--
-- * Leitrohstoff je Rezeptzeile im Auftrag (K06-1): neue Spalte basis_item_position
-- * Befund B2 aus dem Freigabebericht Modul 02: Chargenzeilen nur aus der Version der Charge
--
-- Keine neue Tabelle, keine Änderung vorhandener Daten (bisher gibt es keine Aufträge und Chargen).

-- Gewählte Rezeptzeile beim Leitrohstoff „je Zeile“; leer = Leitrohstoff „gesamt“
-- (Summe aller Zeilen inklusive Unterrezepten). Nur zusammen mit basis_type 'raw_material'.
ALTER TABLE production_order
    ADD COLUMN basis_item_position INTEGER CHECK (basis_item_position IS NULL OR basis_item_position >= 1);

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

-- B2: Eine Chargenzeile mit Bezug auf eine Rezeptzeile muss aus der Version der Charge stammen.
-- (Zweite Sicherung neben build_batch_items im Rezeptserver.)
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
