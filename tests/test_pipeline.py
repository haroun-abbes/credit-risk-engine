"""Test de bout en bout : faux fichiers -> chargement -> contrôles qualité.

Lancer avec :  python -m pytest -q
Ce test n'utilise jamais tes vraies données (il travaille dans un dossier temporaire).
"""
import os
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / script), *args],
                          env=env, capture_output=True, text=True, cwd=ROOT)


def test_full_pipeline(tmp_path):
    env = {**os.environ, "CRE_DATA_DIR": str(tmp_path)}
    assert run("tests/make_fake_sample.py", env, str(tmp_path / "raw"), "300").returncode == 0

    load = run("src/load_freddie.py", env)
    assert load.returncode == 0, load.stdout + load.stderr

    con = duckdb.connect(str(tmp_path / "processed" / "credit_risk.duckdb"), read_only=True)
    assert con.execute("SELECT count(*) FROM loans").fetchone()[0] == 600
    # un prêt "non disponible" (9999) doit devenir NULL, jamais 9999
    assert con.execute("SELECT max(fico_score) FROM borrowers").fetchone()[0] <= 850
    # les cohortes sont bien déduites de l'identifiant du prêt
    assert {r[0] for r in con.execute("SELECT DISTINCT vintage_year FROM loans").fetchall()} == {2006, 2016}
    con.close()

    checks = run("src/run_quality_checks.py", env)
    assert checks.returncode == 0, checks.stdout  # aucun contrôle bloquant en échec


def test_phase2_analytics(tmp_path):
    """Phase 2 : couche analytique, contrôles de cohérence et graphiques."""
    env = {**os.environ, "CRE_DATA_DIR": str(tmp_path)}
    assert run("tests/make_fake_sample.py", env, str(tmp_path / "raw"), "400").returncode == 0
    assert run("src/load_freddie.py", env).returncode == 0

    build = run("src/build_analytics.py", env)
    assert build.returncode == 0, build.stdout + build.stderr   # aucun contrôle A01-A11 en échec

    con = duckdb.connect(str(tmp_path / "processed" / "credit_risk.duckdb"), read_only=True)
    # la définition du défaut englobe toutes les sorties avec perte
    n_loss_not_default = con.execute("""SELECT count(*) FROM loan_default
        WHERE zero_balance_code IN ('02','03','09','15') AND NOT ever_default""").fetchone()[0]
    assert n_loss_not_default == 0
    # un taux de défaut cumulé ne redescend jamais
    assert con.execute("""SELECT count(*) FROM (SELECT cum_default_rate - lag(cum_default_rate)
        OVER (PARTITION BY vintage_year ORDER BY age) AS d FROM v_vintage_curve) WHERE d < 0""").fetchone()[0] == 0
    con.close()

    figs = run("src/make_figures.py", env, "--out", str(tmp_path / "figures"))
    assert figs.returncode == 0, figs.stdout + figs.stderr
    assert len(list((tmp_path / "figures").glob("*.png"))) == 5


def test_phase3_pd_model(tmp_path):
    """Phase 3 : modèle de PD, notes et contrôles P01-P06."""
    env = {**os.environ, "CRE_DATA_DIR": str(tmp_path)}
    assert run("tests/make_fake_sample.py", env, str(tmp_path / "raw"), "1500").returncode == 0
    assert run("src/load_freddie.py", env).returncode == 0
    assert run("src/build_analytics.py", env).returncode == 0

    train = run("src/train_pd_model.py", env, "--figures-out", str(tmp_path / "figures"),
                "--model-out", str(tmp_path / "model"))
    assert train.returncode == 0, train.stdout + train.stderr   # aucun contrôle P01-P04 en échec

    con = duckdb.connect(str(tmp_path / "processed" / "credit_risk.duckdb"), read_only=True)
    n, lo, hi = con.execute("SELECT count(*), min(pd_12m), max(pd_12m) FROM risk_ratings").fetchone()
    assert n > 0 and 0 < lo and hi < 1
    assert con.execute("SELECT count(*) FROM rating_scale").fetchone()[0] == 8
    con.close()
    assert (tmp_path / "model" / "pd_model_report.md").exists()
    assert len(list((tmp_path / "figures").glob("*.png"))) == 4


def test_phase4_ecl(tmp_path):
    """Phase 4 : calibrage, staging IFRS 9, ECL, migrations, capital et contrôles E01-E09."""
    env = {**os.environ, "CRE_DATA_DIR": str(tmp_path)}
    assert run("tests/make_fake_sample.py", env, str(tmp_path / "raw"), "1500").returncode == 0
    assert run("src/load_freddie.py", env).returncode == 0
    assert run("src/build_analytics.py", env).returncode == 0
    assert run("src/train_pd_model.py", env, "--figures-out", str(tmp_path / "figures"),
               "--model-out", str(tmp_path / "model")).returncode == 0

    ecl = run("src/build_ecl.py", env, "--model", str(tmp_path / "model" / "pd_model.json"),
              "--figures-out", str(tmp_path / "figures"), "--model-out", str(tmp_path / "model"))
    assert ecl.returncode == 0, ecl.stdout + ecl.stderr   # aucun contrôle E01-E07 en échec

    con = duckdb.connect(str(tmp_path / "processed" / "credit_risk.duckdb"), read_only=True)
    n, n_stages, bad = con.execute("""SELECT count(*), count(DISTINCT stage),
                                             count(*) FILTER (WHERE ecl < 0 OR ecl > ead)
                                      FROM ecl_results""").fetchone()
    assert n > 0 and n_stages >= 2 and bad == 0
    assert abs(con.execute("SELECT sum(weight) FROM ecl_scenarios").fetchone()[0] - 1) < 1e-9
    con.close()
    assert (tmp_path / "model" / "ecl_report.md").exists()
    assert len(list((tmp_path / "figures").glob("1[0-3]_*.png"))) == 4
