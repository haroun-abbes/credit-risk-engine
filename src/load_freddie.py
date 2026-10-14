"""Construit la base DuckDB à partir des fichiers Freddie Mac.

Utilisation (depuis la racine du projet) :
    python src/load_freddie.py

Ce que fait le script :
  1. décompresse les ZIP présents dans data/raw/ vers data/interim/ ;
  2. associe chaque fichier d'origination à son fichier de performance ;
  3. (re)crée la base data/processed/credit_risk.duckdb avec sql/01_schema.sql ;
  4. nettoie les données (codes "non disponible" -> NULL, dates, libellés)
     et les insère dans borrowers, loans, loan_performance et loan_outcomes.

La base est reconstruite de zéro à chaque exécution : le résultat est donc
toujours reproductible à partir des fichiers bruts.
"""
from __future__ import annotations

import re
import sys
import time
import zipfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    DATA_INTERIM,
    DATA_RAW,
    DB_PATH,
    ORIGINATION_COLUMNS,
    PERFORMANCE_COLUMNS,
    SQL_DIR,
)

# ---------------------------------------------------------------------------
# 1. Repérage des fichiers
# ---------------------------------------------------------------------------

def extract_zips() -> None:
    """Décompresse chaque ZIP de data/raw dans son propre sous-dossier de data/interim."""
    for zip_path in sorted(DATA_RAW.glob("*.zip")):
        target = DATA_INTERIM / zip_path.stem
        if target.exists() and any(target.iterdir()):
            print(f"  déjà décompressé : {zip_path.name}")
            continue
        target.mkdir(parents=True, exist_ok=True)
        print(f"  décompression : {zip_path.name}")
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                # on n'extrait que des .txt à plat (protection contre les chemins piégés)
                name = Path(member).name
                if name.lower().endswith(".txt"):
                    with zf.open(member) as src, open(target / name, "wb") as dst:
                        dst.write(src.read())


def find_file_pairs() -> list[tuple[Path, Path]]:
    """Retourne les couples (fichier origination, fichier performance).

    Formats reconnus :
      sample_orig_2006.txt  <->  sample_perf_2006.txt (ou sample_svcg_2006.txt, ancien nom)
      orig_2006Q1.txt       <->  perf_2006Q1.txt
    """
    candidates = list(DATA_INTERIM.rglob("*.txt")) + list(DATA_RAW.glob("*.txt"))
    origination = [p for p in candidates if re.search(r"(^|_)orig_", p.name)]
    pairs = []
    for orig in sorted(origination):
        perf = None
        for token in ("perf", "svcg"):
            candidate = orig.with_name(re.sub(r"orig_", f"{token}_", orig.name, count=1))
            if candidate.exists():
                perf = candidate
                break
        if perf is None:
            print(f"  ATTENTION : pas de fichier de performance pour {orig.name}, ignoré")
            continue
        pairs.append((orig, perf))
    return pairs


def check_column_count(path: Path, expected: list[str]) -> None:
    """Vérifie que le fichier a bien le nombre de colonnes attendu par config.py."""
    with open(path, encoding="latin-1") as f:
        first_line = f.readline().rstrip("\r\n")
    found = first_line.count("|") + 1
    if found != len(expected):
        raise SystemExit(
            f"\nERREUR : {path.name} contient {found} colonnes, {len(expected)} attendues.\n"
            "Freddie Mac a peut-être modifié le format. Compare la première ligne du\n"
            "fichier avec le 'file layout' publié sur la page du dataset, puis mets à\n"
            "jour la liste correspondante dans src/config.py.\n"
            f"Première ligne : {first_line[:200]}"
        )


# ---------------------------------------------------------------------------
# 2. Transformations SQL
# ---------------------------------------------------------------------------

def read_csv_sql(path: Path, columns: list[str]) -> str:
    """Expression DuckDB qui lit un fichier Freddie Mac (sans en-tête, séparateur |)."""
    cols = ", ".join(f"'{c}': 'VARCHAR'" for c in columns)
    p = path.as_posix().replace("'", "''")
    return (
        f"read_csv('{p}', delim='|', header=false, quote='', escape='', "
        f"columns={{{cols}}}, encoding='latin-1')"
    )


