# fda-recall

Loads openFDA recall enforcement exports (https://open.fda.gov/data/downloads/) into a SQLite database for analysis. Uses only the standard library (Python 3.10+).

## Load / refresh

1. Download the latest export (`.json` or the `.zip` as-is) into this folder.
2. Run:

```bash
python -m fda_recall.load
```

With no arguments it loads every `.json`/`.zip` in this folder into `data/recalls.db`. You can also pass files and a database: `python -m fda_recall.load path/to/export.zip --db other.db`.

It's safe to re-run. Records are matched by `recall_number`:
- **new** records are inserted
- **changed** records (e.g. status `Ongoing` → `Terminated`) are updated, and the previous version goes into `recall_history`
- **unchanged** records are left alone apart from `last_seen_run`

## Web UI

```bash
python -m fda_recall.web.serve
```

opens a dev server at http://127.0.0.1:8000 that runs every query live against `data/recalls.db`, so query or page changes show up on refresh.

To deploy:

```bash
python -m fda_recall.web.export
```

writes `dist/`: the `site/` files plus every API response pre-built as a static JSON file at the same URL the dev server uses (`api/states.json`, `api/dashboard/impacting/TX.json`, ...). Upload `dist/` to any static host or CDN (GitHub Pages, Cloudflare Pages, S3 + CloudFront); there's no database or server in production. Re-run the export after each data load.

How it fits together:

- `fda_recall/web/endpoints.py` defines each API response as a Python function registered at a path. A path parameter like `{scope}` must come with a function listing its allowed values, which is what lets the export enumerate every file. The dev server refuses values the export wouldn't produce, so dev can't drift from the deployed site.
- `site/` is plain HTML/CSS/JS modules, with no build step or chart library. It fetches `api/<path>.json` with relative URLs, so it works from any base path.
- To add a stat: add or extend an endpoint, then render it in `site/app.js`.

Each recall event has a details page, `event.html?id=<event_id>`, built from `api/event/<id>.json`: the firm, dates, class, status, size, a map of where it was distributed, the reason(s), every product (recall number, description, quantity, lot codes, UPCs) and the firm's other recalls. Pages are per event rather than per recall number because an event is one firm's single recall announcement, while recall numbers are FDA's per-product entries within it. Products differ only in description, codes and occasionally class or reason, and those are shown per product. Link to one product with `event.html?id=99611#H-1364-2026`. The search box on the main page takes a recall number, UPC (with or without its leading zero or check digit) or event ID. It uses `api/lookup.json` (about 175 KB compressed), which is fetched only when someone searches.

`search.html` searches all recall events in the browser: keywords (firm name and the start of the first product's description), a date range on report or recall-start date with presets, reason, kind of food, state (impacted or firm location), status, class, size, illness and nationwide. Results can be sorted and are paged. It downloads `api/search_index.json` once (about 550 KB compressed), and every filter change after that runs locally. Filters are kept in the query string, so searches can be shared.

The full export is about 8,000 files, around 9.5 MB compressed.

The main page leads with a tile map of ongoing recalls per state. Its toggle switches between **recalls impacting a state** (the distribution reached it; nationwide recalls count everywhere) and **recalls originating from a state** (the recalling firm is located there). Selecting a state scopes the whole dashboard to it, and the view and state are kept in the URL (`#originating/CA`), so links can be shared.

## Tables

The database has two layers.

**Import layer** — written only by the loader and a faithful copy of what the FDA published (apart from dates reformatted to `YYYY-MM-DD` and empty strings stored as NULL):

| table | contents |
|---|---|
| `recalls` | one row per recall number, with the full original record in `raw_json` |
| `recall_history` | prior versions of recalls that later changed |
| `load_runs` | one row per file loaded: timestamp, file hash, openFDA `last_updated`, counts |

Fields openFDA adds later are kept in `raw_json` and reported during the load, so you can add columns for them later without reloading anything.

**Clean layer** — the tables to analyze. `fda_recall/clean.py` drops and rebuilds them from `recalls` at the end of every load (or on its own with `python -m fda_recall.clean`), so changing a cleanup rule never requires reloading.

| table | contents |
|---|---|
| `events` | one row per recall event: firm, address, distribution, initiation/report dates, plus `firm_key`, `product_count`, `most_severe_class`, `ongoing_product_count`, `est_units`, `size`, `is_nationwide`, `is_foreign`, `is_online`, `state_count`, `illness_reported` (any product) |
| `event_states` | the US states / territories (2-letter codes) named in each event's `distribution_pattern` |
| `event_state_reach` (view) | `event_states` plus all 50 states + DC for nationwide events; `via_nationwide` = 1 for those added rows |
| `products` | one row per recall number (product), linked by `event_id`; `reason_category` (main recall reason), `product_category` (kind of food), `illness_reported` |
| `product_detection_sources` | how the problem was found, e.g. `regulator_testing`, `supplier_notification`; a product can have several, most have none stated |
| `product_upcs` | UPC / EAN codes (digits only) found in the product description |
| `product_reason_tags` | every `(category, detail)` matched in the recall reason, e.g. `pathogen / listeria`, `undeclared_allergen / peanut`; a product can have several |
| `data_issues` | records that failed a sanity check, for manual review; nothing is auto-corrected |

Cleanup applied: whitespace trimmed and collapsed (line breaks kept), placeholders like `N/A` turned into NULL, and `firm_key` added for matching firm-name variants (`Ventura Foods, LLC` = `VENTURA FOODS LLC`).

Note: one event covers many products, so decide whether you're counting events or products.

### Recall size

`fda_recall/quantity.py` parses the free-text `product_quantity` ("1,221 cases (6/2 lb. bags per case)", "528,250 lbs", "Approx 19.5 gallons") into rough **estimated retail units**: a unit/bottle/bag = 1, 1 lb = 1, volumes via the weight of water. For cases, boxes, cartons and pallets it uses the pack size when the text gives one: "144 units per case", "(12/case)", "cases of 12", "(54 units each)", "(6/2 lb bags per case)", "(20 lbs/case)", "41,436 x 6 x 5 lb". Failing that it uses a unit total FDA stated for the cases ("179 cases (1,432 bottles)"), and failing that 12 per case and 600 per pallet. Each event's products are combined (identical quantity text counted once, since it's usually a shared total) into `events.est_units`, then bucketed by order of magnitude:

| size | est. retail units |
|---|---|
| XS | under 100 |
| S | 100 – 999 |
| M | 1,000 – 9,999 |
| L | 10,000 – 99,999 |
| XL | 100,000 – 999,999 |
| XXL | 1 million + |

`size` is NULL when no quantity was given ("Unknown"). The estimates are only good to an order of magnitude — use `size` for comparisons, not `est_units` for totals. Per-product values are in `products.est_units` / `quantity_unit_type` / `quantity_is_total`.

### Distribution

`fda_recall/distribution.py` reads `distribution_pattern` ("IL, MI, KY, IN, WI", "New Jersey, New York and Maryland", "Nationwide and Canada", "Domestic: AL, AR. Foreign: Not applicable.") into:

- `event_states`: every state or territory named, by code or full name
- `is_nationwide`: says nationwide / all 50 states / worldwide, or was sold online (these usually list no states)
- `is_online`: sold online, by mail order, or on Amazon etc.; counted as nationwide since anyone could have bought it (Amazon Fresh / physical Amazon stores excluded)
- `is_foreign`: mentions another country or foreign/international distribution, ignoring "no foreign distribution" style negations

Codes that are also words (IN, OR, ME, OK…) only count in upper case in normal text, and only inside a list in all-caps text. About 400 events name no states and aren't nationwide ("Domestic distribution only", "Canada only", "Unknown"). To ask which recalls reached a state, use `event_state_reach` so nationwide recalls are included.

### Product category

`fda_recall/products.py` assigns a kind of food from `product_description` (about 94% of products): `produce`, `bakery`, `prepared_foods`, `dairy`, `sauces_condiments`, `dietary_supplements`, `grains_pasta_cereal`, `spices_seasonings`, `nuts_seeds`, `seafood`, `frozen_dessert`, `candy_chocolate`, `snacks`, `beverages`, `meat_poultry`, `infant_formula_baby_food`, `eggs`. It looks only at the product name (the text before "Ingredients", "Net Wt", "UPC"...; "X with Y" / "X in Y" become X) and uses the **last** food word in it, since that's the head noun: "Chocolate Chip Cookie Dough Ice Cream" is `frozen_dessert`, "Peanut Butter Cookies" is `bakery`. NULL means only a brand name was given ("CardioAdvance").

### UPCs

Codes after a "UPC" label are read as a list ("UPC 74690-028590; and 8 oz., UPC 74690-231556"); a bare 12–13 digit number counts only if its check digit is valid and it isn't labelled as a lot / item / SKU number. Codes are stored as the digits given, so the same product can appear with and without a leading zero or check digit.

### How it was found, and illnesses

`fda_recall/detection.py` reads `reason_for_recall`:

- `product_detection_sources`: `supplier_notification`, `regulator_testing`, `consumer_complaint`, `firm_testing`, `regulator_inspection`, `illness_investigation`, `customer_testing`, `label_or_record_review`. Only about 1 in 8 events says how the problem was found.
- `illness_reported`: the text says illnesses, reactions or an outbreak actually happened. Boilerplate ("an organism which can cause serious and sometimes fatal infections") and negations ("No illnesses have been reported") don't count.

### Recall reason categories

`fda_recall/reasons.py` tags each `reason_for_recall` with regex rules; it covers about 97% of products. Categories, in the priority order used to pick `reason_category`:

`pathogen`, `undeclared_allergen`, `foreign_material`, `chemical`, `unapproved_drug`, `processing`, `temperature_abuse`, `sanitation`, `labeling`, `regulatory_order`, `supplier_recall` — and `other` when nothing matched.

To change a rule, edit `reasons.py`, add a case to `tests/test_reasons.py`, and run `python -m fda_recall.clean` to re-tag everything. Reason texts often name the product ("Hot Smoked Salmon", "plastic clamshell"), so the allergen and foreign-material rules need supporting wording; the tests list known false-positive cases.

## Tests

```bash
python -m unittest
```

## Example queries

```sql
-- Recall events per year, by most severe classification
SELECT substr(report_date, 1, 4) AS yr, most_severe_class, count(*) FROM events
GROUP BY 1, 2 ORDER BY 1, 2;

-- Firms with the most recall events (name variants combined)
SELECT firm_key, count(*) events, sum(product_count) products FROM events
GROUP BY 1 ORDER BY events DESC LIMIT 20;

-- Listeria recall events per year
SELECT substr(e.report_date, 1, 4) AS yr, count(DISTINCT e.event_id) FROM events e
JOIN products p USING (event_id)
JOIN product_reason_tags t USING (recall_number)
WHERE t.category = 'pathogen' AND t.detail = 'listeria'
GROUP BY yr ORDER BY yr;

-- Recall events by size and main reason
SELECT e.size, p.reason_category, count(DISTINCT e.event_id) FROM events e
JOIN products p USING (event_id)
GROUP BY 1, 2 ORDER BY 2, min(e.est_units);

-- Recall events that reached Texas, by main reason (nationwide ones included)
SELECT p.reason_category, count(DISTINCT r.event_id) FROM event_state_reach r
JOIN products p USING (event_id)
WHERE r.state = 'TX'
GROUP BY 1 ORDER BY 2 DESC;

-- Kinds of food in Listeria recall events
SELECT p.product_category, count(DISTINCT p.event_id) FROM products p
JOIN product_reason_tags t USING (recall_number)
WHERE t.category = 'pathogen' AND t.detail = 'listeria'
GROUP BY 1 ORDER BY 2 DESC;

-- Every recall of a given UPC
SELECT p.recall_number, e.report_date, p.reason_for_recall FROM product_upcs u
JOIN products p USING (recall_number) JOIN events e USING (event_id)
WHERE u.upc = '041498205379';

-- Products by main recall reason
SELECT reason_category, count(*) FROM products GROUP BY 1 ORDER BY 2 DESC;

-- Open data issues
SELECT issue, count(*) FROM data_issues GROUP BY 1;

-- What changed in the most recent load
SELECT * FROM recalls WHERE last_changed_run = (SELECT max(run_id) FROM load_runs);
```
