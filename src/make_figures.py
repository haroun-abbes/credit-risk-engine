"""Génère les graphiques de la phase 2 (PNG) à partir des vues SQL.

Utilisation (après build_analytics.py) :
    python src/make_figures.py                  # écrit dans docs/figures/
    python src/make_figures.py --out <dossier>  # autre dossier

Chaque titre est une INTERPRÉTATION calculée à partir des chiffres (pas un
texte écrit à la main) : il reste juste si les données changent. Les graphiques
ne contiennent que des agrégats, publiables sur GitHub.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # pas de fenêtre : on écrit directement des fichiers
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.ticker import FuncFormatter, MultipleLocator  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import DB_PATH, ROOT  # noqa: E402

# --- Charte graphique (identique à la maquette du tableau de bord) -----------
INK, INK_2, GRID, AXIS = "#0F1B2D", "#4A5A70", "#E6EAF0", "#8A96A8"
BLUE = "#2A62B8"
COHORT_COLORS = {2006: "#B4500E", 2007: "#E08A3C", 2012: "#2A62B8", 2017: "#5B9AE6"}
EXTRA_COLORS = ["#7A5BC7", "#1A9E77", "#C2417A", "#8A96A8"]   # cohortes ajoutées plus tard
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]


def setup_style() -> None:
    available = {f.name for f in font_manager.fontManager.ttflist}
    family = next((f for f in ("IBM Plex Sans", "Segoe UI", "Helvetica Neue", "DejaVu Sans")
                   if f in available), "sans-serif")
    plt.rcParams.update({
        "font.family": family, "font.size": 10.5,
        "text.color": INK, "axes.labelcolor": INK_2,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.8,
        "xtick.color": INK_2, "ytick.color": INK_2,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.dpi": 160, "savefig.bbox": "tight",
    })


def fr(x: float, digits: int = 1) -> str:
    """Nombre au format français : virgule décimale."""
    return f"{x:.{digits}f}".replace(".", ",")


def pct_axis(digits: int = 0) -> FuncFormatter:
    return FuncFormatter(lambda v, _: f"{fr(100 * v, digits)} %")


def month_label(d) -> str:
    return f"{MONTHS[d.month - 1]} {d.year}"


def color_for(year: int, i: int) -> str:
    return COHORT_COLORS.get(year, EXTRA_COLORS[i % len(EXTRA_COLORS)])


def titles(fig, title: str, subtitle: str) -> None:
    fig.text(0.01, 1.075, title, fontsize=13.5, fontweight="bold", color=INK, ha="left", va="bottom")
    fig.text(0.01, 1.06, subtitle, fontsize=10, color=INK_2, ha="left", va="top", linespacing=1.4)


def source(fig) -> None:
    fig.text(0.01, -0.03, "Source : Freddie Mac Single-Family Loan-Level Dataset (échantillons), "
             "calculs Credit Risk Analytics Engine.", fontsize=8.5, color=INK_2, ha="left")


# --- 1. Courbes de vintage -----------------------------------------------------
def fig_vintages(con, out: Path) -> None:
    df = con.execute("SELECT vintage_year, age, cum_default_rate FROM v_vintage_curve ORDER BY 1, 2").df()
    if df.empty:
        return
    horizons = df.groupby("vintage_year")["age"].max()
    common = int(min(60, horizons.min()))
    at = df[df["age"] == common].set_index("vintage_year")["cum_default_rate"]
    worst, best = at.idxmax(), at.idxmin()
    if at[best] > 0 and worst != best:
        title = (f"À {common} mois, la cohorte {worst} a fait {fr(at[worst] / at[best], 1)} fois "
                 f"plus défaut que la cohorte {best}")
    else:
        title = "Taux de défaut cumulé selon l'ancienneté du prêt"

    fig, ax = plt.subplots(figsize=(9, 4.8))
    for i, (year, g) in enumerate(df.groupby("vintage_year")):
        c = color_for(year, i)
        ax.plot(g["age"] / 12, g["cum_default_rate"], color=c, linewidth=2)
        last = g.iloc[-1]
        ax.annotate(f"{year} · {fr(100 * last['cum_default_rate'])} %",
                    (last["age"] / 12, last["cum_default_rate"]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9.5, color=INK)
    ax.axvline(common / 12, color=AXIS, linewidth=0.8, linestyle=(0, (3, 3)))
    ax.set_xlabel("Ancienneté du prêt (années depuis la première échéance)")
    ax.xaxis.set_major_locator(MultipleLocator(2))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.yaxis.set_major_formatter(pct_axis())
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=0)
    titles(fig, title, "Part des prêts de chaque cohorte ayant fait défaut (90 jours de retard "
                       "ou sortie avec perte), à ancienneté égale")
    source(fig)
    fig.savefig(out / "01_vintage_curves.png")
    plt.close(fig)


# --- 2. Défaut par score FICO --------------------------------------------------
def fig_fico(con, out: Path) -> None:
    df = con.execute("""
        SELECT segment, segment_order, cohorte, default_rate, n_loans
        FROM v_default_by_segment
        WHERE dimension = 'Score FICO' AND segment <> 'Inconnu'
        ORDER BY segment_order, cohorte""").df()
    if df.empty:
        return
    bands = df.drop_duplicates("segment").sort_values("segment_order")["segment"].tolist()
    tot = df[df["cohorte"] == "Toutes"].set_index("segment")["default_rate"].reindex(bands)
    if tot.is_monotonic_decreasing and tot.iloc[-1] > 0:
        title = (f"Plus le score FICO est élevé, moins le prêt fait défaut : "
                 f"{fr(100 * tot.iloc[0])} % sous 620, {fr(100 * tot.iloc[-1])} % à 780 et plus")
    else:
        title = "Taux de défaut par tranche de score FICO à l'octroi"
    cohorts = [c for c in sorted(df["cohorte"].unique()) if c != "Toutes"]

    fig, ax = plt.subplots(figsize=(9, 4.8))
    width = 0.8 / max(len(cohorts), 1)
    for i, c in enumerate(cohorts):
        g = df[df["cohorte"] == c].set_index("segment")["default_rate"].reindex(bands)
        xs = [b + (i - (len(cohorts) - 1) / 2) * width for b in range(len(bands))]
        ax.bar(xs, g.fillna(0), width=width * 0.92, color=color_for(int(c), i), label=c,
               edgecolor="white", linewidth=0.6)
    ax.set_xticks(range(len(bands)), bands)
    ax.set_xlabel("Score FICO à l'octroi")
    ax.yaxis.set_major_formatter(pct_axis())
    ax.grid(axis="x", visible=False)
    ax.legend(title="Cohorte", frameon=False, ncols=len(cohorts), loc="upper right")
    titles(fig, title, "Part des prêts ayant fait défaut depuis l'octroi, par cohorte")
    source(fig)
    fig.savefig(out / "02_default_by_fico.png")
    plt.close(fig)


# --- 3. Matrice de transition ----------------------------------------------------
def fig_roll_rates(con, out: Path) -> None:
    df = con.execute("""SELECT from_state, from_order, to_state, to_order, share
                        FROM v_roll_rates WHERE annee = 'Toutes'""").df()
    if df.empty:
        return
    rows = df.drop_duplicates("from_state").sort_values("from_order")["from_state"].tolist()
    cols = ["À jour", "30-59 jours", "60-89 jours", "90+ jours", "Remboursé",
            "Sortie avec perte", "Autre sortie"]
    m = df.pivot_table(index="from_state", columns="to_state", values="share", aggfunc="sum")
    m = m.reindex(index=rows, columns=cols).fillna(0)
    roll = m.loc["60-89 jours", "90+ jours"] if "60-89 jours" in m.index else None
    title = (f"Un prêt à 60-89 jours de retard passe à 90 jours le mois suivant dans "
             f"{fr(100 * roll, 0)} % des cas" if roll is not None else "Matrice de transition mensuelle")

    fig, ax = plt.subplots(figsize=(9.5, 3.9))
    ax.imshow(m.values, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m.values[i, j]
            label = "0 %" if v == 0 else (f"{fr(100 * v, 2)} %" if v < 0.01 else f"{fr(100 * v, 1)} %")
            ax.text(j, i, label, ha="center", va="center", fontsize=9.5,
                    color="white" if v > 0.55 else INK)
    ax.set_xticks(range(len(cols)), [c.replace("Sortie avec perte", "Sortie\navec perte")
                                     .replace("Autre sortie", "Autre\nsortie") for c in cols])
    ax.set_yticks(range(len(rows)), rows)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_ylabel("État ce mois-ci")
    titles(fig, title, "Lecture en ligne : où se trouve le prêt le mois suivant (chaque ligne totalise 100 %)")
    fig.subplots_adjust(top=0.78)
    source(fig)
    fig.savefig(out / "03_roll_rates.png")
    plt.close(fig)


# --- 4. Risque de défaut à 12 mois et chômage ------------------------------------
def fig_pd12_macro(con, out: Path) -> None:
    df = con.execute("SELECT period, pd12, unemployment_rate FROM v_pd12_by_month ORDER BY period").df()
    if df.empty:
        return
    peak = df.loc[df["pd12"].idxmax()]
    has_macro = df["unemployment_rate"].notna().any()
    title = (f"Le risque de défaut à 12 mois a culminé à {fr(100 * peak['pd12'])} % "
             f"({month_label(peak['period'])})")
    if has_macro:
        u = df.loc[df["unemployment_rate"].idxmax()]
        title += f" ; le chômage, à {fr(u['unemployment_rate'])} % ({month_label(u['period'])})"

    nrows = 2 if has_macro else 1
    fig, axes = plt.subplots(nrows, 1, figsize=(9, 5.6 if has_macro else 3.6), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1]} if has_macro else None)
    axes = list(axes) if has_macro else [axes]
    axes[0].plot(df["period"], df["pd12"], color=BLUE, linewidth=2)
    axes[0].yaxis.set_major_formatter(pct_axis(1))
    axes[0].set_ylim(bottom=0)
    axes[0].set_ylabel("Défaut dans les 12 mois")
    if has_macro:
        axes[1].plot(df["period"], df["unemployment_rate"] / 100, color=INK_2, linewidth=1.6)
        axes[1].yaxis.set_major_formatter(pct_axis(0))
        axes[1].set_ylim(bottom=0)
        axes[1].set_ylabel("Taux de chômage US")
    titles(fig, title, "Part des prêts sains un mois donné qui font défaut dans les 12 mois suivants. Le niveau dépend\n"
                       "aussi des cohortes présentes ce mois-là ; coïncidence dans le temps ne veut pas dire causalité.")
    source(fig)
    fig.savefig(out / "04_pd12_and_unemployment.png")
    plt.close(fig)


# --- 5. Signaux d'alerte ----------------------------------------------------------
def fig_signals(con, out: Path) -> None:
    df = con.execute("""SELECT ord, signal, pd12, lift, n_loan_months FROM v_signal_backtest
                        WHERE n_loan_months >= 300 ORDER BY ord""").df()
    if df.empty:
        return
    dq30 = df[df["signal"] == "Retard de 30 à 59 jours"]
    title = (f"Un retard de 30 jours multiplie par {fr(dq30['lift'].iloc[0], 0)} le risque de défaut à 12 mois"
             if not dq30.empty and dq30["lift"].notna().iloc[0] else "Taux de défaut à 12 mois selon le signal")
    df = df.iloc[::-1]
    colors = [AXIS if s.startswith("Aucun") else BLUE for s in df["signal"]]

    fig, ax = plt.subplots(figsize=(10, 0.55 * len(df) + 1.4))
    fig.subplots_adjust(left=0.36)  # libellés longs : on les garde dans la figure
    ax.barh(df["signal"], df["pd12"], color=colors, height=0.6)
    for y, (v, lift) in enumerate(zip(df["pd12"], df["lift"])):
        extra = "" if abs(lift - 1) < 1e-9 else f"  (x {fr(lift, 1)})"
        ax.text(v, y, f"  {fr(100 * v)} %{extra}", va="center", fontsize=9.5, color=INK)
    ax.xaxis.set_major_formatter(pct_axis())
    ax.set_xlim(0, df["pd12"].max() * 1.3)
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    titles(fig, title, "Part des prêts présentant le signal qui font défaut dans les 12 mois "
                       "(entre parenthèses : multiple du risque d'un prêt à jour sans signal)")
    source(fig)
    fig.savefig(out / "05_early_warning_signals.png")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "figures")
    args = parser.parse_args()
    if not DB_PATH.exists():
        raise SystemExit("La base n'existe pas : lance d'abord  python src/load_freddie.py")
    args.out.mkdir(parents=True, exist_ok=True)
    setup_style()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    for make in (fig_vintages, fig_fico, fig_roll_rates, fig_pd12_macro, fig_signals):
        make(con, args.out)
        print(f"  {make.__name__:<16} OK")
    con.close()
    print(f"Graphiques enregistrés dans : {args.out}")


if __name__ == "__main__":
    main()
