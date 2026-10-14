-- =============================================================================
-- Contrôles du modèle de PD et des notes attribuées (phase 3)
-- Même format que les autres fichiers de contrôles.
-- =============================================================================

-- @check P01 | BLOQUANT | PD hors de l'intervalle ]0 ; 1[
SELECT count(*) FROM risk_ratings WHERE pd_12m <= 0 OR pd_12m >= 1 OR pd_12m IS NULL;

-- @check P02 | BLOQUANT | Note incohérente avec la PD (PD hors des bornes de sa classe)
SELECT count(*) FROM risk_ratings AS r JOIN rating_scale AS s USING (grade)
WHERE NOT (r.pd_12m >= s.pd_lower AND r.pd_12m < s.pd_upper);

-- @check P03 | BLOQUANT | Échelle de notation non contiguë (trou ou chevauchement entre classes)
SELECT count(*) FROM (
    SELECT pd_lower, lag(pd_upper) OVER (ORDER BY grade) AS prev_upper FROM rating_scale
) WHERE prev_upper IS NOT NULL AND pd_lower <> prev_upper;

-- @check P04 | BLOQUANT | Prêt noté à une date où il était déjà en défaut
SELECT count(*) FROM risk_ratings AS r JOIN loan_default AS d USING (loan_id)
WHERE d.default_period IS NOT NULL AND d.default_period <= r.rating_date;

-- @check P05 | ALERTE | Taux de défaut observé qui ne monte pas d'une classe à la suivante
WITH obs AS (
    SELECT r.grade, avg(p.default_12m::INT) AS dr, count(*) AS n
    FROM risk_ratings AS r
    JOIN loan_month_pd AS p ON p.loan_id = r.loan_id AND p.period = r.rating_date
    WHERE p.window_complete
    GROUP BY r.grade
)
SELECT count(*) FROM (SELECT dr, lag(dr) OVER (ORDER BY grade) AS prev FROM obs WHERE n >= 100)
WHERE dr < prev;

-- @check P06 | ALERTE | Une classe concentre plus de 40 % des prêts notés à la dernière date
SELECT count(*) FROM (
    SELECT grade, count(*)::DOUBLE / sum(count(*)) OVER () AS share
    FROM risk_ratings
    WHERE rating_date = (SELECT max(rating_date) FROM risk_ratings)
    GROUP BY grade
) WHERE share > 0.40;
