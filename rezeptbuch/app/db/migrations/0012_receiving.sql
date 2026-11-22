-- Migration 0012 – Wareneingang aus BÄKO-Belegen, Teil W1 (Modul 03, docs/wareneingang.md 6, freigegeben 21.11.2026)
--
-- * receiving_document: eingelesener Beleg (in W1 nur Auftragsbestätigungen; Rechnung/Gutschrift mit W2)
-- * receiving_line: Belegposition mit Ziel, Liefermenge in Belegeinheit und in Gramm (M03-18)
-- * other_article: „Sonstige Artikel“ je Händler ohne Bestand (K03-27, geändert durch H-A)
-- stock_movement hat die Spalte receiving_line_id seit 0011 (Neuaufbau einmal in S1).

CREATE TABLE receiving_document (
    id              INTEGER PRIMARY KEY,
    dealer_id       INTEGER NOT NULL REFERENCES dealer (id) ON DELETE RESTRICT,
    kind            TEXT    NOT NULL CHECK (kind IN ('order_confirmation', 'invoice', 'credit_note')),
    doc_no          TEXT    NOT NULL CHECK (length(trim(doc_no)) > 0),
    doc_date        TEXT,
    expected_date   TEXT,
    chefslist_ref   TEXT,
    status          TEXT    NOT NULL DEFAULT 'expected'
                    CHECK (status IN ('expected', 'partial', 'booked', 'cancelled', 'open', 'matched')),
    reader_version  TEXT,
    reader_json     TEXT    NOT NULL,
    file_name       TEXT,
    file_sha256     TEXT,
    file_path       TEXT,
    net_cents       INTEGER,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    booked_at       TEXT,
    note            TEXT,
    UNIQUE (dealer_id, kind, doc_no)
);
CREATE INDEX idx_receiving_document_status ON receiving_document (kind, status, expected_date);

CREATE TABLE other_article (
    id               INTEGER PRIMARY KEY,
    dealer_id        INTEGER NOT NULL REFERENCES dealer (id) ON DELETE RESTRICT,
    article_no       TEXT    NOT NULL CHECK (length(trim(article_no)) > 0),
    description      TEXT,
    commodity_group  TEXT,
    last_price_e4    INTEGER,
    last_unit        TEXT,
    archived         INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (dealer_id, article_no)
);

CREATE TABLE receiving_line (
    id                   INTEGER PRIMARY KEY,
    document_id          INTEGER NOT NULL REFERENCES receiving_document (id) ON DELETE CASCADE,
    line_no              INTEGER NOT NULL,
    article_no           TEXT,
    description          TEXT,
    commodity_group      TEXT,
    qty_milli            INTEGER NOT NULL DEFAULT 0 CHECK (qty_milli >= 0),
    unit_code            TEXT    NOT NULL DEFAULT 'KG',
    pack_text            TEXT,
    price_e4             INTEGER,
    price_unit           TEXT,
    net_cents            INTEGER,
    vat_percent          INTEGER,
    order_item           INTEGER NOT NULL DEFAULT 0 CHECK (order_item IN (0, 1)),
    unexpected           INTEGER NOT NULL DEFAULT 0 CHECK (unexpected IN (0, 1)),
    order_no             TEXT,
    delivery_note_no     TEXT,
    delivery_date        TEXT,
    target               TEXT    NOT NULL CHECK (target IN ('raw_material', 'other', 'substitute', 'strecke', 'unknown')),
    raw_material_id      INTEGER REFERENCES raw_material (id) ON DELETE RESTRICT,
    other_article_id     INTEGER REFERENCES other_article (id) ON DELETE RESTRICT,
    state                TEXT    NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'booked', 'backorder', 'cancelled')),
    delivered_qty_milli  INTEGER NOT NULL DEFAULT 0 CHECK (delivered_qty_milli >= 0),
    grams                INTEGER NOT NULL DEFAULT 0,
    grams_per_unit_used  INTEGER CHECK (grams_per_unit_used IS NULL OR grams_per_unit_used > 0),
    stock_movement_id    INTEGER REFERENCES stock_movement (id) ON DELETE SET NULL,
    invoice_line_id      INTEGER,
    note                 TEXT,
    UNIQUE (document_id, line_no),
    CHECK (target NOT IN ('raw_material', 'substitute') OR raw_material_id IS NOT NULL),
    CHECK (target <> 'other' OR other_article_id IS NOT NULL)
);
CREATE INDEX idx_receiving_line_rm ON receiving_line (raw_material_id);
CREATE INDEX idx_receiving_line_state ON receiving_line (state);
