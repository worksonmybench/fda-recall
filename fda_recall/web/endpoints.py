"""The JSON endpoints behind the web UI.

Each endpoint is a function (conn, **params) -> JSON-able dict, registered
with a URL path like "dashboard/{scope}". The same functions serve both
modes:

- dev:    `python -m fda_recall.web.serve` runs them live per request
- deploy: `python -m fda_recall.web.export` runs each once per parameter
          value and writes static files (api/dashboard/TX.json, ...)

So every parameter must have a finite list of values (the `params`
functions below), which is also what keeps the deployed site static.
"""

import re

from .. import distribution

ENDPOINTS = {}


def endpoint(path, **params):
    """Register fn at `path`; params maps each {name} in the path to fn(conn) -> allowed values."""
    names = re.findall(r"\{(\w+)\}", path)
    assert set(names) == set(params), f"{path}: every path parameter needs a list of values"

    def register(fn):
        ENDPOINTS[path] = (fn, params)
        return fn

    return register


def resolve(conn, url_path):
    """Find the endpoint for an API path like 'dashboard/TX'. Returns (fn, kwargs) or None.

    Only parameter values the export would produce are accepted, so the dev
    server can never serve something the static site can't.
    """
    for path, (fn, params) in ENDPOINTS.items():
        pattern = "^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path) + "$"
        m = re.match(pattern, url_path)
        if m and all(m[name] in values(conn) for name, values in params.items()):
            return fn, m.groupdict()
    return None


def all_paths(conn):
    """Every concrete (url_path, fn, kwargs) the static export should write."""
    for path, (fn, params) in ENDPOINTS.items():
        combos = [{}]
        for name, values in params.items():
            combos = [{**c, name: v} for c in combos for v in values(conn)]
        for kwargs in combos:
            yield path.format(**kwargs), fn, kwargs


def _rows(conn, sql, args=()):
    cur = conn.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# --- views & scopes -------------------------------------------------------

ALL_US = "US"
# "impacting": the recall's distribution reached the state (nationwide = every state).
# "originating": the recalling firm is located in the state.
VIEWS = ["impacting", "originating"]
STATE_NAMES = {**distribution.STATES, **distribution.TERRITORIES}


def views(conn):
    return VIEWS


def scopes(conn):
    """'US' (everything) plus every state/territory code with recalls in either view."""
    codes = {r[0] for r in conn.execute("SELECT DISTINCT state FROM event_state_reach")}
    codes |= {r[0] for r in conn.execute("SELECT DISTINCT state FROM events") if r[0] in STATE_NAMES}
    return [ALL_US, *sorted(codes)]


def _scope_filter(view, scope):
    """SQL fragment + args restricting `events e` to a view + scope."""
    if scope == ALL_US:
        return "1=1", ()
    if view == "originating":
        return "e.state = ?", (scope,)
    return "e.event_id IN (SELECT event_id FROM event_state_reach WHERE state = ?)", (scope,)


# --- endpoints ------------------------------------------------------------

@endpoint("meta")
def meta(conn):
    last = conn.execute(
        "SELECT source_last_updated, loaded_at FROM load_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    return {
        "data_last_updated": last[0] if last else None,
        "loaded_at": last[1] if last else None,
        "views": VIEWS,
        "scopes": [
            {"code": code, "name": "All US" if code == ALL_US else STATE_NAMES.get(code, code)}
            for code in scopes(conn)
        ],
    }


@endpoint("states")
def states(conn):
    """Per-state counts for the map, in both views."""
    metrics = """
        count(*) AS events,
        sum(e.ongoing_product_count > 0) AS ongoing,
        sum(e.most_severe_class = 'Class I') AS class_1,
        sum(e.illness_reported) AS illness"""
    result = {code: {"name": name} for code, name in STATE_NAMES.items()}
    for row in _rows(conn, f"""
            SELECT r.state AS code, {metrics}, sum(r.via_nationwide) AS via_nationwide
            FROM event_state_reach r JOIN events e USING (event_id) GROUP BY 1"""):
        result[row.pop("code")]["impacting"] = row
    for row in _rows(conn, f"SELECT e.state AS code, {metrics} FROM events e GROUP BY 1"):
        code = row.pop("code")
        if code in result:
            result[code]["originating"] = row
    empty = {"events": 0, "ongoing": 0, "class_1": 0, "illness": 0}
    for entry in result.values():
        for view in VIEWS:
            entry.setdefault(view, dict(empty))
    return {"states": result}


