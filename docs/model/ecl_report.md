# Phase 4 — Calibrage, perte attendue IFRS 9 et capital

Date d'arrêté : **01/03/2026**. Rapport généré par `src/build_ecl.py` ; toutes les valeurs sont recalculées à chaque exécution.

## 1. Calibrage de la PD

- Taux de défaut moyen de long terme (moyenne des taux annuels) : **1,75 %**.
- Décalage de la constante du modèle pour obtenir la PD TTC : **−0,393** (en logit).
- Modèle de Vasicek, corrélation ρ = 0,15 (valeur bâloise des crédits immobiliers).

Modèle satellite (Z expliqué par la conjoncture, 18 années, 2020 exclue) : Z = -0,170 − 0,012 × hausse du chômage + 6,980 × évolution des prix immobiliers ; R² = 0,58.

| Année | Taux observé | PD du modèle | PD TTC | Facteur Z | PD PIT (conjoncture) |
| --- | --- | --- | --- | --- | --- |
| 2007 | 0,90 % | 1,34 % | 0,93 % | -0,40 | 0,67 % |
| 2008 | 2,29 % | 2,02 % | 1,43 % | -0,95 | 1,73 % |
| 2009 | 5,35 % | 3,74 % | 2,76 % | -1,30 | 4,64 % |
| 2010 | 5,02 % | 5,09 % | 3,83 % | -0,74 | 4,08 % |
| 2011 | 4,51 % | 4,85 % | 3,62 % | -0,65 | 3,97 % |
| 2012 | 3,80 % | 4,33 % | 3,21 % | -0,57 | 3,40 % |
| 2013 | 1,21 % | 1,74 % | 1,26 % | -0,33 | 0,71 % |
| 2014 | 0,93 % | 1,91 % | 1,37 % | 0,08 | 0,62 % |
| 2015 | 0,74 % | 2,21 % | 1,57 % | 0,48 | 0,99 % |
| 2016 | 0,56 % | 2,05 % | 1,45 % | 0,70 | 0,86 % |
| 2017 | 0,70 % | 1,93 % | 1,36 % | 0,35 | 0,79 % |
| 2018 | 0,39 % | 1,37 % | 0,95 % | 0,50 | 0,48 % |
| 2019 | 0,47 % | 1,84 % | 1,29 % | 0,65 | 0,78 % |
| 2020 | 3,97 % | 2,37 % | 1,66 % | -1,42 | 1,06 % |
| 2021 | 0,72 % | 2,23 % | 1,57 % | 0,49 | 0,66 % |
| 2022 | 0,53 % | 1,99 % | 1,39 % | 0,61 | 0,30 % |
| 2023 | 0,41 % | 1,76 % | 1,23 % | 0,74 | 0,76 % |
| 2024 | 0,47 % | 1,76 % | 1,23 % | 0,59 | 0,65 % |
| 2025 | 0,35 % | 1,74 % | 1,21 % | 0,85 | 0,73 % |

## 2. Scénarios macroéconomiques

Hypothèses illustratives, à 12 mois. Elles ne sont pas des prévisions officielles.

| Scénario | Poids | Hausse du chômage | Prix immobiliers | Facteur Z | PD moyenne (prêts sains) | ECL |
| --- | --- | --- | --- | --- | --- | --- |
| Central | 60 % | 0,0 pt | +3 % | 0,04 | 1,12 % | 18,29 M$ |
| Adverse | 30 % | +2,0 pt | -5 % | -0,54 | 1,80 % | 23,92 M$ |
| Sévère | 10 % | +5,0 pt | -15 % | -1,28 | 3,26 % | 35,50 M$ |

**ECL pondérée retenue : 21,70 M$.**

## 3. LGD et EAD

LGD = pertes / exposition au défaut, sur les défauts résolus (les défauts guéris comptent avec une perte nulle). LGD de crise : défauts de 2008 à 2011.

| Tranche de CLTV | Défauts résolus | Taux de guérison | Sévérité si liquidation | LGD | LGD de crise retenue |
| --- | --- | --- | --- | --- | --- |
| 60 % ou moins | 1 702 | 69,5 % | 45,7 % | 12,5 % | 20,5 % |
| 61-80 % | 7 163 | 46,5 % | 57,3 % | 29,5 % | 41,0 % |
| 81-90 % | 2 680 | 38,7 % | 48,4 % | 28,6 % | 37,5 % |
| 91-95 % | 2 059 | 44,1 % | 40,6 % | 21,5 % | 32,7 % |
| Plus de 95 % | 1 898 | 39,1 % | 36,7 % | 22,2 % | 32,2 % |
| Tous | 15 502 | 46,5 % | 49,7 % | 25,8 % | 36,8 % |

Facteur d'EAD (encours au défaut / encours 12 mois avant) : **0,985** : l'EAD retenue est l'encours. La LGD n'augmente pas avec la CLTV au-delà de 80 % : chez Freddie Mac, ces prêts sont couverts par une assurance hypothécaire (mortgage insurance), dont les indemnités réduisent la perte. Remboursements anticipés : **15,1 % par an** (5 dernières années).

## 4. Staging IFRS 9

Règles, dans l'ordre : Stage 3 si 90 jours de retard ou plus ; Stage 2 si retard de 30 jours ou plus, sortie du défaut ou restructuration depuis moins de 2 ans (période probatoire), plan d'aide en cours, ou dégradation d'au moins 2 crans depuis l'octroi avec une PD d'au moins 1 % ; sinon Stage 1. La note « à l'octroi » est recalculée à ancienneté égale, sans les retards : la dégradation mesure donc le comportement de paiement.

