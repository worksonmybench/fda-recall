import io
import json
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

from fda_recall import db, media


def article(headline, subjects=(), orgs=()):
    keywords = [{"name": "subject", "value": s} for s in subjects] + [{"name": "organizations", "value": o} for o in orgs]
    return {"headline": {"main": headline}, "pub_date": "2018-04-13T00:00:00+0000", "web_url": "https://example",
            "keywords": keywords}


def archive(*docs):
    return {"copyright": "x", "response": {"meta": {"hits": len(docs)}, "docs": list(docs)}}


MONTH = archive(
    article("206 Million Eggs Recalled Over Salmonella Fears", ["Food Contamination and Poisoning", "Eggs"]),
    article("F.D.A. Updates Recall of Tomatoes", ["Recalls and Bans of Products", "Food"]),
    article("Ford Recalling 196,500 Minivans", ["Recalls and Bans of Products", "Automobiles"]),
    article("Peanut Butter Recall Widens", ["Recalls and Bans of Products", "Peanuts"], ["Food and Drug Administration"]),
    article("F.D.A. Moves to Ban Flavored Vaping Pods", ["Recalls and Bans of Products", "E-Cigarettes"], ["Food and Drug Administration"]),
    article("Yankees Win", ["Baseball"]),
)


class FakeAPI:
    """Stands in for urlopen: returns MONTH for any month, optionally failing first."""

    def __init__(self, fail_first=0):
        self.months = []
        self.fail_first = fail_first

    def __call__(self, url, timeout=None):
        year, month = url.split("/archive/v1/")[1].split(".json")[0].split("/")
        self.months.append(f"{int(year):04d}-{int(month):02d}")
        if self.fail_first:
            self.fail_first -= 1
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, io.BytesIO())
        return io.BytesIO(json.dumps(MONTH).encode())


class RuleTests(unittest.TestCase):
    def test_food_safety_rules(self):
        docs = media.slim(MONTH)
        self.assertEqual([media.is_food_safety(d) for d in docs], [True, True, False, True, False, False])

    def test_2025_keyword_names(self):
        doc = {"headline": {"main": "F.D.A. Updates Recall of Tomatoes"}, "keywords": [
            {"name": "Subject", "value": "Recalls and Bans of Products"},
            {"name": "Subject", "value": "Food"},
            {"name": "Organization", "value": "Food and Drug Administration"},
        ]}
        [slimmed] = media.slim(archive(doc))
        self.assertEqual(slimmed["orgs"], ["Food and Drug Administration"])
        self.assertTrue(media.is_food_safety(slimmed))

    def test_slim_rejects_unexpected_shape(self):
        with self.assertRaises(ValueError):
            media.slim({"response": {"metadata": {"hits": 3}}})

    def test_months_and_url(self):
        self.assertEqual(media.months("2012-11", "2013-02"), ["2012-11", "2012-12", "2013-01", "2013-02"])
        self.assertIn("/archive/v1/2013/2.json?api-key=KEY", media.request_url("2013-02", "KEY"))


class FetchAndLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        self.api = FakeAPI()
        self.kwargs = dict(cache_dir=self.cache, start="2013-01", today=date(2013, 4, 10),
                           opener=self.api, sleep=lambda s: None, log=lambda *a: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fetch_caches_and_refetches_only_recent_months(self):
        self.assertEqual(media.fetch("KEY", **self.kwargs), 4)
        self.api.months.clear()
        self.assertEqual(media.fetch("KEY", **self.kwargs), 2)  # only the last 2 months again
        self.assertEqual(self.api.months, ["2013-03", "2013-04"])

    def test_retries_on_rate_limit(self):
        self.api.fail_first = 2
        self.assertEqual(media.fetch("KEY", **{**self.kwargs, "start": "2013-04"}), 1)

    def test_load_and_sample(self):
        media.fetch("KEY", **self.kwargs)
        conn = db.connect(":memory:")
        self.assertEqual(media.load(conn, self.cache), 4)
        counts = dict(conn.execute("SELECT query_id, sum(hits) FROM media_attention GROUP BY 1"))
        self.assertEqual(counts, {"food_recall": 3 * 4, "all": 6 * 4})
        self.assertEqual(media.load(conn, self.cache), 4)  # reloading replaces, doesn't duplicate
        self.assertEqual(conn.execute("SELECT count(*) FROM media_attention").fetchone()[0], 8)
        self.assertEqual([d["headline"] for d in media.sample(self.cache, "2013-02")][0],
                         "206 Million Eggs Recalled Over Salmonella Fears")
        self.assertIsNone(media.sample(self.cache, "2020-01"))


if __name__ == "__main__":
    unittest.main()
