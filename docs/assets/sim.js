/* Simulateur : tout est recalculé dans le navigateur, à chaque mouvement d'un curseur.
   1. Noter un emprunteur  (grille du modèle de PD)
   2. Provision IFRS 9     (scénarios économiques et règles de staging)
   3. Capital bâlois       (formule IRB)
   Les prêts actifs sont regroupés en paquets de prêts semblables. Pour chaque paquet, le
   simulateur applique l'écart entre le nouveau calcul et le calcul de référence à la
   provision officielle : avec les réglages par défaut, il retrouve exactement les
   chiffres du rapport. */
(function () {
  const { F } = Charts;

  /* --- Loi normale ------------------------------------------------------------------------- */
  function normCdf(x) {
    const t = 1 / (1 + 0.2316419 * Math.abs(x)), d = 0.3989422804014327 * Math.exp(-x * x / 2);
    const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
    return x > 0 ? 1 - p : p;
  }
  function normInv(p) {             // algorithme d'Acklam
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const pl = 0.02425;
    if (p <= 0) return -Infinity; if (p >= 1) return Infinity;
    if (p < pl) { const q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    if (p > 1 - pl) { const q = Math.sqrt(-2 * Math.log(1 - p));
      return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    const q = p - 0.5, r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const sigmoid = (x) => 1 / (1 + Math.exp(-x));
  const logit = (p) => { p = clamp(p, 1e-9, 1 - 1e-9); return Math.log(p / (1 - p)); };
  const vasicek = (pd, z, rho) => normCdf((normInv(clamp(pd, 1e-9, 1 - 1e-9)) - Math.sqrt(rho) * z) / Math.sqrt(1 - rho));
  function irbK(pd, lgd, rho, q, pdFloor, lgdFloor) {
    const p = Math.max(pd, pdFloor), l = Math.max(lgd, lgdFloor);
    return l * (normCdf((normInv(p) + Math.sqrt(rho) * normInv(q)) / Math.sqrt(1 - rho)) - p);
  }

  /* --- Perte attendue d'un paquet (même formule que src/build_ecl.py) ------------------------- */
  function expectedLoss(b, pit1, cpr, maxYears) {
    const rem = clamp(b.rem, 1, 12 * maxYears), horizon = Math.ceil(rem / 12);
    const rate = clamp(b.rate, 0.01, 20) / 100, rm = rate / 12, gn = Math.pow(1 + rm, rem);
    let surv = 1, e12 = 0, elt = 0;
    for (let y = 1; y <= Math.min(horizon, maxYears); y++) {
      const h = y === 1 ? pit1 : y === 2 ? 0.5 * pit1 + 0.5 * b.pd_clean : b.pd_clean;
      const bal = Math.max(0, b.ead * (gn - Math.pow(1 + rm, 12 * (y - 1))) / (gn - 1));
      const m = surv * h * b.lgd * bal * Math.pow(1 + rate, -(y - 0.5));
      if (y === 1) e12 = m;
      elt += m;
      surv *= (1 - h) * (1 - cpr);
    }
    return [e12, elt];
  }

  /* ============================================================================================ */
  window.Simulator = function build(grid, S, D, helpers) {
    const { T, legend, tableHtml } = helpers;
    const P = S.params, rho = P.rho, cpr = P.cpr, maxYears = P.max_years || 30;
    const scale = S.master_scale;
    const gradeOf = (pd) => { for (let g = 1; g < scale.length; g++) if (pd < scale[g]) return g; return scale.length - 1; };
    const buckets = S.buckets.map((row) => Object.fromEntries(S.bucket_cols.map((c, k) => [c, row[k]])));
    const fallback = P.sat_fallback > 0 || !F.ok(P.sat_b0);
    const zOf = (du, hpi, k) => (fallback ? S.scenarios[k].z : P.sat_b0 + P.sat_b_unemp * du + P.sat_b_hpi * hpi);
    const swap = (el) => { const n = el.cloneNode(false); el.replaceWith(n); return n; };

    /* Calcul de référence de chaque paquet (réglages par défaut) */
    const baseScen = S.scenarios.map((s, k) => ({ du: s.d_unemp, hpi: s.hpi, w: s.weight, z: zOf(s.d_unemp, s.hpi, k) }));
    function perScenario(b, scen) {
      return scen.map((s) => expectedLoss(b, vasicek(b.pd_ttc, s.z, rho), cpr, maxYears));
    }
    buckets.forEach((b) => {
      if (b.state_i === 3) return;
      const r = perScenario(b, baseScen);
      b.e12_ref = r.reduce((a, x, k) => a + baseScen[k].w * x[0], 0);
      b.elt_ref = r.reduce((a, x, k) => a + baseScen[k].w * x[1], 0);
    });
    const basePolicy = { dpd: true, prob: true, restr: true, sicr: true, notches: P.sicr_notches, minPd: P.sicr_min_pd };
    function stageOf(b, pol) {
      if (b.state_i === 3) return 3;
      if (pol.dpd && (b.state_i === 1 || b.state_i === 2)) return 2;
      if (pol.prob && b.prev) return 2;
      if (pol.restr && b.restr) return 2;
      if (pol.sicr && b.grade_now - b.grade_orig >= pol.notches && scale[b.grade_now - 1] >= pol.minPd - 1e-12) return 2;
      return 1;
    }
    function provision(scen, pol) {
      const wsum = scen.reduce((a, s) => a + s.w, 0) || 1;
      const out = { stages: { 1: { n: 0, ead: 0, ecl: 0 }, 2: { n: 0, ead: 0, ecl: 0 }, 3: { n: 0, ead: 0, ecl: 0 } },
                    byScen: scen.map(() => 0), perfEcl: 0 };
      buckets.forEach((b) => {
        const st = stageOf(b, pol);
        let ecl, per;
        if (st === 3) { ecl = b.ecl; per = scen.map(() => b.ecl); }
        else {
          const r = perScenario(b, scen);
          const sc12 = b.e12_ref > 0 ? b.e12 / b.e12_ref : 0, scLt = b.elt_ref > 0 ? b.elt / b.elt_ref : 0;
          per = r.map((x) => (st === 1 ? x[0] * sc12 : x[1] * scLt));
          ecl = per.reduce((a, v, k) => a + (scen[k].w / wsum) * v, 0);
          out.perfEcl += ecl;
        }
        const o = out.stages[st]; o.n += b.n; o.ead += b.ead; o.ecl += ecl;
        per.forEach((v, k) => { out.byScen[k] += v; });
      });
      out.total = out.stages[1].ecl + out.stages[2].ecl + out.stages[3].ecl;
      out.ead = out.stages[1].ead + out.stages[2].ead + out.stages[3].ead;
      return out;
    }

    /* ======================= 1. Noter un emprunteur ======================= */
    const RANGES = {
      fico_score: { min: 300, max: 850, step: 5, value: 740, fmt: (v) => F.num(v) },
      cltv_pct: { min: 20, max: 125, step: 1, value: 80, fmt: (v) => `${F.num(v)} %` },
      dti_pct: { min: 0, max: 65, step: 1, value: 35, fmt: (v) => `${F.num(v)} %` },
      sato: { min: -1.5, max: 2.5, step: 0.05, value: 0, fmt: (v) => `${v > 0 ? "+" : ""}${F.num(v, 2)} pt` },
      age: { min: 0, max: 300, step: 1, value: 24, fmt: (v) => `${F.num(v)} mois` },
    };
    const FR = { "Purchase": "Achat", "Cash-out refi": "Refinancement avec retrait", "No cash-out refi": "Refinancement sans retrait",
                 "Primary residence": "Résidence principale", "Investment": "Investissement locatif", "Second home": "Résidence secondaire" };
    const tr = (s) => FR[s] || s;
    const TERMS = { fico_score: "fico", cltv_pct: "cltv", dti_pct: "dti", sato: "sato" };
    const feats = S.features;
    const nF = feats.length, pts = S.points, factor = pts.pdo / Math.log(2), offset = pts.base_score - factor * Math.log(pts.base_odds);
    const cltvFeat = feats.find((f) => f.name === "cltv_pct");
    const state1 = {};
    feats.forEach((f) => {
      if (f.type === "num") state1[f.name] = (RANGES[f.name] || { value: f.bins[1]?.lo ?? 0 }).value;
      else {
        const pref = { dq_state: "À jour", dq_history_12m: "Aucun retard" }[f.name];
        state1[f.name] = (f.options.find((o) => o.label === pref) || f.options.reduce((a, o) => (o.share > a.share ? o : a), f.options[0])).label;
      }
    });
    state1.amount = 200000;
    if (!cltvFeat) state1.cltv_pct = 80;

    const lgdBand = (cltv) => {
      const name = cltv <= 60 ? "60 % ou moins" : cltv <= 80 ? "61-80 %" : cltv <= 90 ? "81-90 %" : cltv <= 95 ? "91-95 %" : "Plus de 95 %";
      return S.lgd_by_band.find((r) => r.cltv_band === name) || S.lgd_by_band.find((r) => r.cltv_band === "Tous");
    };
    const binOf = (f, v) => f.bins.find((b) => (b.lo === null || v >= b.lo) && (b.hi === null || v < b.hi)) || f.bins[f.bins.length - 1];

    const p1 = document.createElement("article");
    p1.className = "panel span-12 sim"; p1.id = "sim-score";
    const field = (f) => {
      const lab = TERMS[f.name] ? T(TERMS[f.name], f.label) : f.label;
      if (f.type === "num") {
        const r = RANGES[f.name] || { min: 0, max: 100, step: 1, value: 0, fmt: (v) => F.num(v) };
        return `<div class="field"><div class="field-head"><label for="in-${f.name}">${lab}</label><output id="out-${f.name}"></output></div>
          <input type="range" id="in-${f.name}" data-f="${f.name}" min="${r.min}" max="${r.max}" step="${r.step}" value="${state1[f.name]}"></div>`;
      }
      return `<div class="field"><div class="field-head"><label for="in-${f.name}">${lab}</label></div>
        <select id="in-${f.name}" data-f="${f.name}">${f.options.map((o) => `<option value="${o.label}"${o.label === state1[f.name] ? " selected" : ""}>${tr(o.label)}</option>`).join("")}</select></div>`;
    };
    const extraCltv = cltvFeat ? "" : field({ name: "cltv_pct", label: "CLTV à l'octroi (%)", type: "num" });
    p1.innerHTML = `<div class="panel-head"><div><h3 class="panel-title">Noter un emprunteur</h3>
        <p class="panel-sub">Réglez le profil : la ${T("pd", "probabilité de défaut")}, la note et le score se recalculent avec la grille du modèle</p></div>
        <button type="button" class="btn-ghost sim-reset" data-reset="score">Revenir au profil type</button></div>
      <div class="sim-grid">
        <form class="sim-controls" onsubmit="return false">${feats.map(field).join("")}${extraCltv}
          <div class="field"><div class="field-head"><label for="in-amount">Montant restant dû</label><output id="out-amount"></output></div>
          <input type="range" id="in-amount" data-f="amount" min="50000" max="1000000" step="10000" value="${state1.amount}"></div></form>
        <div class="sim-results">
          <div class="sim-kpis" id="score-kpis"></div>
          <div class="grade-strip" id="score-strip" aria-label="Échelle de notation"></div>
          <h4 class="sim-h">Ce qui fait monter ou baisser le score</h4>
          <div class="legend" id="score-legend"></div>
          <div class="chart" id="score-chart"></div>
          <div class="reading"><span class="reading-label">Lecture</span><p id="score-reading"></p></div>
        </div>
      </div>
      <div class="panel-foot"><span class="panel-note">Variables et classes du modèle de la phase 3 ; PD recalibrée sur le taux de défaut de long terme (TTC).</span>
        <button type="button" class="data-toggle" aria-expanded="false">Voir le détail du calcul</button></div>
      <div class="data-table" hidden></div>`;
    grid.appendChild(p1);

    function renderScore() {
      let zsum = S.intercept, total = 0;
      const rows = feats.map((f) => {
        let woe, cls;
        if (f.type === "num") { const b = binOf(f, state1[f.name]); woe = b.woe; cls = b.label; }
        else { const o = f.options.find((x) => x.label === state1[f.name]); woe = o ? o.woe : 0; cls = tr(state1[f.name]); }
        zsum += f.coef * woe;
        const p = Math.round(-(f.coef * woe + S.intercept / nF) * factor + offset / nF);
        total += p;
        return { label: f.label, cls, woe, effect: -f.coef * woe * factor, points: p };
      });
      const pdModel = sigmoid(zsum), pdTtc = sigmoid(logit(pdModel) + P.delta), g = gradeOf(pdTtc);
      const central = S.scenarios.find((s) => s.scenario === "Central") || S.scenarios[0];
      const pit = vasicek(pdTtc, zOf(central.d_unemp, central.hpi, S.scenarios.indexOf(central)), rho);
      const L = lgdBand(state1.cltv_pct), amt = state1.amount;
      const ecl12 = pit * L.lgd * amt, cap = 0.08 * 12.5 * irbK(pdTtc, L.lgd_downturn, rho, 0.999, P.pd_floor, P.lgd_floor) * amt;
      feats.concat(cltvFeat ? [] : [{ name: "cltv_pct" }]).forEach((f) => {
        const o = document.getElementById(`out-${f.name}`); if (o && RANGES[f.name]) o.textContent = RANGES[f.name].fmt(+state1[f.name]);
      });
      document.getElementById("out-amount").textContent = F.usd(amt);
      document.getElementById("score-kpis").innerHTML = `
        <div class="stat big"><div class="lab">PD à 12 mois</div><div class="val">${F.pct(pdTtc, pdTtc < 0.01 ? 2 : 1)}</div><div class="sub">PD du modèle avant recalibrage : ${F.pct(pdModel, 2)}</div></div>
        <div class="stat big"><div class="lab">Note</div><div class="val grade g${g}">R${g}</div><div class="sub">PD de ${F.pct(scale[g - 1], 2)} à ${F.pct(scale[g], 2)}</div></div>
        <div class="stat big"><div class="lab">Score</div><div class="val">${F.num(total)} pts</div><div class="sub">600 pts = 50 bons payeurs pour 1 mauvais</div></div>
        <div class="stat big"><div class="lab">${T("ecl", "Perte attendue")}</div><div class="val">${F.usd(ecl12, 0)}</div><div class="sub">sur 12 mois ; fonds propres requis : ${F.usd(cap, 0)}</div></div>`;
      document.getElementById("score-strip").innerHTML = scale.slice(0, -1).map((lo, k) =>
        `<span class="${k + 1 === g ? "on" : ""}" title="R${k + 1} : PD de ${F.pct(lo, 2)} à ${F.pct(scale[k + 1], 2)}">R${k + 1}</span>`).join("");
      document.getElementById("score-legend").innerHTML = legend([{ name: "Réduit le risque", color: "var(--s1)", type: "sq" },
        { name: "Augmente le risque", color: "var(--s2)", type: "sq" }]);
      const sorted = rows.slice().sort((a, b) => Math.abs(b.effect) - Math.abs(a.effect));
      Charts.divergeH(swap(document.getElementById("score-chart")), {
        label: "Contribution de chaque variable au score",
        rows: sorted.map((r) => ({ ...r, label: `${r.label} : ${r.cls}`, value: r.effect })),
        posColor: "var(--s1)", negColor: "var(--s2)", fmt: (v) => `${v >= 0 ? "+" : "−"}${F.num(Math.abs(v), 0)} pts`,
        tip: (r) => `<b>${r.label}</b><div>Classe : ${r.cls}</div><div>${r.value >= 0 ? "Réduit" : "Augmente"} le risque (${r.value >= 0 ? "+" : "−"}${F.num(Math.abs(r.value), 0)} pts par rapport à un profil moyen)</div>`,
      });
      const worst = sorted.filter((r) => r.effect < 0)[0], best = sorted.filter((r) => r.effect > 0)[0];
      document.getElementById("score-reading").innerHTML =
        `Ce profil obtient la note <strong>R${g}</strong>, avec <strong>${F.pct(pdTtc, pdTtc < 0.01 ? 2 : 1)}</strong> de risque de défaut dans l'année.
         ${worst ? `Ce qui pèse le plus : « ${worst.label} » (${worst.cls}). ` : ""}${best ? `Ce qui protège le plus : « ${best.label} » (${best.cls}).` : ""}
         ${g >= 6 ? "Un tel dossier serait refusé ou très surveillé." : g >= 4 ? "Un dossier acceptable, à suivre." : "Un très bon dossier."}`;
      p1.querySelector(".data-table").innerHTML = tableHtml(["Variable", "Classe", "WoE", "Points"],
        rows.map((r) => [r.label, r.cls, F.num(r.woe, 3), F.num(r.points)]).concat([["<b>Total</b>", "", "", `<b>${F.num(total)}</b>`]]));
    }
    p1.addEventListener("input", (e) => {
      const f = e.target.dataset.f; if (!f) return;
      state1[f] = e.target.type === "range" ? +e.target.value : e.target.value;
      requestAnimationFrame(renderScore);
    });

    /* ======================= 2. Provision IFRS 9 ======================= */
    const st2 = { scen: baseScen.map((s) => ({ ...s })), pol: { ...basePolicy } };
    const base = provision(baseScen, basePolicy);
    const p2 = document.createElement("article");
    p2.className = "panel span-12 sim"; p2.id = "sim-ecl";
    const scenCard = (s, k) => `<fieldset class="scen-card"><legend><i style="background:${["var(--s1)", "var(--stage2)", "var(--stage3)"][k]}"></i>${S.scenarios[k].scenario}</legend>
      <div class="field"><div class="field-head"><label for="du-${k}">Hausse du chômage</label><output id="o-du-${k}"></output></div>
        <input type="range" id="du-${k}" data-s="du" data-k="${k}" min="-2" max="8" step="0.5" value="${s.du}" ${fallback ? "disabled" : ""}></div>
      <div class="field"><div class="field-head"><label for="hpi-${k}">Prix immobiliers</label><output id="o-hpi-${k}"></output></div>
        <input type="range" id="hpi-${k}" data-s="hpi" data-k="${k}" min="-0.35" max="0.15" step="0.01" value="${s.hpi}" ${fallback ? "disabled" : ""}></div>
      <div class="field"><div class="field-head"><label for="w-${k}">Poids</label><output id="o-w-${k}"></output></div>
        <input type="range" id="w-${k}" data-s="w" data-k="${k}" min="0" max="1" step="0.05" value="${s.w}"></div></fieldset>`;
    // Sensibilité du facteur Z : on prévient si l'un des deux curseurs n'a presque aucun effet
    const zU = Math.abs(5 * P.sat_b_unemp), zH = Math.abs(0.15 * P.sat_b_hpi);
    const macroNote = fallback ? `<p class="sim-note">Pas assez de variation macroéconomique dans les données : seuls les poids sont modifiables.</p>`
      : zU < 0.25 * zH ? `<p class="sim-note">Dans le modèle satellite, +5 points de chômage déplacent le facteur Z de ${F.num(zU, 2)}, contre ${F.num(zH, 2)} pour −15 % sur les prix :
          une fois les prix pris en compte, le chômage n'apporte presque rien. La provision réagit surtout aux prix immobiliers.</p>`
      : zH < 0.25 * zU ? `<p class="sim-note">Dans le modèle satellite, la provision réagit surtout au chômage ; les prix immobiliers n'apportent presque rien.</p>` : "";
    const opt = (key, vals, cur, fmt) => `<select data-p="${key}">${vals.map((v) => `<option value="${v}"${v === cur ? " selected" : ""}>${fmt(v)}</option>`).join("")}</select>`;
    p2.innerHTML = `<div class="panel-head"><div><h3 class="panel-title">Simuler la provision ${T("ifrs9", "IFRS 9")}</h3>
        <p class="panel-sub">Modifiez les ${T("scenarios", "scénarios économiques")} et les règles de passage en Stage 2 : la provision des ${F.num(base.stages[1].n + base.stages[2].n + base.stages[3].n)} prêts actifs se recalcule</p></div>
        <button type="button" class="btn-ghost sim-reset" data-reset="ecl">Revenir aux réglages du rapport</button></div>
      <div class="sim-grid">
        <form class="sim-controls" onsubmit="return false">
          <h4 class="sim-h">Scénarios sur 12 mois</h4>${macroNote}${st2.scen.map(scenCard).join("")}
          <h4 class="sim-h">Règles de ${T("sicr", "passage en Stage 2")}</h4>
          <label class="check"><input type="checkbox" data-p="dpd" checked> Retard de 30 jours ou plus</label>
          <label class="check"><input type="checkbox" data-p="prob" checked> Sorti du défaut depuis moins de 2 ans</label>
          <label class="check"><input type="checkbox" data-p="restr" checked> Restructuré ou plan d'aide</label>
          <label class="check"><input type="checkbox" data-p="sicr" checked> Dégradation de la note depuis l'octroi</label>
          <div class="field inline"><label>Crans perdus, au moins</label>${opt("notches", [1, 2, 3, 4], basePolicy.notches, (v) => `${v}`)}</div>
          <div class="field inline"><label>Et une PD d'au moins</label>${opt("minPd", [0, 0.005, 0.01, 0.02, 0.05], basePolicy.minPd, (v) => (v ? F.pct(v, v < 0.01 ? 1 : 0) : "aucun seuil"))}</div>
        </form>
        <div class="sim-results">
          <div class="sim-kpis" id="ecl-kpis"></div>
          <h4 class="sim-h">Répartition par stage</h4>
          <div class="legend">${legend([1, 2, 3].map((k) => ({ name: `Stage ${k}`, color: `var(--stage${k})`, type: "sq" })))}</div>
          <div class="chart" id="ecl-stack"></div>
          <h4 class="sim-h">Provision si chaque scénario se réalisait</h4>
          <div class="chart" id="ecl-scen"></div>
          <div class="reading"><span class="reading-label">Lecture</span><p id="ecl-reading"></p></div>
        </div>
      </div>
      <div class="panel-foot"><span class="panel-note">Facteur systémique Z = ${fallback ? "valeurs fixées par scénario" : `${F.num(P.sat_b0, 2)} ${P.sat_b_unemp >= 0 ? "+" : "−"} ${F.num(Math.abs(P.sat_b_unemp), 3)} × chômage + ${F.num(P.sat_b_hpi, 2)} × prix (modèle satellite, R² ${F.num(P.sat_r2, 2)})`}. Prêts regroupés par profil ; réglages par défaut = chiffres du rapport.</span>
        <button type="button" class="data-toggle" aria-expanded="false">Voir les données</button></div>
      <div class="data-table" hidden></div>`;
    grid.appendChild(p2);

    let lastProv = base;
    function renderEcl() {
      const res = provision(st2.scen, st2.pol); lastProv = res;
      const wsum = st2.scen.reduce((a, s) => a + s.w, 0);
      st2.scen.forEach((s, k) => {
        document.getElementById(`o-du-${k}`).textContent = `${s.du > 0 ? "+" : ""}${F.num(s.du, 1)} pt`;
        document.getElementById(`o-hpi-${k}`).textContent = `${s.hpi > 0 ? "+" : ""}${F.pct(s.hpi, 0)}`;
        document.getElementById(`o-w-${k}`).textContent = wsum > 0 ? F.pct(s.w / wsum, 0) : "–";
      });
      const d = res.total / base.total - 1, s2 = res.stages[2];
      const delta = (v) => `<span class="${Math.abs(v) < 0.0005 ? "flat" : v > 0 ? "up" : "down"}">${Math.abs(v) < 0.0005 ? "identique au rapport" : `${v > 0 ? "+" : "−"}${F.pct(Math.abs(v), 1)} par rapport au rapport`}</span>`;
      document.getElementById("ecl-kpis").innerHTML = `
        <div class="stat big"><div class="lab">Provision</div><div class="val">${F.usd(res.total)}</div><div class="sub">${delta(d)}</div></div>
        <div class="stat big"><div class="lab">${T("couverture", "Couverture")}</div><div class="val">${F.pct(res.total / res.ead, 2)}</div><div class="sub">de l'encours</div></div>
        <div class="stat big"><div class="lab">Prêts en Stage 2</div><div class="val">${F.num(s2.n)}</div><div class="sub">${F.pct(s2.ead / res.ead, 1)} de l'encours (rapport : ${F.num(base.stages[2].n)})</div></div>
        <div class="stat big"><div class="lab">Provision du Stage 2</div><div class="val">${F.usd(s2.ecl)}</div><div class="sub">${F.pct(s2.ecl / res.total, 0)} de la provision</div></div>`;
      Charts.stack100(swap(document.getElementById("ecl-stack")), {
        label: "Répartition par stage",
        bars: [{ label: "Encours", parts: [1, 2, 3].map((k) => ({ name: `Stage ${k}`, value: res.stages[k].ead, color: `var(--stage${k})` })) },
               { label: "Provision", parts: [1, 2, 3].map((k) => ({ name: `Stage ${k}`, value: res.stages[k].ecl, color: `var(--stage${k})` })) }],
        fmt: (v) => F.pct(v, 0),
        tip: (b, p, sh) => `<b>${p.name}</b><div>${F.pct(sh, 1)} ${b.label === "Encours" ? "de l'encours" : "de la provision"}</div><div>${F.usd(p.value)}</div>`,
      });
      const maxS = Math.max(...res.byScen, res.total);
      Charts.columns(swap(document.getElementById("ecl-scen")), {
        height: 220, bottom: 44, label: "Provision par scénario", ref: { value: res.total },
        rows: st2.scen.map((s, k) => ({ label: S.scenarios[k].scenario, value: res.byScen[k], color: ["var(--s1)", "var(--stage2)", "var(--stage3)"][k],
                                         sub: `poids ${wsum > 0 ? F.pct(s.w / wsum, 0) : "–"}` })),
        yFmt: (v) => F.usd(v), yTick: F.usdTick(maxS), valueFmt: (r) => F.usd(r.value), barW: 70,
        tip: (r) => `<b>Scénario ${r.label.toLowerCase()}</b><div>Provision : ${F.usd(r.value, 2)}</div>`,
      });
      const kWorst = res.byScen.indexOf(Math.max(...res.byScen));
      document.getElementById("ecl-reading").innerHTML = wsum === 0 ? "Donnez un poids à au moins un scénario." :
        `Avec ces réglages, la provision est de <strong>${F.usd(res.total)}</strong> (${F.pct(res.total / res.ead, 2)} de l'encours), ${Math.abs(d) < 0.0005 ? "comme dans le rapport" : `soit <strong>${d > 0 ? "+" : "−"}${F.pct(Math.abs(d), 1)}</strong> par rapport au rapport`}.
         Le Stage 2 compte ${F.num(s2.n)} prêts et pèse ${F.pct(s2.ecl / res.total, 0)} de la provision pour ${F.pct(s2.ead / res.ead, 1)} de l'encours.
         Le scénario « ${S.scenarios[kWorst].scenario.toLowerCase()} » coûterait ${F.usd(res.byScen[kWorst])} à lui seul.`;
      p2.querySelector(".data-table").innerHTML = tableHtml(["Stage", "Prêts", "Encours", "Provision", "Couverture", "Rapport"],
        [1, 2, 3].map((k) => [`Stage ${k}`, F.num(res.stages[k].n), F.usd(res.stages[k].ead), F.usd(res.stages[k].ecl, 2),
          F.pct(res.stages[k].ead ? res.stages[k].ecl / res.stages[k].ead : null, 2), F.usd(base.stages[k].ecl, 2)]));
      renderCap();
    }
    p2.addEventListener("input", (e) => {
      const t = e.target;
      if (t.dataset.s) { const s = st2.scen[+t.dataset.k]; s[t.dataset.s] = +t.value; s.z = zOf(s.du, s.hpi, +t.dataset.k); }
      else if (t.dataset.p) {
        const k = t.dataset.p;
        st2.pol[k] = t.type === "checkbox" ? t.checked : +t.value;
      } else return;
      requestAnimationFrame(renderEcl);
    });

    /* ======================= 3. Capital bâlois ======================= */
    const perf = buckets.filter((b) => b.state_i !== 3);
    const st3 = { rho: rho, q: 0.999, pdF: P.pd_floor, lgdF: P.lgd_floor, lgdType: "downturn", ratio: 0.08 };
    perf.forEach((b) => { b.k_ref = irbK(b.pd_ttc, b.lgd_downturn, rho, 0.999, P.pd_floor, P.lgd_floor); });
    const eadPerf = perf.reduce((a, b) => a + b.ead, 0), rwaBase = perf.reduce((a, b) => a + b.rwa, 0);
    const p3 = document.createElement("article");
    p3.className = "panel span-12 sim"; p3.id = "sim-cap";
    const segc = (key, vals, cur, fmt) => `<div class="seg" role="group">${vals.map((v) => `<button type="button" data-c="${key}" data-v="${v}" aria-pressed="${v === cur}">${fmt(v)}</button>`).join("")}</div>`;
    p3.innerHTML = `<div class="panel-head"><div><h3 class="panel-title">Simuler le capital bâlois (${T("irb", "IRB")})</h3>
        <p class="panel-sub">Changez les paramètres de la formule : actifs pondérés et fonds propres des prêts sains se recalculent</p></div>
        <button type="button" class="btn-ghost sim-reset" data-reset="cap">Revenir aux paramètres bâlois</button></div>
      <div class="sim-grid">
        <form class="sim-controls" onsubmit="return false">
          <div class="field"><div class="field-head"><label for="cap-rho">Corrélation au cycle (ρ)</label><output id="o-rho"></output></div>
            <input type="range" id="cap-rho" data-c="rho" min="0.05" max="0.30" step="0.01" value="${rho}"></div>
          <div class="field"><label class="field-head">Niveau de confiance</label>${segc("q", [0.99, 0.995, 0.999, 0.9995], 0.999, (v) => F.pct(v, v === 0.99 ? 0 : v === 0.9995 ? 2 : 1))}</div>
          <div class="field"><label class="field-head">${T("lgd", "LGD")} utilisée</label>${segc("lgdType", ["downturn", "normal"], "downturn", (v) => (v === "downturn" ? "LGD de crise" : "LGD moyenne"))}</div>
          <div class="field"><label class="field-head">Plancher de PD</label>${segc("pdF", [0, 0.0003, 0.0005, 0.001], P.pd_floor, (v) => (v ? F.pct(v, 2) : "aucun"))}</div>
          <div class="field"><label class="field-head">Plancher de LGD</label>${segc("lgdF", [0, 0.05, 0.10, 0.15], P.lgd_floor, (v) => (v ? F.pct(v, 0) : "aucun"))}</div>
          <div class="field"><label class="field-head">Ratio de fonds propres</label>${segc("ratio", [0.08, 0.105, 0.13], 0.08, (v) => F.pct(v, v === 0.105 ? 1 : 0))}</div>
        </form>
        <div class="sim-results">
          <div class="sim-kpis" id="cap-kpis"></div>
          <div class="chart" id="cap-chart"></div>
          <div class="reading"><span class="reading-label">Lecture</span><p id="cap-reading"></p></div>
        </div>
      </div>
      <div class="panel-foot"><span class="panel-note">8 % : minimum réglementaire ; 10,5 % : avec le coussin de conservation ; 13 % : niveau courant des grandes banques.</span></div>`;
    grid.appendChild(p3);

    function renderCap() {
      let rwa = 0, el = 0;
      perf.forEach((b) => {
        const l = st3.lgdType === "downturn" ? b.lgd_downturn : b.lgd;
        const k = irbK(b.pd_ttc, l, st3.rho, st3.q, st3.pdF, st3.lgdF);
        rwa += b.k_ref > 0 ? b.rwa * (k / b.k_ref) : 0;
        el += Math.max(b.pd_ttc, st3.pdF) * Math.max(l, st3.lgdF) * b.ead;
      });
      const cap = st3.ratio * rwa, capBase = 0.08 * rwaBase, prov = lastProv.perfEcl, gap = prov - el;
      document.getElementById("o-rho").textContent = F.num(st3.rho, 2);
      const d = cap / capBase - 1;
      document.getElementById("cap-kpis").innerHTML = `
        <div class="stat big"><div class="lab">${T("rwa", "RWA")}</div><div class="val">${F.usd(rwa)}</div><div class="sub">densité ${F.pct(rwa / eadPerf, 1)}</div></div>
        <div class="stat big"><div class="lab">${T("capital", "Fonds propres")}</div><div class="val">${F.usd(cap)}</div>
          <div class="sub"><span class="${Math.abs(d) < 0.0005 ? "flat" : d > 0 ? "up" : "down"}">${Math.abs(d) < 0.0005 ? "identique au rapport" : `${d > 0 ? "+" : "−"}${F.pct(Math.abs(d), 0)} par rapport au rapport`}</span></div></div>
        <div class="stat big"><div class="lab">${T("el", "Perte attendue (Bâle)")}</div><div class="val">${F.usd(el)}</div><div class="sub">provision des prêts sains : ${F.usd(prov)}</div></div>`;
      const maxV = Math.max(cap, capBase, el, prov);
      Charts.columns(swap(document.getElementById("cap-chart")), {
        height: 220, label: "Capital simulé",
        rows: [{ label: "Provision", value: prov, color: "var(--s1)" }, { label: "Perte attendue", value: el, color: "var(--s3)" },
               { label: "Capital du rapport", value: capBase, color: "var(--neutral)" }, { label: "Capital simulé", value: cap, color: "var(--s4)" }],
        yFmt: (v) => F.usd(v), yTick: F.usdTick(maxV), valueFmt: (r) => F.usd(r.value), barW: 64,
        tip: (r) => `<b>${r.label}</b><div>${F.usd(r.value, 2)}</div>`,
      });
      document.getElementById("cap-reading").innerHTML =
        `Les prêts sains (${F.usd(eadPerf)}) pèsent <strong>${F.usd(rwa)}</strong> d'actifs pondérés, soit <strong>${F.usd(cap)}</strong> de fonds propres à ${F.pct(st3.ratio, st3.ratio === 0.105 ? 1 : 0)}.
         ${st3.q > 0.999 ? "Un niveau de confiance plus exigeant alourdit fortement le capital : on couvre des crises plus rares. " : st3.q < 0.999 ? "Un niveau de confiance plus faible allège le capital, mais couvre des crises moins sévères. " : ""}
         ${gap >= 0 ? `La provision dépasse la perte attendue bâloise de ${F.usd(gap)} : pas de déduction des fonds propres.`
                    : `La provision est inférieure de ${F.usd(-gap)} à la perte attendue bâloise : cet écart serait déduit des fonds propres.`}`;
    }
    p3.addEventListener("input", (e) => { if (e.target.dataset.c === "rho") { st3.rho = +e.target.value; requestAnimationFrame(renderCap); } });
    p3.addEventListener("click", (e) => {
      const b = e.target.closest("[data-c]"); if (!b || b.tagName !== "BUTTON") return;
      const k = b.dataset.c; st3[k] = k === "lgdType" ? b.dataset.v : +b.dataset.v;
      b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      renderCap();
    });

    /* Boutons « revenir » et « voir les données » */
    grid.addEventListener("click", (e) => {
      const r = e.target.closest("[data-reset]");
      if (r) {
        const w = r.dataset.reset;
        if (w === "score") {
          Object.assign(state1, initial1);
          p1.querySelectorAll("[data-f]").forEach((i) => { i.value = state1[i.dataset.f]; });
          renderScore();
        } else if (w === "ecl") {
          st2.scen = baseScen.map((s) => ({ ...s })); st2.pol = { ...basePolicy };
          st2.scen.forEach((s, k) => { p2.querySelector(`#du-${k}`).value = s.du; p2.querySelector(`#hpi-${k}`).value = s.hpi; p2.querySelector(`#w-${k}`).value = s.w; });
          p2.querySelectorAll("input[type=checkbox]").forEach((c) => { c.checked = true; });
          p2.querySelector("[data-p=notches]").value = basePolicy.notches; p2.querySelector("[data-p=minPd]").value = basePolicy.minPd;
          renderEcl();
        } else {
          Object.assign(st3, { rho: rho, q: 0.999, pdF: P.pd_floor, lgdF: P.lgd_floor, lgdType: "downturn", ratio: 0.08 });
          p3.querySelector("#cap-rho").value = rho;
          p3.querySelectorAll("button[data-c]").forEach((b) => b.setAttribute("aria-pressed", String(String(st3[b.dataset.c]) === b.dataset.v)));
          renderCap();
        }
        return;
      }
      const t = e.target.closest(".data-toggle");
      if (t && t.closest(".sim")) {
        const tb = t.closest(".sim").querySelector(".data-table"), open = tb.hidden;
        tb.hidden = !open; t.setAttribute("aria-expanded", String(open));
        t.textContent = open ? "Masquer" : t.closest("#sim-score") ? "Voir le détail du calcul" : "Voir les données";
      }
    });

    const initial1 = { ...state1 };
    renderScore();
    renderEcl();
    return { base, check: { ecl: base.total, rwa: rwaBase } };
  };
})();
