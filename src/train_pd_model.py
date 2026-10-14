"""Phase 3 : entraîne, valide et applique le modèle de PD à 12 mois.

Utilisation (après build_analytics.py) :
    python src/train_pd_model.py

Étapes :
  1. construit le jeu de données (sql/13_pd_dataset.sql) ;
  2. découpe dans le temps : apprentissage (observations jusqu'à 2014, dont 25 %
     des prêts mis de côté pour la validation) et test hors période (2015 et après) ;
  3. calcule WoE et IV, estime la régression logistique (sélection pas à pas) ;
  4. mesure la performance (AUC, Gini, KS), la calibration et la stabilité (PSI),
     et compare à un modèle « challenger » (gradient boosting) ;
  5. attribue une note R1 à R8 et remplit les tables rating_scale et risk_ratings ;
  6. écrit le rapport (docs/model/), le modèle (JSON lisible) et 4 graphiques ;
  7. lance les contrôles de sql/14_pd_checks.sql.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DB_PATH, ROOT, SQL_DIR  # noqa: E402
from pd_model import (FEATURES, MASTER_SCALE, WoEBinner, assign_grade, auc_gini,  # noqa: E402
                      iv_strength, ks_stat, predict_pd, psi, rating_scale,
                      scorecard_points, select_and_fit)
from run_quality_checks import print_report, run_checks  # noqa: E402

MODEL_VERSION = "pd-logit-woe-v2"
SEED = 42


def fr(x: float, digits: int = 1) -> str:
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")


def pct(x: float, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{fr(100 * x, digits)} %"


def split_samples(dev: pd.DataFrame, train_until: int) -> pd.Series:
    """Renvoie pour chaque ligne : 'Apprentissage', 'Validation' ou 'Hors période'.
    La validation contient 25 % des PRÊTS (et non des lignes) de la période
    d'apprentissage : un même prêt n'est jamais des deux côtés."""
    in_time = dev["period"].dt.year <= train_until
    loans = np.sort(dev.loc[in_time, "loan_id"].unique())
    rng = np.random.default_rng(SEED)
    holdout = set(rng.choice(loans, size=int(0.25 * len(loans)), replace=False))
    sample = np.where(~in_time, "Hors période",
                      np.where(dev["loan_id"].isin(holdout), "Validation", "Apprentissage"))
    return pd.Series(sample, index=dev.index)


def challenger_auc(train: pd.DataFrame, test: pd.DataFrame, features: list[str]) -> float:
    """Gradient boosting sur les variables brutes : sert de point de comparaison.
    S'il fait beaucoup mieux, la régression logistique laisse de la performance de côté."""
    def prep(df):
        X = df[features].copy()
        for f in features:
            if FEATURES[f]["type"] == "cat":
                X[f] = X[f].astype("category")
        return X
    tr = train.sample(n=min(len(train), 400_000), random_state=SEED)
    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, max_leaf_nodes=31,
                                           categorical_features="from_dtype", random_state=SEED)
    Xtr, Xte = prep(tr), prep(test)
    for f in features:                       # mêmes catégories des deux côtés
        if FEATURES[f]["type"] == "cat":
            cats = Xtr[f].cat.categories.union(Xte[f].dropna().unique())
            Xtr[f] = Xtr[f].cat.set_categories(cats)
            Xte[f] = Xte[f].astype("category").cat.set_categories(cats)
    model.fit(Xtr, tr["default_12m"].astype(int))
    return auc_gini(test["default_12m"].astype(int), model.predict_proba(Xte)[:, 1])[0]


