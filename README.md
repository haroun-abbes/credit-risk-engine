# Credit Risk Analytics Engine

Surveillance du risque de crédit d'un portefeuille de prêts immobiliers à partir des
données granulaires de Freddie Mac (Single-Family Loan-Level Dataset) : taux de défaut,
concentrations, signaux d'alerte, migrations de notation, perte attendue et staging IFRS 9.

> Projet en cours de construction. Phase actuelle : **1 — base de données et qualité**.

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
```

Sans les vraies données, on peut tester toute la chaîne sur de faux fichiers :
`python -m pytest -q`.

## Structure

```
src/        scripts Python (chargement, contrôles, requêtes)
sql/        schéma, contrôles qualité, analyses
tests/      générateur de faux fichiers et test de bout en bout
notebooks/  modèle de PD (phase 3)
app/        tableau de bord Streamlit (phase 5)
docs/       méthodologie et définitions
```

## Feuille de route

- [x] Phase 1 — Base relationnelle, chargement, contrôles qualité
- [ ] Phase 2 — Analyses SQL : défauts, encours, concentrations, retards, vintages, roll rates
- [ ] Phase 3 — Modèle de PD et échelle de notation interne
- [ ] Phase 4 — Migrations, perte attendue (PD × LGD × EAD), staging IFRS 9
- [ ] Phase 5 — Tableau de bord Streamlit et reporting mensuel
