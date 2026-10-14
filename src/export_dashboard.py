"""Phase 5 : exporte les résultats agrégés pour le tableau de bord web.

Utilisation (après build_ecl.py) :
    python src/export_dashboard.py

Écrit docs/data/dashboard.json. Ce fichier ne contient QUE des agrégats
(taux, montants, comptes par segment), jamais une ligne de prêt : il peut être
publié sans enfreindre les conditions d'utilisation de Freddie Mac.

Le script refuse d'écrire un fichier qui contiendrait une valeur absurde
(taux hors de [0 ; 1], montant négatif, valeur manquante là où elle est attendue).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ecl import LGD_FLOOR_BASEL, PD_FLOOR_BASEL, RHO, SCENARIOS, irb_capital  # noqa: E402
from pd_model import FEATURES, MISSING, bin_labels  # noqa: E402
from config import DB_PATH, ROOT  # noqa: E402

MIN_SEGMENT_LOANS = 30          # en dessous, un taux de défaut n'a pas de sens : segment masqué


# --- Outils ----------------------------------------------------------------------
def clean(x):
    """Convertit les types numpy / pandas en JSON propre ; NaN -> None ; arrondi."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        if math.isnan(x) or math.isinf(x):
            return None
        return float(f"{float(x):.6g}")
    if isinstance(x, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(x).strftime("%Y-%m-%d")
    if x is pd.NaT:
        return None
    return x


def records(df: pd.DataFrame) -> list[dict]:
    return clean(df.to_dict(orient="records"))


class Checker:
    """Accumule les anomalies : le fichier n'est écrit que s'il n'y en a aucune."""
    def __init__(self):
        self.errors: list[str] = []

    def rate(self, name, values):
        for v in np.atleast_1d(values):
            if v is None or (isinstance(v, float) and math.isnan(v)) or not (0 <= v <= 1):
                self.errors.append(f"{name} : taux hors de [0 ; 1] ({v})")
                return

    def positive(self, name, values):
        for v in np.atleast_1d(values):
            if v is None or (isinstance(v, float) and math.isnan(v)) or v < 0:
                self.errors.append(f"{name} : valeur négative ou manquante ({v})")
                return

    def nonempty(self, name, obj):
        if obj is None or len(obj) == 0:
            self.errors.append(f"{name} : aucune donnée")


def iv_from_bins(bins: list[dict]) -> float:
    """Information Value recalculée à partir des parts et taux de défaut de chaque classe."""
    bad = np.array([b["share"] * b["bad_rate"] for b in bins])
    good = np.array([b["share"] * (1 - b["bad_rate"]) for b in bins])
    keep = (bad > 0) & (good > 0)
    if bad.sum() == 0 or good.sum() == 0:
        return float("nan")
    b, g = bad[keep] / bad.sum(), good[keep] / good.sum()
    return float(((g - b) * np.log(g / b)).sum())


# --- Données du simulateur ------------------------------------------------------------
def simulator_data(con, q, model: dict, tables: set, chk: "Checker") -> dict:
    """Tout ce qu'il faut pour recalculer, dans le navigateur, la note d'un emprunteur,
    la provision IFRS 9 (scénarios, règles de staging) et le capital bâlois.
    Les prêts actifs sont regroupés en « paquets » de prêts semblables : aucune ligne
    individuelle n'est publiée."""
    if "ecl_parameters" not in tables:
        raise SystemExit("Paramètres IFRS 9 absents : relance d'abord  python src/build_ecl.py")
    par = dict(q("SELECT name, value FROM ecl_parameters").itertuples(index=False))

    # 1. Grille du modèle de PD, pour noter un emprunteur
    feats = []
    for f in model["features"]:
        spec = FEATURES[f["name"]]
        woe = {b["bin"]: b["woe"] for b in f["bins"]}
        item = {"name": f["name"], "label": f["label"], "coef": f["coef"], "type": spec["type"]}
        if spec["type"] == "num":
            edges = spec["edges"]
            labels = bin_labels(edges, spec["fmt"])
            bounds = [None, *edges, None]
            item["bins"] = [{"lo": bounds[k], "hi": bounds[k + 1], "label": lab, "woe": woe.get(lab, 0.0)}
                            for k, lab in enumerate(labels)]
        else:
            item["options"] = [{"label": b["bin"], "woe": b["woe"], "share": b["share"]}
                               for b in f["bins"] if b["bin"] not in ("Autre", MISSING)]
        feats.append(item)

    # 2. Paquets de prêts actifs (même état, mêmes indicateurs de staging, mêmes classes,
    #    même tranche de CLTV et même durée restante)
    loans = q("""
        SELECT r.state, r.stage, r.grade_orig, r.grade_now, r.pd_ttc, r.pd_orig AS pd_clean, r.lgd, r.lgd_downturn,
               r.ead, r.ecl_12m, r.ecl_lifetime, r.ecl,
               s.previously_defaulted::INT AS prev, (s.recently_modified OR s.assistance_plan = 'Oui')::INT AS restr,
               coalesce(s.cltv_band, 'Inconnu') AS cltv_band,
               coalesce(s.remaining_months, 360) AS rem, coalesce(s.current_rate, 4.0) AS rate
        FROM ecl_results AS r JOIN ecl_snapshot_input AS s USING (loan_id)""")
    perf = loans["state"] != "90+ jours"
    loans["k_rwa"] = 0.0
    loans.loc[perf, "k_rwa"] = 12.5 * irb_capital(loans.loc[perf, "pd_ttc"].to_numpy(),
                                                    loans.loc[perf, "lgd_downturn"].to_numpy()) * loans.loc[perf, "ead"]
    loans["term"] = np.select([loans["rem"] <= 120, loans["rem"] <= 240], [0, 1], 2)
    for c in ("pd_ttc", "pd_clean", "lgd", "lgd_downturn", "rem", "rate"):
        loans[c + "_w"] = loans[c] * loans["ead"]
    keys = ["state", "prev", "restr", "grade_orig", "grade_now", "cltv_band", "term"]
    g = loans.groupby(keys, dropna=False)
    bk = g.agg(n=("ead", "size"), ead=("ead", "sum"), e12=("ecl_12m", "sum"), elt=("ecl_lifetime", "sum"),
               ecl=("ecl", "sum"), rwa=("k_rwa", "sum"), stage_min=("stage", "min"), stage_max=("stage", "max"),
               **{c: (c + "_w", "sum") for c in ("pd_ttc", "pd_clean", "lgd", "lgd_downturn", "rem", "rate")}).reset_index()
    for c in ("pd_ttc", "pd_clean", "lgd", "lgd_downturn", "rem", "rate"):
        bk[c] = bk[c] / bk["ead"]
    if (bk["stage_min"] != bk["stage_max"]).any():
        chk.errors.append("simulateur : un paquet de prêts mélange plusieurs stages")
    bk["stage"] = bk["stage_min"]
    states = ["À jour", "30-59 jours", "60-89 jours", "90+ jours"]
    bands = sorted(bk["cltv_band"].unique().tolist())
    bk["state_i"] = bk["state"].map({st: k for k, st in enumerate(states)})
    bk["band_i"] = bk["cltv_band"].map({b: k for k, b in enumerate(bands)})
    cols = ["state_i", "prev", "restr", "grade_orig", "grade_now", "band_i", "term", "stage", "n", "ead",
            "pd_ttc", "pd_clean", "lgd", "lgd_downturn", "rem", "rate", "e12", "elt", "ecl", "rwa"]
    chk.rate("simulateur : PD", bk[["pd_ttc", "pd_clean", "lgd", "lgd_downturn"]].to_numpy().ravel())
    chk.positive("simulateur : provisions", bk[["e12", "elt", "ecl", "rwa"]].to_numpy().ravel())

    lgd = q("SELECT cltv_band, lgd, lgd_downturn FROM v_lgd_by_segment")
    scen = q("SELECT scenario, weight, d_unemp, hpi, z FROM ecl_scenarios")
    return {
        "params": par, "intercept": model["intercept"], "features": feats, "master_scale": model["master_scale"],
        "points": {"base_score": 600, "base_odds": 50, "pdo": 20},
        "lgd_by_band": records(lgd), "scenarios": records(scen),
        "states": states, "bands": bands, "bucket_cols": cols, "buckets": clean(bk[cols].to_numpy().tolist()),
        "base": {"ecl": clean(loans["ecl"].sum()), "ead": clean(loans["ead"].sum()), "rwa": clean(loans["k_rwa"].sum()),
                 "stage_n": clean(loans.groupby("stage").size().to_dict())},
    }


# --- Programme principal --------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=ROOT / "docs" / "model" / "pd_model.json")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "data" / "dashboard.json")
    args = parser.parse_args()
    if not args.model.exists():
        raise SystemExit("Modèle introuvable : lance d'abord  python src/train_pd_model.py")
    model = json.loads(args.model.read_text(encoding="utf-8"))
    con = duckdb.connect(str(DB_PATH), read_only=True)
    q = lambda sql: con.execute(sql).df()  # noqa: E731
    chk = Checker()
    D: dict = {}

    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    for t in ("v_vintage_curve", "risk_ratings", "ecl_results"):
        if t not in tables:
            raise SystemExit(f"Table {t} absente : lance d'abord build_analytics.py, train_pd_model.py "
                             "et build_ecl.py")

    print("1/6  Portefeuille")
    snap = q("SELECT * FROM v_portfolio_snapshot").iloc[0]
    kpis = q("SELECT * FROM v_monthly_kpis ORDER BY period DESC")
    # Les premiers mois d'une cohorte comptent peu de prêts : taux trop bruités, on les écarte
    monthly = q("""SELECT period, n_active, upb_musd, dq30_rate, dq90_rate, unemployment_rate
                   FROM v_monthly_portfolio
                   WHERE n_active >= 0.05 * (SELECT max(n_active) FROM v_monthly_portfolio)
                   ORDER BY period""")
    vint = q("SELECT * FROM v_default_by_vintage ORDER BY cohorte = 'Toutes', cohorte")
    conc = q("SELECT * FROM v_concentration_state ORDER BY rank LIMIT 10")
    conc_sum = q("SELECT * FROM v_concentration_summary")
    n_loans = int(q("SELECT count(*) AS n FROM loans")["n"].iloc[0])
    D["meta"] = {
        "snapshot_date": snap["snapshot_date"], "generated": date.today(),
        "n_loans": n_loans, "cohorts": [c for c in vint["cohorte"] if c != "Toutes"],
        "first_period": monthly["period"].min(), "model_version": model["version"],
        "train_until": model["train_until"],
    }
    D["portfolio"] = {"snapshot": clean(snap.to_dict()), "kpis": records(kpis), "monthly": records(monthly),
                      "top_states": records(conc), "concentration": records(conc_sum)}
    chk.rate("taux de retard", monthly[["dq30_rate", "dq90_rate"]].to_numpy().ravel())
    chk.positive("encours mensuel", monthly["upb_musd"])
    chk.rate("parts par État", conc["share"])

    print("2/6  Défauts")
    curve = q("""SELECT vintage_year, age, cum_default_rate FROM v_vintage_curve
                 WHERE age % 3 = 0 OR age = 1 ORDER BY vintage_year, age""")
    seg = q(f"""SELECT dimension, segment, segment_order, cohorte, n_loans, n_defaults, default_rate, ci_low, ci_high
                FROM v_default_by_segment
                WHERE dimension <> 'État' AND segment <> 'Inconnu' AND n_loans >= {MIN_SEGMENT_LOANS}
                ORDER BY dimension, cohorte, segment_order""")
    sev = q("SELECT * FROM v_loss_severity ORDER BY cohorte = 'Toutes', cohorte")
    miles = q("SELECT * FROM v_vintage_milestones ORDER BY vintage_year")
    D["defaults"] = {"by_vintage": records(vint), "curves": records(curve), "segments": records(seg),
                     "severity": records(sev), "milestones": records(miles)}
    chk.rate("taux de défaut par cohorte", vint[["default_rate", "ci_low", "ci_high"]].to_numpy().ravel())
    chk.rate("courbes de vintage", curve["cum_default_rate"])
    chk.rate("taux par segment", seg[["default_rate", "ci_low", "ci_high"]].to_numpy().ravel())
    chk.rate("sévérité", sev["severity"].dropna())

    print("3/6  Signaux d'alerte")
    sig = q("SELECT * FROM v_signal_backtest WHERE n_loan_months > 0 AND pd12 IS NOT NULL ORDER BY ord")
    watch = q("SELECT * FROM v_watchlist ORDER BY ord")
    roll = q("""SELECT from_state, from_order, to_state, to_order, sum(n) AS n
                FROM v_roll_rates GROUP BY ALL ORDER BY from_order, to_order""")
    roll["share"] = roll["n"] / roll.groupby("from_state")["n"].transform("sum")
    D["signals"] = {"backtest": records(sig), "watchlist": records(watch), "roll": records(roll)}
    chk.rate("signaux", sig[["pd12", "ci_low", "ci_high"]].to_numpy().ravel())
    chk.rate("roll rates", roll["share"])

    print("4/6  Modèle de PD")
    oot_from = model["train_until"] + 1
    scale = q(f"""
        SELECT r.grade, count(*) AS n, avg(r.pd_12m) AS pd_pred, avg(p.default_12m::INT) AS observed
        FROM risk_ratings AS r
        JOIN loan_month_pd AS p ON p.loan_id = r.loan_id AND p.period = r.rating_date
        WHERE p.window_complete AND year(r.rating_date) >= {oot_from}
        GROUP BY r.grade ORDER BY r.grade""")
    scale["share"] = scale["n"] / scale["n"].sum()
    bounds = model["master_scale"]
    scale["pd_lower"] = [bounds[g - 1] for g in scale["grade"]]
    scale["pd_upper"] = [bounds[g] for g in scale["grade"]]
    iv = sorted(({"name": f["name"], "label": f["label"], "iv": iv_from_bins(f["bins"]), "coef": f["coef"]}
                 for f in model["features"]), key=lambda r: -r["iv"])
    D["model"] = {"version": model["version"], "train_until": model["train_until"], "oot_from": oot_from,
                  "performance": clean(model["performance"]), "challenger_auc_oot": clean(model["challenger_auc_oot"]),
                  "psi": clean(model["psi"]), "scale": records(scale), "iv": clean(iv)}
    chk.rate("échelle de notation", scale[["pd_pred", "observed", "share"]].to_numpy().ravel())
    chk.nonempty("échelle de notation", scale)

    print("5/6  IFRS 9")
    cal = q("SELECT * FROM pd_calibration_by_year ORDER BY year")
    stages = q("""SELECT stage, count(*) AS n, sum(ead) AS ead, sum(ecl) AS ecl FROM ecl_results
                  GROUP BY stage ORDER BY stage""")
    stages["ead_share"] = stages["ead"] / stages["ead"].sum()
    stages["ecl_share"] = stages["ecl"] / stages["ecl"].sum()
    stages["coverage"] = stages["ecl"] / stages["ead"]
    reasons = q("""SELECT stage, stage_reason, count(*) AS n, sum(ead) AS ead FROM ecl_results
                   GROUP BY ALL ORDER BY stage, n DESC""")
    by_vintage = q("""SELECT vintage_year, count(*) AS n, sum(ead) AS ead, sum(ecl) AS ecl,
                             sum(ecl) / sum(ead) AS coverage,
                             sum(ead) FILTER (WHERE stage >= 2) / sum(ead) AS stage23_share
                      FROM ecl_results GROUP BY vintage_year ORDER BY vintage_year""")
    scen = q("SELECT * FROM ecl_scenarios")
    lgd = q("SELECT * FROM v_lgd_by_segment")
    ead_factor = q("SELECT * FROM v_ead_factor").iloc[0]
    cpr = q("SELECT * FROM v_prepayment_rate").iloc[0]
    mig = q("SELECT period, from_grade, to_state, n, share FROM migration_matrix")
    drift = q("SELECT * FROM migration_drift") if "migration_drift" in tables else pd.DataFrame()
    D["ifrs9"] = {"calibration": records(cal), "lra": clean(cal["observed"].mean()),
                  "stages": records(stages), "reasons": records(reasons), "by_vintage": records(by_vintage),
                  "scenarios": records(scen), "weighted_ecl": clean(stages["ecl"].sum()),
                  "total_ead": clean(stages["ead"].sum()), "lgd": records(lgd),
                  "ead_factor": clean(ead_factor["ead_factor"]), "cpr": clean(cpr["annual_prepayment_rate"]),
                  "migration": records(mig), "drift": records(drift),
                  "assumptions": {"rho": RHO, "scenarios": [{"name": n, "weight": w, "d_unemp": du, "hpi": h}
                                                            for n, w, du, h in SCENARIOS]}}
    chk.rate("PD calibrées", cal[["observed", "pd_ttc", "pd_pit_macro"]].to_numpy().ravel())
    chk.rate("couverture", stages["coverage"])
    chk.positive("ECL", stages["ecl"])
    chk.rate("LGD", lgd[["lgd", "lgd_downturn", "cure_rate"]].to_numpy().ravel())
    chk.rate("migrations", mig["share"])
    chk.positive("ECL par scénario", scen["ecl"])

    print("6/6  Capital réglementaire")
    perf = q("SELECT pd_ttc, lgd_downturn, ead, ecl FROM ecl_results WHERE state <> '90+ jours'")
    k = irb_capital(perf["pd_ttc"].to_numpy(), perf["lgd_downturn"].to_numpy())
    ead = perf["ead"].to_numpy()
    rwa = float(12.5 * (k * ead).sum())
    el = float((np.maximum(perf["pd_ttc"], PD_FLOOR_BASEL) * np.maximum(perf["lgd_downturn"], LGD_FLOOR_BASEL)
                * ead).sum())
    D["capital"] = {"ead_performing": clean(ead.sum()), "rwa": clean(rwa), "density": clean(rwa / ead.sum()),
                    "capital_8pct": clean(0.08 * rwa), "el_regulatory": clean(el),
                    "provision_performing": clean(perf["ecl"].sum()),
                    "pd_floor": PD_FLOOR_BASEL, "lgd_floor": LGD_FLOOR_BASEL, "rho": RHO}
    chk.positive("RWA", rwa)

    print("+    Simulateur")
    D["simulator"] = simulator_data(con, q, model, tables, chk)
    con.close()

    if chk.errors:
        print("\nExport refusé : valeurs incohérentes détectées")
        for e in chk.errors:
            print("  -", e)
        sys.exit(1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(clean(D), ensure_ascii=False, separators=(",", ":"))
    args.out.write_text(text, encoding="utf-8")
    (args.out.parent.parent / ".nojekyll").touch()      # GitHub Pages : servir les fichiers tels quels
    print(f"\nExport OK : {args.out}  ({len(text) / 1024:.0f} Ko, uniquement des agrégats)")


if __name__ == "__main__":
    main()