# --- Graphiques ------------------------------------------------------------------
def make_figures(out: Path, iv: pd.DataFrame, kept: list[str], curves: dict, by_year: pd.DataFrame,
                 grades: pd.DataFrame, train_until: int, gini: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    from make_figures import AXIS, BLUE, INK, INK_2, fr as frf, setup_style, source, titles

    setup_style()
    pfmt = lambda d: FuncFormatter(lambda v, _: f"{frf(100 * v, d)} %")  # noqa: E731

    # 06 — Information Value
    top = iv.iloc[0]
    fig, ax = plt.subplots(figsize=(10, 0.42 * len(iv) + 1.6))
    fig.subplots_adjust(left=0.36)
    d = iv.iloc[::-1]
    ax.barh(d["label"], d["iv"], color=[BLUE if f in kept else AXIS for f in d["feature"]], height=0.62)
    for y, v in enumerate(d["iv"]):
        ax.text(v, y, f"  {frf(v, 2)}", va="center", fontsize=9.5, color=INK)
    for x in (0.02, 0.1, 0.3):
        ax.axvline(x, color=AXIS, linewidth=0.8, linestyle=(0, (3, 3)))
    ax.set_xlim(0, d["iv"].max() * 1.18)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: frf(v, 1)))
    fig.subplots_adjust(top=0.93)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    titles(fig, f"La variable la plus discriminante est « {top['label']} » (IV = {frf(top['iv'], 2)})",
           "Information Value de chaque variable candidate. En bleu : variables du modèle final ; en gris : écartées\n"
           "(IV trop faible, redondance, ou conjoncture traitée en phase 4). "
           "Repères : 0,02 = seuil d'utilité, 0,1 = faible, 0,3 = fort.")
    source(fig)
    fig.savefig(out / "06_pd_information_value.png")
    plt.close(fig)

    # 07 — Courbes ROC
    colors = {"Apprentissage": BLUE, "Validation": "#5B9AE6", "Hors période": "#B4500E"}
    fig, ax = plt.subplots(figsize=(6.6, 6))
    for name, (fpr, tpr) in curves.items():
        ax.plot(fpr, tpr, color=colors[name], linewidth=2, label=f"{name} · Gini {frf(100 * gini[name], 1)} %")
    ax.plot([0, 1], [0, 1], color=AXIS, linewidth=1, linestyle=(0, (3, 3)))
    ax.set_xlabel("Part des prêts sains signalés à tort")
    ax.set_ylabel("Part des défauts détectés")
    ax.xaxis.set_major_formatter(pfmt(0))
    ax.yaxis.set_major_formatter(pfmt(0))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(frameon=False, loc="lower right")
    titles(fig, f"Hors période, le modèle garde un Gini de {frf(100 * gini['Hors période'], 0)} %",
           "Courbe ROC : plus elle s'écarte de la diagonale (hasard), mieux le modèle\nsépare les prêts qui feront défaut des autres.")
    source(fig)
    fig.savefig(out / "07_pd_roc.png")
    plt.close(fig)

    # 08 — Calibration par année d'observation
    gap = by_year[by_year["year"] > train_until]
    mean_gap = (gap["predicted"] - gap["observed"]).abs().mean() if len(gap) else float("nan")
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.axvspan(train_until + 0.5, by_year["year"].max() + 0.5, color="#F3F5F8", zorder=0)
    ax.plot(by_year["year"], by_year["observed"], color=INK_2, linewidth=2, marker="o", markersize=5,
            label="Taux de défaut observé")
    ax.plot(by_year["year"], by_year["predicted"], color=BLUE, linewidth=2, marker="o", markersize=5,
            label="PD moyenne prédite")
    ax.text(train_until + 0.7, ax.get_ylim()[1] * 0.95, "Hors période", color=INK_2, fontsize=9.5, va="top")
    ax.yaxis.set_major_formatter(pfmt(1))
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Année d'observation (défaut mesuré sur les 12 mois suivants)")
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(frameon=False, loc="upper right")
    titles(fig, f"Hors période, la PD prédite s'écarte en moyenne de {frf(100 * mean_gap, 2)} point du taux observé",
           "Calibration : la PD moyenne prédite doit suivre le taux de défaut réellement observé, année après année.")
    source(fig)
    fig.savefig(out / "08_pd_calibration.png")
    plt.close(fig)

    # 09 — Échelle de notation
    g = grades[grades["n"] > 0].sort_values("grade")
    first, last = g.iloc[0], g.iloc[-1]
    solid = g[g["n"] >= 100]["observed"]               # classes assez peuplées pour juger
    monotonic = solid.is_monotonic_increasing
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4.4))
    a1.bar(g["label"], g["share"], color=BLUE, width=0.65)
    for x, v in zip(g["label"], g["share"]):
        a1.text(x, v, f"{frf(100 * v, 0)} %", ha="center", va="bottom", fontsize=9, color=INK)
    a1.yaxis.set_major_formatter(pfmt(0))
    a1.set_title("Répartition des prêts", fontsize=10.5, color=INK_2, loc="left")
    a1.grid(axis="x", visible=False)
    a2.bar(g["label"], g["observed"], color="#B4500E", width=0.65, label="Taux de défaut observé")
    a2.scatter(g["label"], g["predicted"], color=INK, zorder=3, s=22, label="PD moyenne prédite")
    a2.set_yscale("log")
    a2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{frf(100 * v, 2 if v < 0.01 else 0)} %"))
    a2.set_title("Défaut à 12 mois (échelle logarithmique)", fontsize=10.5, color=INK_2, loc="left")
    a2.legend(frameon=False, fontsize=9, loc="upper left")
    a2.grid(axis="x", visible=False)
    verdict = ("Le taux de défaut observé monte à chaque classe" if monotonic
               else "Le taux de défaut observé n'augmente pas à chaque classe (voir le contrôle P05)")
    titles(fig, f"{verdict} : {pct(first['observed'])} en {first['label']}, "
                f"{pct(last['observed'], 1)} en {last['label']}",
           "Échelle de notation interne, échantillon hors période. Bornes de PD fixes (échelle maîtresse).")
    fig.subplots_adjust(top=0.82, wspace=0.28)
    source(fig)
    fig.savefig(out / "09_rating_scale.png")
    plt.close(fig)


