-- =============================================================================
-- Contrôles de la perte attendue IFRS 9, des migrations et du calibrage (phase 4)
-- Même format que les autres fichiers de contrôles.
-- =============================================================================

-- @check E01 | BLOQUANT | PD hors de l'intervalle ]0 ; 1[ (prêts sains)
SELECT count(*) FROM ecl_results
WHERE state <> '90+ jours'
  AND (pd_ttc IS NULL OR pd_pit IS NULL OR pd_ttc <= 0 OR pd_ttc >= 1 OR pd_pit <= 0 OR pd_pit >= 1);

-- @check E02 | BLOQUANT | LGD hors de [0 ; 1]
SELECT count(*) FROM ecl_results
WHERE lgd IS NULL OR lgd < 0 OR lgd > 1 OR lgd_downturn < 0 OR lgd_downturn > 1;

-- @check E03 | BLOQUANT | Perte attendue négative ou supérieure à l'encours
SELECT count(*) FROM ecl_results
WHERE ecl IS NULL OR ecl < 0 OR ecl > ead + 0.01;

-- @check E04 | BLOQUANT | ECL à maturité inférieure à l'ECL à 12 mois (prêts sains)
SELECT count(*) FROM ecl_results
WHERE state <> '90+ jours' AND ecl_lifetime < ecl_12m - 0.01;

-- @check E05 | BLOQUANT | Prêt actif à la date d'arrêté absent du calcul d'ECL
SELECT count(*) FROM loan_month AS m
WHERE m.period = (SELECT max(period) FROM loan_month)
  AND m.state IN ('À jour', '30-59 jours', '60-89 jours', '90+ jours')
  AND m.current_upb > 0
  AND m.loan_id NOT IN (SELECT loan_id FROM ecl_results);

-- @check E06 | BLOQUANT | Stage 3 incohérent avec le retard de 90 jours ou plus
SELECT count(*) FROM ecl_results
WHERE (stage = 3) <> (state = '90+ jours');

-- @check E07 | BLOQUANT | Ligne de matrice de migration dont la somme ne fait pas 100 %
SELECT count(*) FROM (
    SELECT period, from_grade, sum(share) AS s FROM migration_matrix GROUP BY period, from_grade
) WHERE abs(s - 1) > 1e-6;

-- @check E08 | ALERTE | Taux de couverture qui ne monte pas du Stage 1 au Stage 3
SELECT count(*) FROM (
    SELECT stage, sum(ecl) / sum(ead) AS cov,
           lag(sum(ecl) / sum(ead)) OVER (ORDER BY stage) AS prev
    FROM ecl_results GROUP BY stage
) WHERE prev IS NOT NULL AND cov <= prev;

-- @check E09 | ALERTE | Scénarios dont les poids ne totalisent pas 100 % ou ECL non croissante avec la sévérité
SELECT (abs(sum(weight) - 1) > 1e-9)::INT
     + (count(*) FILTER (WHERE scenario = 'Adverse' AND ecl < (SELECT ecl FROM ecl_scenarios WHERE scenario = 'Central')))
     + (count(*) FILTER (WHERE scenario = 'Sévère'  AND ecl < (SELECT ecl FROM ecl_scenarios WHERE scenario = 'Adverse')))
FROM ecl_scenarios;
