import json
import unittest

from fda_recall import clean, db, load


def make_record(**overrides):
    rec = {
        "recall_number": "F-0001-2020",
        "event_id": "100",
        "status": "Terminated",
        "classification": "Class II",
        "product_type": "Food",
        "recalling_firm": "Acme Foods, Inc.",
        "address_1": "1 Main St",
        "address_2": "N/A",
        "city": "Springfield",
        "state": "IL",
        "postal_code": "62701",
        "country": "United States",
        "voluntary_mandated": "Voluntary: Firm initiated",
        "initial_firm_notification": "Letter",
        "distribution_pattern": "IL",
        "product_description": "Widget  crackers ",
        "product_quantity": "10 cases",
        "reason_for_recall": "Undeclared milk.",
        "code_info": "Lot 1",
        "recall_initiation_date": "20200101",
        "center_classification_date": "20200115",
        "report_date": "20200122",
        "termination_date": "20200601",
        "openfda": {},
    }
    rec.update(overrides)
    return rec


class CleanTextTests(unittest.TestCase):
    def test_placeholders_become_none(self):
        for v in ["", "N/A", "  n/a ", None]:
            self.assertIsNone(clean.clean_text(v))

    def test_collapses_spaces_but_keeps_line_breaks(self):
        self.assertEqual(clean.clean_text("  a   b \n\n c\t d  "), "a b\nc d")

    def test_firm_key(self):
        self.assertEqual(clean.firm_key("Ventura Foods, LLC"), clean.firm_key("VENTURA FOODS LLC"))
        self.assertEqual(clean.firm_key("Twin City Foods Inc."), "TWIN CITY FOODS INC")

    def test_date_issue(self):
        self.assertIsNone(clean.date_issue("2020-01-01"))
        self.assertEqual(clean.date_issue("0212-12-07"), "implausible_date")
        self.assertEqual(clean.date_issue("2020-02-30"), "invalid_date")
        self.assertEqual(clean.date_issue("20200101"), "unparseable_date")


class RebuildTests(unittest.TestCase):
    def rebuild(self, records):
        conn = db.connect(":memory:")
        doc = json.dumps({"meta": {}, "results": records}).encode()
        load.load_document(conn, "test.json", doc)
        counts = clean.rebuild(conn)
        return conn, counts

    def test_events_and_products(self):
        conn, counts = self.rebuild([
            make_record(),
            make_record(recall_number="F-0002-2020", classification="Class I", status="Ongoing", termination_date=""),
            make_record(recall_number="F-0003-2020", event_id="200"),
        ])
        self.assertEqual(counts, {"events": 2, "products": 3, "data_issues": 0})
        row = conn.execute(
            "SELECT address_2, firm_key, product_count, most_severe_class, ongoing_product_count"
            " FROM events WHERE event_id = '100'"
        ).fetchone()
        self.assertEqual(row, (None, "ACME FOODS INC", 2, "Class I", 1))
        desc = conn.execute("SELECT product_description FROM products WHERE recall_number = 'F-0001-2020'").fetchone()
        self.assertEqual(desc, ("Widget crackers",))

    def test_issues_are_flagged(self):
        conn, _ = self.rebuild([
            make_record(recall_number="N/A", recall_initiation_date="02121207"),
            make_record(recall_number="F0152-2014", city="Shelbyville"),
        ])
        record_issues = set(conn.execute(
            "SELECT recall_number, issue FROM data_issues WHERE issue <> 'event_field_mismatch'"
        ))
        self.assertEqual(record_issues, {
            ("N/A", "missing_recall_number"),
            ("N/A", "implausible_date"),
            ("F0152-2014", "malformed_recall_number"),
        })
        event_issues = set(conn.execute(
            "SELECT event_id, field FROM data_issues WHERE issue = 'event_field_mismatch'"
        ))
        self.assertEqual(event_issues, {("100", "city"), ("100", "recall_initiation_date")})

    def test_rebuild_is_repeatable(self):
        conn, first = self.rebuild([make_record()])
        self.assertEqual(clean.rebuild(conn), first)


if __name__ == "__main__":
    unittest.main()
