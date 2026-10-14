# Modèle de PD à 12 mois — rapport de développement

Version `pd-logit-woe-v2`. Rapport généré automatiquement par `src/train_pd_model.py` : toutes les valeurs sont recalculées à chaque exécution.

## 1. Données

Une observation = un prêt sain (pas encore en défaut) observé en janvier d'une année. Cible = défaut (90 jours de retard ou sortie avec perte) dans les 12 mois suivants.

| Échantillon | Période d'observation | Observations | Défauts | Taux de défaut |
| --- | --- | --- | --- | --- |
| Apprentissage | 2006-2014 | 359 565 | 10 680 | 2,97 % |
| Validation | 2006-2014 | 120 363 | 3 598 | 2,99 % |
| Hors période | 2015-2025 | 538 989 | 5 248 | 0,97 % |

## 2. Pouvoir discriminant des variables (Information Value)

| Variable | IV | Lecture | Retenue |
| --- | --- | --- | --- |
| Retard ce mois-ci | 1,369 | Très fort | oui |
| Pire retard des 12 derniers mois | 1,025 | Très fort | oui |
| Score FICO à l'octroi | 0,584 | Très fort | oui |
| Évolution des prix immobiliers sur 12 mois | 0,372 | Fort | retirée : conjoncture : prise en compte en phase 4 |
| Ancienneté du prêt (mois) | 0,288 | Moyen | oui |
| Taux de chômage US (%) | 0,247 | Moyen | retirée : conjoncture : prise en compte en phase 4 |
| Taux d'endettement DTI (%) | 0,211 | Moyen | oui |
| CLTV à l'octroi (%) | 0,154 | Moyen | oui |
| Écart de taux à l'octroi, SATO (points) | 0,097 | Faible | oui |
| Nombre d'emprunteurs | 0,060 | Faible | oui |
| Canal de distribution | 0,052 | Faible | oui |
| Objet du prêt | 0,047 | Faible | oui |
| Occupation du bien | 0,006 | Inutile | retirée : IV < 0,02 |
| Prêt déjà modifié | 0,004 | Inutile | retirée : IV < 0,02 |
| Plan d'aide en cours | 0,000 | Inutile | retirée : IV < 0,02 |

## 3. Modèle (régression logistique sur les WoE)

Avec la convention WoE = ln(% bons / % mauvais), chaque coefficient doit être négatif.

| Variable | Coefficient | Erreur type | p-value |
| --- | --- | --- | --- |
| Constante | -3,4676 | 0,0121 | 0,0e+00 |
| Retard ce mois-ci | -0,6790 | 0,0095 | 0,0e+00 |
| Pire retard des 12 derniers mois | -0,3272 | 0,0121 | 1,4 e-160 |
| Score FICO à l'octroi | -0,5188 | 0,0165 | 3,9 e-217 |
| Ancienneté du prêt (mois) | -0,6084 | 0,0225 | 8,0 e-161 |
| Taux d'endettement DTI (%) | -0,5761 | 0,0260 | 7,5 e-109 |
| CLTV à l'octroi (%) | -0,8815 | 0,0339 | 1,9 e-149 |
| Écart de taux à l'octroi, SATO (points) | -0,5597 | 0,0366 | 9,3 e-53 |
| Nombre d'emprunteurs | -0,7745 | 0,0451 | 5,7 e-66 |
| Canal de distribution | -0,4678 | 0,0492 | 2,0 e-21 |
| Objet du prêt | -0,5613 | 0,0542 | 3,6 e-25 |

## 4. Performance

| Échantillon | AUC | Gini | KS |
| --- | --- | --- | --- |
| Apprentissage | 0,854 | 70,8 % | 52,3 % |
| Validation | 0,844 | 68,7 % | 50,1 % |
| Hors période | 0,812 | 62,3 % | 46,9 % |

Modèle challenger (gradient boosting, variables brutes), AUC hors période : **0,797**, contre 0,812 pour la régression logistique.

## 5. Calibration par année d'observation

