-- Migration 0003 – Rezeptverwaltung (Modul 05, docs/rezepte.md Abschnitt 3)
--
-- * Bearbeitungsstand je Rezept gegen gleichzeitiges Speichern an zwei Geräten (R05-17)
-- * Rezeptnummer ist nach der ersten Verwendung gesperrt (M05-4, R05-1)
-- * Index für die Versionsliste eines Rezepts

-- Wird bei jedem Speichern des Rezepts um 1 erhöht (Modul 05, Teil C2).
ALTER TABLE recipe
    ADD COLUMN revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0);

CREATE INDEX idx_recipe_version_recipe ON recipe_version (recipe_id);

-- Schutz auf Datenbankebene: Die Nummer eines verwendeten Rezepts darf sich nicht mehr ändern.
-- Verwendet = in einem Auftrag oder als Unterrezept in irgendeiner Rezeptversion.
CREATE TRIGGER trg_recipe_number_locked
BEFORE UPDATE OF number ON recipe
WHEN NEW.number <> OLD.number
 AND (   EXISTS (SELECT 1 FROM production_order WHERE recipe_id = OLD.id)
      OR EXISTS (SELECT 1 FROM recipe_item WHERE sub_recipe_id = OLD.id))
BEGIN
    SELECT RAISE(ABORT, 'Rezeptnummer ist bereits verwendet und kann nicht mehr geändert werden');
END;
