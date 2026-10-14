-- =============================================================================
-- Credit Risk Analytics Engine : schéma relationnel
-- Moteur : DuckDB (syntaxe très proche de PostgreSQL)
-- =============================================================================
-- Remarque sur le modèle :
--   Dans les données Freddie Mac, un prêt = un dossier emprunteur (pas d'identifiant
--   client commun à plusieurs prêts). On garde quand même une table `borrowers`
--   séparée : c'est la bonne pratique de modélisation (on sépare ce qui décrit
--   la personne de ce qui décrit le contrat), et cela permettrait d'accueillir
--   des données où un client détient plusieurs prêts.
-- =============================================================================

-- 1. Emprunteurs : caractéristiques mesurées à l'octroi --------------------------
CREATE TABLE borrowers (
    borrower_id        VARCHAR PRIMARY KEY,       -- identifiant technique (= loan_id ici)
    fico_score         SMALLINT,                  -- score de crédit 300-850 (NULL si inconnu)
    vantage_score      SMALLINT,
    dti_pct            SMALLINT,                  -- taux d'endettement (%)
    first_time_buyer   BOOLEAN,
    n_borrowers        SMALLINT
);

-- 2. Prêts : caractéristiques contractuelles à l'origination ---------------------
CREATE TABLE loans (
    loan_id            VARCHAR PRIMARY KEY,
    borrower_id        VARCHAR NOT NULL REFERENCES borrowers (borrower_id),
    vintage_year       SMALLINT NOT NULL,         -- année de production (cohorte)
    vintage_quarter    VARCHAR(6) NOT NULL,       -- ex. 2006Q3
    first_payment_date DATE,
    maturity_date      DATE,
    original_upb       DECIMAL(14, 2) NOT NULL,   -- montant initial (USD)
    original_rate      DECIMAL(6, 3),             -- taux nominal (%)
    original_term      SMALLINT,                  -- durée (mois)
    ltv_pct            SMALLINT,                  -- loan-to-value (%)
    cltv_pct           SMALLINT,
    mi_pct             SMALLINT,                  -- couverture assurance hypothécaire (%)
    loan_purpose       VARCHAR,                   -- Achat / Refinancement...
    channel            VARCHAR,                   -- Agence / Courtier...
    occupancy          VARCHAR,                   -- Résidence principale / Investissement...
    property_type      VARCHAR,
    n_units            SMALLINT,
    property_state     VARCHAR(2),                -- État américain : notre "segment géographique"
    msa_code           VARCHAR,
    postal_code3       VARCHAR(3),
    seller_name        VARCHAR
);

-- 3. Performance mensuelle : une ligne par prêt et par mois ----------------------
--    (c'est la table "repayments" du cahier des charges, en plus riche :
--     elle contient l'encours, le statut de retard et les événements de fin de vie)
CREATE TABLE loan_performance (
    loan_id              VARCHAR NOT NULL REFERENCES loans (loan_id),
    period               DATE NOT NULL,           -- premier jour du mois observé
    current_upb          DECIMAL(14, 2),          -- encours restant dû
    delinquency_status   VARCHAR(3),              -- valeur brute : 0, 1, 2, ..., RA, XX
    months_delinquent    SMALLINT,                -- version numérique (NULL si RA / XX)
    is_reo               BOOLEAN,                 -- bien saisi (Real Estate Owned)
    loan_age             SMALLINT,
    remaining_months     SMALLINT,
    current_rate         DECIMAL(6, 3),
    eltv_pct             SMALLINT,                -- LTV ré-estimée chaque mois
    modification_flag    VARCHAR(1),              -- Y = modifié ce mois, P = modifié avant
    payment_deferral     VARCHAR(1),
    borrower_assistance  VARCHAR(1),              -- F = forbearance, R = repayment, T = trial
    zero_balance_code    VARCHAR(2),              -- raison de sortie du portefeuille
    zero_balance_date    DATE,
    servicer_name        VARCHAR,
    PRIMARY KEY (loan_id, period)
);

-- 4. Sorties et pertes : une ligne par prêt sorti du portefeuille ---------------
CREATE TABLE loan_outcomes (
    loan_id                     VARCHAR PRIMARY KEY REFERENCES loans (loan_id),
    zero_balance_code           VARCHAR(2) NOT NULL,
    zero_balance_label          VARCHAR NOT NULL,
    zero_balance_date           DATE,
    removal_upb                 DECIMAL(14, 2),  -- encours au moment de la sortie (= EAD observée)
    net_sale_proceeds           DECIMAL(14, 2),
    mi_recoveries               DECIMAL(14, 2),
    non_mi_recoveries           DECIMAL(14, 2),
    total_expenses              DECIMAL(14, 2),
    delinquent_accrued_interest DECIMAL(14, 2),
    actual_loss                 DECIMAL(14, 2)   -- perte réalisée (positive = perte)
);

-- 5. Indicateurs macroéconomiques (mensuels) ------------------------------------
CREATE TABLE economic_indicators (
    period             DATE PRIMARY KEY,
    unemployment_rate  DOUBLE,
    mortgage_rate_30y  DOUBLE,
    fed_funds_rate     DOUBLE,
    house_price_index  DOUBLE
);

-- 6. Échelle de notation interne (remplie en phase 3) ---------------------------
CREATE TABLE rating_scale (
    grade        SMALLINT PRIMARY KEY,           -- 1 = meilleur risque
    label        VARCHAR NOT NULL,               -- ex. "A", "B"...
    pd_lower     DOUBLE NOT NULL,                -- bornes de PD de la classe
    pd_upper     DOUBLE NOT NULL
);

-- 7. Notations attribuées (remplie en phase 3) ----------------------------------
CREATE TABLE risk_ratings (
    loan_id        VARCHAR NOT NULL REFERENCES loans (loan_id),
    rating_date    DATE NOT NULL,                -- date d'observation (trimestrielle)
    pd_12m         DOUBLE NOT NULL,              -- probabilité de défaut à 12 mois
    grade          SMALLINT NOT NULL REFERENCES rating_scale (grade),
    model_version  VARCHAR NOT NULL,
    PRIMARY KEY (loan_id, rating_date)
);
