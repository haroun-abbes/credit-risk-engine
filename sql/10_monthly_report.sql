-- =============================================================================
-- Phase 2 — Reporting mensuel
-- Attention à l'interprétation : le portefeuille est reconstitué à partir de 4
-- cohortes. Quand une nouvelle cohorte entre (2012, 2017), sa production neuve
-- fait mécaniquement baisser les taux de retard. On compare donc les mois
-- proches entre eux, et les cohortes entre elles via les vintages.
-- =============================================================================

-- 1. Série mensuelle du portefeuille --------------------------------------------
CREATE OR REPLACE VIEW v_monthly_portfolio AS
WITH active AS (
    SELECT period,
           count(*)                                                AS n_active,
           sum(current_upb)                                        AS upb,
           count(*) FILTER (WHERE state <> 'À jour')               AS n_dq30,
           count(*) FILTER (WHERE state IN ('60-89 jours', '90+ jours')) AS n_dq60,
           count(*) FILTER (WHERE state = '90+ jours')             AS n_dq90
    FROM loan_month
    WHERE state IN ('À jour', '30-59 jours', '60-89 jours', '90+ jours')
      AND current_upb > 0
    GROUP BY period
),
new_defaults AS (
    SELECT default_period AS period, count(*) AS n_new_defaults
    FROM loan_default WHERE ever_default GROUP BY 1
)
SELECT
    a.period,
    a.n_active,
    round(a.upb / 1e6, 1)                          AS upb_musd,
    a.n_dq30::DOUBLE / a.n_active                  AS dq30_rate,
    a.n_dq60::DOUBLE / a.n_active                  AS dq60_rate,
    a.n_dq90::DOUBLE / a.n_active                  AS dq90_rate,
    coalesce(d.n_new_defaults, 0)                  AS n_new_defaults,
    e.unemployment_rate,
    e.mortgage_rate_30y
FROM active AS a
LEFT JOIN new_defaults AS d USING (period)
LEFT JOIN economic_indicators AS e USING (period)
ORDER BY a.period;

-- 2. Tableau de bord du dernier mois : M, M-1 et M-12 ----------------------------
CREATE OR REPLACE VIEW v_monthly_kpis AS
WITH last AS (SELECT max(period) AS p FROM v_monthly_portfolio)
SELECT
    CASE m.period
        WHEN l.p THEN 'Mois M'
        WHEN CAST(l.p - INTERVAL 1 MONTH AS DATE) THEN 'Mois M-1'
        ELSE 'Mois M-12'
    END                              AS reference,
    m.period, m.n_active, m.upb_musd, m.dq30_rate, m.dq90_rate, m.n_new_defaults
FROM v_monthly_portfolio AS m, last AS l
WHERE m.period IN (l.p, CAST(l.p - INTERVAL 1 MONTH AS DATE), CAST(l.p - INTERVAL 12 MONTH AS DATE))
ORDER BY m.period DESC;

-- 3. Segments les plus risqués à la date d'arrêté --------------------------------
--    Taux de retard de 30 jours ou plus, segments d'au moins 300 prêts actifs,
--    avec intervalle de confiance : on ne classe pas des taux calculés sur 12 prêts.
CREATE OR REPLACE VIEW v_risky_segments AS
WITH long AS (
    SELECT 'État' AS dimension, property_state AS segment, count(*) AS n,
           count(*) FILTER (WHERE state <> 'À jour') AS k
    FROM v_snapshot_active GROUP BY property_state
    UNION ALL
    SELECT 'Score FICO', fico_band, count(*), count(*) FILTER (WHERE state <> 'À jour')
    FROM v_snapshot_active GROUP BY fico_band
    UNION ALL
    SELECT 'LTV à l''octroi', ltv_band, count(*), count(*) FILTER (WHERE state <> 'À jour')
    FROM v_snapshot_active GROUP BY ltv_band
    UNION ALL
    SELECT 'Cohorte', CAST(vintage_year AS VARCHAR), count(*), count(*) FILTER (WHERE state <> 'À jour')
    FROM v_snapshot_active GROUP BY vintage_year
),
overall AS (
    SELECT count(*) FILTER (WHERE state <> 'À jour')::DOUBLE / count(*) AS rate_all
    FROM v_snapshot_active
)
SELECT
    l.dimension, l.segment,
    l.n                                   AS n_active,
    l.k                                   AS n_dq30,
    l.k::DOUBLE / l.n                     AS dq30_rate,
    wilson_low(l.k, l.n)                  AS ci_low,
    wilson_high(l.k, l.n)                 AS ci_high,
    (l.k::DOUBLE / l.n) / nullif(o.rate_all, 0) AS vs_portfolio
FROM long AS l, overall AS o
WHERE l.n >= 300
ORDER BY dq30_rate DESC
LIMIT 10;
