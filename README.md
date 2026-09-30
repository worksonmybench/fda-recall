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
| `events` | one row per recall event: firm, address, distribution, initiation/report dates, plus `firm_key`, `product_count`, `most_severe_class`, `ongoing_product_count` |
| `products` | one row per recall number (product), linked by `event_id`; `reason_category` is its main recall reason |
| `product_reason_tags` | every `(category, detail)` matched in the recall reason, e.g. `pathogen / listeria`, `undeclared_allergen / peanut`; a product can have several |
| `data_issues` | records that failed a sanity check, for manual review; nothing is auto-corrected |

Cleanup applied: whitespace trimmed and collapsed (line breaks kept), placeholders like `N/A` turned into NULL, and `firm_key` added for matching firm-name variants (`Ventura Foods, LLC` = `VENTURA FOODS LLC`).

Note: one event covers many products, so decide whether you're counting events or products.

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

-- Products by main recall reason
SELECT reason_category, count(*) FROM products GROUP BY 1 ORDER BY 2 DESC;

-- Open data issues
SELECT issue, count(*) FROM data_issues GROUP BY 1;

-- What changed in the most recent load
SELECT * FROM recalls WHERE last_changed_run = (SELECT max(run_id) FROM load_runs);
```
