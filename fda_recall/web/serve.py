"""Dev server: static site + live JSON endpoints.

Usage:
    python -m fda_recall.web.serve [--port 8000] [--db PATH]

Serves site/ as-is and answers /api/<path>.json by running the endpoint
against the database on every request, so query changes show up on
refresh. The deployed site gets the same URLs as pre-built files (see
export.py); nothing here is meant for production.
"""

import argparse
import json
import sqlite3
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import db
from . import endpoints

SITE_DIR = Path(__file__).resolve().parents[2] / "site"


class Handler(SimpleHTTPRequestHandler):
    db_path = None

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            return self.send_api(path[len("/api/"):])
        return super().do_GET()

    def send_api(self, api_path):
        if not api_path.endswith(".json"):
            return self.send_error(404)
        # Read-only connection: the web layer never writes.
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        try:
            found = endpoints.resolve(conn, api_path[: -len(".json")])
            if not found:
                return self.send_error(404, "No such endpoint or parameter value")
            fn, kwargs = found
            body = json.dumps(fn(conn, **kwargs)).encode()
        finally:
            conn.close()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")  # always see the latest in dev
        super().end_headers()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=db.DEFAULT_DB)
    args = parser.parse_args(argv)
    if not args.db.exists():
        parser.error(f"{args.db} not found; run python -m fda_recall.load first")

    Handler.db_path = args.db.resolve().as_posix()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(SITE_DIR)))
    print(f"Serving {SITE_DIR} with live data from {args.db} at http://127.0.0.1:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
