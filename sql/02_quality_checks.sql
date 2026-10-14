-- =============================================================================
-- Contrôles qualité des données
-- Chaque contrôle commence par une ligne "-- @check" :
--   -- @check <code> | <BLOQUANT ou ALERTE> | <description>
-- et la requête qui suit renvoie le NOMBRE d'anomalies (0 = contrôle réussi).
--   BLOQUANT : l'anomalie fausserait les indicateurs, il faut la corriger.
--   ALERTE   : anomalie connue ou tolérable, à documenter dans le README.
-- =============================================================================

-- @check QC01 | BLOQUANT | Prêts sans aucune ligne de performance
SELECT count(*) FROM loans l
WHERE NOT EXISTS (SELECT 1 FROM loan_performance p WHERE p.loan_id = l.loan_id);

-- @check QC02 | BLOQUANT | Montant initial nul ou négatif
SELECT count(*) FROM loans WHERE original_upb <= 0;

-- @check QC03 | BLOQUANT | Encours mensuel négatif
SELECT count(*) FROM loan_performance WHERE current_upb < 0;

-- @check QC04 | BLOQUANT | Statut de retard non reconnu (ni nombre, ni RA, ni XX)
SELECT count(*) FROM loan_performance
WHERE delinquency_status IS NOT NULL
  AND months_delinquent IS NULL
  AND delinquency_status NOT IN ('RA', 'XX');


-- @check QC05 | BLOQUANT | Lignes de performance après la date de sortie du prêt (hors décalage connu)
SELECT count(*) FROM loan_performance p
JOIN loan_outcomes o USING (loan_id)
WHERE p.period > o.zero_balance_date
  AND NOT (p.period = o.zero_balance_date + INTERVAL 1 MONTH AND p.current_upb = 0);

-- @check QC05b | ALERTE | Décalage d'un mois entre sortie et dernière ligne (encours nul, cycle de reporting Freddie Mac)
SELECT count(*) FROM loan_performance p
JOIN loan_outcomes o USING (loan_id)
WHERE p.period = o.zero_balance_date + INTERVAL 1 MONTH AND p.current_upb = 0;

-- @check QC06 | ALERTE | Prêts avec des mois manquants dans l'historique
WITH spans AS (
    SELECT loan_id,
           count(*)                                        AS n_obs,
           date_diff('month', min(period), max(period)) + 1 AS n_expected
    FROM loan_performance GROUP BY loan_id
)
SELECT count(*) FROM spans WHERE n_obs <> n_expected;

-- @check QC07 | ALERTE | Encours supérieur de plus de 5 % au montant initial (hors prêts modifiés)
SELECT count(*) FROM loan_performance p
JOIN loans l USING (loan_id)
WHERE p.current_upb > 1.05 * l.original_upb
  AND p.modification_flag IS NULL;

-- @check QC08 | ALERTE | Score FICO non renseigné
SELECT count(*) FROM borrowers WHERE fico_score IS NULL;

-- @check QC09 | ALERTE | LTV non renseignée
SELECT count(*) FROM loans WHERE ltv_pct IS NULL;

-- @check QC10 | ALERTE | Taux d'endettement (DTI) non renseigné
SELECT count(*) FROM borrowers WHERE dti_pct IS NULL;

-- @check QC11 | ALERTE | Perte renseignée pour une sortie qui n'est pas un défaut (codes 02, 03, 09, 15)
SELECT count(*) FROM loan_outcomes
WHERE actual_loss IS NOT NULL AND zero_balance_code NOT IN ('02', '03', '09', '15');

-- @check QC12 | ALERTE | Mois de performance sans donnée macroéconomique
SELECT count(DISTINCT p.period) FROM loan_performance p
LEFT JOIN economic_indicators e USING (period)
WHERE e.period IS NULL;
