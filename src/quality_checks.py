"""
Checks the cleaned dataset before anyone builds a report on it.

Two of these are expected to fail. Missing emails and out-of-band offers are real
problems, but they aren't things a pipeline should silently fix - the first needs a
change to the application form, the second needs a person from Finance to look at it.
So they're reported as warnings rather than dropped.

Run: python src/quality_checks.py
"""

import json
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

VALID_SOURCES = ["LinkedIn", "Referral", "Careers Site", "University", "Agency", "Sourced"]


def build_checks(df):
    """Each check returns the rows that failed it."""
    return [
        {
            "name": "email is present",
            "severity": "warning",
            "why": "Coordinators need a way to contact the candidate.",
            "failures": df[df["email"].isna() | (df["email"] == "")],
            "action": "Make email required on the Lever application form. Until then these go to a manual worklist.",
        },
        {
            "name": "one row per candidate per requisition",
            "severity": "blocking",
            "why": "Duplicate applications double-count the funnel.",
            "failures": df[df.duplicated(subset=["email", "req_id"], keep=False) & df["email"].notna()],
            "action": "Handled by the deduplication step in pipeline.py.",
        },
        {
            "name": "req_id exists in Workday",
            "severity": "blocking",
            "why": "An application against a missing requisition has no department or hiring manager.",
            "failures": df[df["department"].isna()],
            "action": "Rejected rows are written to rejected_rows.csv for Recruiting to reassign.",
        },
        {
            "name": "source is a known channel",
            "severity": "blocking",
            "why": "Attribution reporting only works if the channel names agree.",
            "failures": df[~df["source"].isin(VALID_SOURCES)],
            "action": "Normalised in the pipeline. Worth fixing the ATS picklist too.",
        },
        {
            "name": "applied_at is not in the future",
            "severity": "blocking",
            "why": "Future dates break any report grouped by month.",
            "failures": df[df["applied_at"] > pd.Timestamp("2026-10-08")],
            "action": "Rejected during cleaning and reported back to whoever owns the integration.",
        },
        {
            "name": "offer is within the approved band",
            "severity": "warning",
            "why": "Offers outside the requisition band need Finance sign-off.",
            "failures": df[df["offer_amount"].notna() &
                           ((df["offer_amount"] < df["comp_min"] * 0.8) |
                            (df["offer_amount"] > df["comp_max"] * 1.1))],
            "action": "Not always a mistake - exceptions get approved. Flagged for review.",
        },
    ]


def run():
    df = pd.read_csv(PROCESSED / "applications_clean.csv", parse_dates=["applied_at", "last_activity_at"])
    checks = build_checks(df)

    print(f"Running {len(checks)} checks on {len(df)} rows\n")
    results, blocking_failures = [], 0

    for check in checks:
        count = len(check["failures"])
        passed = count == 0
        if not passed and check["severity"] == "blocking":
            blocking_failures += 1

        label = "PASS" if passed else f"{check['severity'].upper()}"
        detail = "" if passed else f"  ({count} row{'s' if count != 1 else ''})"
        print(f"  [{label:<8}] {check['name']}{detail}")
        if not passed:
            print(f"             {check['action']}")

        results.append({
            "name": check["name"],
            "severity": check["severity"],
            "passed": bool(passed),
            "failing_rows": int(count),
            "why": check["why"],
            "action": check["action"],
        })

    with open(PROCESSED / "quality_report.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} checks passed, "
          f"{blocking_failures} blocking failures")
    print("Saved -> data/processed/quality_report.json")

    if blocking_failures:
        raise SystemExit(1)  # a real pipeline should stop here
    return results


if __name__ == "__main__":
    run()
