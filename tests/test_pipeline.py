"""
Tests for the cleaning rules in sql/.

Each test builds a tiny table by hand, runs the real SQL against it, and checks
the result. Testing against fixed input rather than the generated dataset means a
failure points at the rule that broke, not at a change in the random data.

Run: pytest -q
"""

import duckdb
import pytest
from pathlib import Path

SQL = Path(__file__).resolve().parents[1] / "sql"

COLUMNS = ["candidate_id", "candidate_name", "email", "source", "req_id", "stage",
           "recruiter", "applied_at", "last_activity_at", "offer_amount"]


def application(**overrides):
    """A valid application row. Pass keywords to break one field at a time."""
    row = {
        "candidate_id": "cand_1", "candidate_name": "Test Candidate",
        "email": "test@example.com", "source": "LinkedIn", "req_id": "REQ-4100",
        "stage": "Applied", "recruiter": "a.okafor",
        "applied_at": "2026-09-01", "last_activity_at": "2026-10-01",
        "offer_amount": "",
    }
    row.update(overrides)
    return row


def load(applications, requisitions=None):
    """Run the real SQL files against the given rows."""
    requisitions = requisitions or [{
        "req_id": "REQ-4100", "title": "Data Engineer", "department": "Engineering",
        "level": "IC3", "region": "AMER", "hiring_manager": "r.aldridge",
        "opened_at": "2026-06-01", "status": "Open",
        "comp_min": 120000, "comp_max": 160000,
    }]

    con = duckdb.connect()
    app_values = ", ".join(
        "(" + ", ".join("'" + str(r[c]).replace("'", "''") + "'" for c in COLUMNS) + ")"
        for r in applications
    )
    con.execute(f"CREATE VIEW raw_applications AS SELECT * FROM (VALUES {app_values}) "
                f"AS t({', '.join(COLUMNS)})")

    req_cols = list(requisitions[0])
    req_values = ", ".join(
        "(" + ", ".join(
            str(r[c]) if isinstance(r[c], int) else "'" + str(r[c]) + "'" for c in req_cols
        ) + ")" for r in requisitions
    )
    con.execute(f"CREATE VIEW raw_requisitions AS SELECT * FROM (VALUES {req_values}) "
                f"AS t({', '.join(req_cols)})")

    for script in sorted(SQL.glob("*.sql")):
        con.execute(script.read_text())
    return con


# --- source normalisation ------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("linkedin", "LinkedIn"),
    ("  LinkedIn ", "LinkedIn"),
    ("LINKEDIN", "LinkedIn"),
    ("Employee Referral", "Referral"),
    ("Website", "Careers Site"),
    ("Outbound", "Sourced"),
])
def test_source_variants_fold_to_one_name(raw, expected):
    con = load([application(source=raw)])
    assert con.execute("SELECT source FROM clean_applications").fetchone()[0] == expected


def test_unrecognised_source_becomes_unknown():
    """A new channel should show up as Unknown, not be silently dropped."""
    con = load([application(source="Carrier Pigeon")])
    assert con.execute("SELECT source FROM clean_applications").fetchone()[0] == "Unknown"


# --- date handling -------------------------------------------------------

def test_both_date_formats_parse_to_the_same_date():
    con = load([application(candidate_id="a", applied_at="2026-07-14"),
                application(candidate_id="b", email="b@example.com", applied_at="07/14/2026")])
    dates = con.execute("SELECT DISTINCT applied_at FROM clean_applications").fetchall()
    assert len(dates) == 1


def test_future_application_is_rejected():
    # last_activity is after applied_at here, so this row can only be rejected
    # by the future-date rule and not by the activity-ordering rule.
    con = load([application(applied_at="2026-12-25", last_activity_at="2026-12-26")])
    assert con.execute("SELECT count(*) FROM clean_applications").fetchone()[0] == 0


def test_activity_before_application_is_rejected():
    con = load([application(applied_at="2026-09-01", last_activity_at="2026-08-01")])
    assert con.execute("SELECT count(*) FROM clean_applications").fetchone()[0] == 0


# --- deduplication -------------------------------------------------------

def test_reapplication_keeps_the_most_recent():
    con = load([
        application(candidate_id="old", applied_at="2026-05-01"),
        application(candidate_id="new", applied_at="2026-08-01"),
    ])
    rows = con.execute("SELECT candidate_id FROM clean_applications").fetchall()
    assert rows == [("new",)]


def test_same_person_on_two_requisitions_is_not_deduplicated():
    """Applying to two different roles is two applications, not a duplicate."""
    con = load(
        [application(candidate_id="a", req_id="REQ-4100"),
         application(candidate_id="b", req_id="REQ-4101")],
        requisitions=[
            {"req_id": "REQ-4100", "title": "Data Engineer", "department": "Engineering",
             "level": "IC3", "region": "AMER", "hiring_manager": "r.aldridge",
             "opened_at": "2026-06-01", "status": "Open", "comp_min": 120000, "comp_max": 160000},
            {"req_id": "REQ-4101", "title": "Security Engineer", "department": "Security",
             "level": "IC3", "region": "AMER", "hiring_manager": "s.bello",
             "opened_at": "2026-06-01", "status": "Open", "comp_min": 120000, "comp_max": 160000},
        ])
    assert con.execute("SELECT count(*) FROM fact_applications").fetchone()[0] == 2


def test_missing_emails_are_not_collapsed_together():
    """Two different people with no email on file are two people."""
    con = load([application(candidate_id="a", email=""),
                application(candidate_id="b", email="")])
    assert con.execute("SELECT count(*) FROM clean_applications").fetchone()[0] == 2


# --- join and derived metrics -------------------------------------------

def test_application_against_missing_requisition_is_excluded():
    con = load([application(req_id="REQ-9999")])
    assert con.execute("SELECT count(*) FROM clean_applications").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM fact_applications").fetchone()[0] == 0


def test_days_in_stage_counts_from_last_activity():
    con = load([application(last_activity_at="2026-10-01")])
    assert con.execute("SELECT days_in_stage FROM fact_applications").fetchone()[0] == 7


def test_past_sla_triggers_beyond_twice_the_target():
    """Applied has a 4 day target, so the flag turns on after 8 days idle."""
    within = load([application(last_activity_at="2026-10-02")])   # 6 days idle
    beyond = load([application(last_activity_at="2026-09-20")])   # 18 days idle
    assert within.execute("SELECT past_sla FROM fact_applications").fetchone()[0] is False
    assert beyond.execute("SELECT past_sla FROM fact_applications").fetchone()[0] is True


def test_hired_candidates_are_never_past_sla():
    con = load([application(stage="Hired", applied_at="2026-01-05",
                            last_activity_at="2026-03-01")])
    assert con.execute("SELECT past_sla FROM fact_applications").fetchone()[0] is False


def test_time_to_hire_only_set_for_hires():
    hired = load([application(stage="Hired", applied_at="2026-08-01",
                              last_activity_at="2026-09-10")])
    active = load([application(stage="Onsite")])
    assert hired.execute("SELECT time_to_hire_days FROM fact_applications").fetchone()[0] == 40
    assert active.execute("SELECT time_to_hire_days FROM fact_applications").fetchone()[0] is None
