"""Briques du modèle de PD : découpage en classes, WoE / IV, régression logistique.

Méthode « scorecard » classique en risque de crédit :
  1. chaque variable est découpée en classes (bins) ;
  2. chaque classe reçoit son Weight of Evidence (WoE), qui mesure si elle
     contient plus ou moins de défauts que la moyenne ;
  3. l'Information Value (IV) résume le pouvoir discriminant de la variable ;
  4. une régression logistique est estimée sur les WoE.
Avantages : modèle lisible classe par classe, robuste aux valeurs extrêmes et
aux valeurs manquantes (classe « Manquant »), facile à valider et à expliquer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import roc_auc_score, roc_curve

MISSING = "Manquant"

# --- Spécification des variables candidates ----------------------------------
# Bornes choisies pour être lisibles par un métier (et non optimisées à l'aveugle).
FEATURES: dict[str, dict] = {
    "fico_score":        {"label": "Score FICO à l'octroi", "type": "num",
                          "edges": [620, 660, 700, 740, 780], "fmt": "{:.0f}"},
    "cltv_pct":          {"label": "CLTV à l'octroi (%)", "type": "num",
                          "edges": [60, 80, 90, 95], "fmt": "{:.0f}"},
    "dti_pct":           {"label": "Taux d'endettement DTI (%)", "type": "num",
                          "edges": [20, 30, 40, 45], "fmt": "{:.0f}"},
    "sato":              {"label": "Écart de taux à l'octroi, SATO (points)", "type": "num",
                          "edges": [-0.25, 0, 0.25, 0.5], "fmt": "{:+.2f}"},
    "age":               {"label": "Ancienneté du prêt (mois)", "type": "num",
                          "edges": [12, 24, 36, 60, 120], "fmt": "{:.0f}"},
    # Variables de conjoncture : mesurées mais exclues du modèle principal (voir README).
    # Elles ne prennent qu'UNE valeur par date d'observation : avec 9 années
    # d'apprentissage, leurs classes reviennent à reconnaître l'année, pas un mécanisme.
    "unemployment_rate": {"label": "Taux de chômage US (%)", "type": "num", "macro": True,
                          "edges": [4.5, 5.5, 7, 9], "fmt": "{:.1f}"},
    "hpi_yoy":           {"label": "Évolution des prix immobiliers sur 12 mois", "type": "num", "macro": True,
                          "edges": [-0.05, 0, 0.05, 0.10], "fmt": "{:+.0%}"},
    "dq_state":          {"label": "Retard ce mois-ci", "type": "cat"},
    "dq_history_12m":    {"label": "Pire retard des 12 derniers mois", "type": "cat"},
    "modified":          {"label": "Prêt déjà modifié", "type": "cat"},
    "assistance_plan":   {"label": "Plan d'aide en cours", "type": "cat"},
    "loan_purpose":      {"label": "Objet du prêt", "type": "cat"},
    "occupancy":         {"label": "Occupation du bien", "type": "cat"},
    "channel_group":     {"label": "Canal de distribution", "type": "cat"},
    "n_borrowers":       {"label": "Nombre d'emprunteurs", "type": "cat"},
}


def bin_labels(edges: list[float], fmt: str) -> list[str]:
    f = fmt.format
    labels = [f"< {f(edges[0])}"]
    labels += [f"{f(a)} à {f(b)}" for a, b in zip(edges[:-1], edges[1:])]
    labels.append(f"≥ {f(edges[-1])}")
    return labels


def apply_bins(s: pd.Series, spec: dict) -> pd.Series:
    """Transforme une colonne en libellés de classes (chaînes)."""
    if spec["type"] == "num":
        edges = spec["edges"]
        cut = pd.cut(s.astype(float), bins=[-np.inf, *edges, np.inf], right=False,
                     labels=bin_labels(edges, spec["fmt"]))
        return cut.astype(object).where(s.notna(), MISSING).astype(str)
    out = s.astype(object).where(s.notna(), MISSING).astype(str)
    allowed = spec.get("categories")
    if allowed is not None:                      # catégories rares regroupées à l'apprentissage
        out = out.where(out.isin(allowed), "Autre")
    return out


@dataclass
class WoEBinner:
    """Calcule et applique les WoE. Convention : WoE = ln(% de bons / % de mauvais).
    Un WoE positif = classe moins risquée que la moyenne."""
    specs: dict[str, dict]
    min_share: float = 0.001          # catégories < 0,1 % des observations regroupées en « Autre »
    min_bin_obs: int = 500            # classe trop petite : WoE neutre (0) plutôt qu'un WoE bruité
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)

    def fit(self, df: pd.DataFrame, y: pd.Series) -> "WoEBinner":
        y = y.astype(int).to_numpy()
        n_bad, n_good = y.sum(), len(y) - y.sum()
        # seuil de taille d'une classe : 500 observations, ou 0,2 % de l'échantillon s'il est petit
        min_obs = min(self.min_bin_obs, max(10, int(0.002 * len(y))))
        for name, spec in self.specs.items():
            spec = dict(spec)
            if spec["type"] == "cat":
                shares = df[name].astype(object).fillna(MISSING).astype(str).value_counts(normalize=True)
                spec["categories"] = sorted(shares[shares >= self.min_share].index.tolist())
                self.specs[name] = spec
            bins = apply_bins(df[name], spec)
            t = (pd.DataFrame({"bin": bins.to_numpy(), "bad": y})
                 .groupby("bin", sort=False)["bad"].agg(n="size", bad="sum").reset_index())
            t["good"] = t["n"] - t["bad"]
            k = len(t)
            # lissage de 0,5 pour éviter ln(0) dans une classe sans défaut
            t["dist_good"] = (t["good"] + 0.5) / (n_good + 0.5 * k)
            t["dist_bad"] = (t["bad"] + 0.5) / (n_bad + 0.5 * k)
            t["woe"] = np.log(t["dist_good"] / t["dist_bad"])
            t.loc[t["n"] < min_obs, "woe"] = 0.0
            t["iv_part"] = (t["dist_good"] - t["dist_bad"]) * t["woe"]
            t["bad_rate"] = t["bad"] / t["n"]
            t["share"] = t["n"] / t["n"].sum()
            t = t.sort_values("woe", ascending=False) if spec["type"] == "cat" else t
            if spec["type"] == "num":
                order = bin_labels(spec["edges"], spec["fmt"]) + [MISSING]
                t["_o"] = t["bin"].map({b: i for i, b in enumerate(order)})
                t = t.sort_values("_o").drop(columns="_o")
            self.tables[name] = t.reset_index(drop=True)
        return self

    def iv(self) -> pd.DataFrame:
        rows = [{"feature": n, "label": self.specs[n]["label"], "iv": t["iv_part"].sum(),
                 "n_bins": len(t)} for n, t in self.tables.items()]
        return pd.DataFrame(rows).sort_values("iv", ascending=False).reset_index(drop=True)

    def transform(self, df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
        out = {}
        for name in features:
            mapping = dict(zip(self.tables[name]["bin"], self.tables[name]["woe"]))
            # classe jamais vue à l'apprentissage : WoE neutre (0 = risque moyen)
            out[name] = apply_bins(df[name], self.specs[name]).map(mapping).fillna(0.0)
        return pd.DataFrame(out, index=df.index)


def iv_strength(iv: float) -> str:
    """Grille de lecture usuelle de l'Information Value."""
    if iv < 0.02:
        return "Inutile"
    if iv < 0.1:
        return "Faible"
    if iv < 0.3:
        return "Moyen"
    if iv < 0.5:
        return "Fort"
    return "Très fort"


