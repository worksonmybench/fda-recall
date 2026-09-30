"""Media attention to food recalls, from the NYT Archive API.

Usage:
    python -m fda_recall.media fetch  [--db PATH] [--start YYYY-MM]
    python -m fda_recall.media load   [--db PATH]
    python -m fda_recall.media sample YYYY-MM

For every month the Archive API returns the metadata of everything the
Times published (headline, date, subject tags...). We count the articles
the Times itself tagged as food-safety coverage (see `is_food_safety`) and
divide by all articles that month. Normalising by total output matters: the
Times publishes about half as many articles now as in 2013.

Why the Archive API rather than Article Search: since its 2025 update,
Article Search doesn't honour field filters and handles AND / OR
unpredictably ("recall AND listeria" returned everything matching
"recall"), so its counts can't isolate a topic. Archive gives every article,
so the matching is done here, with rules that are explicit and tested.

`fetch` needs an API key in NYT_API_KEY (free at https://developer.nytimes.com,
with the Archive API enabled for the app). Each month is one request of
roughly 10-20 MB; only the fields used are kept, gzipped, under
data/media/nyt/, so the rules can change without downloading again. Re-runs
only fetch months not cached yet plus the most recent ones.

Data provided by The New York Times.
"""

import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from . import db

SOURCE = "nyt"
SOURCE_NAME = "The New York Times"
API_URL = "https://api.nytimes.com/svc/archive/v1/{year}/{month}.json"
DEFAULT_CACHE = db.DEFAULT_DB.parent / "media" / SOURCE
START_MONTH = "2012-06"  # FDA enforcement data starts June 2012
REQUEST_INTERVAL = 12.5  # seconds; the developer tier allows 5 requests / minute
REFRESH_RECENT = 2       # months at the end that are always re-fetched
MAX_RETRIES = 4

# --- what counts as food-safety coverage ------------------------------------
# The Times' own subject tags, which its editors apply consistently across
# years, rather than keyword matching on text.
FOOD_SAFETY_TAG = "Food Contamination and Poisoning"
RECALL_TAG = "Recalls and Bans of Products"  # mostly cars and gadgets on its own...
FOOD_TAGS = {                                # ...so it only counts alongside a food tag
    "Food", "Salmonella (Bacteria)", "E Coli (Bacteria)", "Listeria (Bacteria)", "Allergies",
    "Food Allergies", "Eggs", "Produce", "Seafood", "Meat", "Poultry", "Baby Foods",
    "Infant Formula", "Dietary Supplements", "Peanuts", "Lettuce", "Food Safety",
}
# An FDA / USDA organization tag alone isn't enough: FDA also regulates e-cigarettes,
# and vaping "bans" carry the recalls tag.


def is_food_safety(doc):
    """doc: a slimmed article ({"subjects": [...], "orgs": [...]})."""
    subjects = set(doc.get("subjects") or [])
    if FOOD_SAFETY_TAG in subjects:
        return True
    return RECALL_TAG in subjects and bool(subjects & FOOD_TAGS)


MEDIA_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_attention (
    source      TEXT NOT NULL,
    month       TEXT NOT NULL,   -- YYYY-MM
    query_id    TEXT NOT NULL,   -- "food_recall" = matching articles, "all" = every article
    hits        INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (source, month, query_id)
);
"""


def months(start, end):
    """Every 'YYYY-MM' from start to end inclusive."""
    y, m = map(int, start.split("-"))
    end_y, end_m = map(int, end.split("-"))
    out = []
    while (y, m) <= (end_y, end_m):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def cache_path(cache_dir, month):
    return Path(cache_dir) / f"{month}.json.gz"


def slim(raw):
    """Keep only what the rules and `sample` use, from one month's Archive response."""
    docs = (raw.get("response") or {}).get("docs")
    if docs is None:
        raise ValueError(f"Unexpected Archive response: keys {sorted(raw)}")
    # Keyword types were "subject" / "organizations" until the API's 2025
    # update renamed them "Subject" / "Organization".
    kind = lambda k: (k.get("name") or "").lower().rstrip("s")
    out = []
    for d in docs:
        keywords = d.get("keywords") or []
        out.append({
            "headline": (d.get("headline") or {}).get("main"),
            "pub_date": (d.get("pub_date") or "")[:10],
            "url": d.get("web_url"),
            "subjects": [k.get("value") for k in keywords if kind(k) == "subject"],
            "orgs": [k.get("value") for k in keywords if kind(k) == "organization"],
        })
    return out


