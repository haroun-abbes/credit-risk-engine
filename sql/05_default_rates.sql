-- =============================================================================
-- Phase 2 — Taux de défaut et sévérité des pertes
-- Toutes les vues donnent le numérateur, le dénominateur et le taux, plus un
-- intervalle de confiance à 95 % (Wilson) : un taux sans effectif ne veut rien dire.
-- =============================================================================

-- Segments de risque mesurés à l'octroi ----------------------------------------
CREATE OR REPLACE VIEW v_loan_segments AS
SELECT
    l.loan_id,
    l.vintage_year,
    coalesce(l.property_state, 'Inconnu')  AS property_state,
    coalesce(l.loan_purpose, 'Inconnu')    AS loan_purpose,
    coalesce(l.occupancy, 'Inconnu')       AS occupancy,
    coalesce(l.channel, 'Inconnu')         AS channel,
    CASE
        WHEN b.fico_score IS NULL THEN 'Inconnu'
        WHEN b.fico_score < 620 THEN '< 620'
        WHEN b.fico_score < 660 THEN '620-659'
        WHEN b.fico_score < 700 THEN '660-699'
        WHEN b.fico_score < 740 THEN '700-739'
        WHEN b.fico_score < 780 THEN '740-779'
        ELSE '780 et plus'
    END AS fico_band,
    CASE
        WHEN b.fico_score IS NULL THEN 9
        WHEN b.fico_score < 620 THEN 1 WHEN b.fico_score < 660 THEN 2
        WHEN b.fico_score < 700 THEN 3 WHEN b.fico_score < 740 THEN 4
        WHEN b.fico_score < 780 THEN 5 ELSE 6
    END AS fico_order,
    CASE
        WHEN l.ltv_pct IS NULL THEN 'Inconnu'
        WHEN l.ltv_pct <= 60 THEN '60 % ou moins'
        WHEN l.ltv_pct <= 80 THEN '61-80 %'
        WHEN l.ltv_pct <= 90 THEN '81-90 %'
        WHEN l.ltv_pct <= 95 THEN '91-95 %'
        ELSE 'Plus de 95 %'
    END AS ltv_band,
    CASE
        WHEN l.ltv_pct IS NULL THEN 9
        WHEN l.ltv_pct <= 60 THEN 1 WHEN l.ltv_pct <= 80 THEN 2
        WHEN l.ltv_pct <= 90 THEN 3 WHEN l.ltv_pct <= 95 THEN 4 ELSE 5
    END AS ltv_order,
    CASE
        WHEN l.cltv_pct IS NULL THEN 'Inconnu'
        WHEN l.cltv_pct <= 60 THEN '60 % ou moins'
        WHEN l.cltv_pct <= 80 THEN '61-80 %'
        WHEN l.cltv_pct <= 90 THEN '81-90 %'
        WHEN l.cltv_pct <= 95 THEN '91-95 %'
        ELSE 'Plus de 95 %'
    END AS cltv_band,
    CASE
        WHEN l.cltv_pct IS NULL THEN 9
        WHEN l.cltv_pct <= 60 THEN 1 WHEN l.cltv_pct <= 80 THEN 2
        WHEN l.cltv_pct <= 90 THEN 3 WHEN l.cltv_pct <= 95 THEN 4 ELSE 5
    END AS cltv_order,
    CASE
        WHEN b.dti_pct IS NULL THEN 'Inconnu'
        WHEN b.dti_pct < 20 THEN 'Moins de 20 %'
        WHEN b.dti_pct < 30 THEN '20-29 %'
        WHEN b.dti_pct < 40 THEN '30-39 %'
        WHEN b.dti_pct <= 45 THEN '40-45 %'
        ELSE 'Plus de 45 %'
    END AS dti_band,
    CASE
        WHEN b.dti_pct IS NULL THEN 9
        WHEN b.dti_pct < 20 THEN 1 WHEN b.dti_pct < 30 THEN 2
        WHEN b.dti_pct < 40 THEN 3 WHEN b.dti_pct <= 45 THEN 4 ELSE 5
    END AS dti_order
FROM loans AS l
JOIN borrowers AS b USING (borrower_id);

-- 1. Taux de défaut par cohorte -----------------------------------------------
CREATE OR REPLACE VIEW v_default_by_vintage AS
WITH agg AS (
    SELECT
        coalesce(CAST(d.vintage_year AS VARCHAR), 'Toutes')            AS cohorte,
        count(*)                                                       AS n_loans,
        count(*) FILTER (WHERE d.ever_default)                         AS n_defaults,
        count(*) FILTER (WHERE d.zero_balance_code IN ('02', '03', '09', '15')) AS n_loss_exits,
        round(sum(l.original_upb) / 1e6, 1)                            AS original_upb_musd
    FROM loan_default AS d
    JOIN loans AS l USING (loan_id)
    GROUP BY GROUPING SETS ((d.vintage_year), ())
)
SELECT
    cohorte, n_loans, n_defaults,
    n_defaults::DOUBLE / n_loans                 AS default_rate,
    wilson_low(n_defaults, n_loans)              AS ci_low,
    wilson_high(n_defaults, n_loans)             AS ci_high,
    n_loss_exits,
    n_loss_exits::DOUBLE / n_loans               AS loss_exit_rate,
    original_upb_musd
