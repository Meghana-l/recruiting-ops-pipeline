-- Joins each application to its requisition and derives the metrics every
-- report needs.
--
-- These are calculated once, here, rather than in the dashboard. That is what
-- stops two reports from disagreeing about the same number.

CREATE OR REPLACE VIEW fact_applications AS

WITH stage_targets(stage, stage_sla_days) AS (
    VALUES ('Applied', 4),
           ('Recruiter Screen', 5),
           ('Technical Screen', 7),
           ('Onsite', 9),
           ('Offer', 5)
),

stage_ranks(stage, stage_rank) AS (
    VALUES ('Applied', 0),
           ('Recruiter Screen', 1),
           ('Technical Screen', 2),
           ('Onsite', 3),
           ('Offer', 4),
           ('Hired', 5)
)

SELECT
    a.candidate_id,
    a.candidate_name,
    a.email,
    a.source,
    a.req_id,
    a.stage,
    a.recruiter,
    a.applied_at,
    a.last_activity_at,
    a.offer_amount,

    r.title,
    r.department,
    r.level,
    r.region,
    r.hiring_manager,
    r.status,
    r.comp_min,
    r.comp_max,

    DATE_DIFF('day', a.last_activity_at, DATE '2026-10-08') AS days_in_stage,
    t.stage_sla_days,

    -- Flagged once nobody has touched the candidate in twice the stage target.
    -- Hired candidates have no target, so they are never past it.
    COALESCE(
        DATE_DIFF('day', a.last_activity_at, DATE '2026-10-08')
            > (t.stage_sla_days * 2),
        FALSE
    )                                                       AS past_sla,

    CASE WHEN a.stage = 'Hired'
         THEN DATE_DIFF('day', a.applied_at, a.last_activity_at)
    END                                                     AS time_to_hire_days,

    k.stage_rank

-- An inner join drops applications whose requisition no longer exists in
-- Workday. Those rows are reported separately rather than silently lost.
FROM clean_applications a
JOIN raw_requisitions r USING (req_id)
JOIN stage_ranks      k ON k.stage = a.stage
LEFT JOIN stage_targets t ON t.stage = a.stage;
