-- =============================================================================
-- Phase 2 — Signaux d'alerte précoce
-- Question métier : quels signes, visibles AVANT le défaut, annoncent un risque ?
-- Chaque signal est d'abord « backtesté » sur l'historique : on mesure le taux
-- de défaut à 12 mois des prêts qui le présentaient. Un signal n'est retenu que
-- s'il sépare vraiment les prêts risqués des autres.
-- =============================================================================

-- 1. Taux de défaut à 12 mois selon l'état de retard du mois --------------------
CREATE OR REPLACE VIEW v_pd12_by_state AS
SELECT
    state,
    count(*)                                         AS n_loan_months,
    count(*) FILTER (WHERE default_12m)              AS n_default_12m,
    count(*) FILTER (WHERE default_12m)::DOUBLE / count(*) AS pd12,
    wilson_low(count(*) FILTER (WHERE default_12m), count(*))  AS ci_low,
    wilson_high(count(*) FILTER (WHERE default_12m), count(*)) AS ci_high
FROM loan_month_pd
WHERE window_complete
GROUP BY state
ORDER BY CASE state WHEN 'À jour' THEN 1 WHEN '30-59 jours' THEN 2 ELSE 3 END;

-- 2. Backtest des signaux ---------------------------------------------------------
--    lift = taux de défaut avec le signal / taux des prêts à jour sans aucun signal
CREATE OR REPLACE VIEW v_signal_backtest AS
WITH hist AS (
    SELECT * FROM loan_month_pd WHERE window_complete
),
baseline AS (
    SELECT count(*) FILTER (WHERE default_12m)::DOUBLE / count(*) AS pd12_base
    FROM hist
    WHERE state = 'À jour'
      AND NOT (s_recent_dq OR s_negative_equity OR s_modified OR s_assistance)
),
signals AS (
    SELECT 1 AS ord, 'Aucun signal (prêt à jour)' AS signal,
           count(*) AS n, count(*) FILTER (WHERE default_12m) AS k
    FROM hist WHERE state = 'À jour' AND NOT (s_recent_dq OR s_negative_equity OR s_modified OR s_assistance)
    UNION ALL
    SELECT 2, 'Retard récent, aujourd''hui régularisé', count(*), count(*) FILTER (WHERE default_12m)
    FROM hist WHERE s_recent_dq
    UNION ALL
    SELECT 3, 'Bien valant moins que la dette (LTV estimée > 100 %)', count(*), count(*) FILTER (WHERE default_12m)
    FROM hist WHERE s_negative_equity
    UNION ALL
    SELECT 4, 'Prêt déjà modifié', count(*), count(*) FILTER (WHERE default_12m)
    FROM hist WHERE s_modified
    UNION ALL
    SELECT 5, 'Plan d''aide en cours (moratoire, échéancier)', count(*), count(*) FILTER (WHERE default_12m)
    FROM hist WHERE s_assistance
    UNION ALL
    SELECT 6, 'Retard de 30 à 59 jours', count(*), count(*) FILTER (WHERE default_12m)
    FROM hist WHERE s_dq30
    UNION ALL
    SELECT 7, 'Retard de 60 à 89 jours', count(*), count(*) FILTER (WHERE default_12m)
    FROM hist WHERE s_dq60
)
SELECT
    s.ord, s.signal,
    s.n                                   AS n_loan_months,
    s.k                                   AS n_default_12m,
    s.k::DOUBLE / nullif(s.n, 0)          AS pd12,
    wilson_low(s.k, s.n)                  AS ci_low,
    wilson_high(s.k, s.n)                 AS ci_high,
    (s.k::DOUBLE / nullif(s.n, 0)) / nullif(b.pd12_base, 0) AS lift
FROM signals AS s, baseline AS b
ORDER BY s.ord;

-- 3. Liste de surveillance à la date d'arrêté -------------------------------------
CREATE OR REPLACE VIEW v_watchlist AS
WITH snap AS (
    SELECT * FROM loan_month_pd WHERE period = (SELECT max(period) FROM loan_month_pd)
),
flags AS (
    SELECT 2 AS ord, 'Retard récent, aujourd''hui régularisé' AS signal, s_recent_dq AS f, current_upb FROM snap
    UNION ALL SELECT 3, 'Bien valant moins que la dette (LTV estimée > 100 %)', s_negative_equity, current_upb FROM snap
    UNION ALL SELECT 4, 'Prêt déjà modifié', s_modified, current_upb FROM snap
    UNION ALL SELECT 5, 'Plan d''aide en cours (moratoire, échéancier)', s_assistance, current_upb FROM snap
    UNION ALL SELECT 6, 'Retard de 30 à 59 jours', s_dq30, current_upb FROM snap
    UNION ALL SELECT 7, 'Retard de 60 à 89 jours', s_dq60, current_upb FROM snap
    UNION ALL SELECT 8, 'Au moins un signal',
        s_recent_dq OR s_negative_equity OR s_modified OR s_assistance OR s_dq30 OR s_dq60, current_upb FROM snap
)
SELECT
    ord, signal,
    count(*) FILTER (WHERE f)                                   AS n_loans,
    count(*) FILTER (WHERE f)::DOUBLE / count(*)                AS share_of_loans,
    round(coalesce(sum(current_upb) FILTER (WHERE f), 0) / 1e6, 1) AS upb_musd
FROM flags
GROUP BY ord, signal
ORDER BY ord;

-- 4. Taux de défaut à 12 mois observé, mois par mois, avec la conjoncture --------
CREATE OR REPLACE VIEW v_pd12_by_month AS
SELECT
    p.period,
    count(*)                                                  AS n_performing,
    count(*) FILTER (WHERE p.default_12m)                     AS n_default_12m,
    count(*) FILTER (WHERE p.default_12m)::DOUBLE / count(*)  AS pd12,
    any_value(e.unemployment_rate)                            AS unemployment_rate,
    any_value(e.house_price_index)                            AS house_price_index
FROM loan_month_pd AS p
LEFT JOIN economic_indicators AS e USING (period)
WHERE p.window_complete
GROUP BY p.period
ORDER BY p.period;
