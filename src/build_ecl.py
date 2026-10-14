"""Phase 4 : de la PD à la perte attendue (IFRS 9) et au capital (Bâle).

Utilisation (après train_pd_model.py) :
    python src/build_ecl.py

Étapes :
  1. Calibrage de la PD
     - TTC (through-the-cycle) : on décale la constante du modèle pour que la PD
       moyenne égale le taux de défaut moyen de long terme (moyenne des années) ;
     - PIT (point-in-time) : modèle à un facteur de Vasicek. Chaque année a un
       « facteur systémique » Z ; on relie Z à la conjoncture (chômage, prix
       immobiliers) pour projeter la PD selon des scénarios.
  2. LGD par tranche de CLTV (avec guérisons), LGD de crise, facteur d'EAD,
     taux de remboursement anticipé (sql/15_lgd_ead.sql).
  3. Staging IFRS 9 à la date d'arrêté : Stage 1, 2 ou 3.
  4. Perte attendue (ECL) : 12 mois en Stage 1, à maturité en Stage 2,
     LGD x EAD en Stage 3 ; pondération de 3 scénarios macroéconomiques.
  5. Matrices de migration annuelles entre classes R1 à R8 (PD TTC).
  6. Capital réglementaire (formule IRB des crédits immobiliers).
  7. Rapport (docs/model/ecl_report.md), 4 graphiques, contrôles sql/17.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DB_PATH, ROOT, SQL_DIR  # noqa: E402
from pd_model import FEATURES, MASTER_SCALE, MISSING, apply_bins, assign_grade  # noqa: E402
from run_quality_checks import print_report, run_checks  # noqa: E402

# --- Hypothèses (toutes modifiables ici, et rappelées dans le rapport) ----------
RHO = 0.15                     # corrélation au facteur systémique (Bâle, crédits immobiliers)
SCENARIOS = [                  # nom, poids, hausse du chômage (points), évolution des prix immobiliers
    ("Central", 0.60, 0.0, 0.03),
    ("Adverse", 0.30, 2.0, -0.05),
    ("Sévère", 0.10, 5.0, -0.15),
]
SICR_NOTCHES = 2               # dégradation significative : au moins 2 crans depuis l'octroi...
SICR_MIN_PD = 0.01             # ... et une PD actuelle d'au moins 1 %
EXCLUDED_YEARS = {2020}        # moratoires Covid : défauts sans lien avec le cycle habituel
PD_FLOOR_BASEL, LGD_FLOOR_BASEL = 0.0005, 0.10
MAX_YEARS = 30


def fr(x: float, d: int = 1) -> str:
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def pct(x: float, d: int = 2) -> str:
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{fr(100 * x, d)} %"


def logit(p):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


# --- Application du modèle de PD à partir de son fichier JSON --------------------
def score_from_json(df: pd.DataFrame, model: dict) -> np.ndarray:
    """Recalcule la PD du modèle (phase 3) : classes -> WoE -> régression logistique."""
    z = np.full(len(df), model["intercept"], dtype=float)
    for feat in model["features"]:
        name = feat["name"]
        spec = dict(FEATURES[name])
        woe = {b["bin"]: b["woe"] for b in feat["bins"]}
        if spec["type"] == "cat":
            spec["categories"] = [b for b in woe if b != "Autre"]
        labels = apply_bins(df[name], spec)
        z += feat["coef"] * labels.map(woe).fillna(0.0).to_numpy()
    return sigmoid(z)


def vasicek(pd_ttc: np.ndarray, z: float) -> np.ndarray:
    """PD conditionnelle au facteur systémique Z (Z < 0 : mauvaise conjoncture)."""
    pd_ttc = np.clip(pd_ttc, 1e-9, 1 - 1e-9)
    return norm.cdf((norm.ppf(pd_ttc) - math.sqrt(RHO) * z) / math.sqrt(1 - RHO))


# --- 1. Calibrage ----------------------------------------------------------------
def calibrate(dev: pd.DataFrame) -> dict:
    dev = dev.assign(year=dev["period"].dt.year)
    annual = dev.groupby("year").agg(n=("default_12m", "size"), observed=("default_12m", "mean"),
                                     pd_model=("pd_model", "mean"),
                                     d_unemp=("unemp_chg_12m", "first"), hpi=("hpi_yoy", "first"))
    annual = annual[annual["n"] >= 1000].copy()
    lra = annual["observed"].mean()                      # taux de défaut moyen de long terme
    years = annual.index.tolist()
    groups = {y: logit(dev.loc[dev["year"] == y, "pd_model"].to_numpy()) for y in years}

    def gap(delta):
        return np.mean([sigmoid(g + delta).mean() for g in groups.values()]) - lra
    delta = brentq(gap, -10, 10)
    annual["pd_ttc"] = [sigmoid(groups[y] + delta).mean() for y in years]

    # Facteur systémique Z de chaque année : la valeur qui reproduit le taux observé
    zs = []
    for y in years:
        p = sigmoid(groups[y] + delta)
        dr = annual.loc[y, "observed"]
        zs.append(brentq(lambda z: vasicek(p, z).mean() - dr, -8, 8) if 0 < dr < 1 else np.nan)
    annual["z"] = zs

    # Lien entre Z et la conjoncture (« modèle satellite »), hors années exclues
    fit = annual[~annual.index.isin(EXCLUDED_YEARS)].dropna(subset=["z", "d_unemp", "hpi"])
    X = np.column_stack([np.ones(len(fit)), fit["d_unemp"], fit["hpi"]]) if len(fit) else np.empty((0, 3))
    if len(fit) >= 6 and np.linalg.matrix_rank(X) == 3:
        beta, *_ = np.linalg.lstsq(X, fit["z"].to_numpy(), rcond=None)
        pred = X @ beta
        ss_res = ((fit["z"] - pred) ** 2).sum()
        ss_tot = ((fit["z"] - fit["z"].mean()) ** 2).sum()
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        satellite = {"beta": beta.tolist(), "r2": r2, "n_years": len(fit), "fallback": False}
        scen_z = {name: beta[0] + beta[1] * du + beta[2] * hpi for name, _, du, hpi in SCENARIOS}
    else:   # pas assez de variation macro : scénarios fixés sur la loi normale du facteur
        satellite = {"beta": None, "r2": float("nan"), "n_years": len(fit), "fallback": True}
        scen_z = {"Central": 0.0, "Adverse": -1.0, "Sévère": -2.0}
    zfit = []
    for y in years:
        if satellite["beta"] is not None and not np.isnan(annual.loc[y, "d_unemp"]) and not np.isnan(annual.loc[y, "hpi"]):
            b = satellite["beta"]
            zf = b[0] + b[1] * annual.loc[y, "d_unemp"] + b[2] * annual.loc[y, "hpi"]
        else:
            zf = annual.loc[y, "z"]
        zfit.append(vasicek(sigmoid(groups[y] + delta), zf).mean())
    annual["pd_pit_macro"] = zfit
    return {"delta": delta, "lra": lra, "annual": annual.reset_index(), "satellite": satellite, "scen_z": scen_z}


# --- 4. Perte attendue -------------------------------------------------------------
def expected_loss(snap: pd.DataFrame, pit_1y: np.ndarray, ttc_clean: np.ndarray, lgd: np.ndarray,
                  cpr: float) -> tuple[np.ndarray, np.ndarray]:
    """ECL à 12 mois et à maturité, par prêt, pour UN scénario.
    Probabilité de défaut annuelle : PIT la 1re année, moitié PIT / moitié TTC la
    2e, puis TTC « assainie » (comme si le prêt était à jour) ensuite.
    Encours : amortissement contractuel. Survie : ni défaut, ni remboursement anticipé.
    Actualisation au taux du prêt (taux d'intérêt effectif)."""
    n = len(snap)
    years = np.arange(1, MAX_YEARS + 1)
    rem = np.clip(snap["remaining_months"].fillna(360).to_numpy(), 1, 12 * MAX_YEARS)
    horizon = np.ceil(rem / 12)
    rate = np.clip(snap["current_rate"].fillna(4.0).to_numpy(), 0.01, 20) / 100
    r_m = rate / 12
    upb = snap["current_upb"].to_numpy()

    h = np.tile(ttc_clean[:, None], (1, MAX_YEARS))
    h[:, 0] = pit_1y
    h[:, 1] = 0.5 * pit_1y + 0.5 * ttc_clean
    alive = years[None, :] <= horizon[:, None]
    h = np.where(alive, h, 0.0)

    k = 12 * (years[None, :] - 1)                                      # mois écoulés en début d'année
    growth_n = (1 + r_m[:, None]) ** rem[:, None]
    growth_k = (1 + r_m[:, None]) ** k
    balance = upb[:, None] * (growth_n - growth_k) / (growth_n - 1)    # encours restant dû
    balance = np.clip(np.where(alive, balance, 0.0), 0, None)
    df = (1 + rate[:, None]) ** (-(years[None, :] - 0.5))

    survival = np.ones((n, MAX_YEARS))
    survival[:, 1:] = np.cumprod((1 - h[:, :-1]) * (1 - cpr), axis=1)
    marginal = survival * h * lgd[:, None] * balance * df
    return marginal[:, 0], marginal.sum(axis=1)


# --- 6. Capital IRB ----------------------------------------------------------------
def irb_capital(pd_ttc: np.ndarray, lgd_dt: np.ndarray) -> np.ndarray:
    """Exigence en capital K par euro d'exposition (formule IRB, crédits immobiliers)."""
    p = np.maximum(pd_ttc, PD_FLOOR_BASEL)
    lg = np.maximum(lgd_dt, LGD_FLOOR_BASEL)
    stressed = norm.cdf((norm.ppf(p) + math.sqrt(RHO) * norm.ppf(0.999)) / math.sqrt(1 - RHO))
    return lg * stressed - lg * p


# --- Graphiques ----------------------------------------------------------------------
def make_figures(out: Path, annual: pd.DataFrame, matrix: pd.DataFrame, stages: pd.DataFrame,
                 scen: pd.DataFrame, weighted_ecl: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    from make_figures import AXIS, BLUE, INK, INK_2, fr as frf, setup_style, source, titles

    setup_style()
    pf = lambda d: FuncFormatter(lambda v, _: f"{frf(100 * v, d)} %")  # noqa: E731

    # 10 — Calibrage TTC / PIT
    a = annual
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.plot(a["year"], a["observed"], color=INK_2, lw=2, marker="o", ms=5, label="Taux de défaut observé")
    ax.plot(a["year"], a["pd_ttc"], color=BLUE, lw=2, label="PD TTC (moyenne de long terme)")
    ax.plot(a["year"], a["pd_pit_macro"], color="#B4500E", lw=2, ls=(0, (4, 3)),
            label="PD PIT expliquée par la conjoncture")
    ax.yaxis.set_major_formatter(pf(1))
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, loc="upper right")
    for y in EXCLUDED_YEARS:
        if y in set(a["year"]):
            v = a.loc[a["year"] == y, "observed"].iloc[0]
            ax.annotate(f"{y} : moratoires Covid,\nexclue du lien avec la conjoncture", xy=(y, v),
                        xytext=(y - 0.4, v), ha="right", va="center", fontsize=8.5, color=INK_2)
    lra = a["observed"].mean()
    titles(fig, f"La PD TTC lisse le cycle ({pct(a['pd_ttc'].min(), 1)} à {pct(a['pd_ttc'].max(), 1)}), "
                f"les défauts observés vont de {pct(a['observed'].min(), 1)} à {pct(a['observed'].max(), 1)}",
           f"PD TTC : constante décalée pour que la PD moyenne égale le taux moyen de long terme ({pct(lra)}).\n"
           "PD PIT : modèle à un facteur de Vasicek relié au chômage et aux prix immobiliers.")
    source(fig)
    fig.savefig(out / "10_pd_calibration_ttc_pit.png")
    plt.close(fig)

    # 11 — Matrice de migration
    m = matrix[matrix["period"] == "Toutes années"]
    rows = [f"R{g}" for g in range(1, 9)]
    cols = rows + ["Défaut", "Sorti"]
    piv = m.pivot_table(index="from_grade", columns="to_state", values="share", aggfunc="sum")
    piv = piv.reindex(index=[r for r in rows if r in piv.index], columns=cols).fillna(0)
    stay = m.loc[m["from_grade"] == m["to_state"], "n"].sum() / m.loc[m["to_state"] != "Sorti", "n"].sum()
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.imshow(piv.values, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            lab = "" if v == 0 else ("< 1 %" if v < 0.01 else f"{frf(100 * v, 0)} %")
            ax.text(j, i, lab, ha="center", va="center", fontsize=8.5, color="white" if v > 0.55 else INK)
    ax.set_xticks(range(len(cols)), cols)
    ax.set_yticks(range(len(piv.index)), piv.index)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_ylabel("Classe en janvier de l'année N")
    titles(fig, f"D'une année sur l'autre, {frf(100 * stay, 0)} % des prêts encore suivis gardent la même classe",
           "Matrice de migration annuelle (classes de PD TTC), toutes années. Lecture en ligne : où se trouve le prêt\n"
           "en janvier N+1. « Sorti » = remboursé ou plus observé. Une partie des glissements vers la droite vient\n"
           "du vieillissement des prêts récents (le risque culmine entre 24 et 36 mois d'ancienneté).")
    fig.subplots_adjust(top=0.74)
    source(fig)
    fig.savefig(out / "11_migration_matrix.png")
    plt.close(fig)

    # 12 — Stages IFRS 9
    st = stages.set_index("stage").reindex([1, 2, 3]).fillna(0)
    labels = ["Stage 1", "Stage 2", "Stage 3"]
    colors = [BLUE, "#E08A3C", "#B4500E"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.2))
    for ax_, col, ttl in ((a1, "ead_share", "Part de l'encours"), (a2, "ecl_share", "Part de la perte attendue")):
        ax_.bar(labels, st[col], color=colors, width=0.6)
        for x, v in zip(labels, st[col]):
            ax_.text(x, v, f"{frf(100 * v, 1)} %", ha="center", va="bottom", fontsize=9.5, color=INK)
        ax_.yaxis.set_major_formatter(pf(0))
        ax_.set_ylim(0, 1.1)
        ax_.set_title(ttl, fontsize=10.5, color=INK_2, loc="left")
        ax_.grid(axis="x", visible=False)
    cov = st["coverage"]
    titles(fig, f"Le Stage 2 pèse {frf(100 * st.loc[2, 'ead_share'], 1)} % de l'encours mais "
                f"{frf(100 * st.loc[2, 'ecl_share'], 0)} % de la perte attendue",
           f"Taux de couverture (ECL / encours) : Stage 1 {pct(cov[1])}, Stage 2 {pct(cov[2])}, Stage 3 {pct(cov[3], 1)}.")
    fig.subplots_adjust(top=0.8, wspace=0.3)
    source(fig)
    fig.savefig(out / "12_ifrs9_stages.png")
    plt.close(fig)

    # 13 — Scénarios
    d = 2 if scen["ecl"].max() < 10e6 else 1
    fig, ax = plt.subplots(figsize=(8, 4.4))
    ax.bar(scen["scenario"], scen["ecl"] / 1e6, color=[BLUE, "#E08A3C", "#B4500E"], width=0.55)
    for x, v, w in zip(scen["scenario"], scen["ecl"] / 1e6, scen["weight"]):
        ax.text(x, v + 0.01 * scen["ecl"].max() / 1e6, f"{frf(v, d)} M$\n(poids {frf(100 * w, 0)} %)",
                ha="center", va="bottom", fontsize=9.5, color=INK, zorder=5,
                bbox=dict(boxstyle="square,pad=0.15", facecolor="white", edgecolor="none"))
    ax.axhline(weighted_ecl / 1e6, color=INK, lw=1.2, ls=(0, (4, 3)), zorder=4,
               label=f"ECL pondérée retenue : {frf(weighted_ecl / 1e6, d)} M$")
    ax.legend(frameon=False, loc="upper left")
    ax.set_ylabel("Perte attendue (M$)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: frf(v, d - 1 if d > 1 else 0) if v else "0"))
    ax.set_ylim(0, scen["ecl"].max() / 1e6 * 1.3)
    ax.grid(axis="x", visible=False)
    sev = scen.set_index("scenario")["ecl"]
    titles(fig, f"Dans le scénario sévère, la perte attendue serait {frf(sev['Sévère'] / sev['Central'], 1)} fois "
                "celle du scénario central",
           "Perte attendue IFRS 9 du portefeuille actif selon le scénario macroéconomique, et moyenne pondérée\n"
           "par les probabilités des scénarios (montant provisionné).")
    source(fig)
    fig.savefig(out / "13_ecl_scenarios.png")
    plt.close(fig)


# --- Programme principal ------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=ROOT / "docs" / "model" / "pd_model.json")
    parser.add_argument("--figures-out", type=Path, default=ROOT / "docs" / "figures")
    parser.add_argument("--model-out", type=Path, default=ROOT / "docs" / "model")
    args = parser.parse_args()
    if not args.model.exists():
        raise SystemExit("Modèle de PD introuvable : lance d'abord  python src/train_pd_model.py")
    start = time.time()
    model = json.loads(args.model.read_text(encoding="utf-8"))
    con = duckdb.connect(str(DB_PATH))

    print("1/7  Calibrage de la PD (TTC et PIT)")
    dev = con.execute("""SELECT d.*, r.pd_12m AS pd_model FROM pd_dataset AS d
                         JOIN risk_ratings AS r ON r.loan_id = d.loan_id AND r.rating_date = d.period
                         WHERE d.window_complete""").df()
    dev["period"] = pd.to_datetime(dev["period"])
    dev["default_12m"] = dev["default_12m"].astype(int)
    cal = calibrate(dev)
    delta, annual, sat, scen_z = cal["delta"], cal["annual"], cal["satellite"], cal["scen_z"]
    print(f"  Taux de défaut moyen de long terme : {pct(cal['lra'])}   décalage de la constante : {delta:+.3f}")
    if sat["fallback"]:
        print("  Conjoncture insuffisante : scénarios fixés sur le facteur Z (0, -1, -2)")
    else:
        print(f"  Lien Z / conjoncture sur {sat['n_years']} années : R² = {sat['r2']:.2f}")
    shift = lambda p: sigmoid(logit(p) + delta)  # noqa: E731

    print("2/7  LGD, EAD et remboursements anticipés")
    con.execute((SQL_DIR / "15_lgd_ead.sql").read_text(encoding="utf-8"))
    lgd_tab = con.execute("SELECT * FROM v_lgd_by_segment").df()
    ead_factor = con.execute("SELECT ead_factor FROM v_ead_factor").fetchone()[0] or 1.0
    cpr = con.execute("SELECT annual_prepayment_rate FROM v_prepayment_rate").fetchone()[0] or 0.0
    overall = lgd_tab[lgd_tab["cltv_band"] == "Tous"].iloc[0]
    print(f"  LGD globale {pct(overall['lgd'])} (crise : {pct(overall['lgd_downturn'])}), "
          f"facteur d'EAD {fr(ead_factor, 3)}, remboursements anticipés {pct(cpr, 1)} par an")

    print("3/7  Staging IFRS 9 à la date d'arrêté")
    con.execute((SQL_DIR / "16_ecl_snapshot.sql").read_text(encoding="utf-8"))
    snap = con.execute("SELECT * FROM ecl_snapshot_input").df()
    snapshot_date = pd.Timestamp(snap["snapshot_date"].iloc[0]).strftime("%d/%m/%Y")
    perf = snap["state"] != "90+ jours"
    pd_now = shift(score_from_json(snap, model))
    clean = snap.assign(dq_state="À jour", dq_history_12m="Aucun retard")
    pd_clean = shift(score_from_json(clean, model))
    # PD « à l'octroi » : même prêt, même ancienneté, sans les retards. Comparer à
    # ancienneté égale évite de prendre l'effet normal du vieillissement du prêt
    # pour une dégradation du risque (les variables d'octroi, elles, ne changent pas).
    pd_orig = pd_clean
    snap["pd_ttc"], snap["pd_ttc_clean"], snap["pd_orig"] = pd_now, pd_clean, pd_orig
    snap["grade_now"], snap["grade_orig"] = assign_grade(pd_now), assign_grade(pd_orig)
    lgd_map = dict(zip(lgd_tab["cltv_band"], lgd_tab["lgd"]))
    lgd_dt_map = dict(zip(lgd_tab["cltv_band"], lgd_tab["lgd_downturn"]))
    snap["lgd"] = snap["cltv_band"].map(lgd_map).fillna(overall["lgd"]).clip(0, 1)
    snap["lgd_downturn"] = snap["cltv_band"].map(lgd_dt_map).fillna(overall["lgd_downturn"]).clip(0, 1)
    snap["ead"] = snap["current_upb"]

    notches = snap["grade_now"] - snap["grade_orig"]
    conditions = [
        (~perf, 3, "90 jours de retard ou plus (défaut)"),
        (snap["state"].isin(["30-59 jours", "60-89 jours"]), 2, "Retard de 30 jours ou plus"),
        (snap["previously_defaulted"], 2, "Sorti du défaut depuis moins de 2 ans (période probatoire)"),
        (snap["recently_modified"] | (snap["assistance_plan"] == "Oui"), 2,
         "Restructuré depuis moins de 2 ans ou plan d'aide en cours"),
        ((notches >= SICR_NOTCHES) & (snap["pd_ttc"] >= SICR_MIN_PD), 2, "Hausse significative du risque (SICR)"),
    ]
    snap["stage"], snap["stage_reason"] = 1, "Pas de dégradation significative"
    for cond, stage, reason in reversed(conditions):     # la première règle vérifiée l'emporte
        snap.loc[cond, "stage"] = stage
        snap.loc[cond, "stage_reason"] = reason
    print("  " + "   ".join(f"Stage {s} : {(snap['stage'] == s).sum():,}".replace(",", " ") for s in (1, 2, 3)))

    print("4/7  Perte attendue (ECL) par scénario")
    rows, ecl_w12, ecl_wlt, pit_w = [], np.zeros(len(snap)), np.zeros(len(snap)), np.zeros(len(snap))
    for name, weight, du, hpi in SCENARIOS:
        pit = vasicek(snap["pd_ttc"].to_numpy(), scen_z[name])
        e12, elt = expected_loss(snap, pit, snap["pd_ttc_clean"].to_numpy(), snap["lgd"].to_numpy(), cpr)
        ecl = np.where(snap["stage"] == 1, e12, np.where(snap["stage"] == 2, elt, snap["lgd"] * snap["ead"]))
        rows.append({"scenario": name, "weight": weight, "d_unemp": du, "hpi": hpi, "z": scen_z[name],
                     "pd_mean": pit[perf.to_numpy()].mean(), "ecl": ecl.sum()})
        ecl_w12 += weight * e12
        ecl_wlt += weight * elt
        pit_w += weight * pit
    scen = pd.DataFrame(rows)
    snap["pd_pit"] = np.where(perf, pit_w, 1.0)
    snap["ecl_12m"] = np.where(perf, ecl_w12, snap["lgd"] * snap["ead"])
    snap["ecl_lifetime"] = np.where(perf, ecl_wlt, snap["lgd"] * snap["ead"])
    snap["ecl"] = np.where(snap["stage"] == 1, snap["ecl_12m"],
                           np.where(snap["stage"] == 2, snap["ecl_lifetime"], snap["lgd"] * snap["ead"]))
    weighted = snap["ecl"].sum()
    print(f"  ECL pondérée : {fr(weighted / 1e6, 2)} M$ pour {fr(snap['ead'].sum() / 1e6, 1)} M$ d'encours")

    stages = (snap.groupby("stage").agg(n=("loan_id", "size"), ead=("ead", "sum"), ecl=("ecl", "sum"))
              .reset_index())
    stages["ead_share"] = stages["ead"] / stages["ead"].sum()
    stages["ecl_share"] = stages["ecl"] / stages["ecl"].sum()
    stages["coverage"] = stages["ecl"] / stages["ead"]
    reasons = (snap.groupby(["stage", "stage_reason"]).agg(n=("loan_id", "size"), ead=("ead", "sum"))
               .reset_index().sort_values(["stage", "n"], ascending=[True, False]))

    print("5/7  Matrices de migration")
    rr = con.execute("""SELECT r.loan_id, r.rating_date, r.pd_12m, d.default_12m, d.age
                        FROM risk_ratings AS r
                        JOIN pd_dataset AS d ON d.loan_id = r.loan_id AND d.period = r.rating_date
                        WHERE month(r.rating_date) = 1 AND d.window_complete""").df()
    rr["rating_date"] = pd.to_datetime(rr["rating_date"])
    rr["grade"] = assign_grade(shift(rr["pd_12m"].to_numpy()))
    nxt = rr[["loan_id", "rating_date", "grade"]].copy()
    nxt["rating_date"] = nxt["rating_date"] - pd.DateOffset(years=1)
    mig = rr.merge(nxt.rename(columns={"grade": "grade_next"}), on=["loan_id", "rating_date"], how="left")
    mig["to_state"] = np.where(mig["default_12m"].astype(bool), "Défaut",
                               np.where(mig["grade_next"].notna(),
                                        "R" + mig["grade_next"].fillna(0).astype(int).astype(str), "Sorti"))
    mig["from_grade"] = "R" + mig["grade"].astype(str)
    # Un an plus tard, le prêt a 12 mois de plus : il peut changer de tranche d'ancienneté
    # dans le modèle (le risque culmine entre 24 et 36 mois), donc de classe.
    mig["age_bin_change"] = (apply_bins(mig["age"], FEATURES["age"]).to_numpy()
                             != apply_bins(mig["age"] + 12, FEATURES["age"]).to_numpy())
    year = mig["rating_date"].dt.year
    periods = {"Toutes années": year > 0, "Crise (2008-2010)": year.between(2008, 2010),
               "Calme (2015-2019)": year.between(2015, 2019)}
    mats = []
    for label, mask in periods.items():
        t = mig[mask].groupby(["from_grade", "to_state"]).size().rename("n").reset_index()
        if t.empty:
            continue
        t["share"] = t["n"] / t.groupby("from_grade")["n"].transform("sum")
        t["period"] = label
        mats.append(t)
    matrix = pd.concat(mats, ignore_index=True)

    def drift(label):
        m = mig[periods[label]]
        m = m[m["to_state"].str.startswith("R") | (m["to_state"] == "Défaut")]
        g_next = m["to_state"].replace("Défaut", "R9").str[1:].astype(int).to_numpy()
        down_grade = (g_next > m["grade"]) & (m["to_state"] != "Défaut")
        return {"up": (g_next < m["grade"]).mean(), "same": (g_next == m["grade"]).mean(),
                "down": (g_next > m["grade"]).mean(), "n": len(m),
                "down_age": m.loc[down_grade, "age_bin_change"].mean() if down_grade.any() else float("nan")}
    drifts = {k: drift(k) for k in periods if periods[k].any()}

    print("6/7  Capital réglementaire (IRB)")
    k = irb_capital(snap.loc[perf, "pd_ttc"].to_numpy(), snap.loc[perf, "lgd_downturn"].to_numpy())
    ead_perf = snap.loc[perf, "ead"].to_numpy()
    rwa = 12.5 * (k * ead_perf).sum()
    el_basel = (np.maximum(snap.loc[perf, "pd_ttc"], PD_FLOOR_BASEL)
                * np.maximum(snap.loc[perf, "lgd_downturn"], LGD_FLOOR_BASEL) * ead_perf).sum()
    print(f"  RWA {fr(rwa / 1e6, 1)} M$ (densité {pct(rwa / ead_perf.sum(), 1)}), "
          f"fonds propres à 8 % : {fr(0.08 * rwa / 1e6, 1)} M$")

    print("7/7  Enregistrement, rapport, graphiques, contrôles")
    out_cols = ["loan_id", "snapshot_date", "vintage_year", "state", "stage", "stage_reason", "grade_orig",
                "grade_now", "pd_orig", "pd_ttc", "pd_pit", "lgd", "lgd_downturn", "ead", "ecl_12m",
                "ecl_lifetime", "ecl"]
    con.register("ecl_df", snap[out_cols])
    con.execute("CREATE OR REPLACE TABLE ecl_results AS SELECT * FROM ecl_df")
    con.register("mig_df", matrix)
    con.execute("CREATE OR REPLACE TABLE migration_matrix AS SELECT period, from_grade, to_state, n, share FROM mig_df")
    con.register("cal_df", annual)
    con.execute("CREATE OR REPLACE TABLE pd_calibration_by_year AS SELECT * FROM cal_df")
    con.register("scen_df", scen)
    con.execute("CREATE OR REPLACE TABLE ecl_scenarios AS SELECT * FROM scen_df")
    drift_df = pd.DataFrame([{"period": k, **d} for k, d in drifts.items()])
    con.register("drift_df", drift_df)
    con.execute("CREATE OR REPLACE TABLE migration_drift AS SELECT * FROM drift_df")
    # Paramètres du calcul, réutilisés par le simulateur du tableau de bord (phase 5)
    sat_beta = sat["beta"] or [float("nan")] * 3
    params = {"delta": delta, "lra": cal["lra"], "rho": RHO, "cpr": cpr, "ead_factor": ead_factor,
              "sat_b0": sat_beta[0], "sat_b_unemp": sat_beta[1], "sat_b_hpi": sat_beta[2], "sat_r2": sat["r2"],
              "sat_fallback": float(sat["fallback"]), "sicr_notches": SICR_NOTCHES, "sicr_min_pd": SICR_MIN_PD,
              "pd_floor": PD_FLOOR_BASEL, "lgd_floor": LGD_FLOOR_BASEL, "max_years": MAX_YEARS}
    con.register("par_df", pd.DataFrame([{"name": k, "value": float(v)} for k, v in params.items()]))
    con.execute("CREATE OR REPLACE TABLE ecl_parameters AS SELECT * FROM par_df")

    args.model_out.mkdir(parents=True, exist_ok=True)
    args.figures_out.mkdir(parents=True, exist_ok=True)
    write_report(args.model_out / "ecl_report.md", locals())
    make_figures(args.figures_out, annual, matrix, stages, scen, weighted)
    report = run_checks(con, "17_ecl_checks.sql")
    n_fail = print_report(report)
    con.close()
    print(f"\nTerminé en {time.time() - start:.0f} s. Rapport : {args.model_out / 'ecl_report.md'}")
    sys.exit(1 if n_fail else 0)


def write_report(path: Path, v: dict) -> None:
    sat, annual, scen, stages = v["sat"], v["annual"], v["scen"], v["stages"]
    L = ["# Phase 4 — Calibrage, perte attendue IFRS 9 et capital\n",
         f"Date d'arrêté : **{v['snapshot_date']}**. Rapport généré par `src/build_ecl.py` ; toutes les valeurs "
         "sont recalculées à chaque exécution.\n",
         "## 1. Calibrage de la PD\n",
         f"- Taux de défaut moyen de long terme (moyenne des taux annuels) : **{pct(v['cal']['lra'])}**.",
         f"- Décalage de la constante du modèle pour obtenir la PD TTC : **{'+' if v['delta'] >= 0 else '−'}{fr(abs(v['delta']), 3)}** (en logit).",
         f"- Modèle de Vasicek, corrélation ρ = {fr(RHO, 2)} (valeur bâloise des crédits immobiliers).\n"]
    if sat["fallback"]:
        L.append("Lien avec la conjoncture : variation macroéconomique insuffisante, scénarios fixés sur Z = 0, -1, -2.\n")
    else:
        b = sat["beta"]
        L.append(f"Modèle satellite (Z expliqué par la conjoncture, {sat['n_years']} années, 2020 exclue) : "
                 f"Z = {fr(b[0], 3)} {'+' if b[1] >= 0 else '−'} {fr(abs(b[1]), 3)} × hausse du chômage "
                 f"{'+' if b[2] >= 0 else '−'} {fr(abs(b[2]), 3)} × évolution des prix immobiliers ; "
                 f"R² = {fr(sat['r2'], 2)}.\n")
    L += ["| Année | Taux observé | PD du modèle | PD TTC | Facteur Z | PD PIT (conjoncture) |",
          "| --- | --- | --- | --- | --- | --- |"]
    for r in annual.itertuples():
        L.append(f"| {r.year} | {pct(r.observed)} | {pct(r.pd_model)} | {pct(r.pd_ttc)} | "
                 f"{'–' if np.isnan(r.z) else fr(r.z, 2)} | {pct(r.pd_pit_macro)} |")
    L += ["\n## 2. Scénarios macroéconomiques\n",
          "Hypothèses illustratives, à 12 mois. Elles ne sont pas des prévisions officielles.\n",
          "| Scénario | Poids | Hausse du chômage | Prix immobiliers | Facteur Z | PD moyenne (prêts sains) | ECL |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in scen.itertuples():
        L.append(f"| {r.scenario} | {pct(r.weight, 0)} | {'+' if r.d_unemp > 0 else ''}{fr(r.d_unemp, 1)} pt | {'+' if r.hpi > 0 else ''}{pct(r.hpi, 0)} | {fr(r.z, 2)} | "
                 f"{pct(r.pd_mean)} | {fr(r.ecl / 1e6, 2)} M$ |")
    L.append(f"\n**ECL pondérée retenue : {fr(v['weighted'] / 1e6, 2)} M$.**\n")
    L += ["## 3. LGD et EAD\n",
          "LGD = pertes / exposition au défaut, sur les défauts résolus (les défauts guéris comptent avec une "
          "perte nulle). LGD de crise : défauts de 2008 à 2011.\n",
          "| Tranche de CLTV | Défauts résolus | Taux de guérison | Sévérité si liquidation | LGD | LGD de crise retenue |",
          "| --- | --- | --- | --- | --- | --- |"]
    for r in v["lgd_tab"].itertuples():
        L.append(f"| {r.cltv_band} | {fr(r.n_resolved, 0)} | {pct(r.cure_rate, 1)} | {pct(r.severity, 1)} | "
                 f"{pct(r.lgd, 1)} | {pct(r.lgd_downturn, 1)} |")
    L.append(f"\nFacteur d'EAD (encours au défaut / encours 12 mois avant) : **{fr(v['ead_factor'], 3)}** : "
             "l'EAD retenue est l'encours. La LGD n'augmente pas avec la CLTV au-delà de 80 % : chez Freddie Mac, ces "
             "prêts sont couverts par une assurance hypothécaire (mortgage insurance), dont les indemnités "
             "réduisent la perte. Remboursements anticipés : "
             f"**{pct(v['cpr'], 1)} par an** (5 dernières années).\n")
    L += ["## 4. Staging IFRS 9\n",
          f"Règles, dans l'ordre : Stage 3 si 90 jours de retard ou plus ; Stage 2 si retard de 30 jours ou plus, "
          f"sortie du défaut ou restructuration depuis moins de 2 ans (période probatoire), plan d'aide en cours, ou dégradation d'au moins {SICR_NOTCHES} "
          f"crans depuis l'octroi avec une PD d'au moins {pct(SICR_MIN_PD, 0)} ; sinon Stage 1. La note « à l'octroi » est "
          "recalculée à ancienneté égale, sans les retards : la dégradation mesure donc le comportement de paiement.\n",
          "| Stage | Prêts | Encours | Part de l'encours | ECL | Part de l'ECL | Couverture |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in stages.itertuples():
        L.append(f"| Stage {r.stage} | {fr(r.n, 0)} | {fr(r.ead / 1e6, 1)} M$ | {pct(r.ead_share, 1)} | "
                 f"{fr(r.ecl / 1e6, 2)} M$ | {pct(r.ecl_share, 1)} | {pct(r.coverage)} |")
    L += ["\n| Stage | Motif | Prêts | Encours |", "| --- | --- | --- | --- |"]
    for r in v["reasons"].itertuples():
        L.append(f"| {r.stage} | {r.stage_reason} | {fr(r.n, 0)} | {fr(r.ead / 1e6, 1)} M$ |")
    L += ["\n## 5. Migrations annuelles entre classes (PD TTC)\n",
          "| Période | Observations | Amélioration | Stable | Dégradation (y c. défaut) |",
          "| --- | --- | --- | --- | --- |"]
    for k, d in v["drifts"].items():
        L.append(f"| {k} | {fr(d['n'], 0)} | {pct(d['up'], 1)} | {pct(d['same'], 1)} | {pct(d['down'], 1)} |")
    da = v["drifts"].get("Toutes années", {}).get("down_age", float("nan"))
    if not np.isnan(da):
        L.append(f"\nLes dégradations s'expliquent {'surtout' if da >= 0.5 else 'en partie'} par "
                 f"le **vieillissement des prêts**. Le risque d'un crédit immobilier culmine entre 24 et "
                 f"36 mois d'ancienneté ; en un an, un prêt récent change de tranche d'ancienneté dans le modèle. "
                 f"**{pct(da, 0)}** des dégradations (hors défaut) coïncident avec un tel changement de tranche.")
    m = v["matrix"][v["matrix"]["period"] == "Toutes années"]
    cols = [f"R{g}" for g in range(1, 9)] + ["Défaut", "Sorti"]
    piv = m.pivot_table(index="from_grade", columns="to_state", values="share", aggfunc="sum").reindex(columns=cols).fillna(0)
    L += ["\nMatrice toutes années (% de chaque ligne) :\n", "| De \\ vers | " + " | ".join(cols) + " |",
          "| --- |" + " --- |" * len(cols)]
    for g, row in piv.iterrows():
        L.append(f"| {g} | " + " | ".join(fr(100 * x, 1) for x in row) + " |")
    L += ["\n## 6. Capital réglementaire (approche IRB, prêts sains)\n",
          f"PD TTC (plancher {pct(PD_FLOOR_BASEL)}), LGD de crise (plancher {pct(LGD_FLOOR_BASEL, 0)}), ρ = {fr(RHO, 2)}, "
          "quantile 99,9 %.\n",
          f"- Perte attendue réglementaire (EL) : **{fr(v['el_basel'] / 1e6, 2)} M$**",
          f"- Actifs pondérés (RWA) : **{fr(v['rwa'] / 1e6, 1)} M$**, soit une densité de "
          f"{pct(v['rwa'] / v['ead_perf'].sum(), 1)} de l'encours sain",
          f"- Fonds propres à 8 % des RWA : **{fr(0.08 * v['rwa'] / 1e6, 1)} M$**\n",
          "## 7. Limites\n",
          "- La PD TTC contient des variables de comportement (retard du mois), elle-mêmes sensibles au cycle : "
          "c'est une PD hybride, plus proche du TTC que du PIT.",
          "- Le modèle satellite repose sur une vingtaine de points annuels : ses coefficients sont indicatifs.",
          "- Les scénarios sont des hypothèses illustratives ; une banque utilise ceux de sa direction économique.",
          f"- Le scénario central donne une PD moyenne supérieure aux taux de défaut observés récemment "
          f"({pct(annual['observed'].iloc[-1])} la dernière année complète) : la constante du modèle satellite est "
          "estimée sur un cycle qui inclut la crise de 2008, et il n'explique pas tout le niveau très bas des défauts "
          "depuis 2013 (octrois plus prudents). Une banque corrigerait ce point par un ajustement post-modèle "
          "(overlay) documenté ; la provision calculée ici est donc prudente.",
          "- Le modèle satellite relie le facteur de l'année aux évolutions macroéconomiques des 12 mois "
          "précédents ; les scénarios appliquent la même convention.",
          "- Les PD des années 2 et suivantes reviennent vers la PD TTC « assainie » : simplification courante.",
          "- LGD : coûts internes de recouvrement et actualisation des flux non inclus ; la LGD de crise est "
          "mesurée sur les défauts de 2008 à 2011."]
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