FROM agg
ORDER BY cohorte = 'Toutes', cohorte;

-- 2. Taux de défaut par segment (format long : une ligne par dimension,
--    segment et cohorte, plus une ligne « Toutes » cohortes confondues) -------
CREATE OR REPLACE VIEW v_default_by_segment AS
WITH base AS (
    SELECT s.*, d.ever_default
    FROM v_loan_segments AS s
    JOIN loan_default AS d USING (loan_id)
),
long AS (
    SELECT 'Score FICO' AS dimension, fico_band AS segment, min(fico_order) AS segment_order,
           vintage_year, count(*) AS n_loans, count(*) FILTER (WHERE ever_default) AS n_defaults
    FROM base GROUP BY GROUPING SETS ((fico_band, vintage_year), (fico_band))
    UNION ALL
    SELECT 'LTV', ltv_band, min(ltv_order), vintage_year, count(*), count(*) FILTER (WHERE ever_default)
    FROM base GROUP BY GROUPING SETS ((ltv_band, vintage_year), (ltv_band))
    UNION ALL
    SELECT 'CLTV', cltv_band, min(cltv_order), vintage_year, count(*), count(*) FILTER (WHERE ever_default)
    FROM base GROUP BY GROUPING SETS ((cltv_band, vintage_year), (cltv_band))
    UNION ALL
    SELECT 'DTI', dti_band, min(dti_order), vintage_year, count(*), count(*) FILTER (WHERE ever_default)
    FROM base GROUP BY GROUPING SETS ((dti_band, vintage_year), (dti_band))
    UNION ALL
    SELECT 'Objet du prêt', loan_purpose, 0, vintage_year, count(*), count(*) FILTER (WHERE ever_default)
    FROM base GROUP BY GROUPING SETS ((loan_purpose, vintage_year), (loan_purpose))
    UNION ALL
    SELECT 'Occupation', occupancy, 0, vintage_year, count(*), count(*) FILTER (WHERE ever_default)
    FROM base GROUP BY GROUPING SETS ((occupancy, vintage_year), (occupancy))
    UNION ALL
    SELECT 'Canal', channel, 0, vintage_year, count(*), count(*) FILTER (WHERE ever_default)
    FROM base GROUP BY GROUPING SETS ((channel, vintage_year), (channel))
    UNION ALL
    SELECT 'État', property_state, 0, vintage_year, count(*), count(*) FILTER (WHERE ever_default)
    FROM base GROUP BY GROUPING SETS ((property_state, vintage_year), (property_state))
)
SELECT
    dimension,
    segment,
    segment_order,
    coalesce(CAST(vintage_year AS VARCHAR), 'Toutes')   AS cohorte,
    n_loans,
    n_defaults,
    n_defaults::DOUBLE / n_loans                        AS default_rate,
    wilson_low(n_defaults, n_loans)                     AS ci_low,
    wilson_high(n_defaults, n_loans)                    AS ci_high,
    n_loans >= 300                                      AS enough_loans
FROM long;

-- 3. Sévérité des pertes par cohorte -------------------------------------------
-- Sévérité observée = perte réalisée / encours au moment de la sortie.
-- Seuls les prêts dont la perte est publiée entrent dans le calcul (Freddie Mac
-- ne publie pas la perte des sorties des 3 derniers mois).
CREATE OR REPLACE VIEW v_loss_severity AS
WITH agg AS (
    SELECT
        coalesce(CAST(vintage_year AS VARCHAR), 'Toutes')                             AS cohorte,
        count(*) FILTER (WHERE zero_balance_code IN ('02', '03', '09', '15'))         AS n_loss_exits,
        count(*) FILTER (WHERE zero_balance_code IN ('02', '03', '09', '15')
                           AND actual_loss IS NOT NULL AND removal_upb > 0)           AS n_with_loss,
        sum(removal_upb) FILTER (WHERE zero_balance_code IN ('02', '03', '09', '15')
                           AND actual_loss IS NOT NULL AND removal_upb > 0)           AS ead,
        sum(actual_loss) FILTER (WHERE zero_balance_code IN ('02', '03', '09', '15')
                           AND actual_loss IS NOT NULL AND removal_upb > 0)           AS loss
    FROM loan_default
    GROUP BY GROUPING SETS ((vintage_year), ())
)
SELECT
    cohorte,
    n_loss_exits,
    n_with_loss,
    round(ead / 1e6, 1)                         AS ead_musd,
    round(loss / 1e6, 1)                        AS loss_musd,
    loss / nullif(ead, 0)                       AS severity,
    round(loss / nullif(n_with_loss, 0), 0)     AS avg_loss_usd
FROM agg
ORDER BY cohorte = 'Toutes', cohorte;
