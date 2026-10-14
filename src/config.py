"""Paramètres centraux du projet : chemins et format des fichiers Freddie Mac.

Les fichiers Freddie Mac n'ont PAS de ligne d'en-tête : l'ordre des colonnes
ci-dessous suit le "General User Guide", Release 47 (juillet 2026).
Si Freddie Mac change le format, c'est le seul fichier à modifier.
"""
import os
from pathlib import Path

# --- Chemins -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
# La variable d'environnement CRE_DATA_DIR permet aux tests d'utiliser un autre dossier
DATA_DIR = Path(os.environ.get("CRE_DATA_DIR", ROOT / "data"))
DATA_RAW = DATA_DIR / "raw"                 # ZIP téléchargés depuis Clarity
DATA_INTERIM = DATA_DIR / "interim"         # fichiers .txt décompressés
DATA_PROCESSED = DATA_DIR / "processed"
DB_PATH = DATA_PROCESSED / "credit_risk.duckdb"
SQL_DIR = ROOT / "sql"

# --- Fichier d'origination (31 colonnes, séparateur "|") ----------------------
ORIGINATION_COLUMNS = [
    "fico",                     # 1  Classic FICO (9999 = non disponible)
    "first_payment_date",       # 2  YYYYMM
    "first_time_buyer",         # 3  Y / N / 9
    "maturity_date",            # 4  YYYYMM
    "msa_code",                 # 5
    "mi_pct",                   # 6  % assurance hypothécaire (999 = n.d.)
    "n_units",                  # 7  (99 = n.d.)
    "occupancy",                # 8  P / I / S / 9
    "cltv",                     # 9  (999 = n.d.)
    "dti",                      # 10 (999 = n.d.)
    "original_upb",             # 11 montant initial
    "ltv",                      # 12 (999 = n.d.)
    "original_rate",            # 13 taux nominal
    "channel",                  # 14 R / B / C / T / 9
    "prepayment_penalty",       # 15 Y / N
    "amortization_type",        # 16 FRM / ARM
    "property_state",           # 17
    "property_type",            # 18 SF / CO / PU / CP / MH / 99
    "postal_code",              # 19 3 premiers chiffres
    "loan_id",                  # 20 identifiant du prêt
    "loan_purpose",             # 21 P / C / N / R / 9
    "original_term",            # 22 en mois
    "n_borrowers",              # 23 (99 = n.d.)
    "seller_name",              # 24
    "super_conforming",         # 25
    "pre_harp_loan_id",         # 26
    "special_program",          # 27
    "harp_indicator",           # 28
    "valuation_method",         # 29
    "interest_only",            # 30
    "vantage_score",            # 31 VantageScore 4.0 (9999 = n.d.)
]

# --- Fichier de performance mensuelle (35 colonnes) ---------------------------
PERFORMANCE_COLUMNS = [
    "loan_id",                      # 1
    "period",                       # 2  YYYYMM
    "current_upb",                  # 3  encours fin de mois
    "delinquency_status",           # 4  0,1,2,... mois de retard ; RA ; XX
    "loan_age",                     # 5
    "remaining_months",             # 6
    "defect_settlement_date",       # 7
    "modification_flag",            # 8  Y / P / vide
    "zero_balance_code",            # 9  01,02,03,09,15,16,96
    "zero_balance_date",            # 10 YYYYMM
    "current_rate",                 # 11
    "non_interest_bearing_upb",     # 12
    "ddlpi",                        # 13 date de la dernière échéance payée
    "mi_recoveries",                # 14
    "net_sale_proceeds",            # 15
    "non_mi_recoveries",            # 16
    "total_expenses",               # 17
    "legal_costs",                  # 18
    "maintenance_costs",            # 19
    "taxes_insurance",              # 20
    "misc_expenses",                # 21
    "actual_loss",                  # 22
    "cumulative_mod_costs",         # 23
    "step_rate_indicator",          # 24
    "payment_deferral",             # 25
    "eltv",                         # 26 LTV estimée (999 = n.d.)
    "zero_balance_removal_upb",     # 27
    "delinquent_accrued_interest",  # 28
    "disaster_delinquency",         # 29
    "borrower_assistance",          # 30 F / R / T / vide
    "current_period_mod_costs",     # 31
    "interest_bearing_upb",         # 32
    "mi_cancellation",              # 33
    "servicer_name",                # 34
    "bankruptcy_cramdown_costs",    # 35
]

# --- Indicateurs macroéconomiques (FRED, téléchargement CSV sans compte) ------
FRED_SERIES = {
    "UNRATE": "unemployment_rate",        # taux de chômage US, mensuel, %
    "MORTGAGE30US": "mortgage_rate_30y",  # taux moyen crédit immo 30 ans, hebdo -> mensuel
    "FEDFUNDS": "fed_funds_rate",         # taux directeur effectif, mensuel, %
    "CSUSHPINSA": "house_price_index",    # indice Case-Shiller national, mensuel
}
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
