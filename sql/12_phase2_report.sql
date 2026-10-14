-- =============================================================================
-- Rapport de lecture de la phase 2 (valeurs arrondies, en %)
-- Lancer avec :  python src/query.py sql/12_phase2_report.sql
-- Les vues gardent les valeurs exactes ; ce fichier ne fait que les mettre en forme.
-- =============================================================================

-- 1. Taux de défaut par cohorte (défaut = 90 jours de retard ou sortie avec perte)
SELECT cohorte AS "Cohorte",
       n_loans AS "Prêts",
       n_defaults AS "Défauts",
       round(100 * default_rate, 2) AS "Taux de défaut %",
       round(100 * ci_low, 2) || ' – ' || round(100 * ci_high, 2) AS "IC 95 %",
       round(100 * loss_exit_rate, 2) AS "Sorties avec perte %"
FROM v_default_by_vintage;

-- 2. Courbes de vintage : taux de défaut cumulé à ancienneté égale (%)
SELECT vintage_year AS "Cohorte",
       round(100 * at_12m, 2) AS "12 mois",
       round(100 * at_24m, 2) AS "24 mois",
       round(100 * at_36m, 2) AS "36 mois",
       round(100 * at_60m, 2) AS "60 mois",
       round(100 * at_120m, 2) AS "120 mois",
       horizon_months AS "Recul max (mois)"
FROM v_vintage_milestones;

-- 3. Taux de défaut par tranche de score FICO et par cohorte (%)
SELECT segment AS "Score FICO",
       round(100 * max(default_rate) FILTER (WHERE cohorte = '2006'), 2) AS "2006",
       round(100 * max(default_rate) FILTER (WHERE cohorte = '2007'), 2) AS "2007",
       round(100 * max(default_rate) FILTER (WHERE cohorte = '2012'), 2) AS "2012",
       round(100 * max(default_rate) FILTER (WHERE cohorte = '2017'), 2) AS "2017",
       round(100 * max(default_rate) FILTER (WHERE cohorte = 'Toutes'), 2) AS "Toutes",
       max(n_loans) FILTER (WHERE cohorte = 'Toutes') AS "Prêts"
FROM v_default_by_segment
WHERE dimension = 'Score FICO'
GROUP BY segment, segment_order
ORDER BY segment_order;

-- 4. LTV ou CLTV ? Taux de défaut des cohortes 2006-2007 selon les deux mesures (%)
SELECT dimension AS "Mesure", segment AS "Tranche",
       sum(n_loans) AS "Prêts",
       round(100 * sum(n_defaults)::DOUBLE / sum(n_loans), 2) AS "Taux de défaut %"
FROM v_default_by_segment
WHERE dimension IN ('LTV', 'CLTV') AND cohorte IN ('2006', '2007')
GROUP BY dimension, segment, segment_order
ORDER BY dimension DESC, segment_order;

-- 5. Matrice de transition mensuelle, toutes années (% de chaque ligne)
SELECT * FROM v_roll_matrix;

-- 6. Signaux d'alerte : taux de défaut dans les 12 mois et « lift »
SELECT signal AS "Signal",
       n_loan_months AS "Prêts-mois observés",
       round(100 * pd12, 2) AS "Défaut à 12 mois %",
       round(lift, 1) AS "x fois le risque de base"
FROM v_signal_backtest;

-- 7. Sévérité des pertes (perte réalisée / encours à la sortie)
SELECT cohorte AS "Cohorte", n_with_loss AS "Sorties avec perte publiée",
       ead_musd AS "Encours M$", loss_musd AS "Pertes M$",
       round(100 * severity, 1) AS "Sévérité %", avg_loss_usd AS "Perte moyenne $"
FROM v_loss_severity;

-- 8. Portefeuille actif à la date d'arrêté
SELECT snapshot_date AS "Date d'arrêté", n_active AS "Prêts actifs", upb_musd AS "Encours M$",
       round(100 * dq30_rate, 2) AS "Retard 30 j+ %", round(100 * dq90_rate, 2) AS "Retard 90 j+ %"
FROM v_portfolio_snapshot;

-- 9. Concentration géographique (HHI : 0 = dispersé, 10 000 = un seul État)
SELECT perimetre AS "Périmètre", n_states AS "États",
       round(100 * top5_share, 1) AS "Top 5 %", round(100 * top10_share, 1) AS "Top 10 %",
       hhi AS "HHI", equivalent_states AS "Nb équivalent d'États"
FROM v_concentration_summary;

-- 10. Segments actifs les plus en retard (30 jours ou plus, au moins 300 prêts)
SELECT dimension AS "Dimension", segment AS "Segment", n_active AS "Prêts actifs",
       round(100 * dq30_rate, 2) AS "Retard 30 j+ %",
       round(vs_portfolio, 1) AS "x la moyenne"
FROM v_risky_segments;