def request_url(month, api_key):
    y, m = map(int, month.split("-"))
    return API_URL.format(year=y, month=m) + f"?api-key={api_key}"


def fetch_month(month, api_key, opener=urllib.request.urlopen, sleep=time.sleep):
    """One Archive request, retrying with backoff on rate limiting / server errors."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            with opener(request_url(month, api_key), timeout=300) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as err:
            err.close()  # release the error response before retrying
            if err.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                sleep(REQUEST_INTERVAL * 2 ** (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def fetch(api_key, cache_dir=DEFAULT_CACHE, start=START_MONTH, today=None,
          opener=urllib.request.urlopen, sleep=time.sleep, log=print):
    """Fetch every uncached month plus the most recent ones. Returns requests made."""
    today = today or date.today()
    all_months = months(start, f"{today.year:04d}-{today.month:02d}")
    recent = set(all_months[-REFRESH_RECENT:])
    todo = [m for m in all_months if m in recent or not cache_path(cache_dir, m).exists()]
    if todo:
        log(f"{len(todo)} months to fetch (about {len(todo) * REQUEST_INTERVAL / 60:.0f} minutes at the API's rate limit)")
    for i, month in enumerate(todo):
        if i:
            sleep(REQUEST_INTERVAL)
        docs = slim(fetch_month(month, api_key, opener=opener, sleep=sleep))
        path = cache_path(cache_dir, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(docs, f)
        log(f"  {month}: {sum(map(is_food_safety, docs))} food-safety articles of {len(docs):,}")
    return len(todo)


def read_month(cache_dir, month):
    path = cache_path(cache_dir, month)
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def load(conn, cache_dir=DEFAULT_CACHE):
    """(Re)count every cached month into media_attention. Returns months loaded."""
    conn.executescript(MEDIA_SCHEMA)
    rows = []
    for path in sorted(Path(cache_dir).glob("*.json.gz")):
        month = path.name[: -len(".json.gz")]
        docs = read_month(cache_dir, month)
        fetched = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(path.stat().st_mtime))
        rows.append((SOURCE, month, "food_recall", sum(map(is_food_safety, docs)), fetched))
        rows.append((SOURCE, month, "all", len(docs), fetched))
    with conn:
        conn.execute("DELETE FROM media_attention WHERE source = ?", (SOURCE,))
        conn.executemany(
            "INSERT INTO media_attention (source, month, query_id, hits, fetched_at) VALUES (?, ?, ?, ?, ?)", rows
        )
    return len(rows) // 2


def sample(cache_dir, month):
    """The month's matching articles, to check the rules' precision."""
    docs = read_month(cache_dir, month)
    return None if docs is None else [d for d in docs if is_food_safety(d)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("fetch", "load"):
        p = sub.add_parser(name)
        p.add_argument("--db", type=Path, default=db.DEFAULT_DB)
        p.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    sub.choices["fetch"].add_argument("--start", default=START_MONTH, help="first month, YYYY-MM")
    p = sub.add_parser("sample")
    p.add_argument("month", help="YYYY-MM")
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)

    if args.command == "sample":
        docs = sample(args.cache, args.month)
        if docs is None:
            parser.error(f"{args.month} isn't cached yet; run fetch first")
        for d in docs:
            print(f"{d['pub_date']}  {d['headline']}")
        print(f"({len(docs)} food-safety articles)")
        return

    if args.command == "fetch":
        api_key = os.environ.get("NYT_API_KEY")
        if not api_key:
            parser.error("set NYT_API_KEY (free at https://developer.nytimes.com) first")
        fetch(api_key, args.cache, start=args.start)

    conn = db.connect(args.db)
    try:
        print(f"Loaded {load(conn, args.cache)} months into media_attention ({args.db})")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
