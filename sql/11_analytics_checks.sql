-- =============================================================================
-- Contrôles de cohérence des résultats de la phase 2
-- Même format que 02_quality_checks.sql : chaque requête compte des anomalies.
-- Objectif : qu'aucun chiffre impossible n'arrive jamais jusqu'au tableau de bord.
-- =============================================================================

-- @check A01 | BLOQUANT | Taux de défaut hors de [0 ; 1] (cohortes et segments)
SELECT (SELECT count(*) FROM v_default_by_vintage WHERE default_rate NOT BETWEEN 0 AND 1)
     + (SELECT count(*) FROM v_default_by_segment WHERE default_rate NOT BETWEEN 0 AND 1);

-- @check A02 | BLOQUANT | Intervalle de confiance qui n'encadre pas le taux
SELECT count(*) FROM v_default_by_segment
WHERE NOT (ci_low <= default_rate + 1e-12 AND default_rate <= ci_high + 1e-12 AND ci_low >= 0 AND ci_high <= 1);

-- @check A03 | BLOQUANT | Plus de défauts que de prêts dans un segment
SELECT count(*) FROM v_default_by_segment WHERE n_defaults > n_loans;

-- @check A04 | BLOQUANT | Somme des segments différente du total (prêts ou défauts)
WITH tot AS (SELECT n_loans, n_defaults FROM v_default_by_vintage WHERE cohorte = 'Toutes'),
     dims AS (SELECT dimension, sum(n_loans) AS n, sum(n_defaults) AS k
              FROM v_default_by_segment WHERE cohorte = 'Toutes' GROUP BY dimension)
SELECT count(*) FROM dims, tot WHERE dims.n <> tot.n_loans OR dims.k <> tot.n_defaults;

-- @check A05 | BLOQUANT | Courbe de vintage qui diminue (un taux cumulé ne peut que monter)
SELECT count(*) FROM (
    SELECT cum_default_rate - lag(cum_default_rate) OVER (PARTITION BY vintage_year ORDER BY age) AS delta
    FROM v_vintage_curve
) WHERE delta < 0;

-- @check A06 | BLOQUANT | Taux de défaut cumulé hors de [0 ; 1]
SELECT count(*) FROM v_vintage_curve WHERE cum_default_rate NOT BETWEEN 0 AND 1;

-- @check A07 | BLOQUANT | Ligne de la matrice de transition qui ne totalise pas 100 %
SELECT count(*) FROM (
    SELECT annee, from_state, sum(share) AS total FROM v_roll_rates GROUP BY ALL
) WHERE abs(total - 1) > 1e-9;

-- @check A08 | BLOQUANT | Parts de concentration qui ne totalisent pas 100 % ou HHI hors de [0 ; 10 000]
SELECT (SELECT count(*) FROM (SELECT sum(share) AS t FROM v_concentration_state) WHERE abs(t - 1) > 1e-9)
     + (SELECT count(*) FROM v_concentration_summary WHERE hhi NOT BETWEEN 0 AND 10000);

-- @check A09 | BLOQUANT | Taux de défaut à 12 mois hors de [0 ; 1]
SELECT (SELECT count(*) FROM v_pd12_by_state WHERE pd12 NOT BETWEEN 0 AND 1)
     + (SELECT count(*) FROM v_pd12_by_month WHERE pd12 NOT BETWEEN 0 AND 1)
     + (SELECT count(*) FROM v_signal_backtest WHERE pd12 NOT BETWEEN 0 AND 1);

-- @check A10 | BLOQUANT | Sortie avec perte non comptée comme défaut
SELECT count(*) FROM loan_default
WHERE zero_balance_code IN ('02', '03', '09', '15') AND NOT ever_default;

-- @check A11 | BLOQUANT | Encours négatif ou nul dans le portefeuille actif
SELECT count(*) FROM v_snapshot_active WHERE current_upb <= 0;

-- @check A12 | ALERTE | Sévérité de perte d'une cohorte hors de [0 ; 1] (gain net ou frais supérieurs à l'encours)
SELECT count(*) FROM v_loss_severity WHERE severity NOT BETWEEN 0 AND 1;

-- @check A13 | ALERTE | Segments de moins de 300 prêts (taux peu fiable, affiché avec réserve)
SELECT count(*) FROM v_default_by_segment WHERE NOT enough_loans;

-- @check A14 | ALERTE | Prêts dont la 1re échéance a été réinitialisée (ancienneté recalculée depuis le trimestre d'octroi)
SELECT count(*) FROM loan_age_anchor WHERE anchor_reset;
