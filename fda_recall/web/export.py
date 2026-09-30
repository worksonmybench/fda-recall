"""Build the deployable static site.

Usage:
    python -m fda_recall.web.export [--out dist] [--db PATH]

Copies site/ into the output folder and writes every endpoint, for every
parameter value, as a static JSON file at the same URL the dev server
uses (api/meta.json, api/dashboard/TX.json, ...). The result is plain
files: upload it to any static host / CDN (GitHub Pages, Cloudflare
Pages, S3 + CloudFront) - no database or server needed.
"""

import argparse
import json
import shutil
import sqlite3
from pathlib import Path

from .. import db
from . import endpoints
from .serve import SITE_DIR

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "dist"


def export(db_path, out_dir):
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(SITE_DIR, out_dir)

    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    files, total_bytes = 0, 0
    try:
        for url_path, fn, kwargs in endpoints.all_paths(conn):
            target = out_dir / "api" / f"{url_path}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            body = json.dumps(fn(conn, **kwargs), separators=(",", ":"))
            target.write_text(body, encoding="utf-8")
            files += 1
            total_bytes += len(body)
    finally:
        conn.close()
    return files, total_bytes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--db", type=Path, default=db.DEFAULT_DB)
    args = parser.parse_args(argv)
    files, total_bytes = export(args.db, args.out)
    print(f"Wrote {files} JSON files ({total_bytes / 1024:.0f} KB) plus site/ to {args.out}")


if __name__ == "__main__":
    main()
