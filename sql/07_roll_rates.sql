-- =============================================================================
-- Phase 2 — Roll rates (matrice de transition mensuelle entre états de retard)
-- Question métier : un prêt dans un état donné ce mois-ci, où sera-t-il le mois
-- prochain ? Chaque ligne de la matrice (état de départ) totalise 100 %.
-- On ne garde que les paires de mois consécutifs (trous d'historique exclus).
-- =============================================================================

CREATE OR REPLACE VIEW v_roll_rates AS
WITH transitions AS (
    SELECT year(period) AS yr, state AS from_state, state_order AS from_order,
           next_state AS to_state,
           CASE next_state
               WHEN 'À jour' THEN 1 WHEN '30-59 jours' THEN 2 WHEN '60-89 jours' THEN 3
               WHEN '90+ jours' THEN 4 WHEN 'Remboursé' THEN 5 WHEN 'Sortie avec perte' THEN 6
               ELSE 7
           END AS to_order
    FROM loan_month
    WHERE state IN ('À jour', '30-59 jours', '60-89 jours', '90+ jours')
      AND next_state IS NOT NULL
      AND next_state <> 'Inconnu'
      AND next_period = CAST(period + INTERVAL 1 MONTH AS DATE)
),
counts AS (
    SELECT coalesce(CAST(yr AS VARCHAR), 'Toutes') AS annee,
           from_state, from_order, to_state, to_order, count(*) AS n
    FROM transitions
    GROUP BY GROUPING SETS ((yr, from_state, from_order, to_state, to_order),
                            (from_state, from_order, to_state, to_order))
)
SELECT
    annee, from_state, from_order, to_state, to_order, n,
    n::DOUBLE / sum(n) OVER (PARTITION BY annee, from_state) AS share
FROM counts;

-- Matrice « toutes années » au format tableau croisé, lisible dans le terminal
CREATE OR REPLACE VIEW v_roll_matrix AS
SELECT
    from_state AS "État ce mois-ci",
    round(100 * coalesce(sum(share) FILTER (WHERE to_state = 'À jour'), 0), 2)            AS "À jour",
    round(100 * coalesce(sum(share) FILTER (WHERE to_state = '30-59 jours'), 0), 2)       AS "30-59 j",
    round(100 * coalesce(sum(share) FILTER (WHERE to_state = '60-89 jours'), 0), 2)       AS "60-89 j",
    round(100 * coalesce(sum(share) FILTER (WHERE to_state = '90+ jours'), 0), 2)         AS "90+ j",
    round(100 * coalesce(sum(share) FILTER (WHERE to_state = 'Remboursé'), 0), 2)         AS "Remboursé",
    round(100 * coalesce(sum(share) FILTER (WHERE to_state = 'Sortie avec perte'), 0), 2) AS "Sortie avec perte",
    round(100 * coalesce(sum(share) FILTER (WHERE to_state = 'Autre sortie'), 0), 2)      AS "Autre sortie",
    sum(n)                                                                   AS "Nb de prêts-mois"
FROM v_roll_rates
WHERE annee = 'Toutes'
GROUP BY from_state, from_order
ORDER BY from_order;
