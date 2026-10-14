-- =============================================================================
-- Phase 2 — Couche analytique de base
-- Construit trois tables dérivées, recalculées à chaque exécution :
--   loan_month    : la vie de chaque prêt mois par mois, avec son ÉTAT de risque
--   loan_default  : une ligne par prêt, avec la date de son PREMIER défaut
--   loan_month_pd : pour chaque mois sain, le prêt fait-il défaut dans les 12 mois ?
-- =============================================================================
--
-- DÉFINITION DU DÉFAUT RETENUE
--   Un prêt est en défaut le premier mois où l'une de ces conditions est vraie :
--     1. il a au moins 90 jours de retard (statut >= 3 mois) ;
--     2. le bien a été saisi (statut "RA", REO) ;
--     3. il sort du portefeuille avec une perte (codes 02, 03, 09, 15).
--   C'est la transposition du critère des 90 jours de retard de l'article 178
--   du règlement européen CRR. On ne retient pas le critère « d'improbabilité
--   de paiement » (restructurations), faute d'information fiable : c'est une
--   limite documentée, testée en analyse de sensibilité plus tard.
-- =============================================================================

-- 0. loan_age_anchor : point de départ de l'ancienneté de chaque prêt -----------
-- Normalement la date de 1re échéance. Mais pour certains prêts modifiés,
-- Freddie Mac REMPLACE cette date par celle de la modification (parfois des
-- années plus tard), ce qui fausserait l'ancienneté et les courbes de vintage.
-- Règle : si la 1re échéance tombe plus de 6 mois après le début du trimestre
-- d'octroi (connu grâce à l'identifiant du prêt), on prend le début du
-- trimestre + 3 mois. Le contrôle A14 compte les prêts concernés.
CREATE OR REPLACE TABLE loan_age_anchor AS
WITH q AS (
    SELECT loan_id, vintage_year, first_payment_date,
           make_date(CAST(left(vintage_quarter, 4) AS INTEGER),
                     (CAST(right(vintage_quarter, 1) AS INTEGER) - 1) * 3 + 1, 1) AS quarter_start
    FROM loans
)
SELECT
    loan_id, vintage_year, first_payment_date, quarter_start,
    first_payment_date IS NULL
        OR first_payment_date > CAST(quarter_start + INTERVAL 6 MONTH AS DATE)       AS anchor_reset,
    CASE WHEN first_payment_date IS NULL
              OR first_payment_date > CAST(quarter_start + INTERVAL 6 MONTH AS DATE)
         THEN CAST(quarter_start + INTERVAL 3 MONTH AS DATE)
         ELSE first_payment_date END                                                AS anchor_date
FROM q;

-- 1. loan_month ----------------------------------------------------------------
CREATE OR REPLACE TABLE loan_month AS
WITH base AS (
    SELECT p.*, a.vintage_year, a.anchor_date
    FROM loan_performance AS p
    JOIN loan_age_anchor AS a USING (loan_id)
    LEFT JOIN loan_outcomes AS o USING (loan_id)
    -- on écarte les lignes publiées après la sortie du prêt (contrôle QC05b)
    WHERE o.zero_balance_date IS NULL OR p.period <= o.zero_balance_date
),
classified AS (
    SELECT
        *,
        CASE
            WHEN zero_balance_code = '01'                          THEN 'Remboursé'
            WHEN zero_balance_code IN ('02', '03', '09', '15')     THEN 'Sortie avec perte'
            WHEN zero_balance_code IS NOT NULL                     THEN 'Autre sortie'
            WHEN is_reo OR months_delinquent >= 3                  THEN '90+ jours'
            WHEN months_delinquent = 2                             THEN '60-89 jours'
            WHEN months_delinquent = 1                             THEN '30-59 jours'
            WHEN months_delinquent = 0                             THEN 'À jour'
            ELSE 'Inconnu'
        END AS state
    FROM base
)
SELECT
    loan_id,
    vintage_year,
    period,
    -- ancienneté calculée depuis la 1re échéance d'origine (loan_age est remis
    -- à zéro par Freddie Mac quand un prêt est modifié : inutilisable ici)
    date_diff('month', anchor_date, period) + 1                    AS age,
    current_upb,
    lag(current_upb) OVER w                                        AS prev_upb,
    months_delinquent,
    state,
    CASE state
        WHEN 'À jour' THEN 1 WHEN '30-59 jours' THEN 2 WHEN '60-89 jours' THEN 3
        WHEN '90+ jours' THEN 4 WHEN 'Remboursé' THEN 5 WHEN 'Sortie avec perte' THEN 6
        WHEN 'Autre sortie' THEN 7 ELSE 8
    END                                                            AS state_order,
    state IN ('90+ jours', 'Sortie avec perte')                    AS is_default_event,
    lead(state)  OVER w                                            AS next_state,
    lead(period) OVER w                                            AS next_period,
    -- pire retard observé sur les 12 mois précédents (signal de rechute)
    max(months_delinquent) OVER (PARTITION BY loan_id ORDER BY period
                                 ROWS BETWEEN 12 PRECEDING AND 1 PRECEDING) AS max_dq_prev12,
    eltv_pct,
    modification_flag,
    payment_deferral,
    borrower_assistance
