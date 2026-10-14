# Credit Risk Analytics Engine

Surveillance du risque de crédit d'un portefeuille de prêts immobiliers à partir des
données granulaires de Freddie Mac (Single-Family Loan-Level Dataset) : taux de défaut,
concentrations, signaux d'alerte, migrations de notation, perte attendue et staging IFRS 9.

> Projet en cours de construction. Phase actuelle : **2 — analyses du risque**.

## Problématique

Comment surveiller un portefeuille de prêts, identifier les segments risqués et
détecter les signes de dégradation du crédit avant le défaut ?

## Données

| Source | Contenu | Accès |
|---|---|---|
| Freddie Mac SFLLD (échantillons annuels, 50 000 prêts par cohorte) | caractéristiques à l'octroi, performance mensuelle, pertes réalisées | gratuit, compte Clarity |
| FRED (Réserve fédérale de Saint-Louis) | chômage, taux immobilier 30 ans, Fed funds, indice Case-Shiller | gratuit, sans compte |

Les données Freddie Mac ne sont **pas** incluses dans ce dépôt : leurs conditions
d'utilisation interdisent la redistribution. Le code permet de reconstruire la base
à l'identique après téléchargement.

## Modèle de données

```
borrowers 1───1 loans 1───n loan_performance (une ligne par prêt et par mois)
                  │
                  ├──0..1 loan_outcomes (sortie du portefeuille, pertes)
                  └───n risk_ratings n───1 rating_scale
economic_indicators (une ligne par mois, jointure sur la période)
```

## Installation et exécution

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate    |   macOS / Linux : source .venv/bin/activate
pip install -r requirements.txt

# placer les ZIP Freddie Mac (ex. sample_2006.zip) dans data/raw/, puis :
python src/load_freddie.py          # construit data/processed/credit_risk.duckdb
python src/load_macro.py            # ajoute les indicateurs macro
python src/run_quality_checks.py    # contrôles qualité
python src/query.py sql/03_first_look.sql

# phase 2 : analyses du risque
python src/build_analytics.py       # tables et vues d'analyse + contrôles de cohérence
python src/query.py sql/12_phase2_report.sql
python src/make_figures.py          # graphiques dans docs/figures/
```

Sans les vraies données, on peut tester toute la chaîne sur de faux fichiers :
`python -m pytest -q`.

## Définition du défaut

Un prêt est en défaut le premier mois où il a **90 jours de retard ou plus**, où le
bien est **saisi**, ou où il **sort du portefeuille avec une perte** (codes Freddie Mac
02, 03, 09, 15). C'est la transposition du critère des 90 jours de l'article 178 du
règlement CRR. Le critère d'« improbabilité de paiement » (restructurations) n'est pas
retenu, faute d'information fiable : c'est une limite assumée.

## Analyses (phase 2)

| Question métier | Méthode | Fichier |
|---|---|---|
| Quelle cohorte fait le plus défaut, à ancienneté égale ? | Courbes de vintage « static pool », censure à droite | `sql/06_vintages.sql` |
| Quels profils d'emprunteurs sont les plus risqués ? | Taux de défaut par segment, intervalle de Wilson à 95 % | `sql/05_default_rates.sql` |
| Comment un retard évolue-t-il d'un mois à l'autre ? | Matrice de transition (roll rates) | `sql/07_roll_rates.sql` |
| Le portefeuille est-il concentré géographiquement ? | Part du top 5 / top 10, indice HHI | `sql/08_concentration.sql` |
| Quels signes annoncent un défaut ? | Backtest de signaux : taux de défaut à 12 mois et « lift » | `sql/09_early_warning.sql` |
| Que surveiller ce mois-ci ? | Reporting M / M-1 / M-12, segments les plus en retard | `sql/10_monthly_report.sql` |

Chaque résultat passe 13 contrôles de cohérence avant d'être affiché
(`sql/11_analytics_checks.sql`) : taux entre 0 et 100 %, courbes cumulées croissantes,
lignes de matrice à 100 %, somme des segments égale au total, etc.

![Courbes de vintage](docs/figures/01_vintage_curves.png)
![Signaux d'alerte](docs/figures/05_early_warning_signals.png)

## Structure

```
src/        scripts Python (chargement, contrôles, requêtes)
sql/        schéma, contrôles qualité, analyses
tests/      générateur de faux fichiers et test de bout en bout
notebooks/  modèle de PD (phase 3)
app/        tableau de bord web (phase 5)
docs/       méthodologie, définitions et graphiques (docs/figures)
```

## Feuille de route

- [x] Phase 1 — Base relationnelle, chargement, contrôles qualité
- [x] Phase 2 — Analyses SQL : défauts, encours, concentrations, retards, vintages, roll rates
- [ ] Phase 3 — Modèle de PD et échelle de notation interne
- [ ] Phase 4 — Migrations, perte attendue (PD × LGD × EAD), staging IFRS 9
- [ ] Phase 5 — Tableau de bord web (GitHub Pages) et reporting mensuel
