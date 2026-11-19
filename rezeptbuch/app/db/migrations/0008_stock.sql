-- Migration 0008 – Rohstoffbestand und Meldewert (Modul 03, Ergänzung VC03-b, docs/bestand.md)
--
-- * raw_material.stock_g: aktueller Bestand in Gramm; leer = keine Bestandsführung (B2), negativ erlaubt (B3)
-- * raw_material.stock_alert_g: Meldewert in Gramm; leer = keiner
-- * stock_movement: Protokoll jeder Buchung (Zugang, Inventur, Abzug beim Verwiegen, Rückbuchung)
--
-- Modul 04 (PDF-Import) nimmt danach die nächste freie Nummer (0009, K03-11).

ALTER TABLE raw_material ADD COLUMN stock_g INTEGER;

ALTER TABLE raw_material
    ADD COLUMN stock_alert_g INTEGER CHECK (stock_alert_g IS NULL OR stock_alert_g >= 0);

CREATE TABLE stock_movement (
    id               INTEGER PRIMARY KEY,
    raw_material_id  INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE CASCADE,
    kind             TEXT    NOT NULL CHECK (kind IN ('receipt', 'inventory', 'consumption', 'reversal')),
    -- Änderung in Gramm (bei Inventur die Differenz; leer, wenn vorher oder nachher keine Führung)
    delta_g          INTEGER,
    -- Bestand nach der Buchung; leer = Bestandsführung beendet
    stock_after_g    INTEGER,
    batch_id         INTEGER REFERENCES batch (id) ON DELETE RESTRICT,
    batch_item_id    INTEGER REFERENCES batch_item (id) ON DELETE RESTRICT,
    station_id       INTEGER REFERENCES station (id) ON DELETE RESTRICT,
    source           TEXT    NOT NULL DEFAULT 'admin',
    note             TEXT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_stock_movement_raw_material ON stock_movement (raw_material_id, id);
CREATE INDEX idx_stock_movement_batch ON stock_movement (batch_id);
