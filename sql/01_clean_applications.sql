-- Cleans the raw Lever export.
--
-- Three problems are handled here: source names that were typed inconsistently,
-- two different date formats in the same column, and candidates who applied to
-- the same requisition more than once.

CREATE OR REPLACE VIEW clean_applications AS

WITH typed AS (
    SELECT
        candidate_id,
        candidate_name,
        NULLIF(TRIM(email), '')                     AS email,

        -- Every spelling of a channel folds back to one name, so that
        -- attribution reporting actually adds up.
        CASE LOWER(TRIM(source))
            WHEN 'linkedin'          THEN 'LinkedIn'
            WHEN 'referral'          THEN 'Referral'
            WHEN 'employee referral' THEN 'Referral'
            WHEN 'careers site'      THEN 'Careers Site'
            WHEN 'website'           THEN 'Careers Site'
            WHEN 'university'        THEN 'University'
            WHEN 'campus'            THEN 'University'
            WHEN 'agency'            THEN 'Agency'
            WHEN 'sourced'           THEN 'Sourced'
            WHEN 'outbound'          THEN 'Sourced'
            ELSE 'Unknown'
        END                                          AS source,

        req_id,
        stage,
        recruiter,

        -- Lever returns ISO dates from the API and MM/DD/YYYY from the
        -- recruiter UI. Both land in the same column.
        COALESCE(
            TRY_STRPTIME(applied_at, '%Y-%m-%d'),
            TRY_STRPTIME(applied_at, '%m/%d/%Y')
        )::DATE                                      AS applied_at,
        COALESCE(
            TRY_STRPTIME(last_activity_at, '%Y-%m-%d'),
            TRY_STRPTIME(last_activity_at, '%m/%d/%Y')
        )::DATE                                      AS last_activity_at,

        TRY_CAST(NULLIF(offer_amount, '') AS INTEGER) AS offer_amount
    FROM raw_applications
),

valid AS (
    SELECT *
    FROM typed
    WHERE applied_at IS NOT NULL
      AND applied_at <= DATE '2026-10-08'        -- no applying in the future
      AND last_activity_at >= applied_at          -- no activity before applying
)

-- A reapplication is the same person on the same requisition. Keep the most
-- recent one. Rows with no email fall back to candidate_id so that two
-- different people with missing emails aren't collapsed into one.
SELECT * FROM valid
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY COALESCE(email, candidate_id), req_id
    ORDER BY applied_at DESC
) = 1;
