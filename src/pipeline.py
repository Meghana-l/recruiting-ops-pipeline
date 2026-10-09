"""
Runs the SQL transformations against the raw CSV exports.

The actual cleaning logic lives in sql/, not in this file. DuckDB reads the CSVs
directly, so there's no database to set up. This script wires it together, prints
what each step removed, and writes the results out.

Run: python src/pipeline.py
"""

import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SQL = ROOT / "sql"


def connect():
    """Register the two raw CSVs as tables and load the SQL views."""
    con = duckdb.connect()
    con.execute(f"""
        CREATE VIEW raw_applications  AS SELECT * FROM read_csv_auto('{RAW / "lever_applications.csv"}', all_varchar=true);
        CREATE VIEW raw_requisitions  AS SELECT * FROM read_csv_auto('{RAW / "workday_requisitions.csv"}');
    """)
    for script in sorted(SQL.glob("*.sql")):
        con.execute(script.read_text())
    return con


def count(con, sql):
    return con.execute(sql).fetchone()[0]


def run(verbose=True):
    PROCESSED.mkdir(parents=True, exist_ok=True)
    con = connect()

    raw_apps = count(con, "SELECT count(*) FROM raw_applications")
    raw_reqs = count(con, "SELECT count(*) FROM raw_requisitions")
    clean = count(con, "SELECT count(*) FROM clean_applications")
    final = count(con, "SELECT count(*) FROM fact_applications")

    # Break the losses down so each cleaning rule is accounted for.
    future = count(con, """
        SELECT count(*) FROM raw_applications
        WHERE COALESCE(TRY_STRPTIME(applied_at,'%Y-%m-%d'),
                       TRY_STRPTIME(applied_at,'%m/%d/%Y'))::DATE > DATE '2026-10-08'
    """)
    backdated = count(con, """
        SELECT count(*) FROM raw_applications
        WHERE COALESCE(TRY_STRPTIME(last_activity_at,'%Y-%m-%d'),
                       TRY_STRPTIME(last_activity_at,'%m/%d/%Y'))::DATE
            < COALESCE(TRY_STRPTIME(applied_at,'%Y-%m-%d'),
                       TRY_STRPTIME(applied_at,'%m/%d/%Y'))::DATE
          AND COALESCE(TRY_STRPTIME(applied_at,'%Y-%m-%d'),
                       TRY_STRPTIME(applied_at,'%m/%d/%Y'))::DATE <= DATE '2026-10-08'
    """)
    duplicates = raw_apps - future - backdated - clean
    orphaned = clean - final

    if verbose:
        print(f"Loaded {raw_apps} applications and {raw_reqs} requisitions\n")
        print("Cleaning")
        for label, removed in [
            ("applied_at in the future", future),
            ("activity before application", backdated),
            ("duplicate applications", duplicates),
            ("req_id not found in Workday", orphaned),
        ]:
            print(f"  {label:<40} removed {removed:>3}")
        print(f"\nDeriving metrics")
        print("  days_in_stage, past_sla, time_to_hire_days, stage_rank")

    # Applications pointing at a requisition that no longer exists are real
    # people, so they are written out for recruiting to reassign.
    con.execute(f"""
        COPY (
            SELECT a.*, 'req_id not found in Workday' AS rejected_reason
            FROM clean_applications a
            WHERE a.req_id NOT IN (SELECT req_id FROM raw_requisitions)
        ) TO '{PROCESSED / "rejected_rows.csv"}' (HEADER, DELIMITER ',')
    """)
    con.execute(f"""
        COPY (SELECT * FROM fact_applications)
        TO '{PROCESSED / "applications_clean.csv"}' (HEADER, DELIMITER ',')
    """)

    if verbose:
        cols = count(con, "SELECT count(*) FROM (DESCRIBE fact_applications)")
        print(f"\n{orphaned} rejected rows saved for review -> data/processed/rejected_rows.csv")
        print(f"\nFinal dataset: {final} rows, {cols} columns")
        print("Saved -> data/processed/applications_clean.csv")

    return con


if __name__ == "__main__":
    run()
