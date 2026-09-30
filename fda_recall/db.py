"""SQLite schema and connection helpers."""

import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "recalls.db"

# Scalar fields from the openFDA food enforcement export, in column order.
# Dates are stored as ISO strings (YYYY-MM-DD); everything else as text.
TEXT_FIELDS = [
    "event_id",
    "status",
    "classification",
    "product_type",
    "recalling_firm",
    "address_1",
    "address_2",
    "city",
    "state",
    "postal_code",
    "country",
    "voluntary_mandated",
    "initial_firm_notification",
    "distribution_pattern",
    "product_description",
    "product_quantity",
    "reason_for_recall",
    "code_info",
    "more_code_info",
]
DATE_FIELDS = [
    "recall_initiation_date",
    "center_classification_date",
    "report_date",
    "termination_date",
]
# Fields we know about but don't give their own column (kept in raw_json).
IGNORED_FIELDS = {"openfda"}
KNOWN_FIELDS = {"recall_number", *TEXT_FIELDS, *DATE_FIELDS, *IGNORED_FIELDS}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS load_runs (
    run_id              INTEGER PRIMARY KEY,
    loaded_at           TEXT NOT NULL,
    source_file         TEXT NOT NULL,
    source_sha256       TEXT NOT NULL,
    source_last_updated TEXT,
    record_count        INTEGER,
    inserted            INTEGER,
    updated             INTEGER,
    unchanged           INTEGER
);

CREATE TABLE IF NOT EXISTS recalls (
    recall_number       TEXT PRIMARY KEY,
    {", ".join(f"{f} TEXT" for f in TEXT_FIELDS + DATE_FIELDS)},
    raw_json            TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    first_seen_run      INTEGER NOT NULL REFERENCES load_runs(run_id),
    last_seen_run       INTEGER NOT NULL REFERENCES load_runs(run_id),
    last_changed_run    INTEGER NOT NULL REFERENCES load_runs(run_id)
);

-- Previous versions of a recall, saved whenever a reload changes it
-- (e.g. status Ongoing -> Terminated).
CREATE TABLE IF NOT EXISTS recall_history (
    recall_number       TEXT NOT NULL,
    replaced_in_run     INTEGER NOT NULL REFERENCES load_runs(run_id),
    raw_json            TEXT NOT NULL,
    PRIMARY KEY (recall_number, replaced_in_run)
);

CREATE INDEX IF NOT EXISTS ix_recalls_event          ON recalls(event_id);
CREATE INDEX IF NOT EXISTS ix_recalls_firm           ON recalls(recalling_firm);
CREATE INDEX IF NOT EXISTS ix_recalls_classification ON recalls(classification);
CREATE INDEX IF NOT EXISTS ix_recalls_status         ON recalls(status);
CREATE INDEX IF NOT EXISTS ix_recalls_report_date    ON recalls(report_date);
"""


def connect(db_path=DEFAULT_DB):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