| Année | Observations | Taux observé | PD moyenne prédite |
| --- | --- | --- | --- |
| 2006 | 52 | 0,00 % | 1,05 % |
| 2007 | 45 744 | 0,90 % | 1,34 % |
| 2008 | 89 586 | 2,29 % | 2,02 % |
| 2009 | 79 779 | 5,35 % | 3,74 % |
| 2010 | 58 051 | 5,02 % | 5,09 % |
| 2011 | 43 047 | 4,51 % | 4,85 % |
| 2012 | 33 760 | 3,80 % | 4,33 % |
| 2013 | 69 754 | 1,21 % | 1,74 % |
| 2014 | 60 155 | 0,93 % | 1,91 % |
| 2015 | 54 309 | 0,74 % | 2,21 % |
| 2016 | 48 451 | 0,56 % | 2,05 % |
| 2017 | 42 003 | 0,70 % | 1,93 % |
| 2018 | 84 786 | 0,39 % | 1,37 % |
| 2019 | 78 509 | 0,47 % | 1,84 % |
| 2020 | 68 818 | 3,97 % | 2,37 % |
| 2021 | 47 462 | 0,72 % | 2,23 % |
| 2022 | 33 952 | 0,53 % | 1,99 % |
| 2023 | 29 271 | 0,41 % | 1,76 % |
| 2024 | 26 855 | 0,47 % | 1,76 % |
| 2025 | 24 573 | 0,35 % | 1,74 % |

## 6. Échelle de notation (échantillon hors période)

| Classe | PD de la classe | Part des prêts | PD moyenne prédite | Taux de défaut observé |
| --- | --- | --- | --- | --- |
| R1 | 0,00 % à 0,25 % | 4,6 % | 0,19 % | 0,06 % |
| R2 | 0,25 % à 0,50 % | 12,3 % | 0,38 % | 0,16 % |
| R3 | 0,50 % à 1,00 % | 25,4 % | 0,74 % | 0,28 % |
| R4 | 1,00 % à 2,00 % | 30,5 % | 1,44 % | 0,55 % |
| R5 | 2,00 % à 5,00 % | 23,2 % | 2,96 % | 1,47 % |
| R6 | 5,00 % à 10,00 % | 2,8 % | 6,37 % | 4,20 % |
| R7 | 10,00 % à 25,00 % | 0,5 % | 15,07 % | 11,93 % |
| R8 | 25,00 % à 100,00 % | 0,6 % | 46,52 % | 29,85 % |

Stabilité de la répartition par classe entre apprentissage et hors période : PSI = **0,064** (< 0,10 stable ; 0,10 à 0,25 à surveiller ; > 0,25 instable).

## 7. Grille de points (600 points = 50 bons pour 1 mauvais, +20 points = cote doublée)