@endpoint("dashboard/{view}/{scope}", view=views, scope=scopes)
def dashboard(conn, view, scope):
    where, args = _scope_filter(view, scope)

    totals = _rows(conn, f"""
        SELECT count(*) AS events,
               coalesce(sum(product_count), 0) AS products,
               coalesce(sum(ongoing_product_count > 0), 0) AS ongoing_events,
               coalesce(sum(illness_reported), 0) AS illness_events,
               min(report_date) AS first_report, max(report_date) AS last_report
        FROM events e WHERE {where}""", args)[0]

    by_year = _rows(conn, f"""
        SELECT substr(report_date, 1, 4) AS year,
               sum(most_severe_class = 'Class I') AS class_1,
               sum(most_severe_class = 'Class II') AS class_2,
               sum(most_severe_class = 'Class III') AS class_3
        FROM events e WHERE {where} AND report_date IS NOT NULL
        GROUP BY 1 ORDER BY 1""", args)

    # An event counts once per reason / product category it involves.
    by_reason = _rows(conn, f"""
        SELECT p.reason_category AS key, count(DISTINCT p.event_id) AS events
        FROM products p JOIN events e USING (event_id)
        WHERE {where} GROUP BY 1 ORDER BY 2 DESC""", args)

    by_product = _rows(conn, f"""
        SELECT coalesce(p.product_category, 'unknown') AS key, count(DISTINCT p.event_id) AS events
        FROM products p JOIN events e USING (event_id)
        WHERE {where} GROUP BY 1 ORDER BY 2 DESC""", args)

    by_size = _rows(conn, f"""
        SELECT coalesce(size, 'unknown') AS key, count(*) AS events
        FROM events e WHERE {where} GROUP BY 1""", args)
    order = ["XS", "S", "M", "L", "XL", "XXL", "unknown"]
    by_size.sort(key=lambda r: order.index(r["key"]))

    recent = _rows(conn, f"""
        SELECT e.event_id, e.report_date, e.recalling_firm, e.most_severe_class, e.size,
               e.is_nationwide, e.state_count,
               (SELECT reason_for_recall FROM products p WHERE p.event_id = e.event_id LIMIT 1) AS reason,
               (SELECT reason_category FROM products p WHERE p.event_id = e.event_id
                ORDER BY reason_category = 'other' LIMIT 1) AS reason_category
        FROM events e WHERE {where}
        ORDER BY e.report_date DESC, e.event_id DESC LIMIT 15""", args)

    return {
        "view": view,
        "scope": scope,
        "totals": totals,
        "by_year": by_year,
        "by_reason": by_reason,
        "by_product": by_product,
        "by_size": by_size,
        "recent": recent,
    }


# --- event details ----------------------------------------------------------

def event_ids(conn):
    return [r[0] for r in conn.execute("SELECT event_id FROM events ORDER BY event_id")]