def fit_logit(X: pd.DataFrame, y: pd.Series):
    return sm.Logit(y.astype(int), sm.add_constant(X, has_constant="add")).fit(disp=False, maxiter=200)


def select_and_fit(X: pd.DataFrame, y: pd.Series, max_iter: int = 20):
    """Régression logistique avec élimination pas à pas.
    Avec des WoE (positifs = moins risqué), chaque coefficient doit être NÉGATIF :
    un coefficient positif ou non significatif (p > 5 %) signale une variable
    redondante avec une autre ; on la retire et on ré-estime."""
    features = list(X.columns)
    removed = []
    for _ in range(max_iter):
        res = fit_logit(X[features], y)
        params, pvals = res.params.drop("const"), res.pvalues.drop("const")
        bad = [(f, "coefficient de mauvais signe") for f in features if params[f] >= 0]
        bad += [(f, "non significative (p > 5 %)") for f in features if pvals[f] > 0.05 and params[f] < 0]
        if not bad:
            return res, features, removed
        # on retire la pire : d'abord les mauvais signes, puis la p-value la plus haute
        worst = max(bad, key=lambda b: (b[1].startswith("coefficient"), pvals[b[0]]))
        features.remove(worst[0])
        removed.append(worst)
        if not features:
            raise ValueError("Aucune variable retenue")
    return res, features, removed