MACROS = """
-- 'YYYYMM' -> DATE (premier jour du mois)
CREATE OR REPLACE TEMP MACRO ym(x) AS TRY_STRPTIME(x || '01', '%Y%m%d')::DATE;
-- convertit en entier et remplace un code "non disponible" par NULL
CREATE OR REPLACE TEMP MACRO int_na(x, na_code) AS NULLIF(TRY_CAST(x AS INTEGER), na_code);
CREATE OR REPLACE TEMP MACRO money(x) AS TRY_CAST(x AS DECIMAL(14, 2));
"""

INSERT_BORROWERS = """
INSERT INTO borrowers
SELECT
    loan_id                                   AS borrower_id,
    int_na(fico, 9999)                        AS fico_score,
    int_na(vantage_score, 9999)               AS vantage_score,
    int_na(dti, 999)                          AS dti_pct,
    CASE first_time_buyer WHEN 'Y' THEN TRUE WHEN 'N' THEN FALSE END,
    int_na(n_borrowers, 99)                   AS n_borrowers
FROM stg_orig;
"""

INSERT_LOANS = """
INSERT INTO loans
SELECT
    loan_id,
    loan_id                                   AS borrower_id,
    -- l'identifiant encode la cohorte : F + AA + Qn + 7 chiffres (ex. F06Q3...)
    CASE WHEN TRY_CAST(substr(loan_id, 2, 2) AS INT) >= 90
         THEN 1900 ELSE 2000 END + TRY_CAST(substr(loan_id, 2, 2) AS INT)   AS vintage_year,
    CAST(CASE WHEN TRY_CAST(substr(loan_id, 2, 2) AS INT) >= 90
         THEN 1900 ELSE 2000 END + TRY_CAST(substr(loan_id, 2, 2) AS INT) AS VARCHAR)
        || substr(loan_id, 4, 2)              AS vintage_quarter,
    ym(first_payment_date),
    ym(maturity_date),
    money(original_upb),
    TRY_CAST(original_rate AS DECIMAL(6, 3)),
    TRY_CAST(original_term AS SMALLINT),
    int_na(ltv, 999),
    int_na(cltv, 999),
    int_na(mi_pct, 999),
    CASE loan_purpose WHEN 'P' THEN 'Purchase' WHEN 'C' THEN 'Cash-out refi'
                      WHEN 'N' THEN 'No cash-out refi' WHEN 'R' THEN 'Refi (unspecified)' END,
    CASE channel WHEN 'R' THEN 'Retail' WHEN 'B' THEN 'Broker'
                 WHEN 'C' THEN 'Correspondent' WHEN 'T' THEN 'Third party (unspecified)' END,
    CASE occupancy WHEN 'P' THEN 'Primary residence' WHEN 'I' THEN 'Investment'
                   WHEN 'S' THEN 'Second home' END,
    CASE property_type WHEN 'SF' THEN 'Single-family' WHEN 'CO' THEN 'Condo'
                       WHEN 'PU' THEN 'PUD' WHEN 'CP' THEN 'Co-op'
                       WHEN 'MH' THEN 'Manufactured housing' END,
    int_na(n_units, 99),
    property_state,
    msa_code,
    NULLIF(postal_code, '000'),
    seller_name
FROM stg_orig;
"""

