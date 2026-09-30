"""Load openFDA recall enforcement exports into SQLite.

Usage:
    python -m fda_recall.load [FILE_OR_ZIP ...] [--db PATH]

With no files given, loads every *.json / *.zip in the project folder.
Safe to re-run: records are upserted by recall_number, unchanged records
are left alone, and changed ones have their prior version kept in
recall_history. Afterwards the clean tables are rebuilt (see clean.py).
"""

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import clean, db

PROJECT_DIR = Path(__file__).resolve().parent.parent


def iter_documents(path):
    """Yield (name, bytes) for a .json file or each .json inside a .zip."""
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            for name in sorted(zf.namelist()):
                if name.lower().endswith(".json"):
                    yield f"{path.name}!{name}", zf.read(name)
    else:
        yield path.name, path.read_bytes()


def to_iso_date(value):
    """'20260807' -> '2026-08-07'; anything unexpected is returned as-is."""
    if not value:
        return None
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def record_to_row(rec):
    row = {"recall_number": rec["recall_number"]}
    for f in db.TEXT_FIELDS:
        row[f] = rec.get(f) or None  # empty string -> NULL
    for f in db.DATE_FIELDS:
        row[f] = to_iso_date(rec.get(f))
    return row


def load_document(conn, name, raw_bytes):
    doc = json.loads(raw_bytes)
    results = doc.get("results", [])
    meta = doc.get("meta", {})

    unknown = {k for rec in results for k in rec} - db.KNOWN_FIELDS
    if unknown:
        print(f"  note: new fields not in schema (kept in raw_json): {sorted(unknown)}")

    cur = conn.execute(
        "INSERT INTO load_runs (loaded_at, source_file, source_sha256, source_last_updated, record_count)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            name,
            hashlib.sha256(raw_bytes).hexdigest(),
            meta.get("last_updated"),
            len(results),
        ),
    )
    run_id = cur.lastrowid

    existing = dict(conn.execute("SELECT recall_number, content_hash FROM recalls"))
    columns = ["recall_number", *db.TEXT_FIELDS, *db.DATE_FIELDS]
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    unchanged_ids = []

    for rec in results:
        raw_json = json.dumps(rec, sort_keys=True, ensure_ascii=False)
        content_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        recall_number = rec["recall_number"]
        old_hash = existing.get(recall_number)

        if old_hash == content_hash:
            counts["unchanged"] += 1
            unchanged_ids.append((run_id, recall_number))
            continue

        if old_hash is None:
            counts["inserted"] += 1
        else:
            counts["updated"] += 1
            conn.execute(
                "INSERT INTO recall_history (recall_number, replaced_in_run, raw_json)"
                " SELECT recall_number, ?, raw_json FROM recalls WHERE recall_number = ?",
                (run_id, recall_number),
            )

        row = record_to_row(rec)
        values = [row[c] for c in columns] + [raw_json, content_hash, run_id, run_id, run_id]
        placeholders = ", ".join("?" * len(values))
        set_clause = ", ".join(
            f"{c} = excluded.{c}"
            for c in [*columns[1:], "raw_json", "content_hash", "last_seen_run", "last_changed_run"]
        )
        conn.execute(
            f"INSERT INTO recalls ({', '.join(columns)}, raw_json, content_hash,"
            f" first_seen_run, last_seen_run, last_changed_run) VALUES ({placeholders})"
            f" ON CONFLICT(recall_number) DO UPDATE SET {set_clause}",
            values,
        )
        existing[recall_number] = content_hash

    conn.executemany(
        "UPDATE recalls SET last_seen_run = ? WHERE recall_number = ?", unchanged_ids
    )
    conn.execute(
        "UPDATE load_runs SET inserted = ?, updated = ?, unchanged = ? WHERE run_id = ?",
        (counts["inserted"], counts["updated"], counts["unchanged"], run_id),
    )
    return run_id, len(results), counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help="openFDA .json or .zip exports")
    parser.add_argument("--db", type=Path, default=db.DEFAULT_DB, help=f"SQLite file (default: {db.DEFAULT_DB})")
    args = parser.parse_args(argv)

    files = args.files or sorted(
        p for p in PROJECT_DIR.iterdir() if p.suffix.lower() in (".json", ".zip")
    )
    if not files:
        parser.error(f"no .json or .zip files found in {PROJECT_DIR}")

    conn = db.connect(args.db)
    try:
        for path in files:
            for name, raw_bytes in iter_documents(path):
                print(f"Loading {name} ...")
                with conn:  # one transaction per document
                    run_id, total, counts = load_document(conn, name, raw_bytes)
                print(
                    f"  run {run_id}: {total} records -> {counts['inserted']} new,"
                    f" {counts['updated']} changed, {counts['unchanged']} unchanged"
                )
        clean.print_summary(clean.rebuild(conn))
    finally:
        conn.close()
    print(f"Database: {args.db}")


if __name__ == "__main__":
    sys.exit(main())
