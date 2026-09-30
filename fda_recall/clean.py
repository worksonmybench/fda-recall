"""Rebuild the clean analysis tables from the raw `recalls` import table.

Usage:
    python -m fda_recall.clean [--db PATH]

Runs automatically at the end of `python -m fda_recall.load`. The clean
tables are dropped and recreated on every run, so changing a rule here
and re-running is all it takes to apply it to the whole history. Nothing
in the raw import tables is modified.

Tables produced:
    events       one row per recall event (firm, address, distribution, dates),
                 with est_units and a t-shirt size (see quantity.py), and
                 is_nationwide / is_foreign / is_online / state_count (see distribution.py)
    event_states the US states and territories each event's distribution names
    event_state_reach (view)
                 event_states plus every state for nationwide events
    products     one row per recall_number, linked to events by event_id,
                 with reason_category (see reasons.py)
    product_reason_tags
                 every (category, detail) tag matched in reason_for_recall
    data_issues  records that failed a sanity check, for manual review
"""

import argparse
import json
import re
from datetime import date
from itertools import groupby

from . import db, distribution, quantity, reasons

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
DROP VIEW IF EXISTS event_state_reach;
DROP TABLE IF EXISTS event_states;
DROP TABLE IF EXISTS product_reason_tags;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS data_issues;

CREATE TABLE events (
    event_id                TEXT PRIMARY KEY,
    firm_key                TEXT,
    {", ".join(f"{f} TEXT" for f in EVENT_FIELDS)},
    product_count           INTEGER NOT NULL,
    most_severe_class       TEXT,
    ongoing_product_count   INTEGER NOT NULL,
    est_units               REAL,
    size                    TEXT,
    is_nationwide           INTEGER NOT NULL,
    is_foreign              INTEGER NOT NULL,
    is_online               INTEGER NOT NULL,
    state_count             INTEGER NOT NULL
);

CREATE TABLE event_states (
    event_id                TEXT NOT NULL REFERENCES events(event_id),
    state                   TEXT NOT NULL,
    PRIMARY KEY (event_id, state)
);

-- "Which recalls reached this state?": named states, plus all 50 states
-- and DC for nationwide events (incl. online sales; these usually don't list states).
CREATE VIEW event_state_reach AS
    SELECT event_id, state, 0 AS via_nationwide FROM event_states
    UNION
    SELECT e.event_id, s.state, 1 FROM events e
    CROSS JOIN (SELECT value AS state FROM json_each('{json.dumps(sorted(distribution.STATES))}')) s
    WHERE e.is_nationwide
      AND NOT EXISTS (SELECT 1 FROM event_states x WHERE x.event_id = e.event_id AND x.state = s.state);

CREATE TABLE products (
    recall_number           TEXT PRIMARY KEY,
    event_id                TEXT REFERENCES events(event_id),
    {", ".join(f"{f} TEXT" for f in PRODUCT_FIELDS)},
    reason_category         TEXT NOT NULL,
    est_units               REAL,
    quantity_unit_type      TEXT,
    quantity_is_total       INTEGER
);

CREATE TABLE product_reason_tags (
    recall_number           TEXT NOT NULL REFERENCES products(recall_number),
    category                TEXT NOT NULL,
    detail                  TEXT NOT NULL,
    PRIMARY KEY (recall_number, category, detail)
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
CREATE INDEX ix_events_size           ON events(size);
CREATE INDEX ix_event_states_state    ON event_states(state);
CREATE INDEX ix_products_event        ON products(event_id);
CREATE INDEX ix_products_class        ON products(classification);
CREATE INDEX ix_products_status       ON products(status);
CREATE INDEX ix_products_reason_cat   ON products(reason_category);
CREATE INDEX ix_reason_tags_category  ON product_reason_tags(category, detail);
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
        rec["quantity"] = quantity.parse_quantity(rec["product_quantity"])
        records.append(rec)

    events, event_states = [], []
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
        units = quantity.event_units([(rec["product_quantity"], rec["quantity"]) for rec in group])
        states, nationwide, foreign, online = distribution.parse_distribution(first["distribution_pattern"])
        event_states.extend((event_id, state) for state in states)
        events.append((
            event_id,
            firm_key(first["recalling_firm"]),
            *(first[f] for f in EVENT_FIELDS),
            len(group),
            min(classes, key=CLASS_SEVERITY.get) if classes else None,
            sum(rec["status"] == "Ongoing" for rec in group),
            units,
            quantity.size_bucket(units),
            int(nationwide),
            int(foreign),
            int(online),
            len(states),
        ))

    tag_cache = {}  # many products share the same reason text
    products, reason_tags = [], []
    for rec in records:
        text = rec["reason_for_recall"]
        if text not in tag_cache:
            tag_cache[text] = reasons.tag_reason(text)
        tags = tag_cache[text]
        units, unit_type, is_total = rec["quantity"] or (None, None, None)
        products.append((
            rec["raw_recall_number"], rec["event_id"], *(rec[f] for f in PRODUCT_FIELDS),
            reasons.primary_category(tags),
            units, unit_type, is_total,
        ))
        reason_tags.extend((rec["raw_recall_number"], category, detail) for category, detail in tags)

    with conn:
        conn.executescript(SCHEMA)
        conn.executemany(f"INSERT INTO events VALUES ({', '.join('?' * (len(EVENT_FIELDS) + 11))})", events)
        conn.executemany("INSERT INTO event_states VALUES (?, ?)", event_states)
        conn.executemany(f"INSERT INTO products VALUES ({', '.join('?' * (len(PRODUCT_FIELDS) + 6))})", products)
        conn.executemany("INSERT INTO product_reason_tags VALUES (?, ?, ?)", reason_tags)
        conn.executemany(
            "INSERT INTO data_issues (recall_number, event_id, field, value, issue) VALUES (?, ?, ?, ?, ?)",
            issues,
        )
    return {
        "events": len(events),
        "products": len(products),
        "reason_tags": len(reason_tags),
        "untagged_products": sum(p[len(PRODUCT_FIELDS) + 2] == "other" for p in products),
        "unsized_events": sum(e[len(EVENT_FIELDS) + 6] is None for e in events),
        "events_without_location": sum(not e[-1] and not e[-4] for e in events),
        "data_issues": len(issues),
    }


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
        f"Clean tables rebuilt: {counts['events']} events, {counts['products']} products"
        f" ({counts['untagged_products']} with no recall reason category),"
        f" {counts['unsized_events']} events with no usable quantity,"
        f" {counts['events_without_location']} with no states or nationwide flag,"
        f" {counts['data_issues']} data issues"
    )


if __name__ == "__main__":
    main()
