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
