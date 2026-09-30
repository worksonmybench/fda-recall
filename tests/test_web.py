import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fda_recall import clean, db, load
from fda_recall.web import endpoints, export
from tests.test_clean import make_record


def build_db(records):
    conn = db.connect(":memory:")
    load.load_document(conn, "test.json", json.dumps({"meta": {"last_updated": "2026-01-01"}, "results": records}).encode())
    clean.rebuild(conn)
    return conn


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.conn = build_db([
            make_record(),  # event 100, firm in IL, distributed to IL
            make_record(recall_number="F-0002-2020", event_id="200", state="CA",
                        distribution_pattern="Nationwide", status="Ongoing", termination_date=""),
        ])

    def test_every_exported_path_resolves_and_nothing_else_does(self):
        paths = list(endpoints.all_paths(self.conn))
        self.assertIn("dashboard/impacting/IL", [p for p, _, _ in paths])
        for url_path, _, kwargs in paths:
            fn, resolved = endpoints.resolve(self.conn, url_path)
            self.assertEqual(resolved, kwargs)
        self.assertIsNone(endpoints.resolve(self.conn, "dashboard/impacting/ZZ"))
        self.assertIsNone(endpoints.resolve(self.conn, "dashboard/bogus/IL"))
        self.assertIsNone(endpoints.resolve(self.conn, "nope"))

    def test_views(self):
        # Nationwide event 200 impacts IL too; only event 100 originates from IL.
        impacting = endpoints.dashboard(self.conn, "impacting", "IL")["totals"]
        originating = endpoints.dashboard(self.conn, "originating", "IL")["totals"]
        self.assertEqual((impacting["events"], impacting["ongoing_events"]), (2, 1))
        self.assertEqual((originating["events"], originating["ongoing_events"]), (1, 0))

    def test_states_map(self):
        states = endpoints.states(self.conn)["states"]
        self.assertEqual(states["IL"]["impacting"]["events"], 2)
        self.assertEqual(states["IL"]["impacting"]["via_nationwide"], 1)
        self.assertEqual(states["CA"]["originating"]["ongoing"], 1)
        self.assertEqual(states["GU"]["originating"]["events"], 0)  # zero-filled

    def test_export_writes_every_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "recalls.db"
            disk = sqlite3.connect(db_path)
            self.conn.backup(disk)
            disk.close()
            files, _ = export.export(db_path, Path(tmp) / "dist")
            self.assertEqual(files, len(list(endpoints.all_paths(self.conn))))
            meta = json.loads((Path(tmp) / "dist" / "api" / "meta.json").read_text())
            self.assertEqual(meta["data_last_updated"], "2026-01-01")
            self.assertTrue((Path(tmp) / "dist" / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