@endpoint("event/{event_id}", event_id=event_ids)
def event(conn, event_id):
    e = _rows(conn, "SELECT * FROM events WHERE event_id = ?", (event_id,))[0]
    e["states"] = [r[0] for r in conn.execute(
        "SELECT state FROM event_states WHERE event_id = ? ORDER BY state", (event_id,))]

    products = _rows(conn, """
        SELECT recall_number, status, classification, product_category, product_description,
               product_quantity, code_info, more_code_info, reason_for_recall, reason_category,
               center_classification_date, termination_date, illness_reported
        FROM products WHERE event_id = ? ORDER BY recall_number""", (event_id,))
    numbers = [p["recall_number"] for p in products]
    marks = ",".join("?" * len(numbers))

    upcs, tags, sources = {}, {}, {}
    for number, upc in conn.execute(f"SELECT recall_number, upc FROM product_upcs WHERE recall_number IN ({marks}) ORDER BY upc", numbers):
        upcs.setdefault(number, []).append(upc)
    for number, category, detail in conn.execute(
            f"SELECT recall_number, category, detail FROM product_reason_tags WHERE recall_number IN ({marks})", numbers):
        tags.setdefault(number, []).append({"category": category, "detail": detail})
    for number, source in conn.execute(
            f"SELECT recall_number, source FROM product_detection_sources WHERE recall_number IN ({marks})", numbers):
        sources.setdefault(number, []).append(source)
    for p in products:
        p["upcs"] = upcs.get(p["recall_number"], [])
        p["reason_tags"] = tags.get(p["recall_number"], [])
        p["detection_sources"] = sources.get(p["recall_number"], [])

    # Other recall events by the same firm (name variants combined via firm_key).
    firm_history = _rows(conn, """
        SELECT e.event_id, e.report_date, e.most_severe_class, e.size,
               (SELECT reason_category FROM products p WHERE p.event_id = e.event_id
                ORDER BY reason_category = 'other' LIMIT 1) AS reason_category
        FROM events e WHERE e.firm_key = ? AND e.event_id <> ?
        ORDER BY e.report_date DESC LIMIT 25""", (e["firm_key"], event_id))

    return {"event": e, "products": products, "firm_history": firm_history}


@endpoint("lookup")
def lookup(conn):
    """Recall number -> event and UPC -> events, for the search box. Fetched only on search."""
    recalls = dict(conn.execute("SELECT recall_number, event_id FROM products"))
    upcs = {}
    for upc, event_id in conn.execute(
            "SELECT DISTINCT u.upc, p.event_id FROM product_upcs u JOIN products p USING (recall_number) ORDER BY 1, 2"):
        upcs.setdefault(upc, []).append(event_id)
    return {"recalls": recalls, "upcs": upcs}


# --- search -------------------------------------------------------------------

SNIPPET_CHARS = 80
SEARCH_COLUMNS = [
    "id", "reported", "started", "firm", "class", "open", "size", "units", "nationwide",
    "origin", "illness", "products", "reasons", "categories", "states", "snippet",
]


@endpoint("search_index")
def search_index(conn):
    """Every event's filterable fields, for the client-side search page.

    Sent as column names + row arrays (not one object per event) to keep the
    download small. reasons / categories are arrays of codes; states is the
    2-letter codes run together ("ALAZCA") since it's the longest field.
    """
    rows = conn.execute(f"""
        SELECT e.event_id, e.report_date, e.recall_initiation_date, e.recalling_firm,
               replace(e.most_severe_class, 'Class ', ''),
               e.ongoing_product_count > 0, e.size, CAST(round(e.est_units) AS INTEGER),
               e.is_nationwide, e.state, e.illness_reported, e.product_count,
               (SELECT group_concat(DISTINCT p.reason_category) FROM products p WHERE p.event_id = e.event_id),
               (SELECT group_concat(DISTINCT p.product_category) FROM products p WHERE p.event_id = e.event_id),
               (SELECT group_concat(s.state) FROM event_states s WHERE s.event_id = e.event_id),
               (SELECT substr(replace(p.product_description, char(10), ' '), 1, {SNIPPET_CHARS})
                FROM products p WHERE p.event_id = e.event_id ORDER BY p.recall_number LIMIT 1)
        FROM events e
        ORDER BY e.report_date DESC, e.event_id DESC""").fetchall()
    split = lambda v: sorted(v.split(",")) if v else []
    out = []
    for r in rows:
        r = list(r)
        r[12], r[13], r[14] = split(r[12]), split(r[13]), "".join(split(r[14]))
        r[5], r[8], r[10] = int(r[5]), int(r[8]), int(r[10])
        out.append(r)
    return {"columns": SEARCH_COLUMNS, "rows": out}
