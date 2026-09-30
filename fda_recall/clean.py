"""Rebuild the clean analysis tables from the raw `recalls` import table.

Usage:
    python -m fda_recall.clean [--db PATH]

Runs automatically at the end of `python -m fda_recall.load`. The clean
tables are dropped and recreated on every run, so changing a rule here
and re-running is all it takes to apply it to the whole history. Nothing
in the raw import tables is modified.

Tables produced:
    events       one row per recall event (firm, address, distribution, dates)
    products     one row per recall_number, linked to events by event_id
    data_issues  records that failed a sanity check, for manual review
"""

import argparse
import re
from datetime import date
from itertools import groupby

from . import db

# Values the FDA uses to mean "no value".
PLACEHOLDERS = {"", "N/A", "NA", "n/a", "N/a", "None", "none"}

# Fields that describe the recall event as a whole; they should be identical
# on every product row of an event.
EVENT_FIELDS = [
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
    "recall_initiation_date",
    "report_date",
]
# Fields that can legitimately differ between products in one event.
PRODUCT_FIELDS = [
    "status",
    "classification",
    "product_type",
    "product_description",
    "product_quantity",
    "reason_for_recall",
    "code_info",
    "more_code_info",
    "center_classification_date",
    "termination_date",
]

RECALL_NUMBER_RE = re.compile(r"^[FH]-\d+-\d{4}$")
MIN_PLAUSIBLE_YEAR = 1990
CLASS_SEVERITY = {"Class I": 1, "Class II": 2, "Class III": 3}

SCHEMA = f"""
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS data_issues;

CREATE TABLE events (
    event_id                TEXT PRIMARY KEY,
    firm_key                TEXT,
    {", ".join(f"{f} TEXT" for f in EVENT_FIELDS)},
    product_count           INTEGER NOT NULL,
    most_severe_class       TEXT,
    ongoing_product_count   INTEGER NOT NULL
);

CREATE TABLE products (
    recall_number           TEXT PRIMARY KEY,
    event_id                TEXT REFERENCES events(event_id),
    {", ".join(f"{f} TEXT" for f in PRODUCT_FIELDS)}
);

CREATE TABLE data_issues (
    issue_id                INTEGER PRIMARY KEY,
    recall_number           TEXT,
    event_id                TEXT,
    field                   TEXT,
    value                   TEXT,
    issue                   TEXT NOT NULL
);

CREATE INDEX ix_events_firm_key       ON events(firm_key);
CREATE INDEX ix_events_report_date    ON events(report_date);
CREATE INDEX ix_products_event        ON products(event_id);
CREATE INDEX ix_products_class        ON products(classification);
CREATE INDEX ix_products_status       ON products(status);
CREATE INDEX ix_data_issues_issue     ON data_issues(issue);
"""


def clean_text(value):
    """Trim, collapse runs of spaces within lines, drop blank lines, map placeholders to None."""
    if value is None:
        return None
    lines = (re.sub(r"[ \t ]+", " ", line).strip() for line in value.splitlines())
    text = "\n".join(line for line in lines if line)
    return None if text in PLACEHOLDERS else text


def firm_key(name):
    """Matching key for firm names: 'Ventura Foods, LLC' -> 'VENTURA FOODS LLC'."""
    if not name:
        return None
    key = re.sub(r"[.,'\"]", "", name.upper())
    return re.sub(r"\s+", " ", key).strip() or None


def date_issue(value):
    """Return a description of what's wrong with an ISO date string, or None."""
    if value is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return "unparseable_date"
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return "invalid_date"
    if parsed.year < MIN_PLAUSIBLE_YEAR or parsed.year > date.today().year + 1:
        return "implausible_date"
    return None


def rebuild(conn):
    """Drop and recreate the clean tables from `recalls`. Returns row counts."""
    raw_fields = ["recall_number", "event_id", *EVENT_FIELDS, *PRODUCT_FIELDS]
    date_fields = [f for f in raw_fields if f.endswith("_date")]
    rows = conn.execute(
        f"SELECT {', '.join(raw_fields)} FROM recalls ORDER BY event_id, recall_number"
    ).fetchall()

    issues = []

    def flag(rec, field, issue, value=None):
        issues.append((rec["raw_recall_number"], rec["event_id"], field, value, issue))

    records = []
    for row in rows:
        rec = {f: clean_text(v) for f, v in zip(raw_fields, row)}
        rec["raw_recall_number"] = row[0]  # the import key, kept even when it's junk
        if rec["recall_number"] is None:
            flag(rec, "recall_number", "missing_recall_number", row[0])
        elif not RECALL_NUMBER_RE.match(rec["recall_number"]):
            flag(rec, "recall_number", "malformed_recall_number", rec["recall_number"])
        if rec["event_id"] is None:
            flag(rec, "event_id", "missing_event_id")
        for f in date_fields:
            problem = date_issue(rec[f])
            if problem:
                flag(rec, f, problem, rec[f])
        if rec["status"] == "Terminated" and rec["termination_date"] is None:
            flag(rec, "termination_date", "terminated_without_termination_date")
        if rec["status"] == "Ongoing" and rec["termination_date"] is not None:
            flag(rec, "termination_date", "ongoing_with_termination_date", rec["termination_date"])
        if rec["classification"] not in CLASS_SEVERITY:
            flag(rec, "classification", "unclassified", rec["classification"])
        records.append(rec)

    events = []
    for event_id, group in groupby(records, key=lambda r: r["event_id"]):
        group = list(group)
        if event_id is None:
            continue  # already flagged; products keep a NULL event_id
        first = group[0]
        for f in EVENT_FIELDS:
            values = {rec[f] for rec in group}
            if len(values) > 1:
                flag(first, f, "event_field_mismatch", " | ".join(sorted(v or "NULL" for v in values)))
        classes = [rec["classification"] for rec in group if rec["classification"] in CLASS_SEVERITY]
        events.append((
            event_id,
            firm_key(first["recalling_firm"]),
            *(first[f] for f in EVENT_FIELDS),
            len(group),
            min(classes, key=CLASS_SEVERITY.get) if classes else None,
            sum(rec["status"] == "Ongoing" for rec in group),
        ))

    products = [
        (rec["raw_recall_number"], rec["event_id"], *(rec[f] for f in PRODUCT_FIELDS))
        for rec in records
    ]

    with conn:
        conn.executescript(SCHEMA)
        conn.executemany(f"INSERT INTO events VALUES ({', '.join('?' * (len(EVENT_FIELDS) + 5))})", events)
        conn.executemany(f"INSERT INTO products VALUES ({', '.join('?' * (len(PRODUCT_FIELDS) + 2))})", products)
        conn.executemany(
            "INSERT INTO data_issues (recall_number, event_id, field, value, issue) VALUES (?, ?, ?, ?, ?)",
            issues,
        )
    return {"events": len(events), "products": len(products), "data_issues": len(issues)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=db.DEFAULT_DB, help=f"SQLite file (default: {db.DEFAULT_DB})")
    args = parser.parse_args(argv)
    conn = db.connect(args.db)
    try:
        print_summary(rebuild(conn))
    finally:
        conn.close()


def print_summary(counts):
    print(
        f"Clean tables rebuilt: {counts['events']} events, {counts['products']} products,"
        f" {counts['data_issues']} data issues"
    )


if __name__ == "__main__":
    main()
