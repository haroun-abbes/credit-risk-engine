"""Phase 2 : construit la couche analytique puis vérifie la cohérence des résultats.

Utilisation (après load_freddie.py et load_macro.py) :
    python src/build_analytics.py

Étapes :
  1. exécute sql/04 à sql/10 dans l'ordre (tables dérivées et vues d'analyse) ;
  2. lance les contrôles de cohérence de sql/11_analytics_checks.sql ;
  3. affiche un résumé des premiers résultats.
Code de sortie 1 si un contrôle bloquant échoue.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, DB_PATH, SQL_DIR  # noqa: E402
from run_quality_checks import print_report, run_checks  # noqa: E402

ANALYTICS_FILES = [
    "04_analytics_base.sql",
    "05_default_rates.sql",
    "06_vintages.sql",
    "07_roll_rates.sql",
    "08_concentration.sql",
    "09_early_warning.sql",
    "10_monthly_report.sql",
]


def pct(x: float | None, digits: int = 2) -> str:
    return "n.d." if x is None else f"{100 * x:.{digits}f} %".replace(".", ",")


def num(x: float, digits: int = 0) -> str:
    """Nombre au format français : espace pour les milliers, virgule décimale."""
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit("La base n'existe pas : lance d'abord  python src/load_freddie.py")
    start = time.time()
    con = duckdb.connect(str(DB_PATH))

    print("1/3  Construction de la couche analytique")
    for name in ANALYTICS_FILES:
        t0 = time.time()
        con.execute((SQL_DIR / name).read_text(encoding="utf-8"))
        print(f"  {name:<26} ({time.time() - t0:.0f} s)")

    print("2/3  Contrôles de cohérence des résultats")
    report = run_checks(con, "11_analytics_checks.sql")
    report.to_csv(DATA_PROCESSED / "report_11_analytics_checks.csv", index=False)
    n_fail = print_report(report)

    print("\n3/3  Premiers résultats")
    tot = con.execute("""SELECT n_loans, n_defaults, default_rate FROM v_default_by_vintage
                         WHERE cohorte = 'Toutes'""").fetchone()
    print(f"  Prêts : {num(tot[0])}   défauts : {num(tot[1])}   taux de défaut observé : {pct(tot[2])}")
    for cohorte, n, k, rate in con.execute("""SELECT cohorte, n_loans, n_defaults, default_rate
                                              FROM v_default_by_vintage WHERE cohorte <> 'Toutes'""").fetchall():
        print(f"    cohorte {cohorte} : {num(k):>6} défauts sur {num(n)} prêts  ->  {pct(rate)}")
    snap = con.execute("SELECT snapshot_date, n_active, upb_musd FROM v_portfolio_snapshot").fetchone()
    print(f"  Date d'arrêté : {snap[0]}   prêts actifs : {num(snap[1])}   encours : {num(snap[2], 1)} M$")
    con.close()

    print(f"\nTerminé en {time.time() - start:.0f} s.")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
