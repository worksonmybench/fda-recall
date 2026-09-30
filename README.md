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

| table | contents |
|---|---|
| `recalls` | one row per recall; openFDA fields as columns (dates as `YYYY-MM-DD`, empty strings as NULL), plus the full original record in `raw_json` |
| `recall_history` | prior versions of recalls that later changed |
| `load_runs` | one row per file loaded: timestamp, file hash, openFDA `last_updated`, counts |

Fields openFDA adds later are kept in `raw_json` and reported during the load, so you can add columns for them later without reloading anything.

## Example queries

```sql
-- Class I recalls per year
SELECT substr(report_date, 1, 4) AS yr, count(*) FROM recalls
WHERE classification = 'Class I' GROUP BY yr ORDER BY yr;

-- Top recalling firms
SELECT recalling_firm, count(*) n FROM recalls GROUP BY 1 ORDER BY n DESC LIMIT 20;

-- What changed in the most recent load
SELECT * FROM recalls WHERE last_changed_run = (SELECT max(run_id) FROM load_runs);
```
