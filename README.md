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

It's deployed as a Cloudflare Worker with static assets at `fdarecall.worksonmybench.dev` (`wrangler.jsonc`). `site/_headers` sets the security headers, including a CSP with no inline scripts or styles, so set inline styles through `element.style` rather than a `style` attribute. `npx wrangler dev` serves `dist/` with those headers locally.

### Refresh and deploy

`dist/` is committed, and every push to `main` deploys it (`.github/workflows/deploy.yml`, which needs the repo secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`). All data is fetched and built locally, so CI makes no calls to FDA, USDA or the NYT. CI runs the tests and fails if `dist/`'s copies of the `site/` files are out of date, so re-export after changing a page. The export is deterministic, so a refresh commit only touches files whose data changed.

1. Replace the openFDA export in this folder with the latest `food-enforcement-0001-of-0001.json.zip` from https://open.fda.gov/data/downloads/.
2. Refresh `sources/usda/fsis_recalls.json` from the dev server (see [USDA recall data](#usda-recall-data)).
3. `python3 -m fda_recall.load`, then `NYT_API_KEY=... python3 -m fda_recall.media fetch`
4. `python3 -m fda_recall.web.export`
5. Commit `sources/usda/` and `dist/`, and push.

How it fits together:

- `fda_recall/web/endpoints.py` defines each API response as a Python function registered at a path. A path parameter like `{scope}` must come with a function listing its allowed values, which is what lets the export enumerate every file. The dev server refuses values the export wouldn't produce, so dev can't drift from the deployed site.
- `site/` is plain HTML/CSS/JS modules, with no build step or chart library. It fetches `api/<path>.json` with relative URLs, so it works from any base path.
- To add a stat: add or extend an endpoint, then render it in the page's script.

### Pages

Every page shares the same nav (Overview · By state · Search · About) with a "find a recall" box that takes a recall number, UPC (with or without its leading zero or check digit) or event ID. `site/nav.js` runs it; it fetches `api/lookup.json` (about 175 KB compressed) only when someone searches.

| Page | Files | What it is |
|---|---|---|
| Overview | `index.html`, `home.js` | The story: "are food recalls on the rise?" A data-written answer, recall events vs news coverage (both indexed to 2013 = 100), events per year by class, a glance map (a state opens it on the By state page), what gets recalled and why (bars open search pre-filtered), and the latest recalls. Loads about 30 KB: `api/trends.json`, `api/states.json`, `api/dashboard/impacting/US.json`. |
| By state | `state.html`, `state.js` | The interactive map. Its toggle switches between **recalls impacting a state** (the distribution reached it; nationwide recalls count everywhere) and **recalls originating from a state** (the firm is located there). Selecting a state scopes every chart below it; view and state stay in the URL (`state.html#originating/CA`). |
| Search | `search.html`, `search.js` | Filters all recall events in the browser: keywords (firm name and the start of the first product's description), a date range on report or recall-start date with presets, reason, kind of food, state (impacted or firm location), status, class, size, illness and nationwide. Sorted and paged locally from `api/search_index.json` (about 550 KB compressed, downloaded once). Filters stay in the query string. |
| About | `about.html` | Sources, what "event" and "class" mean, how derived fields are built, how news coverage is measured, caveats. |
| Recall details | `event.html`, `event.js` | One page per recall event, `event.html?id=<event_id>`, from `api/event/<id>.json`: firm, dates, class, status, size, a map of where it was distributed, the reason(s), every product (recall number, description, quantity, lot codes, UPCs) and the firm's other recalls. Pages are per event rather than per recall number because an event is one firm's single recall announcement. Link to one product with `event.html?id=99611#H-1364-2026`. |

The full export is about 8,000 files, around 9.5 MB compressed.

### News coverage (media attention)

The Overview compares FDA and USDA recall counts (both indexed to 2014, the first year with both) with New York Times coverage of food safety: the share of all NYT articles each month that the Times tagged *Food Contamination and Poisoning*, or *Recalls and Bans of Products* together with a food tag. It uses the NYT Archive API (every article's metadata and subject tags for a month), and needs a free API key from https://developer.nytimes.com with the Archive API enabled for your app:

```bash
NYT_API_KEY=your-key python -m fda_recall.media fetch
```

This makes one request per month since June 2012, about 170 requests paced at the API's 5-per-minute limit (roughly 36 minutes and 2-3 GB of downloads the first time). Only the fields used (headline, date, tags) are kept, gzipped, in `data/media/nyt/`, so later runs only fetch new months plus the last two, and the matching rules can change without downloading again (`python -m fda_recall.media load` recounts). Results go into the `media_attention` table, which the web export picks up. Until it has been run, the Overview shows the recall line alone with a note.

The matching rules are `is_food_safety` in `fda_recall/media.py`. `python -m fda_recall.media sample 2018-04` prints the matched headlines for a month. The Archive API is used rather than Article Search because, since its 2025 update, Article Search ignores field filters and applies AND/OR unpredictably, so its counts can't isolate a topic. Show "News coverage data provided by The New York Times" wherever the numbers appear (the site already does).

## USDA recall data

FDA's data doesn't cover meat, poultry and processed egg products; USDA's Food Safety and Inspection Service (FSIS) recalls those. Their Recall API (`https://www.fsis.usda.gov/fsis/api/recall/v/1`) is behind bot protection that rejects scripts (curl, Python) but answers normal browser requests, so it's refreshed from a browser and the result is committed:

1. Start the dev server (`python -m fda_recall.web.serve`) and open http://127.0.0.1:8000/dev/usda.html.
2. Click **Fetch from FSIS and save**. Your browser fetches the feed and the dev server writes `sources/usda/fsis_recalls.json`, reporting new, changed and removed recalls.
3. Review and commit that file.

The file keeps English records only (the feed repeats many notices in Spanish), turns the HTML summaries into plain text, and drops personal media-contact details. It's written one record per line in a stable order, so a refresh with nothing new changes only the `fetched_at` line. If you download the feed by hand instead, `python -m fda_recall.usda import path/to/download.json` does the same normalising. The `/dev/` pages are served only by the dev server and are never exported.

`python -m fda_recall.load` loads the committed file into the `usda_recalls` table (same change tracking as FDA), and the clean rebuild folds each notice into `events` / `products` as one event (`USDA-<number>`) with one product row, so every table, endpoint and page covers both agencies. `events.agency` is `FDA` or `USDA`, and `events.recall_type` marks USDA public health alerts, which count as recalls but have no class.

FSIS notices follow a template, so `fda_recall/usda.py` reads only the parts that vary: the opening paragraph (firm, home state, pounds, why), the "The problem was discovered …" sentence (how it was found), the illness sentence, and the states list or "shipped to …" sentence. The standard closing paragraphs ("Anyone concerned about an injury or illness should contact a healthcare provider", the complaint-system link) are dropped first, because every notice has them and they would otherwise flag every recall as an illness or consumer complaint. When the shared reason rules find nothing, FSIS's own reason field (e.g. *Produced Without Benefit of Inspection*) is used.

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
