"""
Builds the single JSON file the dashboard loads.

It ships three things: the summary figures, the full cleaned dataset so the page can
filter and re-aggregate without a server, and the raw rows with their defects flagged
so a visitor can see exactly what the pipeline had to deal with.

Metric definitions (days_in_stage, time_to_hire_days, past_sla) are still calculated
in the pipeline, not here. The page only slices and counts.

Run: python src/build_dashboard.py
"""

import json
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
PUBLIC = ROOT / "public"

TODAY = pd.Timestamp("2026-10-08")
STAGE_ORDER = ["Applied", "Recruiter Screen", "Technical Screen", "Onsite", "Offer", "Hired"]
VALID_SOURCES = ["LinkedIn", "Referral", "Careers Site", "University", "Agency", "Sourced"]

KEEP = ["candidate_id", "candidate_name", "source", "req_id", "title", "department",
        "region", "stage", "stage_rank", "recruiter", "applied_at", "last_activity_at",
        "days_in_stage", "stage_sla_days", "past_sla", "time_to_hire_days",
        "offer_amount", "status", "email"]


def parse_dates(series):
    iso = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
    us = pd.to_datetime(series, format="%m/%d/%Y", errors="coerce")
    return iso.fillna(us)


def flag_raw_defects(raw, req_ids):
    """Mark every problem in the raw export so the page can highlight it."""
    applied = parse_dates(raw["applied_at"])
    activity = parse_dates(raw["last_activity_at"])
    dupe_key = raw["email"].fillna("").replace("", pd.NA).fillna(raw["candidate_id"]) \
        .astype(str) + "|" + raw["req_id"].astype(str)

    flags = pd.DataFrame({
        "missing_email": raw["email"].isna() | (raw["email"].astype(str).str.strip() == ""),
        "messy_source": ~raw["source"].isin(VALID_SOURCES),
        "us_date": raw["applied_at"].astype(str).str.contains("/"),
        "future_date": applied > TODAY,
        "backdated_activity": activity < applied,
        "orphan_req": ~raw["req_id"].isin(req_ids),
        "duplicate": dupe_key.duplicated(keep=False),
    })

    out = raw.copy()
    out["flags"] = [sorted(c for c in flags.columns if row[c]) for _, row in flags.iterrows()]
    return out, {c: int(flags[c].sum()) for c in flags.columns}


def build(df, raw_flagged, defect_counts, quality, removed):
    hired = df[df["stage"] == "Hired"]
    offers = int((df["stage_rank"] >= STAGE_ORDER.index("Offer")).sum())

    rows = df[KEEP].copy()
    for col in ["applied_at", "last_activity_at"]:
        rows[col] = rows[col].dt.strftime("%Y-%m-%d")
    rows = rows.astype(object).where(pd.notna(rows), None)

    raw_out = raw_flagged[["candidate_id", "candidate_name", "email", "source", "req_id",
                           "stage", "recruiter", "applied_at", "last_activity_at", "flags"]]
    raw_out = raw_out.astype(object).where(pd.notna(raw_out), None)

    return {
        "generated_at": TODAY.strftime("%Y-%m-%d"),
        "counts": {
            "raw": int(len(raw_flagged)),
            "clean": int(len(df)),
            "removed": removed,
        },
        "defects": defect_counts,
        "summary": {
            "applications": int(len(df)),
            "open_requisitions": int(df[df["status"] == "Open"]["req_id"].nunique()),
            "median_time_to_hire": int(hired["time_to_hire_days"].median()),
            "offer_acceptance": round(100 * len(hired) / offers, 1) if offers else 0,
            "past_sla": int(df["past_sla"].sum()),
        },
        "stage_order": STAGE_ORDER,
        "quality": quality,
        "rows": rows.to_dict("records"),
        "raw_rows": raw_out.to_dict("records"),
    }


def run():
    df = pd.read_csv(PROCESSED / "applications_clean.csv",
                     parse_dates=["applied_at", "last_activity_at"])
    raw = pd.read_csv(RAW / "lever_applications.csv", dtype=str)
    reqs = pd.read_csv(RAW / "workday_requisitions.csv")
    quality = json.loads((PROCESSED / "quality_report.json").read_text())

    raw["source"] = raw["source"].astype(str).str.strip().str.title() \
        .replace({"Linkedin": "LinkedIn"})
    raw_flagged, defect_counts = flag_raw_defects(
        pd.read_csv(RAW / "lever_applications.csv", dtype=str), set(reqs["req_id"]))

    removed = [
        {"reason": "Applied in the future", "count": defect_counts["future_date"],
         "detail": "A timezone bug in an integration job produced dates that haven't happened yet."},
        {"reason": "Activity before applying", "count": defect_counts["backdated_activity"],
         "detail": "Records backfilled from an older system, where the timeline runs backwards."},
        {"reason": "Duplicate applications", "count": int(len(raw_flagged)) - defect_counts["future_date"]
         - defect_counts["backdated_activity"] - int(len(df)) - defect_counts["orphan_req"],
         "detail": "The same person applied to the same job more than once. Only the latest is kept."},
        {"reason": "Requisition no longer exists", "count": defect_counts["orphan_req"],
         "detail": "The job was deleted after people applied. These are saved separately, not discarded."},
    ]

    PUBLIC.mkdir(parents=True, exist_ok=True)
    data = build(df, raw_flagged, defect_counts, quality, removed)
    with open(PUBLIC / "data.json", "w") as f:
        # allow_nan=False so a stray NaN fails the build instead of producing
        # JSON the browser cannot parse.
        json.dump(data, f, separators=(",", ":"), allow_nan=False)

    size = (PUBLIC / "data.json").stat().st_size / 1024
    print(f"Dashboard data built: {data['counts']['raw']} raw -> {data['counts']['clean']} clean rows")
    print(f"  median time to hire : {data['summary']['median_time_to_hire']} days")
    print(f"  offer acceptance    : {data['summary']['offer_acceptance']}%")
    print(f"  file size           : {size:.0f} KB")
    print("Saved -> public/data.json")


if __name__ == "__main__":
    run()
