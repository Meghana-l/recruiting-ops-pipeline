"""
Creates the two source files this project works with.

There is no public recruiting dataset, so I generated one that behaves like a real
ATS export. The messiness is on purpose - inconsistent source names, a few missing
emails, two date formats, duplicate applications and a handful of requisition IDs
that don't exist in Workday. Those are the things that actually break recruiting
reports, so the pipeline needs something to clean.

Run: python src/generate_data.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
TODAY = date(2026, 10, 8)
random.seed(42)  # same data every run, so numbers in the README stay true

DEPARTMENTS = ["Engineering", "Deployment Strategy", "Security", "Product", "Recruiting Ops"]
TITLES = ["Software Engineer", "Forward Deployed Engineer", "Data Engineer",
          "Security Engineer", "Product Designer", "Recruiting Coordinator"]
STAGES = ["Applied", "Recruiter Screen", "Technical Screen", "Onsite", "Offer", "Hired"]
RECRUITERS = ["a.okafor", "m.strand", "j.rivera", "l.chen", "p.devi"]
REGIONS = ["AMER", "EMEA", "APAC"]

# How a recruiter might actually type each source into the ATS.
SOURCE_VARIANTS = {
    "LinkedIn":     ["LinkedIn", "linkedin", "LINKEDIN", " LinkedIn "],
    "Referral":     ["Referral", "referral", "Employee Referral"],
    "Careers Site": ["Careers Site", "careers site", "Website"],
    "University":   ["University", "university", "Campus"],
    "Agency":       ["Agency", "agency"],
    "Sourced":      ["Sourced", "sourced", "Outbound"],
}

FIRST = ["Amara", "Theo", "Priya", "Nils", "Rosa", "Ken", "Marta", "Yusuf", "Lena", "Dev",
         "Sana", "Nora", "Ravi", "Clara", "Mei", "Idris", "Elif", "Pablo", "Hana", "Noah",
         "Zoe", "Kofi", "Vera", "Arjun", "Lila", "Soren", "Ife", "Owen", "Tobias", "Jonas"]
LAST = ["Adeyemi", "Brandt", "Nair", "Holm", "Delgado", "Watanabe", "Okonkwo", "Keller",
        "Demir", "Vance", "Rao", "Fitzgerald", "Qureshi", "Abara", "Mensah", "Sorensen",
        "Pires", "Tan", "Novak", "Haddad", "Ferreira", "Kim", "Bauer", "Asante", "Silva"]

# Stage distribution - most people never get past the first screen.
STAGE_WEIGHTS = [0.42, 0.22, 0.15, 0.11, 0.03, 0.07]


def make_requisitions(n=26):
    rows = []
    for i in range(n):
        comp_min = random.choice([110000, 120000, 130000, 140000])
        rows.append({
            "req_id": f"REQ-{4100 + i}",
            "title": random.choice(TITLES),
            "department": random.choice(DEPARTMENTS),
            "level": random.choice(["IC2", "IC3", "IC4", "IC5"]),
            "region": random.choice(REGIONS),
            "hiring_manager": random.choice(["r.aldridge", "s.bello", "t.moreau", "k.ivanov"]),
            "opened_at": (TODAY - timedelta(days=random.randint(30, 210))).isoformat(),
            "status": "Open" if random.random() < 0.80 else "Closed",
            "comp_min": comp_min,
            "comp_max": comp_min + random.choice([30000, 40000, 50000]),
        })
    return rows


def make_applications(req_ids, n=430):
    rows = []
    for i in range(n):
        first, last = random.choice(FIRST), random.choice(LAST)
        stage = random.choices(STAGES, weights=STAGE_WEIGHTS)[0]
        applied = TODAY - timedelta(days=random.randint(2, 170))
        days_since_applied = (TODAY - applied).days

        # Hired candidates close out 21-60 days after applying. Everyone else was
        # touched recently, with a long tail of candidates nobody has followed up on.
        if stage == "Hired":
            last_activity = min(TODAY, applied + timedelta(days=random.randint(21, 60)))
        else:
            gap = random.randint(0, min(8, days_since_applied)) if random.random() < 0.85 \
                else random.randint(min(9, days_since_applied), min(55, days_since_applied))
            last_activity = TODAY - timedelta(days=gap)

        clean_source = random.choice(list(SOURCE_VARIANTS))
        rows.append({
            "candidate_id": f"cand_{90000 + i}",
            "candidate_name": f"{first} {last}",
            "email": f"{first}.{last}@{random.choice(['mailbox.com', 'postbox.io', 'gridmail.com'])}".lower(),
            "source": random.choice(SOURCE_VARIANTS[clean_source]),  # messy on purpose
            "req_id": random.choice(req_ids),
            "stage": stage,
            "recruiter": random.choice(RECRUITERS),
            # Lever returns ISO from the API but MM/DD/YYYY from the recruiter UI.
            "applied_at": applied.strftime("%m/%d/%Y") if random.random() < 0.2 else applied.isoformat(),
            "last_activity_at": last_activity.isoformat(),
            "offer_amount": random.choice([130000, 140000, 150000, 160000]) if stage in ("Offer", "Hired") else "",
        })
    return rows


def add_known_defects(apps, req_ids):
    """The specific problems the pipeline is built to catch."""
    # 1. Missing emails - the application form doesn't enforce it.
    for row in random.sample(apps, 10):
        row["email"] = ""

    # 2. Reapplications. Same person, same req, submitted twice.
    for row in random.sample(apps, 14):
        duplicate = dict(row)
        duplicate["candidate_id"] = f"cand_dup_{random.randint(1000, 9999)}"
        apps.append(duplicate)

    # 3. Requisitions deleted in Workday after people had already applied.
    for row in random.sample(apps, 9):
        row["req_id"] = f"REQ-{random.randint(7700, 7799)}"

    # 4. Timezone bug in an integration job produced future dates.
    for row in random.sample(apps, 6):
        row["applied_at"] = (TODAY + timedelta(days=random.randint(5, 40))).isoformat()

    # 5. Records backfilled from the previous ATS, where activity predates the application.
    for row in random.sample(apps, 7):
        applied = date.fromisoformat(row["applied_at"]) if "-" in row["applied_at"] \
            else TODAY - timedelta(days=30)
        row["last_activity_at"] = (applied - timedelta(days=random.randint(5, 30))).isoformat()

    random.shuffle(apps)
    return apps


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {len(rows):>3} rows -> {path.relative_to(path.parents[2])}")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    print("Generating source data")

    reqs = make_requisitions()
    apps = add_known_defects(make_applications([r["req_id"] for r in reqs]), [r["req_id"] for r in reqs])

    write_csv(RAW / "workday_requisitions.csv", reqs)
    write_csv(RAW / "lever_applications.csv", apps)


if __name__ == "__main__":
    main()
