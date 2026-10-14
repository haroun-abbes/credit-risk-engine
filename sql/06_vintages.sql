-- =============================================================================
-- Phase 2 — Analyse par vintage (courbes de défaut cumulé)
-- Question métier : à ancienneté égale, quelle cohorte fait le plus défaut ?
--
-- Méthode « static pool » : dénominateur = TOUS les prêts de la cohorte,
-- y compris ceux remboursés depuis. Numérateur = prêts ayant fait défaut au plus
-- tard à l'ancienneté a.
-- Censure à droite : la courbe d'une cohorte s'arrête à l'ancienneté que TOUS
-- ses prêts ont pu atteindre avant la date d'arrêté des données. Sinon les
-- derniers points seraient sous-estimés (prêts pas encore assez vieux).
-- =============================================================================

CREATE OR REPLACE VIEW v_vintage_curve AS
WITH cutoff AS (
    SELECT max(period) AS last_period FROM loan_month
),
cohort AS (
    SELECT
        a.vintage_year,
        count(*)                                                        AS n_loans,
        date_diff('month', max(a.anchor_date), c.last_period) + 1       AS horizon
    FROM loan_age_anchor AS a, cutoff AS c
    GROUP BY a.vintage_year, c.last_period
),
defaults_by_age AS (
    SELECT vintage_year, default_age AS age, count(*) AS k
    FROM loan_default
    WHERE ever_default
    GROUP BY ALL
),
grid AS (
    SELECT c.vintage_year, c.n_loans, a.age
    FROM cohort AS c, range(1, 481) AS a(age)
    WHERE a.age <= c.horizon
)
SELECT
    g.vintage_year,
    g.age,
    g.n_loans,
    sum(coalesce(d.k, 0)) OVER (PARTITION BY g.vintage_year ORDER BY g.age)            AS cum_defaults,
    sum(coalesce(d.k, 0)) OVER (PARTITION BY g.vintage_year ORDER BY g.age) / g.n_loans AS cum_default_rate
FROM grid AS g
LEFT JOIN defaults_by_age AS d ON d.vintage_year = g.vintage_year AND d.age = g.age;

-- Repères à 12, 24, 36, 60 et 120 mois (NULL = ancienneté pas encore atteinte)
CREATE OR REPLACE VIEW v_vintage_milestones AS
SELECT
    vintage_year,
    max(n_loans)                                              AS n_loans,
    max(cum_default_rate) FILTER (WHERE age = 12)             AS at_12m,
    max(cum_default_rate) FILTER (WHERE age = 24)             AS at_24m,
    max(cum_default_rate) FILTER (WHERE age = 36)             AS at_36m,
    max(cum_default_rate) FILTER (WHERE age = 60)             AS at_60m,
    max(cum_default_rate) FILTER (WHERE age = 120)            AS at_120m,
    max(age)                                                  AS horizon_months
FROM v_vintage_curve
GROUP BY vintage_year
ORDER BY vintage_year;
