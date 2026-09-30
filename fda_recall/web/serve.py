"""Dev server: static site + live JSON endpoints.

Usage:
    python -m fda_recall.web.serve [--port 8000] [--db PATH]

Serves site/ as-is and answers /api/<path>.json by running the endpoint
against the database on every request, so query changes show up on
refresh. The deployed site gets the same URLs as pre-built files (see
export.py); nothing here is meant for production.

Dev-only tools live under /dev/ (fda_recall/web/dev/, never exported):
/dev/usda.html has your browser fetch the USDA FSIS recall feed (which
rejects scripts but allows browsers) and POSTs it to /dev/usda-import,
which saves the normalised file to sources/usda/ for committing.
"""

import argparse
import json
import re
import sqlite3
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import db, usda
from . import endpoints

SITE_DIR = Path(__file__).resolve().parents[2] / "site"
DEV_DIR = Path(__file__).resolve().parent / "dev"
MAX_UPLOAD = 64 * 1024 * 1024
DEV_HEADER = "X-FDA-Recall-Dev"  # custom header: forces a CORS preflight, which this server never approves


class Handler(SimpleHTTPRequestHandler):
    db_path = None
    usda_path = usda.DEFAULT_PATH

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            return self.send_api(path[len("/api/"):])
        if path.startswith("/dev/"):
            return self.send_dev_file(path[len("/dev/"):])
        return super().do_GET()

    def send_dev_file(self, name):
        if not re.fullmatch(r"[a-z0-9_-]+\.(html|js|css)", name) or not (DEV_DIR / name).is_file():
            return self.send_error(404)
        body = (DEV_DIR / name).read_bytes()
        types = {"html": "text/html; charset=utf-8", "js": "text/javascript", "css": "text/css"}
        self.send_response(200)
        self.send_header("Content-Type", types[name.rsplit(".", 1)[1]])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/dev/usda-import":
            return self.send_error(404)
        # Only the dev page on this server may write: another site open in the
        # same browser can't send the custom header (it'd need a CORS preflight)
        # and its Origin wouldn't match.
        origin_ok = self.headers.get("Origin") == f"http://{self.headers.get('Host')}"
        if not origin_ok or self.headers.get(DEV_HEADER) != "1":
            return self.send_json(403, {"error": "only the local dev page can import"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD:
            return self.send_json(400, {"error": "missing or oversized body"})
        try:
            result = usda.save(json.loads(self.rfile.read(length)), self.usda_path)
        except (ValueError, json.JSONDecodeError) as err:
            return self.send_json(400, {"error": str(err)})
        return self.send_json(200, result)

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
