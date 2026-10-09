# Recruiting Pipeline

A small data pipeline that takes a messy applicant tracking system export, cleans it,
joins it to requisition data, checks it, and publishes a dashboard a recruiting team
could actually use.

**[Live dashboard]([https://your-project.vercel.app](https://recruiting-ops-pipeline.vercel.app/))**

---

## Why I built it

Recruiting data is spread across systems that were never designed to agree with each
other. Applications live in the ATS, requisitions live in the HRIS, and the two are
joined by a requisition ID that sometimes doesn't match. The result is that simple
questions — how long are we taking to hire engineers, which candidates are stuck,
which sourcing channels actually work — need someone to rebuild a spreadsheet by hand
every week.

I wanted to show the whole path from raw export to a working dashboard, including the
parts that usually get skipped in a portfolio project: the cleaning rules, the checks,
and the decisions about what *not* to fix automatically.

## The data

There's no public recruiting dataset, so `src/generate_data.py` creates one. It
produces two files that behave like real exports:

- `lever_applications.csv` — 444 candidate applications
- `workday_requisitions.csv` — 26 open and closed requisitions

The raw file is deliberately messy, in the five ways this kind of data usually is:

| Problem | Example | How many |
|---|---|---|
| Inconsistent source names | `LinkedIn`, `linkedin`, `LINKEDIN`, `" LinkedIn "` | ~1 in 4 rows |
| Missing emails | application form doesn't require it | 10 |
| Duplicate applications | same person reapplies to the same req | 14 |
| Orphaned requisition IDs | req deleted in the HRIS after people applied | 9 |
| Two date formats | `2026-07-14` and `07/14/2026` in one column | ~20% |
| Impossible dates | future application dates, activity before applying | 13 |

## The pipeline

The transformations are written in SQL, in `sql/`. DuckDB runs them directly against
the CSV files, so there is no database to set up. `src/pipeline.py` wires it together
and prints what each rule removed:

```
Loaded 444 applications and 26 requisitions

Cleaning
  applied_at in the future                 removed   6  (438 remaining)
  activity before application              removed   6  (432 remaining)
  duplicate applications                   removed  18  (414 remaining)
  req_id not found in Workday              removed   9  (405 remaining)

Final dataset: 405 rows, 24 columns
```

`sql/01_clean_applications.sql` does the cleaning and deduplication.
`sql/02_build_fact.sql` joins the requisition and derives the metrics.

Two decisions worth calling out:

**Rejected rows are written to a file, not deleted.** The 9 applications pointing at a
missing requisition are real people who applied for a real job. They go to
`data/processed/rejected_rows.csv` so recruiting can reassign them, instead of quietly
vanishing from the funnel.

**Metrics are calculated once, in the pipeline.** `days_in_stage`, `time_to_hire_days`
and `past_sla` are computed here and stored, rather than recalculated in the dashboard.
That's what stops two reports from disagreeing about the same number.

## The checks

`src/quality_checks.py` runs six rules against the cleaned data. Four pass. Two fail on
purpose:

- **9 applications have no email.** A pipeline can't invent one. The fix is to make the
  field required on the application form, so this is reported for a human to act on.
- **1 offer sits outside the approved compensation band.** Sometimes that's an approved
  exception, so it's flagged for Finance rather than blocked.

Blocking failures exit with a non-zero status, so this would stop a scheduled run before
a bad dataset reached the dashboard.

## The tests

`pytest -q` runs 18 tests against the SQL. Each one builds a small table by hand and
checks a single rule, so a failure points at the rule that broke rather than at a change
in the generated data.

```
tests/test_pipeline.py .................. 18 passed
```

They cover source normalisation, both date formats, the future-date and
activity-ordering rejections, deduplication (including that the same person on two
different requisitions is *not* a duplicate, and that two people with missing emails
are not collapsed into one), the requisition join, and the derived metrics.

I checked the tests actually catch regressions by breaking each rule in turn and
confirming the right test failed. That exercise found a real problem: my first
future-date test was passing for the wrong reason, because the row was being caught by
the activity-ordering rule instead. It's fixed and now isolates the rule it claims to
test.

## The dashboard

`public/index.html` is a single static page that reads `public/data.json`. It does no
calculation of its own — every number on it comes from the pipeline. It shows:

- Headline numbers: applications, open reqs, median time to hire, offer acceptance
- The stage-by-stage funnel with conversion rates
- Which sourcing channels produce hires, not just applications
- Median time to hire by department
- Candidates with no activity in more than twice their stage target — the list a
  recruiting lead would work through on a Monday
- The results of the quality checks, so anyone reading the dashboard can see what the
  data can and can't be trusted for

## Running it

```bash
pip install -r requirements.txt

python src/generate_data.py     # create the raw source files
python src/pipeline.py          # run the SQL: clean, join, derive
python src/quality_checks.py    # validate
python src/build_dashboard.py   # write public/data.json

pytest -q                       # run the tests
```

Or just `./run.sh` for the whole chain.

Then open `public/index.html`, or serve it:

```bash
cd public && python -m http.server 8000
```

The random seed is fixed, so every run produces the same numbers as the ones quoted
above.

## Structure

```
sql/
  01_clean_applications.sql   normalise, parse dates, reject bad rows, deduplicate
  02_build_fact.sql           join requisitions, derive metrics
src/
  generate_data.py     synthetic Lever + Workday exports
  pipeline.py          runs the SQL against the CSVs with DuckDB
  quality_checks.py    six validation rules
  build_dashboard.py   aggregates into public/data.json
tests/
  test_pipeline.py     18 tests covering the cleaning rules
data/
  raw/                 generated source files
  processed/           clean dataset, rejected rows, quality report
public/
  index.html           dashboard
  data.json            everything the dashboard displays
```

## What I'd add next

- Incremental loads instead of rebuilding the whole dataset each run
- Snapshots of stage history, so the funnel reflects when candidates moved rather than
  only where they are now
- Writeback, so a correction made while reviewing the data reaches the source system

---

Built by Meghana Lakshminarayana Swamy ·
[meghana-l.github.io](https://meghana-l.github.io) ·
all data in this repository is synthetic.
