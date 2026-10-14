-- =============================================================================
-- Phase 4 — Portefeuille à la date d'arrêté, prêt par prêt
-- Tous les prêts actifs (y compris ceux à 90 jours ou plus, et ceux qui ont
-- déjà fait défaut puis se sont régularisés), avec les variables du modèle de
-- PD calculées comme dans sql/13_pd_dataset.sql.
--
-- Période probatoire (IFRS 9 / orientations EBA) : un prêt sorti du défaut, ou
-- restructuré, reste en Stage 2 pendant 24 mois. Au-delà, il redevient un prêt
-- comme les autres et seul le critère de dégradation (SICR) s'applique.
-- =============================================================================

CREATE OR REPLACE TABLE ecl_snapshot_input AS
WITH snap AS (SELECT max(period) AS s FROM loan_month),
history AS (
    SELECT loan_id,
           max(period) FILTER (WHERE state = '90+ jours')      AS last_90_period,
           max(period) FILTER (WHERE modification_flag = 'Y') AS last_modification
    FROM loan_month
    GROUP BY loan_id
)
SELECT
    m.loan_id,
    m.period                                                    AS snapshot_date,
    m.vintage_year,
    m.state,
    m.current_upb,
    lp.current_rate,
    lp.remaining_months,
    coalesce(m.state <> '90+ jours'
             AND h.last_90_period >= CAST(snap.s - INTERVAL 24 MONTH AS DATE), FALSE) AS previously_defaulted,
    coalesce(h.last_modification >= CAST(snap.s - INTERVAL 24 MONTH AS DATE), FALSE)  AS recently_modified,
    seg.cltv_band,
    -- variables du modèle de PD (mêmes définitions que sql/13_pd_dataset.sql)
    b.fico_score,
    l.cltv_pct,
    b.dti_pct,
    l.original_rate - e0.mortgage_rate_30y                      AS sato,
    coalesce(l.loan_purpose, 'Inconnu')                         AS loan_purpose,
    coalesce(l.occupancy, 'Inconnu')                            AS occupancy,
    CASE l.channel WHEN 'Retail' THEN 'Agence (retail)'
                   WHEN 'Broker' THEN 'Intermédiaire'
                   WHEN 'Correspondent' THEN 'Intermédiaire'
                   WHEN 'Third party (unspecified)' THEN 'Intermédiaire'
                   ELSE 'Inconnu' END                           AS channel_group,
    CASE WHEN b.n_borrowers = 1 THEN '1 emprunteur'
         WHEN b.n_borrowers >= 2 THEN '2 emprunteurs ou plus'
         ELSE 'Inconnu' END                                     AS n_borrowers,
    m.state                                                     AS dq_state,
    CASE WHEN coalesce(m.max_dq_prev12, 0) = 0 THEN 'Aucun retard'
         WHEN m.max_dq_prev12 = 1 THEN '30 jours max'
         ELSE '60 jours ou plus' END                            AS dq_history_12m,
    m.age,
    CASE WHEN coalesce(m.modification_flag IN ('Y', 'P'), FALSE) THEN 'Oui' ELSE 'Non' END        AS modified,
    CASE WHEN coalesce(m.borrower_assistance IN ('F', 'R', 'T'), FALSE) THEN 'Oui' ELSE 'Non' END AS assistance_plan
FROM loan_month AS m
JOIN snap ON m.period = snap.s
JOIN loan_performance AS lp USING (loan_id, period)
JOIN loans AS l USING (loan_id)
JOIN borrowers AS b ON b.borrower_id = l.borrower_id
JOIN loan_age_anchor AS a USING (loan_id)
JOIN history AS h USING (loan_id)
JOIN v_loan_segments AS seg USING (loan_id)
LEFT JOIN economic_indicators AS e0 ON e0.period = a.quarter_start
WHERE m.state IN ('À jour', '30-59 jours', '60-89 jours', '90+ jours')
  AND m.current_upb > 0;
