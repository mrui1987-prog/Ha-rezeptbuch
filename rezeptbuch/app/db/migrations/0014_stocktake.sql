-- Migration 0014 – Inventur, Teil I1 (Modul 03, docs/strichcode.md 5 und 8, freigegeben 22.11.2026, 08:09)
--
-- * stocktake: eine Inventur mit Stichtag, Bezeichnung und Umfang; höchstens eine offene (Abschnitt 5.1)
-- * stocktake_count: Zähleinträge je Rohstoff und Lagerort, mit Buchbestand im Moment der Zählung
--   (Zählzeitpunkt, Abschnitt 5.4); Menge in derselben Einheit wie raw_material.stock_g
--   (Gramm, bei Hilfs- und Betriebsstoffen 1 Verpackungseinheit = 1000)
-- * stocktake_line: Ergebnis je Rohstoff beim Abschluss, mit festgeschriebenem Preis und Wert (K03-58)
-- stock_movement.stocktake_id gibt es seit 0011 (Neuaufbau einmal in S1); hier nur ein Index dazu.
-- Nummer: I1 sollte 0012 werden; W1 und B1 kamen zuerst, daher die nächste freie (K03-61).

CREATE TABLE stocktake (
    id                   INTEGER PRIMARY KEY,
    name                 TEXT    NOT NULL CHECK (length(trim(name)) > 0),
    stichtag             TEXT    NOT NULL CHECK (stichtag GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    scope                TEXT    NOT NULL DEFAULT 'stocked' CHECK (scope IN ('stocked', 'active')),
    status               TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    closed_at            TEXT,
    total_value_cents    INTEGER,
    missing_price_count  INTEGER,
    note                 TEXT,
    CHECK ((status = 'open') = (closed_at IS NULL))
);
-- Höchstens eine offene Inventur (Abschnitt 5.1)
CREATE UNIQUE INDEX idx_stocktake_one_open ON stocktake (status) WHERE status = 'open';

CREATE TABLE stocktake_count (
    id               INTEGER PRIMARY KEY,
    stocktake_id     INTEGER NOT NULL REFERENCES stocktake (id) ON DELETE CASCADE,
    raw_material_id  INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE RESTRICT,
    location_id      INTEGER REFERENCES storage_location (id) ON DELETE RESTRICT,
    qty              INTEGER NOT NULL CHECK (qty >= 0),
    book_at_count    INTEGER,
    source           TEXT    NOT NULL DEFAULT 'hand' CHECK (source IN ('scan', 'hand')),
    device_id        TEXT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX idx_stocktake_count_rm ON stocktake_count (stocktake_id, raw_material_id, id);

CREATE TABLE stocktake_line (
    stocktake_id       INTEGER NOT NULL REFERENCES stocktake (id) ON DELETE CASCADE,
    raw_material_id    INTEGER NOT NULL REFERENCES raw_material (id) ON DELETE RESTRICT,
    counted            INTEGER,
    action             TEXT    NOT NULL CHECK (action IN ('set', 'unchanged', 'zero')),
    book_before        INTEGER,
    stock_after        INTEGER,
    since_count        INTEGER NOT NULL DEFAULT 0,
    value_qty          INTEGER,
    price_cents        INTEGER,
    value_cents        INTEGER,
    stock_movement_id  INTEGER REFERENCES stock_movement (id) ON DELETE RESTRICT,
    -- Stammdaten zum Abschluss festgeschrieben (Export bleibt gleich, auch wenn der Rohstoff später geändert wird)
    number             INTEGER NOT NULL,
    name               TEXT    NOT NULL,
    type               TEXT    NOT NULL,
    pack_g             INTEGER,
    pack_label         TEXT,
    locations          TEXT,
    PRIMARY KEY (stocktake_id, raw_material_id),
    CHECK ((action = 'set') = (counted IS NOT NULL))
);

CREATE INDEX idx_stock_movement_stocktake ON stock_movement (stocktake_id) WHERE stocktake_id IS NOT NULL;