FROM classified
WINDOW w AS (PARTITION BY loan_id ORDER BY period);

-- 2. loan_default --------------------------------------------------------------
CREATE OR REPLACE TABLE loan_default AS
WITH first_default AS (
    SELECT loan_id, min(period) AS default_period
    FROM loan_month
    WHERE is_default_event
    GROUP BY loan_id
)
SELECT
    l.loan_id,
    l.vintage_year,
    f.default_period IS NOT NULL                                   AS ever_default,
    f.default_period,
    greatest(date_diff('month', a.anchor_date, f.default_period) + 1, 1) AS default_age,
    m.state                                                        AS default_trigger,
    -- exposition au défaut (EAD) : encours du mois, ou du mois précédent si le
    -- défaut est constaté le mois même de la sortie (encours déjà ramené à 0)
    CASE WHEN m.current_upb > 0 THEN m.current_upb ELSE m.prev_upb END AS ead_at_default,
    o.zero_balance_code,
    o.zero_balance_date,
    o.removal_upb,
    o.actual_loss
FROM loans AS l
JOIN loan_age_anchor AS a USING (loan_id)
LEFT JOIN first_default AS f USING (loan_id)
LEFT JOIN loan_month   AS m ON m.loan_id = l.loan_id AND m.period = f.default_period
LEFT JOIN loan_outcomes AS o ON o.loan_id = l.loan_id;

-- 3. loan_month_pd -------------------------------------------------------------
-- Pour chaque mois où le prêt est sain (pas encore en défaut, encours > 0) :
--   default_12m     = le prêt fait-il défaut dans les 12 mois qui suivent ?
--   window_complete = a-t-on bien 12 mois de recul ? (sinon le mois est exclu
--                     des taux, pour ne pas sous-estimer le risque récent)
CREATE OR REPLACE TABLE loan_month_pd AS
SELECT
    m.loan_id,
    m.vintage_year,
    m.period,
    m.state,
    m.current_upb,
    d.default_period IS NOT NULL
        AND d.default_period <= CAST(m.period + INTERVAL 12 MONTH AS DATE)  AS default_12m,
    CAST(m.period + INTERVAL 12 MONTH AS DATE)
        <= (SELECT max(period) FROM loan_month)                             AS window_complete,
    -- signaux d'alerte observables ce mois-ci
    m.state = '30-59 jours'                                                 AS s_dq30,
    m.state = '60-89 jours'                                                 AS s_dq60,
    m.state = 'À jour' AND coalesce(m.max_dq_prev12, 0) >= 1                AS s_recent_dq,
    coalesce(m.eltv_pct > 100, FALSE)                                       AS s_negative_equity,
    coalesce(m.modification_flag IN ('Y', 'P'), FALSE)                      AS s_modified,
    coalesce(m.borrower_assistance IN ('F', 'R', 'T'), FALSE)               AS s_assistance
FROM loan_month AS m
JOIN loan_default AS d USING (loan_id)
WHERE m.state IN ('À jour', '30-59 jours', '60-89 jours')
  AND m.current_upb > 0
  AND (d.default_period IS NULL OR m.period < d.default_period);

-- 4. Fonctions utilitaires -----------------------------------------------------
-- Intervalle de confiance de Wilson à 95 % pour une proportion k / n.
-- Plus fiable que l'intervalle « normal » quand le taux est faible (cas des défauts).
CREATE OR REPLACE MACRO wilson_low(k, n) AS
    CASE WHEN n > 0 THEN
        ((k::DOUBLE / n) + 1.96 * 1.96 / (2 * n)
         - 1.96 * sqrt((k::DOUBLE / n) * (1 - k::DOUBLE / n) / n + 1.96 * 1.96 / (4 * n * n)))
        / (1 + 1.96 * 1.96 / n)
    END;

CREATE OR REPLACE MACRO wilson_high(k, n) AS
    CASE WHEN n > 0 THEN
        ((k::DOUBLE / n) + 1.96 * 1.96 / (2 * n)
         + 1.96 * sqrt((k::DOUBLE / n) * (1 - k::DOUBLE / n) / n + 1.96 * 1.96 / (4 * n * n)))
        / (1 + 1.96 * 1.96 / n)
    END;
