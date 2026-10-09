"""
Turns the clean dataset into the single JSON file the dashboard loads.

The dashboard does no calculation of its own. Everything it shows is computed here,
so the numbers on the page always match the numbers in the pipeline.

Run: python src/build_dashboard.py
"""

import json
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
PUBLIC = ROOT / "public"

STAGE_ORDER = ["Applied", "Recruiter Screen", "Technical Screen", "Onsite", "Offer", "Hired"]


def build(df, quality):
    # Funnel: how many candidates reached each stage or went past it.
    funnel = []
    for i, stage in enumerate(STAGE_ORDER):
        reached = int((df["stage_rank"] >= i).sum())
        previous = funnel[-1]["reached"] if funnel else None
        funnel.append({
            "stage": stage,
            "reached": reached,
            "conversion": round(100 * reached / previous, 1) if previous else None,
        })

    # Which channels actually produce hires, not just applications.
    sources = []
    for source, group in df.groupby("source"):
        hires = int((group["stage"] == "Hired").sum())
        sources.append({
            "source": source,
            "applications": int(len(group)),
            "hires": hires,
            "hire_rate": round(100 * hires / len(group), 1),
        })
    sources.sort(key=lambda s: s["hire_rate"], reverse=True)

    # Time to hire by department, for the departments that actually hired someone.
    by_dept = []
    hired = df[df["stage"] == "Hired"]
    for dept, group in hired.groupby("department"):
        by_dept.append({
            "department": dept,
            "hires": int(len(group)),
            "median_days": int(group["time_to_hire_days"].median()),
        })
    by_dept.sort(key=lambda d: d["median_days"])

    # Candidates nobody has touched in twice their stage SLA.
    stuck = (df[df["past_sla"]]
             .sort_values("days_in_stage", ascending=False)
             .head(10)[["candidate_id", "candidate_name", "title", "department",
                        "stage", "recruiter", "days_in_stage", "stage_sla_days"]])

    offers = int((df["stage_rank"] >= STAGE_ORDER.index("Offer")).sum())
    hires_total = int((df["stage"] == "Hired").sum())

    return {
        "generated_at": "2026-10-08",
        "summary": {
            "applications": int(len(df)),
            "open_requisitions": int(df[df["status"] == "Open"]["req_id"].nunique()),
            "active_candidates": int(((df["stage"] != "Hired")).sum()),
            "median_time_to_hire": int(hired["time_to_hire_days"].median()),
            "offer_acceptance": round(100 * hires_total / offers, 1) if offers else 0,
            "past_sla": int(df["past_sla"].sum()),
        },
        "funnel": funnel,
        "sources": sources,
        "time_to_hire_by_department": by_dept,
        "stuck_candidates": stuck.to_dict("records"),
        "quality": quality,
    }


def run():
    df = pd.read_csv(PROCESSED / "applications_clean.csv", parse_dates=["applied_at", "last_activity_at"])
    quality = json.loads((PROCESSED / "quality_report.json").read_text())

    PUBLIC.mkdir(parents=True, exist_ok=True)
    data = build(df, quality)

    with open(PUBLIC / "data.json", "w") as f:
        json.dump(data, f, indent=2)

    s = data["summary"]
    print(f"Dashboard data built from {s['applications']} applications")
    print(f"  median time to hire : {s['median_time_to_hire']} days")
    print(f"  offer acceptance    : {s['offer_acceptance']}%")
    print(f"  past SLA            : {s['past_sla']} candidates")
    print("Saved -> public/data.json")


if __name__ == "__main__":
    run()