| Variable | Classe | Part | Taux de défaut | Points |
| --- | --- | --- | --- | --- |
| Retard ce mois-ci | À jour | 97,5 % | 1,94 % | 67 |
| Retard ce mois-ci | 30-59 jours | 2,0 % | 33,69 % | 4 |
| Retard ce mois-ci | 60-89 jours | 0,6 % | 73,37 % | -29 |
| Pire retard des 12 derniers mois | Aucun retard | 94,1 % | 1,83 % | 63 |
| Pire retard des 12 derniers mois | 30 jours max | 4,9 % | 17,79 % | 40 |
| Pire retard des 12 derniers mois | 60 jours ou plus | 1,0 % | 36,69 % | 31 |
| Score FICO à l'octroi | < 620 | 3,7 % | 7,95 % | 43 |
| Score FICO à l'octroi | 620 à 660 | 9,6 % | 6,75 % | 46 |
| Score FICO à l'octroi | 660 à 700 | 17,1 % | 4,76 % | 51 |
| Score FICO à l'octroi | 700 à 740 | 20,6 % | 3,14 % | 58 |
| Score FICO à l'octroi | 740 à 780 | 24,9 % | 1,63 % | 68 |
| Score FICO à l'octroi | ≥ 780 | 24,1 % | 0,68 % | 81 |
| Score FICO à l'octroi | Manquant | 0,1 % | 0,74 % | 59 |
| Ancienneté du prêt (mois) | < 12 | 29,1 % | 1,14 % | 76 |
| Ancienneté du prêt (mois) | 12 à 24 | 27,2 % | 2,71 % | 60 |
| Ancienneté du prêt (mois) | 24 à 36 | 14,3 % | 5,18 % | 49 |
| Ancienneté du prêt (mois) | 36 à 60 | 18,3 % | 4,49 % | 51 |
| Ancienneté du prêt (mois) | 60 à 120 | 11,1 % | 3,06 % | 58 |
| Taux d'endettement DTI (%) | < 20 | 9,0 % | 1,26 % | 73 |
| Taux d'endettement DTI (%) | 20 à 30 | 20,0 % | 1,80 % | 67 |
| Taux d'endettement DTI (%) | 30 à 40 | 27,0 % | 2,98 % | 59 |
| Taux d'endettement DTI (%) | 40 à 45 | 12,9 % | 3,82 % | 54 |
| Taux d'endettement DTI (%) | ≥ 45 | 22,3 % | 4,84 % | 50 |
| Taux d'endettement DTI (%) | Manquant | 8,7 % | 1,35 % | 72 |
| CLTV à l'octroi (%) | < 60 | 21,4 % | 1,23 % | 82 |
| CLTV à l'octroi (%) | 60 à 80 | 29,0 % | 3,04 % | 58 |
| CLTV à l'octroi (%) | 80 à 90 | 24,0 % | 3,21 % | 57 |
| CLTV à l'octroi (%) | 90 à 95 | 9,5 % | 4,31 % | 49 |
| CLTV à l'octroi (%) | ≥ 95 | 16,1 % | 4,02 % | 51 |
| CLTV à l'octroi (%) | Manquant | 0,0 % | 0,00 % | 59 |
| Écart de taux à l'octroi, SATO (points) | < -0.25 | 27,1 % | 1,91 % | 66 |
| Écart de taux à l'octroi, SATO (points) | -0.25 à +0.00 | 24,6 % | 2,58 % | 61 |
| Écart de taux à l'octroi, SATO (points) | +0.00 à +0.25 | 26,2 % | 3,31 % | 57 |
| Écart de taux à l'octroi, SATO (points) | +0.25 à +0.50 | 12,4 % | 3,82 % | 55 |
| Écart de taux à l'octroi, SATO (points) | ≥ +0.50 | 9,7 % | 4,90 % | 50 |
| Nombre d'emprunteurs | 2 emprunteurs ou plus | 53,6 % | 2,31 % | 64 |
| Nombre d'emprunteurs | Autre | 0,0 % | 0,00 % | 59 |
| Nombre d'emprunteurs | 1 emprunteur | 46,4 % | 3,73 % | 53 |
| Canal de distribution | Agence (retail) | 48,4 % | 2,30 % | 62 |
| Canal de distribution | Intermédiaire | 51,6 % | 3,60 % | 56 |
| Objet du prêt | No cash-out refi | 27,3 % | 2,26 % | 63 |
| Objet du prêt | Purchase | 39,6 % | 2,75 % | 60 |
| Objet du prêt | Cash-out refi | 33,0 % | 3,82 % | 54 |

## 8. Variante écartée : modèle avec variables de conjoncture

Le chômage et l'évolution des prix immobiliers ne prennent qu'une valeur par date d'observation : sur 9 années d'apprentissage, leurs classes reviennent surtout à reconnaître l'année. Le modèle principal les exclut ; la conjoncture sera intégrée en phase 4 (recalibrage et scénarios IFRS 9). Comparaison :

| Échantillon | Gini modèle principal | Gini avec conjoncture |
| --- | --- | --- |
| Apprentissage | 70,8 % | 72,1 % |
| Validation | 68,7 % | 69,9 % |
| Hors période | 62,3 % | 59,2 % |

Écart moyen hors période entre PD prédite et taux observé (par année) : 1,38 point pour le modèle principal, 0,71 point avec conjoncture.

