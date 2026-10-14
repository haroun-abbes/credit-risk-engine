/* Tableau de bord : lit docs/data/dashboard.json et construit la page.
   Toutes les phrases d'interprétation sont calculées à partir des données. */
(function () {
  const { F } = Charts;
  const T = (k, label) => window.term(k, label);
  const $ = (sel, root = document) => root.querySelector(sel);
  const COH = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
  const STAGE = { 1: "var(--stage1)", 2: "var(--stage2)", 3: "var(--stage3)" };
  const SCEN = { Central: "var(--s1)", Adverse: "var(--stage2)", "Sévère": "var(--stage3)" };
  const ym = (iso) => { const [y, m] = iso.split("-").map(Number); return y + (m - 1) / 12; };
  const isoFromYm = (v, list) => list.find((r) => Math.abs(ym(r.period) - v) < 1e-6)?.period;
  const maxBy = (a, f) => a.reduce((b, x) => (f(x) > f(b) ? x : b), a[0]);
  const minBy = (a, f) => a.reduce((b, x) => (f(x) < f(b) ? x : b), a[0]);
  const ratio = (a, b) => (F.ok(a) && F.ok(b) && b > 0 ? a / b : null);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  /* --- Briques d'interface ---------------------------------------------------------------- */
  function legend(items) {
    return items.map((it) => `<span><i class="${it.type || ""}" style="background:${it.color};color:${it.color}"></i>${it.name}</span>`).join("");
  }
  function tableHtml(cols, rows) {
    return `<table><thead><tr>${cols.map((c) => `<th scope="col">${c}</th>`).join("")}</tr></thead><tbody>${
      rows.map((r) => `<tr>${r.map((v) => `<td>${v}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
  }
  function section(id, step, name, lead) {
    const s = document.createElement("section");
    s.className = "section wrap"; s.id = id;
    s.innerHTML = `<div class="section-head"><p class="section-step">Étape ${step} sur 7</p><h2>${name}</h2>
      <p class="section-lead">${lead}</p></div><div class="grid"></div>`;
    $("#sections").appendChild(s);
    return $(".grid", s);
  }
  /* Un panneau : titre, contrôles, légende, graphique, lecture, données. render(state) remplit le tout. */
  function panel(grid, p) {
    const a = document.createElement("article");
    a.className = `panel span-${p.span}`; a.id = p.id;
    a.innerHTML = `<div class="panel-head"><div><h3 class="panel-title">${p.title}</h3>${p.sub ? `<p class="panel-sub">${p.sub}</p>` : ""}</div>
      ${p.controls ? `<div class="controls">${p.controls}</div>` : ""}</div>
      <div class="legend"></div><div class="chart"></div>
      <div class="reading"><span class="reading-label">Lecture</span><p></p></div>
      <div class="panel-foot"><span class="panel-note"></span>
        <button type="button" class="data-toggle" aria-expanded="false">Voir les données</button></div>
      <div class="data-table" hidden></div>`;
    grid.appendChild(a);
    const state = { ...(p.state || {}) };
    const render = () => {
      const out = p.render(state);
      $(".legend", a).innerHTML = out.legend ? legend(out.legend) : "";
      $(".legend", a).hidden = !out.legend;
      const old = $(".chart", a), fresh = document.createElement("div");
      fresh.className = "chart"; old.replaceWith(fresh);
      if (out.html) fresh.innerHTML = out.html;
      if (out.draw) out.draw(fresh);
      $(".reading p", a).innerHTML = out.reading;
      $(".panel-note", a).innerHTML = out.note || "";
      if (out.table) $(".data-table", a).innerHTML = tableHtml(out.table.cols, out.table.rows);
      $(".data-toggle", a).hidden = !out.table;
    };
    a.addEventListener("click", (e) => {
      const b = e.target.closest("[data-key]");
      if (!b || !a.contains(b)) return;
      state[b.dataset.key] = b.dataset.value;
      b.parentElement.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      render();
    });
    $(".data-toggle", a).addEventListener("click", (e) => {
      const t = $(".data-table", a), open = t.hidden;
      t.hidden = !open; e.currentTarget.setAttribute("aria-expanded", String(open));
      e.currentTarget.textContent = open ? "Masquer les données" : "Voir les données";
    });
    render();
    return a;
  }
  const seg = (key, options, current, label) =>
    `<div class="seg" role="group" aria-label="${label}">${options.map((o) =>
      `<button type="button" data-key="${key}" data-value="${esc(o.value)}" aria-pressed="${o.value === current}">${o.label}</button>`).join("")}</div>`;

  /* --- Définitions (bouton « i ») ----------------------------------------------------------------- */
  function setupGlossary() {
    const pop = $("#pop");
    let pinned = null, current = null;
    const open = (btn) => {
      const g = window.GLOSSARY[btn.dataset.term];
      if (!g) return;
      if (current && current !== btn) current.setAttribute("aria-expanded", "false");
      current = btn; btn.setAttribute("aria-expanded", "true");
      pop.innerHTML = `<h4>${g.t}</h4><p>${g.d}</p>${g.w ? `<p class="why"><b>Pourquoi c'est utile :</b> ${g.w}</p>` : ""}`;
      pop.hidden = false;
      const r = btn.getBoundingClientRect(), pr = pop.getBoundingClientRect();
      let left = Math.min(Math.max(8, r.left + r.width / 2 - pr.width / 2), window.innerWidth - pr.width - 8);
      let top = r.bottom + 8;
      if (top + pr.height > window.innerHeight - 8) top = r.top - pr.height - 8;
      pop.style.left = `${left}px`; pop.style.top = `${Math.max(8, top)}px`;
    };
    const close = () => { pop.hidden = true; pinned = null; if (current) current.setAttribute("aria-expanded", "false"); current = null; };
    document.addEventListener("mouseover", (e) => { const b = e.target.closest(".info"); if (b && !pinned) open(b); });
    document.addEventListener("mouseout", (e) => { const b = e.target.closest(".info"); if (b && !pinned && !b.contains(e.relatedTarget)) close(); });
    document.addEventListener("focusin", (e) => { const b = e.target.closest(".info"); if (b) open(b); });
    document.addEventListener("click", (e) => {
      const b = e.target.closest(".info");
      if (b) { if (pinned === b) close(); else { open(b); pinned = b; } e.stopPropagation(); return; }
      if (!e.target.closest("#pop")) close();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    window.addEventListener("scroll", () => { if (!pop.hidden) close(); }, { passive: true });
  }

  /* --- Construction de la page ------------------------------------------------------------------------ */
  function build(D) {
    const P = D.portfolio, Df = D.defaults, S = D.signals, M = D.model, I = D.ifrs9, C = D.capital, meta = D.meta;
    const snap = P.snapshot, cohorts = meta.cohorts.map(String);
    const cohColor = (c) => COH[cohorts.indexOf(String(c)) % COH.length] || "var(--neutral)";
    const allVint = Df.by_vintage.find((r) => r.cohorte === "Toutes");
    const coverage = ratio(I.weighted_ecl, I.total_ead);
    const st = Object.fromEntries(I.stages.map((r) => [r.stage, r]));
    const sigDq30 = S.backtest.find((r) => /30 à 59/.test(r.signal));
    const perfOot = M.performance["Hors période"], perfTrain = M.performance["Apprentissage"], perfVal = M.performance["Validation"];
    const firstYear = meta.first_period.slice(0, 4), snapYear = snap.snapshot_date.slice(0, 4);

    /* Ouverture */
    $("#hero-kicker").textContent = `Portefeuille de crédits immobiliers américains, situation au ${F.date(snap.snapshot_date)}`;
    $("#hero-title").innerHTML = `${F.num(meta.n_loans)} prêts immobiliers suivis de ${firstYear} à ${snapYear}`;
    $("#hero-sub").innerHTML = `Des données de Freddie Mac jusqu'à la provision comptable et au capital : quelle part des prêts a fait
      ${T("defaut", "défaut")}, quels signes l'annonçaient, comment noter chaque prêt et combien mettre de côté aujourd'hui.
      Cohortes ${cohorts.join(", ").replace(/, ([^,]*)$/, " et $1")}, soit des prêts accordés avant, pendant et après la crise de 2008.`;
    const kpi = (label, value, note) => `<div class="kpi"><dt>${label}</dt><dd>${value}<span class="kpi-note">${note}</span></dd></div>`;
    $("#kpis").innerHTML =
      kpi(T("encours", "Encours actif"), F.musd(snap.upb_musd), `${F.num(snap.n_active)} prêts encore en vie`) +
      kpi(`Taux de ${T("defaut", "défaut")}`, F.pct(allVint?.default_rate), `depuis l'octroi, toutes cohortes`) +
      kpi(T("ecl", "Provision IFRS 9"), F.usd(I.weighted_ecl), `${F.pct(coverage, 2)} de l'encours`) +
      kpi(T("capital", "Fonds propres requis"), F.usd(C.capital_8pct), `8 % des RWA de ${F.usd(C.rwa)}`);
    if (D.simulator) {
      const cta = document.createElement("p");
      cta.className = "hero-cta";
      cta.innerHTML = `<a class="btn-primary" href="#simulateur">Ouvrir le simulateur</a>
        <span>Notez un emprunteur, testez une crise, changez les règles IFRS 9 ou bâloises : tout se recalcule en direct.</span>`;
      $("#kpis").after(cta);
    }

    /* Chaîne du risque */
    const chain = [
      ["portefeuille", "Portefeuille", F.musd(snap.upb_musd)],
      ["defauts", "Défauts", F.pct(allVint?.default_rate)],
      ["signaux", "Signaux d'alerte", sigDq30 ? `risque ${F.times(sigDq30.lift, 0)}` : ""],
      ["notation", "Notation", `Gini ${F.pct(perfOot.gini, 0)}`],
      ["provision", "Provision IFRS 9", F.usd(I.weighted_ecl)],
      ["capital", "Capital", F.usd(C.capital_8pct)],
      ["simulateur", "Simulateur", "à vous de jouer"],
    ];
    $("#chain-list").innerHTML = chain.map(([id, name, num], k) =>
      `<li><a href="#${id}"><span class="c-step">Étape ${k + 1}</span><span class="c-name">${name}</span><span class="c-num">${num}</span></a></li>`).join("");

    /* ===== 1. Portefeuille ===== */
    const m12 = P.kpis.find((r) => r.reference === "Mois M-12"), m1 = P.kpis.find((r) => r.reference === "Mois M-1");
    const g1 = section("portefeuille", 1, "Le portefeuille aujourd'hui",
      `Au ${F.date(snap.snapshot_date)}, il reste ${F.num(snap.n_active)} prêts actifs pour ${F.musd(snap.upb_musd)} d'${T("encours", "encours")}.
       Parmi eux, ${F.pct(snap.dq30_rate, 2)} ont au moins 30 jours de retard et ${F.pct(snap.dq90_rate, 2)} en ont 90 ou plus.`);
    const mon = P.monthly;
    const peakUpb = maxBy(mon, (r) => r.upb_musd), peakDq = maxBy(mon, (r) => r.dq30_rate);
    panel(g1, {
      id: "p-upb", span: 6, title: `${T("encours", "Encours actif")} depuis ${firstYear}`, sub: "Capital restant dû, chaque mois",
      render: () => ({
        draw: (el) => Charts.line(el, {
          height: 240, label: "Encours actif par mois",
          series: [{ name: "Encours", color: "var(--s1)", points: mon.map((r) => ({ x: ym(r.period), y: r.upb_musd })) }],
          xFmt: (v) => String(Math.round(v)), yFmt: (v) => F.musd(v), tipTitle: (v) => F.month(isoFromYm(v, mon)),
          yTick: (() => { const u = F.usdTick(peakUpb.upb_musd * 1e6); return (t, st) => u(t * 1e6, st * 1e6); })(),
        }),
        reading: `L'encours monte à chaque nouvelle cohorte puis baisse avec les remboursements. Il a culminé à
          <strong>${F.musd(peakUpb.upb_musd)}</strong> en ${F.month(peakUpb.period)} ; il est de <strong>${F.musd(snap.upb_musd)}</strong> aujourd'hui.`,
        table: { cols: ["Mois", "Prêts actifs", "Encours"], rows: mon.filter((r, k) => k % 12 === 0 || k === mon.length - 1)
          .map((r) => [F.monthShort(r.period), F.num(r.n_active), F.musd(r.upb_musd)]) },
        note: "Un point par mois ; le tableau montre un mois sur douze.",
      }),
    });
    panel(g1, {
      id: "p-dq", span: 6, title: `Prêts en ${T("retard30", "retard")}`, sub: "Part des prêts actifs, chaque mois",
      render: () => ({
        legend: [{ name: "30 jours ou plus", color: "var(--s2)" }, { name: "90 jours ou plus", color: "var(--stage3)" }],
        draw: (el) => Charts.line(el, {
          height: 240, label: "Taux de retard par mois",
          series: [
            { name: "30 jours ou plus", color: "var(--s2)", points: mon.map((r) => ({ x: ym(r.period), y: r.dq30_rate })) },
            { name: "90 jours ou plus", color: "var(--stage3)", points: mon.map((r) => ({ x: ym(r.period), y: r.dq90_rate })) },
          ],
          xFmt: (v) => String(Math.round(v)), yFmt: (v) => F.pct(v, 2), yTick: F.pctTick, tipTitle: (v) => F.month(isoFromYm(v, mon)),
        }),
        reading: `Le retard de 30 jours ou plus a atteint <strong>${F.pct(peakDq.dq30_rate)}</strong> des prêts en ${F.month(peakDq.period)}.
          Il est de <strong>${F.pct(snap.dq30_rate, 2)}</strong> aujourd'hui${m12 ? `, contre ${F.pct(m12.dq30_rate, 2)} un an plus tôt` : ""}.`,
        table: { cols: ["Mois", "30 jours ou plus", "90 jours ou plus"], rows: mon.filter((r, k) => k % 12 === 0 || k === mon.length - 1)
          .map((r) => [F.monthShort(r.period), F.pct(r.dq30_rate, 2), F.pct(r.dq90_rate, 2)]) },
      }),
    });
    const conc = P.concentration.find((r) => /actif/i.test(r.perimetre)) || P.concentration[0];
    const hhiLabel = conc.hhi < 1500 ? "un portefeuille peu concentré" : conc.hhi < 2500 ? "une concentration modérée" : "un portefeuille concentré";
    panel(g1, {
      id: "p-states", span: 7, title: "Répartition géographique de l'encours", sub: "Les 10 premiers États américains",
      render: () => ({
        draw: (el) => Charts.barH(el, {
          label: "Part de l'encours par État", rows: P.top_states.map((r) => ({ ...r, label: r.property_state, value: r.share })),
          xFmt: (v) => F.pct(v, 0), xTick: F.pctTick, valueFmt: (r) => F.pct(r.value),
          tip: (r) => `<b>${r.property_state}</b><div>${F.pct(r.share)} de l'encours</div><div>${F.num(r.n_loans)} prêts, ${F.musd(r.upb_musd)}</div>`,
        }),
        reading: `Les 5 premiers États portent <strong>${F.pct(conc.top5_share, 0)}</strong> de l'encours. L'${T("hhi", "indice HHI")} de
          ${F.num(conc.hhi)} équivaut à un portefeuille réparti à parts égales entre ${F.num(conc.equivalent_states, 0)} États : c'est ${hhiLabel}.`,
        table: { cols: ["Rang", "État", "Prêts", "Encours", "Part"], rows: P.top_states.map((r) =>
          [r.rank, r.property_state, F.num(r.n_loans), F.musd(r.upb_musd), F.pct(r.share)]) },
        note: "Seuils usuels du HHI : moins de 1 500, peu concentré ; plus de 2 500, concentré.",
      }),
    });
    panel(g1, {
      id: "p-month", span: 5, title: "Situation du mois", sub: `${F.month(snap.snapshot_date)}, comparé au mois précédent et à l'an dernier`,
      render: () => {
        const rows = [["Prêts actifs", (r) => F.num(r.n_active)], ["Encours", (r) => F.musd(r.upb_musd)],
          ["Retard 30 j ou plus", (r) => F.pct(r.dq30_rate, 2)], ["Retard 90 j ou plus", (r) => F.pct(r.dq90_rate, 2)],
          ["Nouveaux défauts", (r) => F.num(r.n_new_defaults)]];
        const order = ["Mois M", "Mois M-1", "Mois M-12"].map((k) => P.kpis.find((r) => r.reference === k)).filter(Boolean);
        const head = order.map((r) => F.monthShort(r.period));
        const d = m1 && P.kpis[0] ? P.kpis.find((r) => r.reference === "Mois M") : null;
        return {
          html: `<div class="data-table" style="margin-top:4px">${tableHtml(["", ...head], rows.map(([l, f]) => [l, ...order.map(f)]))}</div>`,
          reading: d && m12 ? `En un an, l'encours a reculé de <strong>${F.pct(1 - d.upb_musd / m12.upb_musd, 0)}</strong>
            (remboursements et amortissement) ; ${d.n_new_defaults} nouveau${d.n_new_defaults > 1 ? "x" : ""} défaut${d.n_new_defaults > 1 ? "s" : ""} ce mois-ci.` : "",
        };
      },
    });

    /* ===== 2. Défauts ===== */
    const vint = Df.by_vintage.filter((r) => r.cohorte !== "Toutes");
    const worst = maxBy(vint, (r) => r.default_rate), best = minBy(vint, (r) => r.default_rate);
    const g2 = section("defauts", 2, "Qui fait défaut, et quand ?",
      `${F.pct(allVint?.default_rate)} des prêts ont fait ${T("defaut", "défaut")} depuis leur octroi. Le premier facteur est l'année d'octroi :
       ${F.pct(worst.default_rate)} pour la ${T("cohorte", "cohorte")} ${worst.cohorte}, contre ${F.pct(best.default_rate)} pour ${best.cohorte}.`);
    const curves = cohorts.map((c) => ({ c, pts: Df.curves.filter((r) => String(r.vintage_year) === c).map((r) => ({ x: r.age, y: r.cum_default_rate })) }));
    const ms = Df.milestones.filter((r) => F.ok(r.at_60m));
    const ms60w = ms.length ? maxBy(ms, (r) => r.at_60m) : null, ms60b = ms.length ? minBy(ms, (r) => r.at_60m) : null;
    panel(g2, {
      id: "p-vintage", span: 8, title: T("vintage", "Courbes de vintage"), sub: "Part cumulée des prêts en défaut selon l'ancienneté du prêt",
      render: () => ({
        legend: cohorts.map((c) => ({ name: `Cohorte ${c}`, color: cohColor(c) })),
        draw: (el) => Charts.line(el, {
          height: 300, label: "Défaut cumulé par cohorte et ancienneté",
          series: curves.map(({ c, pts }) => ({ name: `Cohorte ${c}`, color: cohColor(c), points: pts })),
          xMin: 0, xFmt: (v) => (v === 0 ? "0" : `${F.num(v / 12, v % 12 ? 1 : 0)} an${v >= 24 ? "s" : ""}`),
          xTicks: (a, b, iw) => { const step = iw < 420 ? 60 : 24, out = []; for (let v = 0; v <= b; v += step) out.push(v); return out; },
          yFmt: (v) => F.pct(v, 1), yTick: F.pctTick, tipTitle: (v) => `Ancienneté : ${v} mois`,
        }),
        reading: ms60w && ms60b && ms60w !== ms60b
          ? `À 5 ans d'ancienneté, la cohorte ${ms60w.vintage_year} avait déjà <strong>${F.pct(ms60w.at_60m)}</strong> de prêts en défaut, contre
             <strong>${F.pct(ms60b.at_60m)}</strong> pour ${ms60b.vintage_year}, soit <strong>${F.num(ratio(ms60w.at_60m, ms60b.at_60m), 1)} fois plus</strong>.
             Les prêts accordés juste avant 2008 ont subi la chute des prix immobiliers dès leurs premières années.`
          : "Comparer les cohortes à ancienneté égale isole l'effet des conditions d'octroi et de la conjoncture.",
        table: { cols: ["Cohorte", "Prêts", "À 1 an", "À 2 ans", "À 3 ans", "À 5 ans", "À 10 ans", "Recul"],
          rows: Df.milestones.map((r) => [r.vintage_year, F.num(r.n_loans), F.pct(r.at_12m, 2), F.pct(r.at_24m, 2), F.pct(r.at_36m, 2),
            F.pct(r.at_60m, 2), F.pct(r.at_120m, 2), `${r.horizon_months} mois`]) },
        note: "Une courbe s'arrête au dernier mois observé pour sa cohorte.",
      }),
    });
    panel(g2, {
      id: "p-cohort", span: 4, title: `Taux de ${T("defaut", "défaut")} par cohorte`, sub: `Avec l'${T("ic", "intervalle de confiance à 95 %")}`,
      render: () => ({
        draw: (el) => Charts.columns(el, {
          height: 300, label: "Taux de défaut par cohorte",
          rows: vint.map((r) => ({ ...r, label: String(r.cohorte), value: r.default_rate, lo: r.ci_low, hi: r.ci_high, color: cohColor(r.cohorte) })),
          yFmt: (v) => F.pct(v, 0), yTick: F.pctTick, valueFmt: (r) => F.pct(r.value),
          tip: (r) => `<b>Cohorte ${r.cohorte}</b><div>${F.num(r.n_defaults)} défauts sur ${F.num(r.n_loans)} prêts</div><div>IC à 95 % : ${F.pct(r.ci_low)} à ${F.pct(r.ci_high)}</div>`,
        }),
        reading: `Sorties avec perte : <strong>${F.pct(allVint?.loss_exit_rate)}</strong> des prêts. Beaucoup de défauts se régularisent sans perte.`,
        table: { cols: ["Cohorte", "Prêts", "Défauts", "Taux", "IC bas", "IC haut", "Sorties avec perte"],
          rows: Df.by_vintage.map((r) => [r.cohorte, F.num(r.n_loans), F.num(r.n_defaults), F.pct(r.default_rate, 2), F.pct(r.ci_low, 2),
            F.pct(r.ci_high, 2), F.pct(r.loss_exit_rate, 2)]) },
      }),
    });
    const dims = [...new Set(Df.segments.map((r) => r.dimension))];
    const dimOrder = ["Score FICO", "CLTV", "LTV", "DTI", "Objet du prêt", "Occupation", "Canal"].filter((d) => dims.includes(d));
    const dimTerm = { "Score FICO": "fico", CLTV: "cltv", LTV: "ltv", DTI: "dti" };
    panel(g2, {
      id: "p-segments", span: 8, title: `Taux de ${T("defaut", "défaut")} selon le profil de l'emprunteur`,
      sub: "Choisissez une caractéristique à l'octroi et une cohorte",
      state: { dim: dimOrder[0], coh: "Toutes" },
      controls: seg("dim", dimOrder.map((d) => ({ value: d, label: d })), dimOrder[0], "Caractéristique") +
                seg("coh", [{ value: "Toutes", label: "Toutes" }, ...cohorts.map((c) => ({ value: c, label: c }))], "Toutes", "Cohorte"),
      render: (s) => {
        const rows = Df.segments.filter((r) => r.dimension === s.dim && String(r.cohorte) === s.coh).sort((a, b) => a.segment_order - b.segment_order);
        if (!rows.length) return { html: `<p class="panel-sub">Pas assez de prêts pour cette combinaison.</p>`, reading: "Choisissez une autre cohorte." };
        const hi = maxBy(rows, (r) => r.default_rate), lo = minBy(rows, (r) => r.default_rate);
        const dimName = dimTerm[s.dim] ? T(dimTerm[s.dim], s.dim) : s.dim.toLowerCase();
        return {
          draw: (el) => Charts.barH(el, {
            label: `Taux de défaut par ${s.dim}`, color: s.coh === "Toutes" ? "var(--s1)" : cohColor(s.coh),
            rows: rows.map((r) => ({ ...r, label: r.segment, value: r.default_rate, lo: r.ci_low, hi: r.ci_high })),
            xFmt: (v) => F.pct(v, 0), xTick: F.pctTick, valueFmt: (r) => F.pct(r.value),
            tip: (r) => `<b>${r.segment}</b><div>${F.num(r.n_defaults)} défauts sur ${F.num(r.n_loans)} prêts</div><div>IC à 95 % : ${F.pct(r.ci_low)} à ${F.pct(r.ci_high)}</div>`,
          }),
          reading: hi === lo ? "Un seul segment disponible." :
            `Selon ${s.dim === "Score FICO" ? "le" : "la"} ${dimName}, le taux de défaut va de <strong>${F.pct(lo.default_rate)}</strong> (${lo.segment})
             à <strong>${F.pct(hi.default_rate)}</strong> (${hi.segment}), soit <strong>${F.num(ratio(hi.default_rate, lo.default_rate), 1)} fois plus</strong>
             ${s.coh === "Toutes" ? "sur l'ensemble des cohortes" : `pour la cohorte ${s.coh}`}.`,
          table: { cols: ["Segment", "Prêts", "Défauts", "Taux", "IC bas", "IC haut"],
            rows: rows.map((r) => [r.segment, F.num(r.n_loans), F.num(r.n_defaults), F.pct(r.default_rate, 2), F.pct(r.ci_low, 2), F.pct(r.ci_high, 2)]) },
          note: "Segments de moins de 30 prêts et valeurs inconnues masqués.",
        };
      },
    });
    const sevC = Df.severity.filter((r) => r.cohorte !== "Toutes" && F.ok(r.severity));
    const sevAll = Df.severity.find((r) => r.cohorte === "Toutes");
    panel(g2, {
      id: "p-severity", span: 4, title: T("severite", "Sévérité des pertes"), sub: "Part de la dette perdue quand le bien est revendu",
      render: () => ({
        draw: (el) => Charts.columns(el, {
          height: 260, label: "Sévérité par cohorte",
          rows: sevC.map((r) => ({ ...r, label: String(r.cohorte), value: r.severity, color: cohColor(r.cohorte) })),
          yFmt: (v) => F.pct(v, 0), yTick: F.pctTick, valueFmt: (r) => F.pct(r.value, 0), yMax: 1,
          tip: (r) => `<b>Cohorte ${r.cohorte}</b><div>${F.num(r.n_loss_exits)} liquidations</div><div>Perte moyenne : ${F.usd(r.avg_loss_usd)}</div>`,
        }),
        reading: `En moyenne, une liquidation coûte <strong>${F.pct(sevAll?.severity, 0)}</strong> de la dette. La sévérité suit le prix de revente
          du bien : forte pour les prêts liquidés après 2008, faible quand les prix montent.`,
        table: { cols: ["Cohorte", "Liquidations", "Exposition", "Pertes", "Sévérité"],
          rows: Df.severity.map((r) => [r.cohorte, F.num(r.n_loss_exits), F.musd(r.ead_musd), F.musd(r.loss_musd), F.pct(r.severity, 1)]) },
      }),
    });

    /* ===== 3. Signaux d'alerte ===== */
    const roll = S.roll;
    const rollShare = (f, t) => roll.find((r) => r.from_state === f && r.to_state === t)?.share;
    const r6090 = rollShare("60-89 jours", "90+ jours");
    const g3 = section("signaux", 3, "Les signes qui annoncent un défaut",
      `${sigDq30 ? `Un ${T("retard30", "retard de 30 jours")} multiplie par ${F.num(sigDq30.lift, 0)} le risque de défaut dans l'année. ` : ""}
       ${F.ok(r6090) ? `Une fois à 60 jours, le retard s'aggrave souvent : ${F.pct(r6090, 0)} des prêts passent à 90 jours le mois suivant.` : ""}`);
    const bt = S.backtest;
    panel(g3, {
      id: "p-signals", span: 7, title: "Ce que vaut chaque signal d'alerte", sub: `${T("pd12", "Taux de défaut à 12 mois")} des prêts qui présentent le signal`,
      render: () => ({
        draw: (el) => Charts.barH(el, {
          label: "Taux de défaut à 12 mois par signal",
          rows: bt.map((r) => ({ ...r, label: r.signal, value: r.pd12, lo: r.ci_low, hi: r.ci_high,
                                 color: r.lift <= 1.0001 ? "var(--neutral)" : "var(--s2)" })),
          xFmt: (v) => F.pct(v, 0), xTick: F.pctTick, valueFmt: (r) => `${F.pct(r.value)}  ${r.lift > 1.0001 ? F.times(r.lift, 0) : ""}`,
          tip: (r) => `<b>${esc(r.signal)}</b><div>${F.pct(r.pd12)} de défaut à 12 mois</div><div>Risque multiplié par ${F.num(r.lift, 1)} par rapport à un prêt sans signal</div><div>${F.num(r.n_loan_months)} prêts-mois observés</div>`,
        }),
        reading: (() => {
          const top = maxBy(bt, (r) => r.lift), base = bt.find((r) => r.lift <= 1.0001);
          return `Un prêt sans aucun signal a <strong>${F.pct(base?.pd12, 2)}</strong> de risque de défaut dans l'année. Le signal le plus fort,
            « ${top.signal.toLowerCase()} », porte ce risque à <strong>${F.pct(top.pd12, 0)}</strong>, soit un ${T("lift", "lift")} de ${F.num(top.lift, 0)}.`;
        })(),
        table: { cols: ["Signal", "Prêts-mois", "Défauts à 12 mois", "Taux", "Lift"],
          rows: bt.map((r) => [r.signal, F.num(r.n_loan_months), F.num(r.n_default_12m), F.pct(r.pd12, 2), F.times(r.lift, 1)]) },
        note: "Chiffre après la barre : combien de fois le risque d'un prêt sans signal.",
      }),
    });
    const wl = S.watchlist, wlAny = wl.find((r) => /Au moins/.test(r.signal));
    panel(g3, {
      id: "p-watch", span: 5, title: "Prêts à surveiller ce mois-ci", sub: "Prêts actifs qui présentent chaque signal aujourd'hui",
      render: () => ({
        html: `<div class="data-table" style="margin-top:4px">${tableHtml(["Signal", "Prêts", "Part", "Encours"],
          wl.filter((r) => r.n_loans > 0 || /Au moins/.test(r.signal)).map((r) => [/Au moins/.test(r.signal) ? `<b>${r.signal}</b>` : r.signal,
            F.num(r.n_loans), F.pct(r.share_of_loans, 1), F.musd(r.upb_musd)]))}</div>`,
        reading: wlAny ? `<strong>${F.num(wlAny.n_loans)} prêts</strong> (${F.pct(wlAny.share_of_loans, 1)} du portefeuille, ${F.musd(wlAny.upb_musd)})
          présentent au moins un signal : c'est la liste à transmettre aux équipes de recouvrement.` : "",
        note: "Les signaux absents ce mois-ci ne sont pas affichés.",
      }),
    });
    const rollFrom = [...new Map(roll.map((r) => [r.from_state, r.from_order])).entries()].sort((a, b) => a[1] - b[1]).map((x) => x[0]);
    const rollTo = [...new Map(roll.map((r) => [r.to_state, r.to_order])).entries()].sort((a, b) => a[1] - b[1]).map((x) => x[0]);
    const cure30 = rollShare("30-59 jours", "À jour");
    panel(g3, {
      id: "p-roll", span: 12, title: `Évolution d'un mois sur l'autre : les ${T("roll", "taux de roulement")}`,
      sub: "Lecture en ligne : où se trouve, le mois suivant, un prêt dans l'état indiqué à gauche",
      render: () => ({
        draw: (el) => Charts.heat(el, {
          label: "Matrice de roulement", rows: rollFrom, cols: rollTo, cellH: 36,
          values: rollFrom.map((f) => rollTo.map((t) => rollShare(f, t) ?? 0)),
          fmt: (v) => F.pct(v, v < 0.1 ? 1 : 0), highlight: (i, j) => rollFrom[i] === rollTo[j],
          tip: (i, j, v) => `<b>${rollFrom[i]} → ${rollTo[j]}</b><div>${F.pct(v, 2)} des prêts le mois suivant</div>`,
        }),
        reading: `${F.ok(cure30) ? `Un prêt à 30 jours de retard revient à jour le mois suivant dans <strong>${F.pct(cure30, 0)}</strong> des cas. ` : ""}
          ${F.ok(r6090) ? `À 60 jours, il passe à 90 jours (le défaut) dans <strong>${F.pct(r6090, 0)}</strong> des cas : plus le retard dure, plus il est difficile à rattraper.` : ""}`,
        table: { cols: ["État ce mois-ci", ...rollTo], rows: rollFrom.map((f) => [f, ...rollTo.map((t) => F.pct(rollShare(f, t) ?? 0, 2))]) },
        note: "Cases encadrées : le prêt reste dans le même état. Toutes années confondues.",
      }),
    });

    /* ===== 4. Notation ===== */
    const sc = M.scale;
    const monotone = sc.every((r, k) => k === 0 || r.observed >= sc[k - 1].observed);
    const g4 = section("notation", 4, "Noter chaque prêt",
      `Un modèle de ${T("pd", "probabilité de défaut")} attribue à chaque prêt une note de R1 à R8. Il classe bien les futurs défauts :
       ${T("gini", "Gini")} de ${F.pct(perfOot.gini)} sur des années qu'il n'a jamais vues (${M.oot_from} et après), contre ${F.pct(perfTrain.gini)} à l'apprentissage.`);
    panel(g4, {
      id: "p-perf", span: 5, title: "Performance du modèle", sub: `Régression logistique, version ${M.version}`,
      render: () => ({
        html: `<div class="data-table" style="margin-top:4px">${tableHtml(["Échantillon", T("auc", "AUC"), T("gini", "Gini"), T("ks", "KS")],
          [["Apprentissage", perfTrain], ["Validation", perfVal], [T("oot", "Hors période"), perfOot]].map(([n, p]) =>
            [n, F.num(p.auc, 3), F.pct(p.gini, 1), F.pct(p.ks, 1)]))}</div>
          <div class="stats"><div class="stat"><div class="lab">${T("psi", "PSI")}</div><div class="val">${F.num(M.psi, 3)}</div>
          <div class="sub">${M.psi < 0.1 ? "stable" : M.psi < 0.25 ? "à surveiller" : "instable"}</div></div>
          <div class="stat"><div class="lab">AUC du challenger</div><div class="val">${F.num(M.challenger_auc_oot, 3)}</div>
          <div class="sub">gradient boosting, hors période</div></div></div>`,
        reading: `La perte de Gini entre apprentissage et hors période reste limitée (${F.num((perfTrain.gini - perfOot.gini) * 100, 1)} points) :
          le modèle n'a pas appris par cœur. Il ${perfOot.auc >= M.challenger_auc_oot ? "fait mieux" : "fait presque aussi bien"} qu'un modèle de
          machine learning plus complexe, tout en restant lisible classe par classe.`,
      }),
    });
    panel(g4, {
      id: "p-scale", span: 7, title: `${T("notation", "Échelle de notation")} : risque prédit et risque observé`,
      sub: `Années hors période (${M.oot_from} et après), échelle logarithmique`,
      render: () => ({
        legend: [{ name: "Taux de défaut observé", color: "var(--s1)", type: "dot" }, { name: "PD moyenne prédite", color: "var(--s2)", type: "diamond" }],
        draw: (el) => Charts.dotsLog(el, {
          height: 280, label: "PD prédite et taux observé par classe", cats: sc.map((r) => `R${r.grade}`),
          series: [{ name: "Observé", color: "var(--s1)", values: sc.map((r) => r.observed) },
                   { name: "Prédit", color: "var(--s2)", shape: "diamond", values: sc.map((r) => r.pd_pred) }],
          yFmt: (v) => F.pct(v, v < 0.001 ? 2 : v < 0.01 ? 1 : 0),
          tip: (k) => { const r = sc[k]; return `<b>Classe R${r.grade}</b><div>PD de ${F.pct(r.pd_lower, 2)} à ${F.pct(r.pd_upper, 2)}</div>
            <div>Observé : ${F.pct(r.observed, 2)}</div><div>Prédit : ${F.pct(r.pd_pred, 2)}</div><div>${F.pct(r.share, 1)} des prêts</div>`; },
        }),
        reading: `${monotone ? "Le taux de défaut observé monte à chaque classe" : "Le taux observé n'est pas parfaitement croissant"},
          de <strong>${F.pct(sc[0].observed, 2)}</strong> en R1 à <strong>${F.pct(sc[sc.length - 1].observed, 1)}</strong> en R${sc[sc.length - 1].grade}.
          La PD prédite est au-dessus de l'observé dans ${sc.filter((r) => r.pd_pred > r.observed).length} classes sur ${sc.length} :
          le classement est bon, le niveau est prudent. Il est recalibré à l'étape 5.`,
        table: { cols: ["Classe", "Bornes de PD", "Part des prêts", "PD prédite", "Taux observé"],
          rows: sc.map((r) => [`R${r.grade}`, `${F.pct(r.pd_lower, 2)} à ${F.pct(r.pd_upper, 2)}`, F.pct(r.share, 1), F.pct(r.pd_pred, 2), F.pct(r.observed, 2)]) },
      }),
    });
    const ivStrength = (v) => (v < 0.02 ? "inutile" : v < 0.1 ? "faible" : v < 0.3 ? "moyen" : "fort");
    panel(g4, {
      id: "p-iv", span: 6, title: "Variables du modèle", sub: `Pouvoir de séparation de chaque variable (${T("iv", "Information Value")})`,
      render: () => ({
        draw: (el) => Charts.barH(el, {
          label: "Information Value par variable", rows: M.iv.map((r) => ({ ...r, label: r.label, value: r.iv })),
          xFmt: (v) => F.num(v, 1), xTick: (t, st) => (t === 0 ? "0" : F.num(t, F.dec(st))), valueFmt: (r) => F.num(r.value, 2), color: "var(--s1)",
          tip: (r) => `<b>${esc(r.label)}</b><div>IV : ${F.num(r.iv, 3)} (${ivStrength(r.iv)})</div>`,
        }),
        reading: `${M.iv.length} variables retenues. Les plus fortes sont le comportement de paiement (${M.iv[0].label.toLowerCase()})
          et le profil à l'octroi : ce qu'a fait l'emprunteur récemment en dit plus que tout le reste.`,
        table: { cols: ["Variable", "IV", "Force"], rows: M.iv.map((r) => [r.label, F.num(r.iv, 3), ivStrength(r.iv)]) },
        note: "IV recalculée à partir des classes de la grille. Moins de 0,1 : faible ; plus de 0,3 : fort.",
      }),
    });
    panel(g4, {
      id: "p-dist", span: 6, title: "Répartition des prêts par classe", sub: `Années hors période (${M.oot_from} et après)`,
      render: () => ({
        draw: (el) => Charts.columns(el, {
          height: 260, label: "Part des prêts par classe", rows: sc.map((r) => ({ ...r, label: `R${r.grade}`, value: r.share, color: "var(--s1)" })),
          yFmt: (v) => F.pct(v, 0), yTick: F.pctTick, valueFmt: (r) => F.pct(r.value, 0), barW: 40,
          tip: (r) => `<b>Classe R${r.grade}</b><div>${F.pct(r.share, 1)} des prêts notés</div>`,
        }),
        reading: (() => { const top = maxBy(sc, (r) => r.share), risky = sc.filter((r) => r.grade >= 6).reduce((a, r) => a + r.share, 0);
          return `La classe la plus fréquente est R${top.grade} (${F.pct(top.share, 0)} des prêts). Les classes R6 à R8, les plus risquées,
            ne regroupent que <strong>${F.pct(risky, 1)}</strong> des prêts : c'est là que se concentre la surveillance.`; })(),
        table: { cols: ["Classe", "Prêts notés", "Part"], rows: sc.map((r) => [`R${r.grade}`, F.num(r.n), F.pct(r.share, 1)]) },
      }),
    });

    /* ===== 5. Provision IFRS 9 ===== */
    const g5 = section("provision", 5, "Combien mettre de côté : la provision IFRS 9",
      `La ${T("ecl", "perte attendue")} s'élève à ${F.usd(I.weighted_ecl)} pour ${F.usd(I.total_ead)} d'encours, soit ${F.pct(coverage, 2)}.
       Le ${T("stages", "Stage 2")} ne pèse que ${F.pct(st[2]?.ead_share, 1)} de l'encours mais ${F.pct(st[2]?.ecl_share, 0)} de la provision.`);
    const cal = I.calibration;
    const calYears = cal.map((r) => r.year), excl = cal.find((r) => r.year === 2020);
    panel(g5, {
      id: "p-calib", span: 12, title: `Recalibrer la PD : ${T("ttc", "PD TTC")} et ${T("pit", "PD PIT")}`,
      sub: `Par année d'observation. ${T("vasicek", "Modèle de Vasicek")}, corrélation de ${F.num(I.assumptions.rho, 2)}`,
      render: () => ({
        legend: [{ name: "Taux de défaut observé", color: "var(--ink-2)" }, { name: "PD TTC (moyenne de long terme)", color: "var(--s1)" },
                 { name: "PD PIT expliquée par la conjoncture", color: "var(--s2)", type: "dash" }],
        draw: (el) => Charts.line(el, {
          height: 300, label: "Calibrage TTC et PIT par année",
          series: [{ name: "Observé", color: "var(--ink-2)", markers: true, points: cal.map((r) => ({ x: r.year, y: r.observed })) },
                   { name: "PD TTC", color: "var(--s1)", points: cal.map((r) => ({ x: r.year, y: r.pd_ttc })) },
                   { name: "PD PIT", color: "var(--s2)", dash: true, points: cal.map((r) => ({ x: r.year, y: r.pd_pit_macro })) }],
          xFmt: (v) => String(v), yFmt: (v) => F.pct(v, 2), yTick: F.pctTick, xMin: Math.min(...calYears), xMax: Math.max(...calYears),
          annotations: excl ? [{ x: 2020, y: excl.observed, text: "2020 : moratoires Covid, exclue" }] : [],
        }),
        reading: `La PD TTC lisse le cycle (de ${F.pct(minBy(cal, (r) => r.pd_ttc).pd_ttc)} à ${F.pct(maxBy(cal, (r) => r.pd_ttc).pd_ttc)}) quand les
          défauts observés vont de ${F.pct(minBy(cal, (r) => r.observed).observed)} à ${F.pct(maxBy(cal, (r) => r.observed).observed)}. Elle sert au capital.
          La PD PIT suit la conjoncture (chômage, prix immobiliers) : c'est elle qu'IFRS 9 demande pour la provision.`,
        table: { cols: ["Année", "Observations", "Taux observé", "PD TTC", "PD PIT"],
          rows: cal.map((r) => [r.year, F.num(r.n), F.pct(r.observed, 2), F.pct(r.pd_ttc, 2), F.pct(r.pd_pit_macro, 2)]) },
        note: `Taux de défaut moyen de long terme : ${F.pct(I.lra, 2)}. 2020 (moratoires Covid) est exclue du lien avec la conjoncture.`,
      }),
    });
    panel(g5, {
      id: "p-stages", span: 6, title: `Les trois ${T("stages", "stages IFRS 9")}`, sub: "Part de l'encours et part de la provision",
      render: () => ({
        legend: [1, 2, 3].map((k) => ({ name: `Stage ${k}`, color: STAGE[k], type: "sq" })),
        draw: (el) => Charts.stack100(el, {
          label: "Répartition par stage",
          bars: [{ label: "Encours", parts: [1, 2, 3].map((k) => ({ name: `Stage ${k}`, value: st[k]?.ead || 0, color: STAGE[k] })) },
                 { label: "Provision", parts: [1, 2, 3].map((k) => ({ name: `Stage ${k}`, value: st[k]?.ecl || 0, color: STAGE[k] })) }],
          fmt: (v) => F.pct(v, 0),
          tip: (b, p, sh) => `<b>${p.name}</b><div>${F.pct(sh, 1)} ${b.label === "Encours" ? "de l'encours" : "de la provision"}</div><div>${F.usd(p.value)}</div>`,
        }),
        html: "",
        reading: `Taux de ${T("couverture", "couverture")} : <strong>${F.pct(st[1]?.coverage, 2)}</strong> en Stage 1,
          <strong>${F.pct(st[2]?.coverage, 2)}</strong> en Stage 2 et <strong>${F.pct(st[3]?.coverage, 1)}</strong> en Stage 3.
          En Stage 2, on provisionne la perte sur toute la vie du prêt, et plus seulement sur 12 mois : c'est l'« effet falaise ».`,
        table: { cols: ["Stage", "Prêts", "Encours", "Provision", "Couverture"],
          rows: I.stages.map((r) => [`Stage ${r.stage}`, F.num(r.n), F.usd(r.ead), F.usd(r.ecl, 2), F.pct(r.coverage, 2)]) },
      }),
    });
    const reasons = I.reasons.filter((r) => r.stage >= 2);
    panel(g5, {
      id: "p-reasons", span: 6, title: "Pourquoi un prêt passe en Stage 2 ou 3", sub: `Première règle vérifiée (${T("sicr", "critères SICR")})`,
      render: () => ({
        draw: (el) => Charts.barH(el, {
          label: "Prêts par motif de stage",
          rows: reasons.map((r) => ({ ...r, label: r.stage_reason, value: r.n, color: STAGE[r.stage] })),
          xFmt: (v) => F.num(v), xTick: (t) => (t % 1 ? "" : F.num(t)), valueFmt: (r) => F.num(r.value),
          tip: (r) => `<b>Stage ${r.stage}</b><div>${esc(r.stage_reason)}</div><div>${F.num(r.n)} prêts, ${F.usd(r.ead)}</div>`,
        }),
        reading: (() => { const s2 = reasons.filter((r) => r.stage === 2), tot = s2.reduce((a, r) => a + r.n, 0), top = s2.length ? maxBy(s2, (r) => r.n) : null;
          return top ? `Sur ${F.num(tot)} prêts en Stage 2, le premier motif est « ${top.stage_reason.toLowerCase()} » (${F.pct(top.n / tot, 0)}).
            Le critère de dégradation de la note ne joue qu'en complément des retards et des périodes probatoires.` : "Aucun prêt en Stage 2."; })(),
        table: { cols: ["Stage", "Motif", "Prêts", "Encours"], rows: I.reasons.map((r) => [r.stage, r.stage_reason, F.num(r.n), F.usd(r.ead)]) },
      }),
    });
    const scen = I.scenarios, central = scen.find((r) => r.scenario === "Central"), severe = scen.find((r) => r.scenario === "Sévère");
    panel(g5, {
      id: "p-scen", span: 6, title: `Provision selon le ${T("scenarios", "scénario économique")}`, sub: "Les trois scénarios et leur moyenne pondérée",
      render: () => ({
        legend: [{ name: `Provision pondérée retenue : ${F.usd(I.weighted_ecl)}`, color: "var(--ink)", type: "dash" }],
        draw: (el) => Charts.columns(el, {
          height: 270, bottom: 44, label: "Provision par scénario",
          rows: scen.map((r) => ({ ...r, label: r.scenario, value: r.ecl, color: SCEN[r.scenario] || "var(--s1)", sub: `poids ${F.pct(r.weight, 0)}` })),
          yFmt: (v) => F.usd(v), yTick: F.usdTick(Math.max(...scen.map((r) => r.ecl))), valueFmt: (r) => F.usd(r.value), ref: { value: I.weighted_ecl },
          tip: (r) => `<b>Scénario ${r.scenario.toLowerCase()}</b><div>Chômage : ${r.d_unemp > 0 ? "+" : ""}${F.num(r.d_unemp, 1)} point</div>
            <div>Prix immobiliers : ${r.hpi > 0 ? "+" : ""}${F.pct(r.hpi, 0)}</div><div>PD moyenne : ${F.pct(r.pd_mean, 2)}</div><div>Provision : ${F.usd(r.ecl)}</div>`,
        }),
        reading: central && severe ? `Dans le scénario sévère (chômage +${F.num(severe.d_unemp, 0)} points, prix immobiliers ${F.pct(severe.hpi, 0)}),
          la provision serait <strong>${F.num(ratio(severe.ecl, central.ecl), 1)} fois</strong> celle du scénario central. La moyenne pondérée
          (${F.usd(I.weighted_ecl)}) dépasse le central : une crise coûte plus qu'une embellie ne rapporte.` : "",
        table: { cols: ["Scénario", "Poids", "Chômage", "Prix immobiliers", "PD moyenne", "Provision"],
          rows: scen.map((r) => [r.scenario, F.pct(r.weight, 0), `${r.d_unemp > 0 ? "+" : ""}${F.num(r.d_unemp, 1)} pt`, `${r.hpi > 0 ? "+" : ""}${F.pct(r.hpi, 0)}`,
            F.pct(r.pd_mean, 2), F.usd(r.ecl, 2)]) },
        note: "Hypothèses illustratives sur 12 mois, pas des prévisions officielles.",
      }),
    });
    const lgd = I.lgd.slice().sort((a, b) => (a.cltv_band === "Tous") - (b.cltv_band === "Tous") || a.cltv_order - b.cltv_order);
    const lgdAll = lgd.find((r) => r.cltv_band === "Tous");
    panel(g5, {
      id: "p-lgd", span: 6, title: `${T("lgd", "LGD")} selon l'apport de l'emprunteur`, sub: `Par tranche de ${T("cltv", "CLTV")} à l'octroi (en %)`,
      render: () => ({
        legend: [{ name: "LGD", color: "var(--s1)", type: "dot" }, { name: "LGD de crise (2008-2011)", color: "var(--stage3)", type: "diamond" }],
        draw: (el) => Charts.dotsLog(el, {
          linear: true, height: 270, label: "LGD par tranche de CLTV", cats: lgd.map((r) => r.cltv_band.replace(/^(\d+) % ou moins$/, "≤\u00a0$1").replace(/^Plus de (\d+) %$/, ">\u00a0$1").replace(/ %$/, "")),
          series: [{ name: "LGD", color: "var(--s1)", values: lgd.map((r) => r.lgd) },
                   { name: "LGD de crise", color: "var(--stage3)", shape: "diamond", values: lgd.map((r) => r.lgd_downturn) }],
          yFmt: (v) => F.pct(v, 0), yTick: F.pctTick,
          tip: (k) => { const r = lgd[k]; return `<b>CLTV ${r.cltv_band}</b><div>LGD : ${F.pct(r.lgd, 1)}</div><div>LGD de crise : ${F.pct(r.lgd_downturn, 1)}</div>
            <div>Guérisons : ${F.pct(r.cure_rate, 0)} des défauts</div><div>${F.num(r.n_resolved)} défauts résolus</div>`; },
        }),
        reading: lgdAll ? `<strong>${F.pct(lgdAll.cure_rate, 0)}</strong> des défauts ${T("guerison", "guérissent")} sans perte : la LGD n'est que de
          <strong>${F.pct(lgdAll.lgd, 1)}</strong>, et ${F.pct(lgdAll.lgd_downturn, 1)} en crise. Au-delà de 80 % de CLTV, une assurance hypothécaire
          couvre une partie de la perte : la LGD n'augmente plus avec la CLTV.` : "",
        table: { cols: ["CLTV", "Défauts résolus", "Guérisons", "Sévérité", "LGD", "LGD de crise"],
          rows: lgd.map((r) => [r.cltv_band, F.num(r.n_resolved), F.pct(r.cure_rate, 1), F.pct(r.severity, 1), F.pct(r.lgd, 1), F.pct(r.lgd_downturn, 1)]) },
        note: `${T("ead", "EAD")} = encours (facteur mesuré : ${F.num(I.ead_factor, 3)}). ${T("cpr", "Remboursements anticipés")} : ${F.pct(I.cpr, 1)} par an.`,
      }),
    });
    const migPeriods = [...new Set(I.migration.map((r) => r.period))];
    const grades = [1, 2, 3, 4, 5, 6, 7, 8].map((g) => `R${g}`);
    const migCols = [...grades, "Défaut", "Sorti"];
    panel(g5, {
      id: "p-mig", span: 12, title: `${T("migration", "Matrice de migration")} annuelle`, sub: "Lecture en ligne : la classe du prêt en janvier de l'année suivante",
      state: { per: migPeriods[0] },
      controls: seg("per", migPeriods.map((p) => ({ value: p, label: p })), migPeriods[0], "Période"),
      render: (s) => {
        const m = I.migration.filter((r) => r.period === s.per);
        const rows = grades.filter((g) => m.some((r) => r.from_grade === g));
        const val = (f, t) => m.find((r) => r.from_grade === f && r.to_state === t)?.share ?? 0;
        const dr = (I.drift || []).find((r) => r.period === s.per);
        return {
          draw: (el) => Charts.heat(el, {
            label: `Matrice de migration, ${s.per}`, rows, cols: migCols, cellH: 32,
            values: rows.map((f) => migCols.map((t) => val(f, t))), fmt: (v) => F.pct(v, v < 0.1 ? 1 : 0), minLabel: 0.005,
            highlight: (i, j) => rows[i] === migCols[j],
            tip: (i, j, v) => `<b>${rows[i]} → ${migCols[j]}</b><div>${F.pct(v, 1)} des prêts</div>`,
          }),
          reading: dr ? `Sur la période « ${s.per.toLowerCase()} », <strong>${F.pct(dr.same, 0)}</strong> des prêts suivis gardent leur classe,
            ${F.pct(dr.up, 0)} s'améliorent et <strong>${F.pct(dr.down, 0)}</strong> se dégradent (défaut compris).
            ${F.ok(dr.down_age) ? `${F.pct(dr.down_age, 0)} des dégradations hors défaut coïncident avec le vieillissement du prêt, dont le risque culmine entre 2 et 3 ans.` : ""}`
            : "Comparez la crise et la période calme : les dégradations y sont bien plus fréquentes.",
          table: { cols: ["De \\ vers", ...migCols], rows: rows.map((f) => [f, ...migCols.map((t) => F.pct(val(f, t), 1))]) },
          note: "Notes calculées avec la PD TTC. « Sorti » : remboursé ou plus observé. Points : moins de 0,5 %.",
        };
      },
    });

    /* ===== 6. Capital ===== */
    const g6 = section("capital", 6, "Le capital à immobiliser",
      `Au titre de Bâle (${T("irb", "approche IRB")}), les prêts sains représentent ${F.usd(C.rwa)} d'${T("rwa", "actifs pondérés")}, soit
       ${F.usd(C.capital_8pct)} de fonds propres minimum. Ils couvrent une perte exceptionnelle, au-delà de la perte attendue.`);
    panel(g6, {
      id: "p-capital", span: 7, title: "Perte attendue et perte exceptionnelle", sub: "Prêts sains, en dollars",
      render: () => ({
        draw: (el) => Charts.columns(el, {
          height: 270, label: "Provision, perte attendue réglementaire et fonds propres",
          rows: [{ label: "Provision IFRS 9", value: C.provision_performing, color: "var(--s1)" },
                 { label: "Perte attendue Bâle", value: C.el_regulatory, color: "var(--s3)" },
                 { label: "Fonds propres", value: C.capital_8pct, color: "var(--s4)" }],
          yFmt: (v) => F.usd(v), yTick: F.usdTick(Math.max(C.capital_8pct, C.el_regulatory, C.provision_performing)), valueFmt: (r) => F.usd(r.value), barW: 70,
          tip: (r) => `<b>${r.label}</b><div>${F.usd(r.value, 2)}</div>`,
        }),
        reading: `Les provisions couvrent la perte <em>attendue</em> ; les fonds propres, la perte <em>inattendue</em>, celle qui ne survient
          qu'une année sur mille. ${C.provision_performing >= C.el_regulatory
            ? "La provision comptable dépasse la perte attendue réglementaire : pas de déduction des fonds propres."
            : `La provision comptable est inférieure de ${F.usd(C.el_regulatory - C.provision_performing)} à l'${T("el", "EL réglementaire")} : cet écart serait déduit des fonds propres.`}`,
        table: { cols: ["Mesure", "Montant"], rows: [["Exposition saine", F.usd(C.ead_performing)], ["Provision IFRS 9 (prêts sains)", F.usd(C.provision_performing, 2)],
          ["Perte attendue réglementaire", F.usd(C.el_regulatory, 2)], ["Actifs pondérés (RWA)", F.usd(C.rwa)], ["Fonds propres à 8 %", F.usd(C.capital_8pct)]] },
      }),
    });
    panel(g6, {
      id: "p-rwa", span: 5, title: "Densité de RWA", sub: "Actifs pondérés rapportés à l'exposition",
      render: () => ({
        html: `<div class="stats" style="border-top:0;margin-top:0">
          <div class="stat"><div class="lab">${T("rwa", "RWA")}</div><div class="val">${F.usd(C.rwa)}</div><div class="sub">sur ${F.usd(C.ead_performing)} d'exposition</div></div>
          <div class="stat"><div class="lab">Densité</div><div class="val">${F.pct(C.density, 1)}</div><div class="sub">pondération moyenne</div></div></div>
          <div class="stats"><div class="stat"><div class="lab">Corrélation</div><div class="val">${F.num(C.rho, 2)}</div><div class="sub">valeur bâloise, immobilier</div></div>
          <div class="stat"><div class="lab">Planchers</div><div class="val">${F.pct(C.pd_floor, 2)}</div><div class="sub">PD ; LGD ${F.pct(C.lgd_floor, 0)}</div></div></div>`,
        reading: `Une densité de ${F.pct(C.density, 0)} est ${C.density > 0.3 ? "élevée" : "proche des usages"} pour de l'immobilier résidentiel
          (souvent 10 à 25 % en banque). Les paramètres sont prudents : PD de long terme marquée par 2008 et ${T("lgddt", "LGD de crise")}.`,
      }),
    });

    /* ===== 7. Simulateur ===== */
    if (D.simulator) {
      const g7 = section("simulateur", 7, "À vous de jouer : le simulateur",
        `Trois outils recalculent tout en direct dans votre navigateur, à partir des modèles du projet : la note d'un emprunteur,
         la provision IFRS 9 sous vos propres scénarios et règles, et le capital bâlois avec vos paramètres.`);
      window.Simulator(g7, D.simulator, D, { T, legend, tableHtml });
    }

    /* Méthode et pied de page */
    const repo = repoUrl();
    const doc = (path, label) => (repo ? `<a href="${repo}/blob/main/${path}" target="_blank" rel="noopener">${label}</a>` : label);
    $("#method").innerHTML = `
      <div><h3>Données</h3><p>Freddie Mac Single-Family Loan-Level Dataset : échantillons de 50 000 prêts par cohorte
        (${cohorts.join(", ")}), suivis mois par mois jusqu'en ${F.month(snap.snapshot_date)}. Indicateurs macroéconomiques de la FRED
        (Réserve fédérale de Saint-Louis). Seuls des agrégats sont publiés ici, conformément aux conditions d'utilisation.</p></div>
      <div><h3>Méthodes</h3><ul><li>Base DuckDB, contrôles de qualité et de cohérence en SQL.</li>
        <li>Défaut à 90 jours (article 178 du CRR), courbes de vintage, intervalles de Wilson.</li>
        <li>Notation : WoE, régression logistique, validation hors période (${doc("docs/model/pd_model_report.md", "rapport du modèle")}).</li>
        <li>IFRS 9 et Bâle : Vasicek, LGD avec guérisons, staging, ECL à maturité, IRB (${doc("docs/model/ecl_report.md", "rapport IFRS 9")}).</li></ul></div>
      <div><h3>Limites</h3><ul><li>Prêts immobiliers américains conformes uniquement.</li>
        <li>Pas de critère d'improbabilité de paiement ; moratoires Covid comptés en défaut.</li>
        <li>Scénarios illustratifs ; modèle satellite estimé sur une vingtaine d'années.</li>
        <li>LGD sans actualisation des recouvrements ni coûts internes.</li></ul></div>`;
    $("#footer").innerHTML = `<span>Données : Freddie Mac (SFLLD) et FRED. Calculs : Credit Risk Analytics Engine. Mis à jour le ${F.date(meta.generated)}.</span>
      ${repo ? `<a href="${repo}" target="_blank" rel="noopener">Voir le code sur GitHub</a>` : ""}`;
    const rl = $("#repo-link"); if (repo) rl.href = repo; else rl.hidden = true;
  }

  /* Lien vers le dépôt, déduit de l'adresse GitHub Pages (utilisateur.github.io/projet). */
  function repoUrl() {
    const h = location.hostname, parts = location.pathname.split("/").filter(Boolean);
    if (h.endsWith(".github.io") && parts.length) return `https://github.com/${h.split(".")[0]}/${parts[0]}`;
    return null;
  }

  /* Suivi de l'étape visible dans la barre de navigation */
  function trackSections() {
    const links = [...document.querySelectorAll(".chain-list a")];
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        links.forEach((a) => a.setAttribute("aria-current", String(a.getAttribute("href") === `#${e.target.id}`)));
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    document.querySelectorAll(".section").forEach((s) => obs.observe(s));
  }

  /* Étapes de la visite guidée */
  function tourSteps(D) {
    return [
      { title: "Bienvenue", text: `Ce tableau de bord suit ${F.num(D.meta.n_loans)} crédits immobiliers américains, de l'octroi jusqu'à la provision
        comptable et au capital. La visite dure une minute ; vous pourrez la relancer à tout moment.` },
      { target: "#kpis", title: "L'essentiel en quatre chiffres", text: "L'encours encore en vie, la part des prêts qui ont fait défaut, la provision à constituer et les fonds propres à immobiliser." },
      { target: "#hero .info", title: "Les termes techniques", text: "Chaque terme technique est suivi d'un petit <b>i</b>. Survolez-le, ou touchez-le sur mobile, pour une définition en langage courant." },
      { target: "#chain", title: "Le fil de l'analyse", text: "Six étapes, du portefeuille au capital, chacune avec son chiffre clé. Cliquez sur une étape pour y aller directement." },
      { target: "#p-vintage .chart", title: "Des graphiques à explorer", text: "Survolez une courbe ou une barre pour lire les valeurs exactes." },
      { target: "#p-vintage .reading", title: "Une lecture pour chaque graphique", text: "Sous chaque graphique, une phrase dit ce qu'il faut en retenir. Les chiffres sont recalculés à chaque mise à jour des données." },
      { target: "#p-segments .controls", title: "Changer d'angle", text: "Certains graphiques proposent plusieurs vues : score FICO, apport, endettement, cohorte…" },
      { target: "#p-vintage .data-toggle", title: "Les données derrière le graphique", text: "Affichez le tableau de valeurs de chaque graphique, par exemple pour vérifier un chiffre." },
      { target: "#p-stages", title: "La provision IFRS 9", text: "Le cœur du métier : combien la banque met de côté, et pourquoi une petite part des prêts concentre une grande part de la provision." },
      { target: "#sim-score .sim-controls", title: "Le simulateur", text: "Tout en bas, trois outils à manipuler : notez un emprunteur, testez une crise sur la provision, changez les paramètres de Bâle. Chaque curseur recalcule le résultat instantanément." },
      { target: "#tour-restart", title: "C'est à vous", text: "Ce bouton relance la visite. Bonne exploration\u00a0!", pad: 4 },
    ];
  }

  async function init() {
    setupGlossary();
    try {
      const res = await fetch("data/dashboard.json", { cache: "no-cache" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const D = await res.json();
      build(D);
      trackSections();
      $("#tour-restart").addEventListener("click", () => Tour.start(tourSteps(D)));
      if (Tour.shouldAutoStart()) setTimeout(() => Tour.start(tourSteps(D)), 600);
    } catch (e) {
      $("#hero-title").textContent = "Les données du tableau de bord sont introuvables.";
      $("#hero-sub").innerHTML = "Lancez <code>python src/export_dashboard.py</code> pour créer <code>docs/data/dashboard.json</code>, puis rechargez la page. " +
        "En local, ouvrez la page avec <code>python -m http.server</code> depuis le dossier <code>docs</code>.";
      console.error(e);
    }
  }
  document.addEventListener("DOMContentLoaded", init);
})();