# --- Rapport ----------------------------------------------------------------------
def write_report(path: Path, ctx: dict) -> None:
    L = []
    L.append("# Modèle de PD à 12 mois — rapport de développement\n")
    L.append(f"Version `{MODEL_VERSION}`. Rapport généré automatiquement par `src/train_pd_model.py` : "
             "toutes les valeurs sont recalculées à chaque exécution.\n")
    L.append("## 1. Données\n")
    L.append("Une observation = un prêt sain (pas encore en défaut) observé en janvier d'une année. "
             "Cible = défaut (90 jours de retard ou sortie avec perte) dans les 12 mois suivants.\n")
    L.append("| Échantillon | Période d'observation | Observations | Défauts | Taux de défaut |")
    L.append("| --- | --- | --- | --- | --- |")
    for r in ctx["samples"].itertuples():
        L.append(f"| {r.sample} | {r.years} | {fr(r.n, 0)} | {fr(r.k, 0)} | {pct(r.rate)} |")
    L.append("\n## 2. Pouvoir discriminant des variables (Information Value)\n")
    L.append("| Variable | IV | Lecture | Retenue |")
    L.append("| --- | --- | --- | --- |")
    for r in ctx["iv"].itertuples():
        kept = "oui" if r.feature in ctx["kept"] else ("retirée : " + ctx["removed"].get(r.feature, "IV < 0,02"))
        L.append(f"| {r.label} | {fr(r.iv, 3)} | {iv_strength(r.iv)} | {kept} |")
    L.append("\n## 3. Modèle (régression logistique sur les WoE)\n")
    L.append("Avec la convention WoE = ln(% bons / % mauvais), chaque coefficient doit être négatif.\n")
    L.append("| Variable | Coefficient | Erreur type | p-value |")
    L.append("| --- | --- | --- | --- |")
    res = ctx["res"]
    for name in ["const", *ctx["kept"]]:
        label = "Constante" if name == "const" else FEATURES[name]["label"]
        L.append(f"| {label} | {fr(res.params[name], 4)} | {fr(res.bse[name], 4)} | {res.pvalues[name]:.1e} |".replace("e-", " e-").replace(".", ","))
    L.append("\n## 4. Performance\n")
    L.append("| Échantillon | AUC | Gini | KS |")
    L.append("| --- | --- | --- | --- |")
    for name, m in ctx["perf"].items():
        L.append(f"| {name} | {fr(m['auc'], 3)} | {pct(m['gini'], 1)} | {pct(m['ks'], 1)} |")
    L.append(f"\nModèle challenger (gradient boosting, variables brutes), AUC hors période : "
             f"**{fr(ctx['challenger_auc'], 3)}**, contre {fr(ctx['perf']['Hors période']['auc'], 3)} "
             "pour la régression logistique.\n")
    L.append("## 5. Calibration par année d'observation\n")
    L.append("| Année | Observations | Taux observé | PD moyenne prédite |")
    L.append("| --- | --- | --- | --- |")
    for r in ctx["by_year"].itertuples():
        L.append(f"| {r.year} | {fr(r.n, 0)} | {pct(r.observed)} | {pct(r.predicted)} |")
    L.append("\n## 6. Échelle de notation (échantillon hors période)\n")
    L.append("| Classe | PD de la classe | Part des prêts | PD moyenne prédite | Taux de défaut observé |")
    L.append("| --- | --- | --- | --- | --- |")
    for r in ctx["grades"].itertuples():
        L.append(f"| {r.label} | {pct(r.pd_lower)} à {pct(r.pd_upper)} | {pct(r.share, 1)} | "
                 f"{pct(r.predicted)} | {pct(r.observed)} |")
    L.append(f"\nStabilité de la répartition par classe entre apprentissage et hors période : "
             f"PSI = **{fr(ctx['psi'], 3)}** (< 0,10 stable ; 0,10 à 0,25 à surveiller ; > 0,25 instable).\n")
    L.append("## 7. Grille de points (600 points = 50 bons pour 1 mauvais, +20 points = cote doublée)\n")
    L.append("| Variable | Classe | Part | Taux de défaut | Points |")
    L.append("| --- | --- | --- | --- | --- |")
    for r in ctx["points"].itertuples():
        L.append(f"| {r.label} | {r.bin} | {pct(r.share, 1)} | {pct(r.bad_rate)} | {r.points} |")
    if ctx["variant"]:
        v, by = ctx["variant"], ctx["by_year"]
        oot = by[by["year"] > ctx["train_until"]]
        gap = lambda col: (oot[col] - oot["observed"]).abs().mean()  # noqa: E731
        L.append("\n## 8. Variante écartée : modèle avec variables de conjoncture\n")
        L.append("Le chômage et l'évolution des prix immobiliers ne prennent qu'une valeur par date "
                 "d'observation : sur 9 années d'apprentissage, leurs classes reviennent surtout à reconnaître "
                 "l'année. Le modèle principal les exclut ; la conjoncture sera intégrée en phase 4 "
                 "(recalibrage et scénarios IFRS 9). Comparaison :\n")
        L.append("| Échantillon | Gini modèle principal | Gini avec conjoncture |")
        L.append("| --- | --- | --- |")
        for name in ["Apprentissage", "Validation", "Hors période"]:
            L.append(f"| {name} | {pct(ctx['perf'][name]['gini'], 1)} | {pct(v[name], 1)} |")
        L.append(f"\nÉcart moyen hors période entre PD prédite et taux observé (par année) : "
                 f"{fr(100 * gap('predicted'), 2)} point pour le modèle principal, "
                 f"{fr(100 * gap('predicted_variant'), 2)} point avec conjoncture.\n")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


