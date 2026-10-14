-- =============================================================================
-- Premier regard sur les données (fin de la phase 1)
-- Objectif : vérifier que les chiffres sont plausibles AVANT toute analyse.
-- =============================================================================

-- 1. Taille du portefeuille par cohorte (vintage)
SELECT vintage_year,
       count(*)                                  AS nb_prets,
       round(sum(original_upb) / 1e6, 1)          AS montant_initial_musd,
       round(avg(original_upb) / 1e3, 0)          AS montant_moyen_kusd,
       round(avg(original_rate), 2)               AS taux_moyen_pct
FROM loans
GROUP BY vintage_year
ORDER BY vintage_year;

-- 2. Profil de risque à l'octroi par cohorte
SELECT l.vintage_year,
       round(avg(b.fico_score), 0)                AS fico_moyen,
       round(avg(l.ltv_pct), 1)                   AS ltv_moyenne,
       round(avg(b.dti_pct), 1)                   AS dti_moyen,
       round(100 * avg((l.ltv_pct > 90)::INT), 1) AS pct_ltv_sup_90
FROM loans l
JOIN borrowers b USING (borrower_id)
GROUP BY l.vintage_year
ORDER BY l.vintage_year;

-- 3. Comment les prêts sortent du portefeuille
SELECT zero_balance_code, zero_balance_label,
       count(*)                                   AS nb_prets,
       round(sum(actual_loss) / 1e6, 2)           AS pertes_musd
FROM loan_outcomes
GROUP BY ALL
ORDER BY nb_prets DESC;

-- 4. Répartition des statuts de retard sur le dernier mois de chaque prêt actif
WITH last_month AS (
    SELECT *
    FROM loan_performance
    QUALIFY period = max(period) OVER (PARTITION BY loan_id)   -- dernière observation de chaque prêt
)
SELECT delinquency_status, count(*) AS nb_prets
FROM last_month
WHERE zero_balance_code IS NULL                                   -- prêts encore actifs
GROUP BY delinquency_status
ORDER BY nb_prets DESC
LIMIT 10;
