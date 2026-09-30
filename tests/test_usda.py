import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from fda_recall import usda
from fda_recall.web import serve


def record(number, date, lang="English", **extra):
    return {"langcode": lang, "field_recall_number": number, "field_title": f"Firm {number} Recalls Chicken",
            "field_recall_date": date, "field_summary": "<p>WASHINGTON&nbsp;– Firm is recalling</p><ul><li>item &amp; more</li></ul>",
            "field_states": ["Texas", ""], "field_company_media_contact": ["Jane Doe, 555-1234"],
            "field_media_contact": "Jane Doe", **extra}


FEED = [record("001-2026", "2026-01-05"), record("001-2026", "2026-01-05", lang="Spanish"), record("002-2026", "2026-02-01")]


class NormalizeTests(unittest.TestCase):
    def test_normalize(self):
        data = usda.normalize(FEED)
        self.assertEqual(data["record_count"], 2)  # the Spanish copy is dropped
        first = data["records"][0]
        self.assertEqual(first["recall_number"], "002-2026")  # newest first
        self.assertEqual(first["summary"], "WASHINGTON – Firm is recalling\nitem & more")
        self.assertEqual(first["states"], ["Texas"])
        self.assertNotIn("company_media_contact", first)
        self.assertNotIn("media_contact", first)

    def test_rejects_other_json(self):
        with self.assertRaises(ValueError):
            usda.normalize({"results": []})
        with self.assertRaises(ValueError):
            usda.normalize([{"something": "else"}])

    def test_file_is_valid_json_one_record_per_line(self):
        text = usda.dumps(usda.normalize(FEED))
        self.assertEqual(json.loads(text)["record_count"], 2)
        self.assertEqual(sum(1 for l in text.splitlines() if l.startswith('  {"')), 2)

    def test_save_reports_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fsis.json"
            first = usda.save(FEED[:2], path)
            self.assertEqual((first["records"], first["new"]), (1, ["001-2026"]))
            second = usda.save([record("001-2026", "2026-01-05", field_closed_year="2026"), FEED[2]], path)
            self.assertEqual((second["new"], second["changed"], second["removed"]), (["002-2026"], ["001-2026"], []))


class ImportEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fsis.json"
        handler = type("TestHandler", (serve.Handler,), {"usda_path": self.path, "log_message": lambda *a: None})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(handler, directory=str(serve.SITE_DIR)))
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def post(self, body, origin=None, dev_header=True):
        headers = {"Content-Type": "application/json", "Origin": origin or self.base}
        if dev_header:
            headers[serve.DEV_HEADER] = "1"
        req = urllib.request.Request(f"{self.base}/dev/usda-import", data=json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_saves_from_the_dev_page(self):
        status, result = self.post(FEED)
        self.assertEqual((status, result["records"]), (200, 2))
        self.assertTrue(self.path.exists())

    def test_rejects_other_origins_and_missing_header(self):
        self.assertEqual(self.post(FEED, origin="https://evil.example")[0], 403)
        self.assertEqual(self.post(FEED, dev_header=False)[0], 403)
        self.assertFalse(self.path.exists())

    def test_rejects_non_feed_json(self):
        status, result = self.post({"not": "a feed"})
        self.assertEqual(status, 400)
        self.assertIn("FSIS feed", result["error"])

    def test_serves_dev_page_but_not_arbitrary_files(self):
        with urllib.request.urlopen(f"{self.base}/dev/usda.html") as res:
            self.assertIn(b"Refresh USDA recall data", res.read())
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{self.base}/dev/..%2Fserve.py")


if __name__ == "__main__":
    unittest.main()


FULL_NOTICE = {
    "recall_number": "024-2026", "title": "Sempio Food Services Inc. Recalls Ready-To-Eat Chicken Stew Products Due to Possible Listeria Contamination",
    "recall_date": "2026-09-25", "recall_type": "Active Recall", "recall_classification": "Class I",
    "recall_reason": ["Product Contamination"], "active_notice": "True", "related_to_outbreak": "False",
    "states": ["Florida", "Georgia"], "product_items": ["Pouches of 31.75-oz “Sempio CHICKEN STEW”"],
    "recall_url": "https://www.fsis.usda.gov/recalls-alerts/example",
    "summary": "WASHINGTON, Sept. 25, 2026 – Sempio Food Services Inc., a Cerritos, Calif. establishment, is recalling "
               "approximately 4,596 pounds of ready-to-eat chicken stew products that may be contaminated with Listeria monocytogenes.\n"
               "The problem was discovered during routine FSIS surveillance activities.\n"
               "There have been no confirmed reports of illness due to consumption of these products. "
               "Anyone concerned about an injury or illness should contact a healthcare provider.\n"
               "Some illnesses last longer and can be more severe.\n"
               "For consumers that need to report a problem with a meat, poultry, or egg product, the online Electronic Consumer Complaint Monitoring System can be accessed 24 hours a day.",
}


class NoticeTests(unittest.TestCase):
    def test_parts(self):
        p = usda.notice_parts(FULL_NOTICE)
        self.assertEqual((p["firm"], p["state"], p["country"]), ("Sempio Food Services Inc.", "CA", "United States"))
        self.assertEqual(p["quantity"], "approximately 4,596 pounds")
        self.assertEqual(p["distribution"], "Florida, Georgia")
        self.assertEqual(p["discovery"], "The problem was discovered during routine FSIS surveillance activities.")
        self.assertTrue(p["ongoing"])
        self.assertFalse(p["is_alert"])

    def test_boilerplate_is_not_a_signal(self):
        from fda_recall import detection
        p = usda.notice_parts(FULL_NOTICE)
        self.assertFalse(detection.illness_reported(p["illness_text"]))
        self.assertEqual(usda.fsis_detection_sources(p["discovery"]), ["regulator_inspection"])  # not "consumer complaint"

    def test_generic_title_firm_falls_back_to_the_notice(self):
        notice = {**FULL_NOTICE, "title": "California Firm Recalls Chicken Products"}
        self.assertEqual(usda.firm_name(notice), "Sempio Food Services Inc.")
        self.assertEqual(usda.firm_name({**FULL_NOTICE, "title": "E.A. Sween Company Recalls Sandwiches"}), "E.A. Sween Company")


class CleanLayerTests(unittest.TestCase):
    def test_usda_notice_becomes_an_event(self):
        from fda_recall import clean, db, load
        conn = db.connect(":memory:")
        body = usda.dumps({"source": "x", "fetched_at": "2026-09-30", "record_count": 1, "records": [FULL_NOTICE]}).encode()
        load.load_usda_document(conn, "fsis.json", body)
        counts = clean.rebuild(conn)
        self.assertEqual(counts["usda_events"], 1)
        row = conn.execute("SELECT agency, recall_type, recalling_firm, state, most_severe_class, size, ongoing_product_count,"
                           " illness_reported FROM events").fetchone()
        self.assertEqual(row, ("USDA", "recall", "Sempio Food Services Inc.", "CA", "Class I", "M", 1, 0))
        self.assertEqual(sorted(s for (s,) in conn.execute("SELECT state FROM event_states")), ["FL", "GA"])
        self.assertIn(("pathogen", "listeria"), list(conn.execute("SELECT category, detail FROM product_reason_tags")))
