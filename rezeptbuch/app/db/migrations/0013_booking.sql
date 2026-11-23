-- Migration 0013 – Export für die Buchführung (B1) und Rechnung/Gutschrift einlesen (W2a), Ersatzware (M03-35/36)
-- Modul 03, docs/buchfuehrung-export.md (freigegeben 23.11.2026), docs/wareneingang.md 3.
-- ENTWURF auf Zweig `w2a-export` – Michael 23.11.2026, 20:19: „warte mit der Migration, bestimmt noch was“.
--
-- * booking_group: pflegbare Buchungsgruppen (K03-79), Reihenfolge = Spaltenfolge im Export
-- * commodity_group_booking: gelernte Zuordnung Warengruppe des Händlers → Buchungsgruppe (K03-84)
-- * Gruppe + „geprüft“ an Rohstoff und sonstigem Artikel (K03-81/K03-84), Gruppe an der Belegposition
-- * receiving_line.net_book_cents: Betrag, mit dem die Position in die Belegsumme eingeht (nach Skonto)
-- * receiving_line.substitute_ref: fremde Artikelnummer/Code eines Ersatzes (M03-36, „zweites Mal“)
-- * raw_material.substitute_note: Marke „Ersatzware im Bestand – Pass prüfen“ bis zur Quittung (M03-35)
-- * stock_movement.attachment: Foto eines Belegs zu „Zugang buchen“ (M03-37, 23.11.2026, 20:21)

CREATE TABLE booking_group (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    short_name  TEXT    NOT NULL CHECK (length(trim(short_name)) > 0),
    sort        INTEGER NOT NULL DEFAULT 0,
    archived    INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
);
CREATE UNIQUE INDEX idx_booking_group_name ON booking_group (name COLLATE NOCASE) WHERE archived = 0;

INSERT INTO booking_group (id, name, short_name, sort) VALUES
    (1, 'Leergut', 'Leergut', 1),
    (2, 'Wurst', 'Wurst', 2),
    (3, 'Spirituosen', 'Spirit.', 3),
    (4, 'Feinkost', 'Feinkost', 4),
    (5, 'Handelsware', 'HW', 5),
    (6, 'Kaffee', 'Kaffee', 6),
    (7, 'Zeitung', 'Zeit.', 7),
    (8, 'Rohstoffe', 'Rohst.', 8),
    (9, 'Unkosten', 'Unk.', 9);

CREATE TABLE commodity_group_booking (
    dealer_id         INTEGER NOT NULL REFERENCES dealer (id) ON DELETE CASCADE,
    commodity_group   TEXT    NOT NULL,
    booking_group_id  INTEGER NOT NULL REFERENCES booking_group (id) ON DELETE RESTRICT,
    PRIMARY KEY (dealer_id, commodity_group)
);

ALTER TABLE raw_material ADD COLUMN booking_group_id INTEGER REFERENCES booking_group (id);
ALTER TABLE raw_material ADD COLUMN booking_group_checked INTEGER NOT NULL DEFAULT 0 CHECK (booking_group_checked IN (0, 1));
ALTER TABLE raw_material ADD COLUMN substitute_note TEXT;
ALTER TABLE other_article ADD COLUMN booking_group_id INTEGER REFERENCES booking_group (id);
ALTER TABLE other_article ADD COLUMN booking_group_checked INTEGER NOT NULL DEFAULT 0 CHECK (booking_group_checked IN (0, 1));
ALTER TABLE receiving_line ADD COLUMN booking_group_id INTEGER REFERENCES booking_group (id);
ALTER TABLE receiving_line ADD COLUMN net_book_cents INTEGER;
ALTER TABLE receiving_line ADD COLUMN substitute_ref TEXT;

-- Keine Vorbelegung an den Artikeln: die Gruppe wird beim ersten Beleg aus Warengruppe bzw. Art abgeleitet
-- (ungeprüft, K03-84) – sonst bekäme z. B. Pfand als Hilfs- und Betriebsstoff fälschlich „Unkosten“.

-- M03-37: „Zugang buchen“ ohne Beleg-Zwang, aber mit Kamerataste „Beleg fotografieren“.
-- Dateiname (ohne Pfad) in der Ablage belege/zugang neben der Datenbank; leer = kein Foto.
ALTER TABLE stock_movement ADD COLUMN attachment TEXT;
