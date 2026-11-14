-- Migration 0002 – Rohstoffverwaltung (Modul 03, docs/rohstoffe.md Abschnitt 3)
--
-- * Kurzname für die Anzeige an der Station (M03-3b, K03-4)
-- * Rohstoffnummer ist nach der ersten Verwendung gesperrt (M03-2)
-- * Index für die Suche nach dem Namen

-- Kurzname: optional, nicht eindeutig (z. B. mehrere Margarine-Sorten mit „Margarine“).
-- Leer = an der Station wird der Name angezeigt.
ALTER TABLE raw_material
    ADD COLUMN display_name TEXT CHECK (display_name IS NULL OR length(trim(display_name)) > 0);

CREATE INDEX idx_raw_material_name ON raw_material (name);

-- Schutz auf Datenbankebene: Die Nummer eines verwendeten Rohstoffs darf sich nicht mehr ändern.
-- Verwendet = in einer Rezeptzeile, als Leitrohstoff eines Auftrags oder in einer Charge.
CREATE TRIGGER trg_raw_material_number_locked
BEFORE UPDATE OF number ON raw_material
WHEN NEW.number <> OLD.number
 AND (   EXISTS (SELECT 1 FROM recipe_item WHERE raw_material_id = OLD.id)
      OR EXISTS (SELECT 1 FROM production_order WHERE basis_raw_material_id = OLD.id)
      OR EXISTS (SELECT 1 FROM batch_item WHERE raw_material_id = OLD.id))
BEGIN
    SELECT RAISE(ABORT, 'Rohstoffnummer ist in Rezepten verwendet und kann nicht mehr geändert werden');
END;
