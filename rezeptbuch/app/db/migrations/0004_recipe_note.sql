-- Migration 0004 – interne Notiz je Rezept (Modul 05, Teil C3, KC2-2)
--
-- Die Notiz ist nur im Admin-Bereich sichtbar, nie an der Station und nicht in der
-- Abschlussanzeige. Sie gehört zum Rezept, nicht zur Version: Ändern erzeugt keine
-- neue Version (Entscheidung Michael 17.11.2026). Kopie, Export und Vorlagen-Import
-- übernehmen sie. Nur eine neue Spalte, kein Tabellenumbau.

ALTER TABLE recipe
    ADD COLUMN internal_note TEXT CHECK (internal_note IS NULL OR length(internal_note) <= 2000);
