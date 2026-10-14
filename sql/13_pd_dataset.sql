-- =============================================================================
-- Phase 3 — Jeu de données du modèle de PD
-- Une ligne = un prêt sain observé à une date d'observation, avec :
--   * la cible     : default_12m (fait-il défaut dans les 12 mois ?) ;
--   * les variables connues CE JOUR-LÀ (aucune information du futur).
--
-- Dates d'observation : chaque mois de janvier (un instantané par an et par
-- prêt, pour limiter les répétitions d'un même prêt), plus le dernier mois
-- disponible pour noter le portefeuille actuel.
-- =============================================================================

CREATE OR REPLACE TABLE pd_dataset AS
WITH econ AS (
    SELECT
        period,
        unemployment_rate,
        mortgage_rate_30y,
        unemployment_rate - lag(unemployment_rate, 12) OVER (ORDER BY period)   AS unemp_chg_12m,
        house_price_index / lag(house_price_index, 12) OVER (ORDER BY period) - 1 AS hpi_yoy
    FROM economic_indicators
),
last_month AS (
    SELECT max(period) AS last_period FROM loan_month_pd
)
SELECT
    p.loan_id,
    p.period,
    p.vintage_year,
    p.default_12m,
    p.window_complete,
    p.period = (SELECT last_period FROM last_month)            AS is_last_period,

    -- Caractéristiques à l'octroi -------------------------------------------
    b.fico_score,
    l.cltv_pct,
    b.dti_pct,
    -- SATO (« spread at origination ») : taux du prêt moins taux moyen du
    -- marché au moment de l'octroi. Un prêteur facture plus cher un emprunteur
    -- qu'il juge risqué : c'est une information de risque que le FICO ne voit pas.
    l.original_rate - e0.mortgage_rate_30y                      AS sato,
    coalesce(l.loan_purpose, 'Inconnu')                         AS loan_purpose,
    coalesce(l.occupancy, 'Inconnu')                            AS occupancy,
    coalesce(l.channel, 'Inconnu')                              AS channel,
    -- Canal regroupé : le codage « courtier » / « correspondant » n'est utilisé
    -- de façon détaillée que sur les prêts récents. Le garder distinct ferait du
    -- canal un marqueur d'époque. On compare donc agence et intermédiaires.
    CASE l.channel WHEN 'Retail' THEN 'Agence (retail)'
                   WHEN 'Broker' THEN 'Intermédiaire'
                   WHEN 'Correspondent' THEN 'Intermédiaire'
                   WHEN 'Third party (unspecified)' THEN 'Intermédiaire'
                   ELSE 'Inconnu' END                           AS channel_group,
    CASE WHEN b.n_borrowers = 1 THEN '1 emprunteur'
         WHEN b.n_borrowers >= 2 THEN '2 emprunteurs ou plus'
         ELSE 'Inconnu' END                                     AS n_borrowers,

    -- Comportement observé à la date d'observation ---------------------------
    p.state                                                     AS dq_state,
    CASE WHEN coalesce(m.max_dq_prev12, 0) = 0 THEN 'Aucun retard'
         WHEN m.max_dq_prev12 = 1 THEN '30 jours max'
         ELSE '60 jours ou plus' END                            AS dq_history_12m,
    m.age,
    CASE WHEN p.s_modified THEN 'Oui' ELSE 'Non' END            AS modified,
    CASE WHEN p.s_assistance THEN 'Oui' ELSE 'Non' END          AS assistance_plan,

    -- Conjoncture à la date d'observation -------------------------------------
    e.unemployment_rate,
    e.unemp_chg_12m,
    e.hpi_yoy
FROM loan_month_pd AS p
JOIN loan_month AS m USING (loan_id, period)
JOIN loans AS l USING (loan_id)
JOIN borrowers AS b ON b.borrower_id = l.borrower_id
JOIN loan_age_anchor AS a USING (loan_id)
LEFT JOIN econ AS e  ON e.period = p.period
LEFT JOIN econ AS e0 ON e0.period = a.quarter_start
WHERE month(p.period) = 1
   OR p.period = (SELECT last_period FROM last_month);
