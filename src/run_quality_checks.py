"""Exécute des contrôles SQL (format « -- @check ») et affiche un rapport.

Utilisation :
    python src/run_quality_checks.py                          # contrôles des données (phase 1)
    python src/run_quality_checks.py 11_analytics_checks.sql  # contrôles des résultats (phase 2)

Le rapport est aussi enregistré dans data/processed/ (un CSV par fichier de contrôles).
Code de sortie 1 si un contrôle BLOQUANT échoue (utile pour l'automatisation).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, DB_PATH, SQL_DIR  # noqa: E402

CHECK_HEADER = re.compile(r"^--\s*@check\s+(\w+)\s*\|\s*(\w+)\s*\|\s*(.+)$", re.MULTILINE)


def parse_checks(sql_text: str) -> list[dict]:
    """Découpe le fichier SQL en contrôles (code, sévérité, description, requête)."""
    headers = list(CHECK_HEADER.finditer(sql_text))
    checks = []
    for i, h in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(sql_text)
        query = sql_text[h.end():end].strip().rstrip(";")
        checks.append({"code": h.group(1), "severity": h.group(2),
                       "description": h.group(3).strip(), "query": query})
    return checks


def run_checks(con: duckdb.DuckDBPyConnection, sql_file: str = "02_quality_checks.sql") -> pd.DataFrame:
    checks = parse_checks((SQL_DIR / sql_file).read_text(encoding="utf-8"))
    rows = []
    for c in checks:
        n = con.execute(c["query"]).fetchone()[0] or 0
        status = "OK" if n == 0 else ("ÉCHEC" if c["severity"] == "BLOQUANT" else "ALERTE")
        rows.append({"code": c["code"], "severity": c["severity"], "status": status,
                     "anomalies": n, "description": c["description"]})
    return pd.DataFrame(rows)


def print_report(report: pd.DataFrame) -> int:
    """Affiche le rapport et renvoie le nombre de contrôles bloquants en échec."""
    print(f"\n{'Code':<6} {'Statut':<7} {'Anomalies':>10}  Description")
    print("-" * 90)
    for r in report.itertuples():
        print(f"{r.code:<6} {r.status:<7} {r.anomalies:>10,}  {r.description}")
    n_fail = int((report["status"] == "ÉCHEC").sum())
    n_warn = int((report["status"] == "ALERTE").sum())
    print(f"\n{n_fail} contrôle(s) bloquant(s) en échec, {n_warn} alerte(s).")
    return n_fail


def main() -> None:
    sql_file = sys.argv[1] if len(sys.argv) > 1 else "02_quality_checks.sql"
    if not DB_PATH.exists():
        raise SystemExit("La base n'existe pas : lance d'abord  python src/load_freddie.py")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    report = run_checks(con, sql_file)
    con.close()
    report.to_csv(DATA_PROCESSED / f"report_{Path(sql_file).stem}.csv", index=False)
    n_fail = print_report(report)
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