# --- Programme principal ----------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-until", type=int, default=2014,
                        help="dernière année d'observation de l'apprentissage")
    parser.add_argument("--figures-out", type=Path, default=ROOT / "docs" / "figures")
    parser.add_argument("--model-out", type=Path, default=ROOT / "docs" / "model")
    args = parser.parse_args()
    if not DB_PATH.exists():
        raise SystemExit("La base n'existe pas : lance d'abord  python src/load_freddie.py")
    start = time.time()
    con = duckdb.connect(str(DB_PATH))
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'loan_month_pd'").fetchone()[0] == 0:
        raise SystemExit("La couche analytique n'existe pas : lance d'abord  python src/build_analytics.py")

    print("1/7  Construction du jeu de données")
    con.execute((SQL_DIR / "13_pd_dataset.sql").read_text(encoding="utf-8"))
    df = con.execute("SELECT * FROM pd_dataset").df()
    df["period"] = pd.to_datetime(df["period"])
    dev = df[df["window_complete"]].copy()
    dev["sample"] = split_samples(dev, args.train_until)
    y = dev["default_12m"].astype(int)
    print(f"  {len(df):,} observations, dont {len(dev):,} avec 12 mois de recul".replace(",", " "))

    print("2/7  WoE et Information Value (sur l'apprentissage uniquement)")
    is_train = dev["sample"] == "Apprentissage"
    binner = WoEBinner(copy.deepcopy(FEATURES)).fit(dev[is_train], y[is_train])
    iv = binner.iv()
    useful = iv.loc[iv["iv"] >= 0.02, "feature"].tolist()
    # modèle principal : sans les variables de conjoncture (voir pd_model.FEATURES)
    candidates = [f for f in useful if not FEATURES[f].get("macro")]
    macro_candidates = [f for f in useful if FEATURES[f].get("macro")]
    for r in iv.itertuples():
        print(f"  {r.label:<45} IV = {r.iv:6.3f}  ({iv_strength(r.iv)})")

    print("3/7  Régression logistique")
    X_all = binner.transform(dev, candidates)
    res, kept, removed = select_and_fit(X_all[is_train], y[is_train])
    for f, why in removed:
        print(f"  retirée : {FEATURES[f]['label']} ({why})")
    print(f"  {len(kept)} variables retenues")
    for f in macro_candidates:
        removed.append((f, "conjoncture : prise en compte en phase 4"))
    dev["pd"] = predict_pd(res, X_all[kept])

    # Variante AVEC conjoncture, estimée pour comparaison (et non retenue)
    variant = {}
    if macro_candidates:
        Xv = binner.transform(dev, candidates + macro_candidates)
        res_v, kept_v, _ = select_and_fit(Xv[is_train], y[is_train])
        pd_v = predict_pd(res_v, Xv[kept_v])
        for name in ["Apprentissage", "Validation", "Hors période"]:
            m = (dev["sample"] == name).to_numpy()
            variant[name] = auc_gini(dev.loc[m, "default_12m"].astype(int), pd_v[m])[1]
        dev["pd_variant"] = pd_v

    print("4/7  Performance, calibration, challenger")
    from sklearn.metrics import roc_curve
    perf, curves, gini = {}, {}, {}
    for name in ["Apprentissage", "Validation", "Hors période"]:
        s = dev[dev["sample"] == name]
        if s["default_12m"].nunique() < 2:
            raise SystemExit(f"L'échantillon « {name} » ne contient pas de défaut : impossible de valider.")
        auc, g = auc_gini(s["default_12m"].astype(int), s["pd"])
        perf[name] = {"auc": auc, "gini": g, "ks": ks_stat(s["default_12m"].astype(int), s["pd"])}
        fpr, tpr, _ = roc_curve(s["default_12m"].astype(int), s["pd"])
        step = max(1, len(fpr) // 2000)
        curves[name], gini[name] = (fpr[::step], tpr[::step]), g
        print(f"  {name:<14} AUC {auc:.3f}   Gini {100 * g:5.1f} %   KS {100 * perf[name]['ks']:5.1f} %")
    oot = dev[dev["sample"] == "Hors période"]
    ch_auc = challenger_auc(dev[is_train], oot, candidates)
    print(f"  Challenger (gradient boosting), AUC hors période : {ch_auc:.3f}")

    agg = {"n": ("pd", "size"), "observed": ("default_12m", "mean"), "predicted": ("pd", "mean")}
    if variant:
        agg["predicted_variant"] = ("pd_variant", "mean")
    by_year = dev.assign(year=dev["period"].dt.year).groupby("year").agg(**agg).reset_index()
    samples = (dev.assign(year=dev["period"].dt.year).groupby("sample")
               .agg(n=("pd", "size"), k=("default_12m", "sum"), rate=("default_12m", "mean"),
                    y0=("year", "min"), y1=("year", "max")).reset_index())
    samples["years"] = samples["y0"].astype(str) + "-" + samples["y1"].astype(str)
    samples = samples.set_index("sample").loc[["Apprentissage", "Validation", "Hors période"]].reset_index()

    print("5/7  Échelle de notation et notes")
    dev["grade"] = assign_grade(dev["pd"].to_numpy())
    scale = rating_scale()
    grades = (oot.assign(grade=assign_grade(oot["pd"].to_numpy()))
              .groupby("grade").agg(n=("pd", "size"), predicted=("pd", "mean"), observed=("default_12m", "mean"))
              .reset_index())
    grades = scale.merge(grades, on="grade", how="left").fillna({"n": 0})
    grades["share"] = grades["n"] / grades["n"].sum()
    psi_value = psi(dev.loc[is_train, "grade"], dev.loc[dev["sample"] == "Hors période", "grade"])
    print(f"  PSI apprentissage / hors période : {psi_value:.3f}")

    # Notation de TOUTES les observations (y compris les plus récentes, sans recul)
    df["pd_12m"] = predict_pd(res, binner.transform(df, kept))
    df["grade"] = assign_grade(df["pd_12m"].to_numpy())
    ratings = df[["loan_id", "period", "pd_12m", "grade"]].rename(columns={"period": "rating_date"})
    ratings["rating_date"] = ratings["rating_date"].dt.date
    ratings["model_version"] = MODEL_VERSION
    con.execute("DELETE FROM risk_ratings")
    con.execute("DELETE FROM rating_scale")
    con.register("scale_df", scale)
    con.execute("INSERT INTO rating_scale SELECT grade, label, pd_lower, pd_upper FROM scale_df")
    con.register("ratings_df", ratings)
    con.execute("""INSERT INTO risk_ratings
                   SELECT DISTINCT ON (loan_id, rating_date) loan_id, rating_date, pd_12m, grade, model_version
                   FROM ratings_df""")
    n_rated = con.execute("SELECT count(*) FROM risk_ratings").fetchone()[0]
    print(f"  {n_rated:,} notes enregistrées dans risk_ratings".replace(",", " "))

    print("6/7  Rapport, modèle et graphiques")
    args.model_out.mkdir(parents=True, exist_ok=True)
    args.figures_out.mkdir(parents=True, exist_ok=True)
    points = scorecard_points(binner, res, kept)
    model_json = {
        "version": MODEL_VERSION,
        "target": "défaut (90 jours de retard ou sortie avec perte) dans les 12 mois",
        "train_until": args.train_until,
        "intercept": res.params["const"],
        "features": [{"name": f, "label": FEATURES[f]["label"], "coef": res.params[f],
                      "bins": binner.tables[f][["bin", "woe", "share", "bad_rate"]].to_dict("records")}
                     for f in kept],
        "master_scale": MASTER_SCALE,
        "performance": perf,
        "challenger_auc_oot": ch_auc,
        "psi": psi_value,
    }
    (args.model_out / "pd_model.json").write_text(json.dumps(model_json, ensure_ascii=False, indent=2,
                                                             default=float), encoding="utf-8")
    write_report(args.model_out / "pd_model_report.md",
                 {"samples": samples, "iv": iv, "kept": kept, "removed": dict(removed), "res": res,
                  "perf": perf, "challenger_auc": ch_auc, "by_year": by_year, "grades": grades,
                  "psi": psi_value, "points": points, "variant": variant, "train_until": args.train_until})
    make_figures(args.figures_out, iv, kept, curves, by_year, grades, args.train_until, gini)

    print("7/7  Contrôles du modèle")
    report = run_checks(con, "14_pd_checks.sql")
    n_fail = print_report(report)
    con.close()
    print(f"\nTerminé en {time.time() - start:.0f} s. Rapport : {args.model_out / 'pd_model_report.md'}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
