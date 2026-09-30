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
        self.assertIn("dashboard/all/impacting/IL", [p for p, _, _ in paths])
        self.assertIn("states/usda", [p for p, _, _ in paths])
        for url_path, _, kwargs in paths:
            fn, resolved = endpoints.resolve(self.conn, url_path)
            self.assertEqual(resolved, kwargs)
        self.assertIsNone(endpoints.resolve(self.conn, "dashboard/all/impacting/ZZ"))
        self.assertIsNone(endpoints.resolve(self.conn, "dashboard/all/bogus/IL"))
        self.assertIsNone(endpoints.resolve(self.conn, "dashboard/cdc/impacting/IL"))
        self.assertIsNone(endpoints.resolve(self.conn, "nope"))

    def test_views(self):
        # Nationwide event 200 impacts IL too; only event 100 originates from IL.
        impacting = endpoints.dashboard(self.conn, "all", "impacting", "IL")["totals"]
        originating = endpoints.dashboard(self.conn, "all", "originating", "IL")["totals"]
        self.assertEqual((impacting["events"], impacting["ongoing_events"]), (2, 1))
        self.assertEqual((originating["events"], originating["ongoing_events"]), (1, 0))
        self.assertEqual(endpoints.dashboard(self.conn, "usda", "impacting", "IL")["totals"]["events"], 0)

    def test_states_map(self):
        states = endpoints.states(self.conn, "all")["states"]
        self.assertEqual(endpoints.states(self.conn, "usda")["states"]["IL"]["impacting"]["events"], 0)
        self.assertEqual(states["IL"]["impacting"]["events"], 2)
        self.assertEqual(states["IL"]["impacting"]["via_nationwide"], 1)
        self.assertEqual(states["CA"]["originating"]["ongoing"], 1)
        self.assertEqual(states["GU"]["originating"]["events"], 0)  # zero-filled

    def test_event_details(self):
        data = endpoints.event(self.conn, "100")
        self.assertEqual(data["event"]["event_id"], "100")
        self.assertEqual(data["event"]["states"], ["IL"])
        [product] = data["products"]
        self.assertEqual(product["recall_number"], "F-0001-2020")
        self.assertEqual(product["reason_tags"], [{"category": "undeclared_allergen", "detail": "milk"}])
        self.assertEqual(data["firm_history"][0]["event_id"], "200")  # same firm, other event
        self.assertIsNotNone(endpoints.resolve(self.conn, "event/200"))
        self.assertIsNone(endpoints.resolve(self.conn, "event/999"))

    def test_lookup(self):
        data = endpoints.lookup(self.conn)
        self.assertEqual(data["recalls"], {"F-0001-2020": "100", "F-0002-2020": "200"})
        self.assertEqual(data["upcs"], {})

    def test_search_index(self):
        data = endpoints.search_index(self.conn)
        rows = [dict(zip(data["columns"], r)) for r in data["rows"]]
        self.assertEqual([r["id"] for r in rows], ["200", "100"] if rows[0]["id"] == "200" else ["100", "200"])
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["100"]["states"], "IL")  # codes run together
        self.assertEqual(by_id["100"]["reasons"], ["undeclared_allergen"])
        self.assertEqual(by_id["100"]["class"], "II")
        self.assertEqual((by_id["200"]["nationwide"], by_id["200"]["open"], by_id["200"]["origin"]), (1, 1, "CA"))
        self.assertLessEqual(len(by_id["100"]["snippet"]), endpoints.SNIPPET_CHARS)

    def trend_db(self):
        """FDA recalls in 2014 (base year) and 2020, plus one USDA notice in each."""
        from fda_recall import clean, load, usda
        from tests.test_usda import FULL_NOTICE
        conn = build_db([
            make_record(recall_number="F-0001-2014", event_id="1", report_date="20140115"),
            make_record(recall_number="F-0002-2014", event_id="2", report_date="20140715"),
            make_record(recall_number="F-0001-2020", event_id="3", report_date="20200115"),
        ])
        notices = [{**FULL_NOTICE, "recall_number": "001-2014", "recall_date": "2014-01-10"},
                   {**FULL_NOTICE, "recall_number": "002-2020", "recall_date": "2020-01-10"}]
        body = usda.dumps({"source": "x", "fetched_at": "x", "record_count": 2, "records": notices}).encode()
        load.load_usda_document(conn, "fsis.json", body)
        clean.rebuild(conn)
        return conn

    def test_trends_per_agency(self):
        t = endpoints.trends(self.trend_db())
        self.assertIsNone(t["media_source"])
        years = {y["year"]: y for y in t["years"]}
        self.assertEqual((years[2014]["fda_events"], years[2014]["usda_events"], years[2014]["events"]), (2, 1, 3))
        self.assertEqual((years[2014]["fda_index"], years[2014]["usda_index"]), (100.0, 100.0))
        self.assertTrue(years[2020]["partial"])  # the data ends in January 2020
        self.assertIsNone(years[2020]["media_index"])
        self.assertEqual(t["ongoing_now"], {"fda": 0, "usda": 2})

    def test_trends_with_media(self):
        from fda_recall import media
        conn = self.trend_db()
        conn.executescript(media.MEDIA_SCHEMA)
        conn.executemany(
            "INSERT INTO media_attention VALUES ('nyt', ?, ?, ?, '2026-01-01')",
            [("2014-01", "food_recall", 5), ("2014-01", "all", 1000), ("2020-01", "food_recall", 20), ("2020-01", "all", 1000)],
        )
        t = endpoints.trends(conn)
        self.assertEqual(t["media_source"], "The New York Times")
        years = {y["year"]: y for y in t["years"]}
        self.assertEqual((years[2014]["media_articles"], years[2014]["media_index"]), (5, 100.0))
        self.assertEqual(years[2020]["media_index"], 400.0)

    def test_usda_event_has_notice(self):
        conn = self.trend_db()
        data = endpoints.event(conn, "USDA-001-2014")
        self.assertEqual((data["event"]["agency"], data["event"]["recall_type"]), ("USDA", "recall"))
        self.assertIn("Sempio Food Services", data["notice"])
        rows = endpoints.search_index(conn)
        agency_col = rows["columns"].index("agency")
        self.assertEqual(sorted({r[agency_col] for r in rows["rows"]}), ["FDA", "USDA"])

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