def predict_pd(res, X: pd.DataFrame) -> np.ndarray:
    return np.asarray(res.predict(sm.add_constant(X, has_constant="add")))


# --- Mesures de performance ---------------------------------------------------
def auc_gini(y, p) -> tuple[float, float]:
    auc = roc_auc_score(y, p)
    return auc, 2 * auc - 1


def ks_stat(y, p) -> float:
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def psi(expected: pd.Series, actual: pd.Series) -> float:
    """Population Stability Index entre deux répartitions (par classe de notation)."""
    e = expected.value_counts(normalize=True)
    a = actual.value_counts(normalize=True)
    idx = e.index.union(a.index)
    e, a = e.reindex(idx).fillna(1e-6), a.reindex(idx).fillna(1e-6)
    return float(((a - e) * np.log(a / e)).sum())


# --- Échelle de notation -------------------------------------------------------
# Échelle maîtresse à bornes FIXES de PD : la note d'un prêt ne dépend que de sa
# PD, pas du reste du portefeuille. Bornes approximativement géométriques.
MASTER_SCALE = [0.0, 0.0025, 0.005, 0.01, 0.02, 0.05, 0.10, 0.25, 1.0]


def rating_scale() -> pd.DataFrame:
    rows = []
    for g, (lo, hi) in enumerate(zip(MASTER_SCALE[:-1], MASTER_SCALE[1:]), start=1):
        rows.append({"grade": g, "label": f"R{g}", "pd_lower": lo, "pd_upper": hi})
    return pd.DataFrame(rows)


def assign_grade(pd_values: np.ndarray) -> np.ndarray:
    inner = np.array(MASTER_SCALE[1:-1])
    return np.searchsorted(inner, pd_values, side="right") + 1


# --- Grille de points (présentation « scorecard ») ------------------------------
def scorecard_points(binner: WoEBinner, res, features: list[str],
                     base_score: int = 600, base_odds: float = 50, pdo: int = 20) -> pd.DataFrame:
    """Convertit le modèle en points : 600 points = 50 bons pour 1 mauvais,
    et +20 points (PDO) = cote doublée. Plus le score est haut, moins le risque est élevé."""
    factor = pdo / math.log(2)
    offset = base_score - factor * math.log(base_odds)
    n = len(features)
    b0 = res.params["const"]
    rows = []
    for f in features:
        beta = res.params[f]
        for r in binner.tables[f].itertuples():
            # logit(défaut) = b0 + Σ beta·WoE  ->  ln(cote bons/mauvais) = -(b0 + Σ beta·WoE)
            pts = -(beta * r.woe + b0 / n) * factor + offset / n
            rows.append({"feature": f, "label": binner.specs[f]["label"], "bin": r.bin,
                         "share": r.share, "bad_rate": r.bad_rate, "woe": r.woe, "points": round(pts)})
    return pd.DataFrame(rows)
