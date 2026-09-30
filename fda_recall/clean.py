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
                 with reason_category (see reasons.py), product_category
                 (see products.py) and illness_reported (see detection.py)
    product_reason_tags
                 every (category, detail) tag matched in reason_for_recall
    product_detection_sources
                 how the problem was found, per reason_for_recall (see detection.py)
    product_upcs UPC / EAN codes found in product_description (see products.py)
    data_issues  records that failed a sanity check, for manual review
"""

import argparse
import json
import re
from datetime import date
from itertools import groupby

from . import db, detection, distribution, products as product_text, quantity, reasons, usda

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
DROP TABLE IF EXISTS product_detection_sources;
DROP TABLE IF EXISTS product_upcs;
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
    state_count             INTEGER NOT NULL,
    illness_reported        INTEGER NOT NULL,
    agency                  TEXT NOT NULL,   -- 'FDA' or 'USDA'
    recall_type             TEXT NOT NULL,   -- 'recall' or 'public_health_alert' (USDA only)
    source_url              TEXT             -- the agency's notice page, where there is one
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
    quantity_is_total       INTEGER,
    product_category        TEXT,
    illness_reported        INTEGER NOT NULL
);

CREATE TABLE product_reason_tags (
    recall_number           TEXT NOT NULL REFERENCES products(recall_number),
    category                TEXT NOT NULL,
    detail                  TEXT NOT NULL,
    PRIMARY KEY (recall_number, category, detail)
);

CREATE TABLE product_detection_sources (
    recall_number           TEXT NOT NULL REFERENCES products(recall_number),
    source                  TEXT NOT NULL,
    PRIMARY KEY (recall_number, source)
);

CREATE TABLE product_upcs (
    recall_number           TEXT NOT NULL REFERENCES products(recall_number),
    upc                     TEXT NOT NULL,
    PRIMARY KEY (recall_number, upc)
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
CREATE INDEX ix_products_category     ON products(product_category);
CREATE INDEX ix_detection_source      ON product_detection_sources(source);
CREATE INDEX ix_product_upcs_upc      ON product_upcs(upc);
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


def usda_rows(conn):
    """Clean-layer rows for every USDA FSIS notice in usda_recalls.

    Each notice becomes one event ("USDA-<number>") with one product row
    carrying the FSIS number. The shared text rules only see the parts of the
    notice that vary (see usda.notice_parts), never FSIS's boilerplate.
    """
    out = []
    for number, raw in conn.execute("SELECT recall_number, raw_json FROM usda_recalls ORDER BY recall_number"):
        rec = json.loads(raw)
        p = usda.notice_parts(rec)
        event_id = f"USDA-{number}"
        classification = rec.get("recall_classification")
        firm = p["firm"] or ("Firm not named (public health alert)" if p["is_alert"] else "Firm not named")
        states, nationwide, foreign, online = distribution.parse_distribution(p["distribution"])
        parsed_qty = quantity.parse_quantity(p["quantity"])
        units = parsed_qty[0] if parsed_qty else None
        illness = p["outbreak"] or detection.illness_reported(p["illness_text"])

        tags = reasons.tag_reason(p["reason"])
        if reasons.primary_category(tags) == "other":  # fall back to FSIS's own reason field
            tags = sorted({usda.FSIS_REASON_TAGS[r] for r in rec.get("recall_reason") or [] if r in usda.FSIS_REASON_TAGS})
        first_item = (p["product_description"] or "").split("\n")[0]
        category = product_text.product_category(first_item) or "meat_poultry"  # FSIS's remit
        date_ = rec.get("recall_date")

        fields = {
            "recalling_firm": firm, "address_1": None, "address_2": None, "city": None,
            "state": p["state"], "postal_code": None, "country": p["country"] or ("United States" if p["state"] else None),
            "voluntary_mandated": None, "initial_firm_notification": None,
            "distribution_pattern": p["distribution"], "recall_initiation_date": date_, "report_date": date_,
        }
        event = (
            event_id, firm_key(firm), *(fields[f] for f in EVENT_FIELDS),
            1,
            classification if classification in CLASS_SEVERITY else None,
            int(p["ongoing"]),
            units, quantity.size_bucket(units),
            int(nationwide), int(foreign or (p["country"] not in (None, "United States"))), int(online),
            len(states), int(illness),
            "USDA", "public_health_alert" if p["is_alert"] else "recall", rec.get("recall_url"),
        )
        product_fields = {
            "status": "Ongoing" if p["ongoing"] else "Terminated",
            "classification": classification,
            "product_type": "Meat, poultry and egg products",
            "product_description": p["product_description"],
            "product_quantity": p["quantity"],
            "reason_for_recall": p["reason"],
            "code_info": None, "more_code_info": None,
            "center_classification_date": None,
            "termination_date": None,  # FSIS only records the year a recall closed
        }
        product = (
            number, event_id, *(product_fields[f] for f in PRODUCT_FIELDS),
            reasons.primary_category(tags),
            *(parsed_qty or (None, None, None)),
            category, int(illness),
        )
        out.append({
            "event_id": event_id, "recall_number": number, "event": event, "product": product,
            "states": states, "nationwide": nationwide, "tags": tags,
            "sources": usda.fsis_detection_sources(p["discovery"]),
            "upcs": product_text.find_upcs(p["product_description"]), "illness": bool(illness),
        })
    return out


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
        rec["illness_reported"] = detection.illness_reported(rec["reason_for_recall"])
        records.append(rec)

    events, event_states = [], []
    unsized_events = events_without_location = untagged_products = illness_events = usda_events = 0
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
            int(any(rec["illness_reported"] for rec in group)),
            "FDA", "recall", None,
        ))
        unsized_events += units is None
        events_without_location += not states and not nationwide
        illness_events += any(rec["illness_reported"] for rec in group)

    # Many products share the same reason text, so cache per text.
    reason_cache = {}
    products, reason_tags, detection_rows, upc_rows = [], [], [], []
    for rec in records:
        number, text = rec["raw_recall_number"], rec["reason_for_recall"]
        if text not in reason_cache:
            reason_cache[text] = (reasons.tag_reason(text), detection.detection_sources(text))
        tags, sources = reason_cache[text]
        category = reasons.primary_category(tags)
        untagged_products += category == "other"
        units, unit_type, is_total = rec["quantity"] or (None, None, None)
        products.append((
            number, rec["event_id"], *(rec[f] for f in PRODUCT_FIELDS),
            category,
            units, unit_type, is_total,
            product_text.product_category(rec["product_description"]),
            int(rec["illness_reported"]),
        ))
        reason_tags.extend((number, c, d) for c, d in tags)
        detection_rows.extend((number, s) for s in sources)
        upc_rows.extend((number, upc) for upc in product_text.find_upcs(rec["product_description"]))

    # USDA FSIS notices: one event + one product row each, so every shared
    # table and endpoint works for both agencies.
    for u in usda_rows(conn):
        event_id, number = u["event_id"], u["recall_number"]
        events.append(u["event"])
        event_states.extend((event_id, s) for s in u["states"])
        products.append(u["product"])
        reason_tags.extend((number, c, d) for c, d in u["tags"])
        detection_rows.extend((number, s) for s in u["sources"])
        upc_rows.extend((number, upc) for upc in u["upcs"])
        untagged_products += u["product"][len(PRODUCT_FIELDS) + 2] == "other"
        unsized_events += u["event"][len(EVENT_FIELDS) + 5] is None
        events_without_location += not u["states"] and not u["nationwide"]
        illness_events += u["illness"]
        usda_events += 1

    with conn:
        conn.executescript(SCHEMA)
        for table, rows in [
            ("events", events),
            ("event_states", event_states),
            ("products", products),
            ("product_reason_tags", reason_tags),
            ("product_detection_sources", detection_rows),
            ("product_upcs", upc_rows),
        ]:
            if rows:
                conn.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(rows[0]))})", rows)
        conn.executemany(
            "INSERT INTO data_issues (recall_number, event_id, field, value, issue) VALUES (?, ?, ?, ?, ?)",
            issues,
        )
    return {
        "events": len(events),
        "products": len(products),
        "reason_tags": len(reason_tags),
        "untagged_products": untagged_products,
        "uncategorized_products": sum(p[-2] is None for p in products),
        "unsized_events": unsized_events,
        "events_without_location": events_without_location,
        "illness_events": illness_events,
        "usda_events": usda_events,
        "upcs": len(upc_rows),
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
        f"Clean tables rebuilt: {counts['events']} events ({counts['usda_events']} USDA),"
        f" {counts['products']} products, {counts['upcs']} UPCs,"
        f" {counts['illness_events']} events with illnesses reported, {counts['data_issues']} data issues\n"
        f"  not classified: {counts['untagged_products']} products without a recall reason category,"
        f" {counts['uncategorized_products']} without a product category,"
        f" {counts['unsized_events']} events without a usable quantity,"
        f" {counts['events_without_location']} without states or a nationwide flag"
    )


if __name__ == "__main__":
    main()
