-- =============================================================================
-- Phase 4 — LGD, EAD et remboursements anticipés
-- =============================================================================

-- 1. Issue de chaque défaut --------------------------------------------------------
-- Un défaut se termine de trois façons :
--   * liquidé  : sortie avec perte (02, 03, 09, 15) et perte publiée ;
--   * guéri    : remboursé ensuite (01), ou de nouveau à jour depuis 12 mois
--                à la date d'arrêté -> perte nulle pour le prêteur ;
--   * non résolu : encore en retard, revendu sans perte publiée (16, 96), ou
--                perte pas encore publiée -> exclu du calcul.
CREATE OR REPLACE VIEW v_default_resolution AS
WITH snap AS (SELECT max(period) AS s FROM loan_month),
last_state AS (
    SELECT m.loan_id, m.state, coalesce(m.max_dq_prev12, 0) AS max_dq_prev12
    FROM loan_month AS m, snap
    WHERE m.period = snap.s
)
SELECT
    d.loan_id,
    d.vintage_year,
    d.default_period,
    d.ead_at_default,
    seg.cltv_band,
    seg.cltv_order,
    CASE
        WHEN d.zero_balance_code IN ('02', '03', '09', '15')
             AND d.actual_loss IS NOT NULL AND d.removal_upb > 0       THEN 'Liquidé'
        WHEN d.zero_balance_code = '01'                                 THEN 'Guéri'
        WHEN d.zero_balance_code IS NULL AND ls.state = 'À jour'
             AND ls.max_dq_prev12 = 0                                   THEN 'Guéri'
        ELSE 'Non résolu'
    END AS resolution,
    CASE WHEN d.zero_balance_code IN ('02', '03', '09', '15') THEN d.actual_loss ELSE 0 END AS loss
FROM loan_default AS d
JOIN v_loan_segments AS seg USING (loan_id)
LEFT JOIN last_state AS ls USING (loan_id)
WHERE d.ever_default AND d.ead_at_default > 0;

-- 2. LGD par tranche de CLTV ----------------------------------------------------------
-- LGD = pertes / exposition au défaut, sur les défauts RÉSOLUS (les guéris
-- comptent avec une perte nulle). C'est une LGD « tous défauts confondus ».
-- LGD de ralentissement (downturn) : même calcul, limité aux défauts survenus
-- pendant la crise (2008-2011). Bâle exige une LGD qui reflète une période de crise.
CREATE OR REPLACE VIEW v_lgd_by_segment AS
WITH res AS (
    SELECT * FROM v_default_resolution WHERE resolution <> 'Non résolu'
),
agg AS (
    SELECT
        coalesce(cltv_band, 'Tous') AS cltv_band,
        coalesce(min(cltv_order), 0) AS cltv_order,
        count(*)                                                          AS n_resolved,
        count(*) FILTER (WHERE resolution = 'Guéri')::DOUBLE / count(*)   AS cure_rate,
        sum(loss) FILTER (WHERE resolution = 'Liquidé')
            / nullif(sum(ead_at_default) FILTER (WHERE resolution = 'Liquidé'), 0) AS severity,
        sum(loss) / sum(ead_at_default)                                   AS lgd,
        count(*) FILTER (WHERE year(default_period) BETWEEN 2008 AND 2011) AS n_crisis,
        sum(loss) FILTER (WHERE year(default_period) BETWEEN 2008 AND 2011)
            / nullif(sum(ead_at_default) FILTER (WHERE year(default_period) BETWEEN 2008 AND 2011), 0) AS lgd_crisis
    FROM res
    GROUP BY GROUPING SETS ((cltv_band), ())
)
SELECT
    cltv_band, cltv_order, n_resolved, cure_rate, severity, lgd, n_crisis, lgd_crisis,
    -- downturn : la plus élevée des deux, uniquement si la crise compte assez de défauts
    CASE WHEN n_crisis >= 100 THEN greatest(lgd, lgd_crisis) ELSE lgd END AS lgd_downturn
FROM agg
ORDER BY cltv_band = 'Tous', cltv_order;

-- 3. Facteur d'EAD --------------------------------------------------------------------
-- Un crédit immobilier amortissable n'a pas de montant non tiré : l'exposition au
-- défaut est proche de l'encours. On mesure le rapport entre l'encours au défaut
-- et l'encours 12 mois avant (amortissement contre intérêts impayés capitalisés).
CREATE OR REPLACE VIEW v_ead_factor AS
SELECT
    count(*)                                      AS n_defaults,
    sum(d.ead_at_default) / sum(m.current_upb)    AS ead_factor
FROM loan_default AS d
JOIN loan_month AS m
  ON m.loan_id = d.loan_id
 AND m.period = CAST(d.default_period - INTERVAL 12 MONTH AS DATE)
WHERE d.ever_default AND d.ead_at_default > 0 AND m.current_upb > 0;

-- 4. Taux de remboursement anticipé annuel (5 dernières années observables) --------------
CREATE OR REPLACE VIEW v_prepayment_rate AS
WITH obs AS (
    SELECT p.loan_id, p.period
    FROM pd_dataset AS p
    WHERE p.window_complete
      AND year(p.period) > (SELECT max(year(period)) FROM pd_dataset WHERE window_complete) - 5
)
SELECT
    count(*)                                                                      AS n_obs,
    count(*) FILTER (WHERE o.zero_balance_code = '01'
                       AND o.zero_balance_date > obs.period
                       AND o.zero_balance_date <= CAST(obs.period + INTERVAL 12 MONTH AS DATE))::DOUBLE
        / count(*)                                                                AS annual_prepayment_rate
FROM obs
LEFT JOIN loan_outcomes AS o USING (loan_id);
