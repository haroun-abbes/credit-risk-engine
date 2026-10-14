"""Génère de FAUX fichiers au format Freddie Mac, pour tester la chaîne sans les vraies données.

Utilisation :
    python tests/make_fake_sample.py <dossier_de_sortie> [nb_prets_par_annee]

Les valeurs sont aléatoires (elles ne décrivent aucun prêt réel) mais respectent
le format exact : séparateur "|", pas d'en-tête, 31 colonnes d'origination et
35 colonnes de performance, codes "non disponible" (9999, 999...), défauts et pertes.
"""
from __future__ import annotations

import random
import sys
import zipfile
from pathlib import Path

STATES = ["CA", "FL", "TX", "NY", "IL", "AZ", "NV", "GA", "OH", "WA"]
CUTOFF = (2025, 9)  # dernier mois de performance disponible


def add_months(y: int, m: int, k: int) -> tuple[int, int]:
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def ym(y: int, m: int) -> str:
    return f"{y}{m:02d}"


def make_loan(rng: random.Random, year: int, idx: int) -> tuple[list[str], list[list[str]]]:
    q = rng.randint(1, 4)
    loan_id = f"F{year % 100:02d}Q{q}{idx:07d}"
    orig_month = 3 * (q - 1) + rng.randint(1, 3)
    fp_y, fp_m = add_months(year, orig_month, 2)
    term = rng.choice([360, 360, 360, 180, 240])
    mat_y, mat_m = add_months(fp_y, fp_m, term - 1)
    fico = rng.randint(600, 820)
    ltv = rng.randint(55, 97)
    dti = rng.randint(15, 50)
    upb = round(rng.uniform(80, 450)) * 1000
    rate = round(rng.uniform(3.0, 7.5), 3)
    occupancy = rng.choices(["P", "I", "S"], [85, 10, 5])[0]
    crisis = year in (2005, 2006, 2007)

    # 1 % des prêts : date de 1re échéance « réinitialisée » après modification
    reset_y, reset_m = add_months(fp_y, fp_m, 60) if rng.random() < 0.01 else (fp_y, fp_m)
    orig = [
        "9999" if rng.random() < 0.01 else str(fico), ym(reset_y, reset_m),
        rng.choice(["Y", "N"]), ym(mat_y, mat_m), str(rng.randint(10000, 49999)),
        "0" if ltv <= 80 else str(rng.choice([12, 25, 30])), "1", occupancy,
        str(ltv), "999" if rng.random() < 0.02 else str(dti), str(upb), str(ltv),
        f"{rate}", rng.choice(["R", "B", "C", "T"]), "N", "FRM", rng.choice(STATES),
        rng.choice(["SF", "PU", "CO"]), f"{rng.randint(100, 999)}", loan_id,
        rng.choice(["P", "C", "N"]), str(term), rng.choice(["1", "2"]),
        rng.choice(["BANK A", "BANK B", "OTHER"]), "N", "", "", "N", "2", "N", "9999",
    ]

    # --- Simulation mensuelle : prépaiement, retards, défaut ---------------------
    base_hazard = (0.004 if crisis else 0.0008) * (1 + (720 - fico) / 100) * (1 + (ltv - 80) / 40)
    base_hazard = max(base_hazard, 0.0002)
    rows, balance, dq = [], float(upb), 0
    y, m = fp_y, fp_m
    monthly_rate = rate / 1200
    payment = upb * monthly_rate / (1 - (1 + monthly_rate) ** -term)
    for age in range(1, term + 1):
        if (y, m) > CUTOFF:
            break
        zb_code = zb_date = ""
        loss_fields = [""] * 9   # mi_rec, net_sale, non_mi, total_exp, legal, maint, taxes, misc, actual_loss
        removal_upb = dai = ""
        if dq == 0 and rng.random() < base_hazard:
            dq = 1
        elif dq > 0:
            r = rng.random()
            dq = 0 if r < 0.25 else (dq + 1 if r < 0.9 else dq)
        if dq == 0:
            balance = max(balance - (payment - balance * monthly_rate), 0)
        if dq >= 7 and rng.random() < 0.3:                     # liquidation après défaut
            zb_code, zb_date = rng.choice(["03", "09"]), ym(y, m)
            removal_upb = f"{balance:.2f}"
            severity = rng.uniform(0.15, 0.55)
            sale = -balance * (1 - severity)
            expenses = balance * 0.08
            loss = balance * severity + expenses
            loss_fields = ["0.00", f"{sale:.2f}", "0.00", f"{expenses:.2f}",
                           f"{expenses * 0.3:.2f}", f"{expenses * 0.3:.2f}",
                           f"{expenses * 0.3:.2f}", f"{expenses * 0.1:.2f}", f"{loss:.2f}"]
            dai = f"{balance * monthly_rate * dq:.2f}"
        elif dq == 0 and rng.random() < 0.012:                 # remboursement anticipé
            zb_code, zb_date, removal_upb = "01", ym(y, m), f"{balance:.2f}"
        current_upb = 0.0 if zb_code else balance
        status = "XX" if rng.random() < 0.0005 else str(min(dq, 99))
        mi_rec, net_sale, non_mi, total_exp, legal, maint, taxes, misc, actual = loss_fields
        perf = [
            loan_id, ym(y, m), f"{current_upb:.2f}", status, str(age), str(term - age),
            "", "", zb_code, zb_date, f"{rate}", "0.00", "", mi_rec, net_sale, non_mi,
            total_exp, legal, maint, taxes, misc, actual, "", "", "",
            str(max(1, ltv - age // 12)), removal_upb, dai, "", "", "",
            f"{current_upb:.2f}", "7", "SERVICER X", "",
        ]
        rows.append(perf)
        if zb_code:
            break
        y, m = add_months(y, m, 1)
    return orig, rows


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/raw")
    n_loans = int(sys.argv[2]) if len(sys.argv) > 2 else 2000
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(42)
    for year in (2006, 2016):
        orig_lines, perf_lines = [], []
        for i in range(n_loans):
            orig, perf = make_loan(rng, year, i)
            assert len(orig) == 31 and all(len(r) == 35 for r in perf)
            orig_lines.append("|".join(orig))
            perf_lines.extend("|".join(r) for r in perf)
        with zipfile.ZipFile(out / f"sample_{year}.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"sample_orig_{year}.txt", "\n".join(orig_lines) + "\n")
            zf.writestr(f"sample_perf_{year}.txt", "\n".join(perf_lines) + "\n")
        print(f"sample_{year}.zip : {n_loans} prêts, {len(perf_lines)} lignes mensuelles")


if __name__ == "__main__":
    main()