| Stage | Prêts | Encours | Part de l'encours | ECL | Part de l'ECL | Couverture |
| --- | --- | --- | --- | --- | --- | --- |
| Stage 1 | 23 484 | 2 750,8 M$ | 95,5 % | 7,84 M$ | 36,1 % | 0,28 % |
| Stage 2 | 689 | 101,7 M$ | 3,5 % | 7,11 M$ | 32,8 % | 7,00 % |
| Stage 3 | 166 | 27,3 M$ | 0,9 % | 6,75 M$ | 31,1 % | 24,78 % |

| Stage | Motif | Prêts | Encours |
| --- | --- | --- | --- |
| 1 | Pas de dégradation significative | 23 484 | 2 750,8 M$ |
| 2 | Retard de 30 jours ou plus | 363 | 50,5 M$ |
| 2 | Sorti du défaut depuis moins de 2 ans (période probatoire) | 240 | 39,8 M$ |
| 2 | Hausse significative du risque (SICR) | 75 | 9,4 M$ |
| 2 | Restructuré depuis moins de 2 ans ou plan d'aide en cours | 11 | 2,0 M$ |
| 3 | 90 jours de retard ou plus (défaut) | 166 | 27,3 M$ |

## 5. Migrations annuelles entre classes (PD TTC)

| Période | Observations | Amélioration | Stable | Dégradation (y c. défaut) |
| --- | --- | --- | --- | --- |
| Toutes années | 844 669 | 6,5 % | 65,3 % | 28,2 % |
| Crise (2008-2010) | 187 446 | 5,4 % | 51,9 % | 42,7 % |
| Calme (2015-2019) | 275 023 | 7,1 % | 71,4 % | 21,5 % |

Les dégradations s'expliquent surtout par le **vieillissement des prêts**. Le risque d'un crédit immobilier culmine entre 24 et 36 mois d'ancienneté ; en un an, un prêt récent change de tranche d'ancienneté dans le modèle. **95 %** des dégradations (hors défaut) coïncident avec un tel changement de tranche.

Matrice toutes années (% de chaque ligne) :

| De \ vers | R1 | R2 | R3 | R4 | R5 | R6 | R7 | R8 | Défaut | Sorti |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | 57,4 | 27,7 | 0,3 | 0,0 | 0,1 | 0,0 | 0,0 | 0,0 | 0,1 | 14,4 |
| R2 | 2,3 | 50,9 | 29,9 | 0,6 | 0,1 | 0,1 | 0,1 | 0,0 | 0,2 | 15,9 |
| R3 | 0,0 | 3,5 | 54,2 | 23,1 | 0,8 | 0,1 | 0,3 | 0,1 | 0,6 | 17,2 |
| R4 | 0,0 | 0,1 | 5,2 | 55,8 | 16,6 | 0,6 | 0,6 | 0,7 | 1,6 | 18,9 |
| R5 | 0,0 | 0,0 | 0,7 | 9,8 | 59,5 | 4,0 | 1,0 | 2,3 | 3,6 | 19,0 |
| R6 | 0,0 | 0,0 | 0,5 | 3,3 | 34,5 | 25,8 | 3,5 | 8,9 | 10,4 | 13,0 |
| R7 | 0,0 | 0,0 | 0,1 | 4,4 | 26,1 | 12,9 | 11,6 | 11,5 | 25,4 | 8,0 |
| R8 | 0,0 | 0,0 | 0,0 | 0,3 | 9,1 | 15,5 | 5,1 | 22,2 | 44,0 | 3,8 |

## 6. Capital réglementaire (approche IRB, prêts sains)

PD TTC (plancher 0,05 %), LGD de crise (plancher 10 %), ρ = 0,15, quantile 99,9 %.

- Perte attendue réglementaire (EL) : **19,02 M$**
- Actifs pondérés (RWA) : **1 443,3 M$**, soit une densité de 50,6 % de l'encours sain
- Fonds propres à 8 % des RWA : **115,5 M$**

## 7. Limites

- La PD TTC contient des variables de comportement (retard du mois), elle-mêmes sensibles au cycle : c'est une PD hybride, plus proche du TTC que du PIT.
- Le modèle satellite repose sur une vingtaine de points annuels : ses coefficients sont indicatifs.
- Les scénarios sont des hypothèses illustratives ; une banque utilise ceux de sa direction économique.
- Le scénario central donne une PD moyenne supérieure aux taux de défaut observés récemment (0,35 % la dernière année complète) : la constante du modèle satellite est estimée sur un cycle qui inclut la crise de 2008, et il n'explique pas tout le niveau très bas des défauts depuis 2013 (octrois plus prudents). Une banque corrigerait ce point par un ajustement post-modèle (overlay) documenté ; la provision calculée ici est donc prudente.
- Le modèle satellite relie le facteur de l'année aux évolutions macroéconomiques des 12 mois précédents ; les scénarios appliquent la même convention.
- Les PD des années 2 et suivantes reviennent vers la PD TTC « assainie » : simplification courante.
- LGD : coûts internes de recouvrement et actualisation des flux non inclus ; la LGD de crise est mesurée sur les défauts de 2008 à 2011.
