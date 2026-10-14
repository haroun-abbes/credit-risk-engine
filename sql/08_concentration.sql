-- =============================================================================
-- Phase 2 — Encours et concentration du portefeuille
-- Photographie au dernier mois disponible (« date d'arrêté »).
-- =============================================================================

-- Prêts actifs à la date d'arrêté, avec leurs segments --------------------------
CREATE OR REPLACE VIEW v_snapshot_active AS
SELECT
    m.loan_id, m.vintage_year, m.period AS snapshot_date, m.state, m.current_upb,
    s.property_state, s.fico_band, s.fico_order, s.ltv_band, s.ltv_order
FROM loan_month AS m
JOIN v_loan_segments AS s USING (loan_id)
WHERE m.period = (SELECT max(period) FROM loan_month)
  AND m.state IN ('À jour', '30-59 jours', '60-89 jours', '90+ jours')
  AND m.current_upb > 0;

-- Chiffres clés du portefeuille actif -------------------------------------------
CREATE OR REPLACE VIEW v_portfolio_snapshot AS
SELECT
    max(snapshot_date)                                                         AS snapshot_date,
    count(*)                                                                   AS n_active,
    round(sum(current_upb) / 1e6, 1)                                           AS upb_musd,
    round(avg(current_upb), 0)                                                 AS avg_upb_usd,
    count(*) FILTER (WHERE state <> 'À jour')::DOUBLE / count(*)               AS dq30_rate,
    count(*) FILTER (WHERE state = '90+ jours')::DOUBLE / count(*)             AS dq90_rate,
    sum(current_upb) FILTER (WHERE state <> 'À jour') / sum(current_upb)       AS dq30_upb_share
FROM v_snapshot_active;

-- Encours par État, du plus gros au plus petit -----------------------------------
CREATE OR REPLACE VIEW v_concentration_state AS
WITH by_state AS (
    SELECT property_state, count(*) AS n_loans, sum(current_upb) AS upb
    FROM v_snapshot_active
    GROUP BY property_state
)
SELECT
    row_number() OVER (ORDER BY upb DESC)                                        AS rank,
    property_state,
    n_loans,
    round(upb / 1e6, 1)                                                          AS upb_musd,
    upb / sum(upb) OVER ()                                                       AS share,
    sum(upb) OVER (ORDER BY upb DESC ROWS UNBOUNDED PRECEDING) / sum(upb) OVER () AS cum_share
FROM by_state
ORDER BY rank;

-- Indicateurs de concentration : part du top 5 / top 10 et indice HHI -----------
--   HHI = somme des parts au carré x 10 000 (0 = très dispersé, 10 000 = un seul État)
--   « Nombre équivalent d'États » = 10 000 / HHI : le portefeuille est aussi
--   concentré que s'il était réparti à parts égales sur ce nombre d'États.
CREATE OR REPLACE VIEW v_concentration_summary AS
WITH current_book AS (
    SELECT 'Encours actif (arrêté)' AS perimetre, property_state, sum(current_upb) AS amount
    FROM v_snapshot_active GROUP BY property_state
),
production AS (
    SELECT 'Production ' || CAST(l.vintage_year AS VARCHAR) AS perimetre,
           coalesce(l.property_state, 'Inconnu') AS property_state, sum(l.original_upb) AS amount
    FROM loans AS l GROUP BY ALL
),
shares AS (
    SELECT perimetre, property_state,
           amount / sum(amount) OVER (PARTITION BY perimetre) AS share,
           row_number() OVER (PARTITION BY perimetre ORDER BY amount DESC) AS rank
    FROM (SELECT * FROM current_book UNION ALL SELECT * FROM production)
)
SELECT
    perimetre,
    count(*)                                         AS n_states,
    sum(share) FILTER (WHERE rank <= 5)              AS top5_share,
    sum(share) FILTER (WHERE rank <= 10)             AS top10_share,
    round(10000 * sum(share * share), 0)             AS hhi,
    round(1 / sum(share * share), 1)                 AS equivalent_states
FROM shares
GROUP BY perimetre
ORDER BY perimetre;
