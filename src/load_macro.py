"""Télécharge les indicateurs macroéconomiques depuis FRED et les charge dans la base.

Utilisation (après load_freddie.py) :
    python src/load_macro.py

FRED (Réserve fédérale de Saint-Louis) permet de télécharger chaque série en CSV
sans compte ni clé d'API. Les séries hebdomadaires sont ramenées en moyenne mensuelle.
"""
from __future__ import annotations

import io
import sys
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DATA_PROCESSED, DB_PATH, FRED_SERIES, FRED_URL  # noqa: E402

CACHE = DATA_PROCESSED / "macro_fred.csv"


def download_series(series_id: str) -> pd.Series:
    # un en-tête "navigateur" évite que certains serveurs refusent la requête
    req = urllib.request.Request(FRED_URL.format(series=series_id),
                                 headers={"User-Agent": "Mozilla/5.0 (credit-risk-engine)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        df = pd.read_csv(io.BytesIO(resp.read()), na_values=["."])
    date_col, value_col = df.columns[0], df.columns[1]   # observation_date, <SERIE>
    s = pd.Series(pd.to_numeric(df[value_col], errors="coerce").values,
                  index=pd.to_datetime(df[date_col]), name=series_id)
    return s.resample("MS").mean()                         # MS = début de mois


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit("La base n'existe pas encore : lance d'abord  python src/load_freddie.py")

    try:
        frames = []
        for series_id, column in FRED_SERIES.items():
            print(f"  téléchargement {series_id:<12} -> {column}")
            frames.append(download_series(series_id).rename(column))
        macro = pd.concat(frames, axis=1)
        macro.index.name = "period"
        macro = macro.loc["1999-01-01":].reset_index()
        macro.to_csv(CACHE, index=False)                    # copie locale de secours
    except Exception as exc:                                # pas d'Internet, site indisponible...
        if not CACHE.exists():
            raise SystemExit(f"Téléchargement impossible ({exc}) et aucune copie locale.")
        print(f"  Téléchargement impossible ({exc}) : utilisation de la copie locale.")
        macro = pd.read_csv(CACHE, parse_dates=["period"])

    macro["period"] = pd.to_datetime(macro["period"]).dt.date
    con = duckdb.connect(str(DB_PATH))
    con.execute("DELETE FROM economic_indicators")
    con.register("macro_df", macro)
    con.execute("""
        INSERT INTO economic_indicators
        SELECT period, unemployment_rate, mortgage_rate_30y, fed_funds_rate, house_price_index
        FROM macro_df
    """)
    n, first, last = con.execute(
        "SELECT count(*), min(period), max(period) FROM economic_indicators").fetchone()
    con.close()
    print(f"  economic_indicators : {n} mois, de {first} à {last}")


if __name__ == "__main__":
    main()