INSERT_PERFORMANCE = """
INSERT INTO loan_performance
SELECT
    p.loan_id,
    ym(p.period)                                         AS period,
    money(p.current_upb),
    p.delinquency_status,
    TRY_CAST(p.delinquency_status AS SMALLINT)           AS months_delinquent,
    p.delinquency_status = 'RA'                          AS is_reo,
    TRY_CAST(p.loan_age AS SMALLINT),
    TRY_CAST(p.remaining_months AS SMALLINT),
    TRY_CAST(p.current_rate AS DECIMAL(6, 3)),
    int_na(p.eltv, 999),
    p.modification_flag,
    p.payment_deferral,
    p.borrower_assistance,
    p.zero_balance_code,
    ym(p.zero_balance_date),
    p.servicer_name
FROM stg_perf AS p
-- par sécurité : on ne garde que les prêts présents dans le fichier d'origination
SEMI JOIN stg_orig AS o ON o.loan_id = p.loan_id
-- et une seule ligne par prêt et par mois
QUALIFY row_number() OVER (PARTITION BY p.loan_id, p.period ORDER BY p.loan_age DESC) = 1;
"""

INSERT_OUTCOMES = """
INSERT INTO loan_outcomes
SELECT
    loan_id,
    zero_balance_code,
    CASE zero_balance_code
        WHEN '01' THEN 'Prepaid or matured'
        WHEN '02' THEN 'Third party sale'
        WHEN '03' THEN 'Short sale or charge-off'
        WHEN '09' THEN 'REO disposition'
        WHEN '15' THEN 'Whole loan sale'
        WHEN '16' THEN 'Reperforming loan securitization'
        WHEN '96' THEN 'Defect (repurchase)'
        ELSE 'Other'
    END,
    ym(zero_balance_date),
    money(zero_balance_removal_upb),
    money(net_sale_proceeds),
    money(mi_recoveries),
    money(non_mi_recoveries),
    money(total_expenses),
    money(delinquent_accrued_interest),
    money(actual_loss)
FROM stg_perf AS p
SEMI JOIN stg_orig AS o ON o.loan_id = p.loan_id
WHERE zero_balance_code IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY loan_id ORDER BY period DESC) = 1;
"""


# ---------------------------------------------------------------------------
# 3. Programme principal
# ---------------------------------------------------------------------------

def main() -> None:
    start = time.time()
    print("1/4  Recherche des fichiers")
    DATA_INTERIM.mkdir(parents=True, exist_ok=True)
    extract_zips()
    pairs = find_file_pairs()
    if not pairs:
        raise SystemExit(
            "\nAucun fichier trouvé. Place les ZIP téléchargés (ex. sample_2006.zip)\n"
            f"dans le dossier : {DATA_RAW}"
        )
    for orig, perf in pairs:
        check_column_count(orig, ORIGINATION_COLUMNS)
        check_column_count(perf, PERFORMANCE_COLUMNS)
        print(f"  OK : {orig.name}  +  {perf.name}")

    print("2/4  Création de la base")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", ".wal"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute((SQL_DIR / "01_schema.sql").read_text(encoding="utf-8"))
    con.execute(MACROS)

    print("3/4  Chargement des données")
    for orig, perf in pairs:
        t0 = time.time()
        con.execute(f"CREATE OR REPLACE TEMP TABLE stg_orig AS SELECT * FROM {read_csv_sql(orig, ORIGINATION_COLUMNS)}")
        con.execute(f"CREATE OR REPLACE TEMP TABLE stg_perf AS SELECT * FROM {read_csv_sql(perf, PERFORMANCE_COLUMNS)}")
        con.execute(INSERT_BORROWERS)
        con.execute(INSERT_LOANS)
        con.execute(INSERT_PERFORMANCE)
        con.execute(INSERT_OUTCOMES)
        n_loans = con.execute("SELECT count(*) FROM stg_orig").fetchone()[0]
        n_rows = con.execute("SELECT count(*) FROM stg_perf").fetchone()[0]
        print(f"  {orig.name:<28} {n_loans:>9,} prêts  {n_rows:>12,} lignes mensuelles  ({time.time() - t0:.0f} s)")
    con.execute("DROP TABLE stg_orig; DROP TABLE stg_perf;")

    print("4/4  Résumé")
    for table in ("borrowers", "loans", "loan_performance", "loan_outcomes"):
        n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table:<20} {n:>12,} lignes")
    con.close()
    print(f"\nTerminé en {time.time() - start:.0f} s. Base : {DB_PATH}")


if __name__ == "__main__":
    main()
