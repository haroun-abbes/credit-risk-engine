/* Petits graphiques SVG faits main : courbes, barres, colonnes, cartes de chaleur, points.
   Aucune dépendance. Chaque graphique se redessine quand sa largeur change. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const nf = (d) => new Intl.NumberFormat("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

  /* --- Formats (jamais de NaN affiché : « – » à la place) ------------------------------ */
  const F = {
    ok: (v) => v !== null && v !== undefined && Number.isFinite(v),
    num(v, d = 0) { return F.ok(v) ? nf(d).format(v) : "–"; },
    pct(v, d = 1) {
      if (!F.ok(v)) return "–";
      const p = v * 100, min = Math.pow(10, -d);
      if (p > 0 && p < min) return `<\u00a0${nf(d).format(min)}\u202f%`;
      return `${nf(d).format(p)}\u202f%`;
    },
    pctAuto(v) {          // décimales adaptées : 0,06 % / 1,4 % / 29 %
      if (!F.ok(v)) return "–";
      const p = Math.abs(v * 100);
      return F.pct(v, p < 1 ? 2 : p < 10 ? 1 : 0);
    },
    usd(v, d) {           // montant en dollars -> « 21,7 M$ » ou « 2,9 Md$ »
      if (!F.ok(v)) return "–";
      if (Math.abs(v) >= 1e9) return `${nf(d ?? 1).format(v / 1e9)}\u00a0Md$`;
      if (Math.abs(v) >= 1e6) return `${nf(d ?? 1).format(v / 1e6)}\u00a0M$`;
      return `${nf(0).format(v)}\u00a0$`;
    },
    musd(m, d) { return F.usd(F.ok(m) ? m * 1e6 : m, d); },
    times(v, d = 1) { return F.ok(v) ? `×\u00a0${nf(d).format(v)}` : "–"; },
    /* Graduations : nombre de décimales déduit du pas, jamais « < 1 % » ni doublon */
    dec(step) { return F.ok(step) && step > 0 ? Math.max(0, Math.ceil(-Math.log10(step) - 1e-9)) : 0; },
    pctTick(v, step) { return v === 0 ? "0" : `${nf(F.dec(step * 100)).format(v * 100)}\u202f%`; },
    usdTick(max) {      // unité commune à tout l'axe, choisie d'après la valeur maximale
      const [div, unit] = max >= 1e9 ? [1e9, "Md$"] : max >= 1e6 ? [1e6, "M$"] : [1e3, "k$"];
      return (v, step) => (v === 0 ? "0" : `${nf(F.dec(step / div)).format(v / div)}\u00a0${unit}`);
    },
    month(iso) {
      const t = new Date(iso + "T00:00:00Z");
      return t.toLocaleDateString("fr-FR", { month: "long", year: "numeric", timeZone: "UTC" });
    },
    monthShort(iso) {
      const t = new Date(iso + "T00:00:00Z");
      return t.toLocaleDateString("fr-FR", { month: "short", year: "numeric", timeZone: "UTC" });
    },
    date(iso) {
      const t = new Date(iso + "T00:00:00Z");
      const s = t.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
      return s.replace(/^1 /, "1er ");
    },
  };

  /* --- Outils SVG ----------------------------------------------------------------------- */
  function el(tag, attrs = {}, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null) continue;
      if (k === "text") n.textContent = v; else n.setAttribute(k, v);
    }
    if (parent) parent.appendChild(n);
    return n;
  }
  function niceTicks(min, max, count = 5) {
    if (!(max > min)) return [min];
    const span = max - min, step0 = span / count, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const err = step0 / mag;
    const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
    const out = [];
    for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toFixed(12));
    return out;
  }
  function niceMax(max, count = 5) { const t = niceTicks(0, max, count); return t[t.length - 1] < max ? max : t[t.length - 1]; }
  function textWidth(s, size = 12) { return String(s).length * size * 0.56; }
  function fit(s, width, size = 12) {          // raccourcit un libellé trop long (texte complet dans l'infobulle)
    s = String(s); const max = Math.floor(width / (size * 0.56) + 0.01);
    return s.length <= max ? s : s.slice(0, Math.max(1, max - 1)).trimEnd() + "…";
  }
  function wrap2(s, width, size = 12) {        // coupe un libellé en deux lignes au plus
    s = String(s); if (textWidth(s, size) <= width) return [s];
    const words = s.split(" "); let best = [s];
    for (let k = 1; k < words.length; k++) {
      const a = words.slice(0, k).join(" "), b = words.slice(k).join(" ");
      if (textWidth(a, size) <= width && textWidth(b, size) <= width) return [a, b];
      best = [a, b];
    }
    return best.map((x) => fit(x, width, size));
  }
  function catLabel(svg, x, y, s, width, cls = "lbl") {
    const lines = wrap2(s, width);
    lines.forEach((l, k) => el("text", { class: cls, x, y: y + k * 14, "text-anchor": "middle", text: l }, svg));
    return lines.length;
  }
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  function hexToRgb(h) {
    h = h.replace("#", ""); if (h.length === 3) h = h.split("").map((c) => c + c).join("");
    const n = parseInt(h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function mix(a, b, t) {
    const A = hexToRgb(a), B = hexToRgb(b);
    return `rgb(${A.map((x, i) => Math.round(x + (B[i] - x) * t)).join(",")})`;
  }

  /* --- Infobulle partagée ------------------------------------------------------------------ */
  const tip = () => document.getElementById("tip");
  function showTip(html, x, y) {
    const t = tip(); t.innerHTML = html; t.hidden = false;
    const r = t.getBoundingClientRect(), pad = 14;
    let left = x + pad, top = y + pad;
    if (left + r.width > window.innerWidth - 8) left = x - r.width - pad;
    if (top + r.height > window.innerHeight - 8) top = y - r.height - pad;
    t.style.left = `${Math.max(8, left)}px`; t.style.top = `${Math.max(8, top)}px`;
  }
  function hideTip() { const t = tip(); if (t) t.hidden = true; }
  const sw = (c) => `<span class="sw" style="background:${c}"></span>`;
  function bindTip(node, html) {
    node.classList.add("mark-hover");
    node.addEventListener("pointermove", (e) => showTip(typeof html === "function" ? html() : html, e.clientX, e.clientY));
    node.addEventListener("pointerleave", hideTip);
  }

  /* --- Gestion du redimensionnement -------------------------------------------------------- */
  const registry = new Set();
  function mount(container, draw) {
    const entry = { container, draw, width: 0 };
    const render = () => {
      const w = Math.floor(container.clientWidth);
      if (!w || w === entry.width) return;
      entry.width = w; container.innerHTML = ""; draw(w);
    };
    entry.render = () => { entry.width = 0; render(); };
    registry.add(entry);
    new ResizeObserver(render).observe(container);
    render();
  }
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => registry.forEach((e) => e.render()));

  /* --- Courbes ------------------------------------------------------------------------------------ */
  function line(container, o) {
    mount(container, (W) => {
      const H = o.height || 300;
      const all = o.series.flatMap((s) => s.points);
      const xs = all.map((p) => p.x), ys = all.map((p) => p.y);
      const xMin = o.xMin ?? Math.min(...xs), xMax = o.xMax ?? Math.max(...xs);
      const yMax = o.yMax ?? niceMax(Math.max(...ys) * 1.05);
      const yT = niceTicks(0, yMax, H < 220 ? 3 : 5);
      const yStep = yT.length > 1 ? yT[1] - yT[0] : yMax;
      const yTick = (t) => (o.yTick ? o.yTick(t, yStep) : o.yFmt(t));
      const left = Math.max(...yT.map((t) => textWidth(yTick(t)))) + 14, right = 14, top = 10, bottom = 30;
      const iw = W - left - right, ih = H - top - bottom;
      const X = (v) => left + ((v - xMin) / (xMax - xMin || 1)) * iw;
      const Y = (v) => top + ih - (v / yMax) * ih;
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": o.label || "" }, container);
      const g = el("g", { class: "ax" }, svg);
      yT.forEach((t) => {
        el("line", { class: "grid-line", x1: left, x2: W - right, y1: Y(t), y2: Y(t) }, g);
        el("text", { x: left - 8, y: Y(t) + 4, "text-anchor": "end", text: yTick(t) }, g);
      });
      const xT = o.xTicks ? o.xTicks(xMin, xMax, iw) : niceTicks(xMin, xMax, Math.max(2, Math.floor(iw / 90)));
      xT.forEach((t) => el("text", { x: X(t), y: H - 8, "text-anchor": "middle", text: o.xFmt(t) }, g));
      el("line", { class: "domain", x1: left, x2: W - right, y1: Y(0), y2: Y(0) }, g);
      if (o.xLabel) el("text", { x: W - right, y: H - 8, "text-anchor": "end", class: "lbl-muted", text: "" }, g);

      (o.bands || []).forEach((b) => {
        el("rect", { x: X(b.from), y: top, width: Math.max(0, X(b.to) - X(b.from)), height: ih,
                     style: "fill:var(--surface-2)" }, svg);
        el("text", { x: X(b.from) + 6, y: top + 14, class: "lbl-muted", text: b.label }, svg);
      });
      o.series.forEach((s) => {
        const pts = s.points.filter((p) => F.ok(p.y));
        if (!pts.length) return;
        const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join("");
        el("path", { d, style: `fill:none;stroke:${s.color};stroke-width:${s.width || 2};stroke-linejoin:round;stroke-linecap:round`,
                     "stroke-dasharray": s.dash ? "6 4" : null }, svg);
        if (s.markers) pts.forEach((p) => el("circle", { cx: X(p.x), cy: Y(p.y), r: 3.5,
          style: `fill:${s.color};stroke:var(--surface);stroke-width:1.5` }, svg));
        if (s.endLabel) {
          const p = pts[pts.length - 1];
          el("text", { x: Math.min(X(p.x) + 6, W - 2), y: Y(p.y) + 4, class: "lbl-strong",
                       "text-anchor": X(p.x) + 40 > W ? "end" : "start", text: s.endLabel }, svg);
        }
      });
      (iw < 420 ? [] : o.annotations || []).forEach((a) => {   // pas d'annotation sur petit écran
        const ax = X(a.x), ay = Y(a.y), toLeft = ax > left + iw * 0.6;
        el("text", { x: toLeft ? ax - 10 : ax + 10, y: ay + 4, "text-anchor": toLeft ? "end" : "start",
                     class: "lbl-muted", text: a.text }, svg);
      });

      // Réticule + infobulle
      const cross = el("line", { class: "cross", y1: top, y2: top + ih, visibility: "hidden" }, svg);
      const dots = o.series.map((s) => el("circle", { r: 4.5, visibility: "hidden",
        style: `fill:${s.color};stroke:var(--surface);stroke-width:2` }, svg));
      const xsU = [...new Set(all.map((p) => p.x))].sort((a, b) => a - b);
      const hit = el("rect", { class: "hit", x: left, y: top, width: iw, height: ih }, svg);
      const move = (e) => {
        const r = svg.getBoundingClientRect(), mx = (e.clientX - r.left) * (W / r.width);
        const xv = xMin + ((mx - left) / iw) * (xMax - xMin);
        let best = xsU[0]; for (const v of xsU) if (Math.abs(v - xv) < Math.abs(best - xv)) best = v;
        cross.setAttribute("x1", X(best)); cross.setAttribute("x2", X(best)); cross.setAttribute("visibility", "visible");
        let rows = "";
        o.series.forEach((s, i) => {
          const p = s.points.find((q) => q.x === best);
          if (p && F.ok(p.y)) {
            dots[i].setAttribute("cx", X(p.x)); dots[i].setAttribute("cy", Y(p.y)); dots[i].setAttribute("visibility", "visible");
            rows += `<div class="row">${sw(s.color)}${s.name} : <b>${o.yFmt(p.y, true)}</b></div>`;
          } else dots[i].setAttribute("visibility", "hidden");
        });
        showTip(`<b>${o.tipTitle ? o.tipTitle(best) : o.xFmt(best)}</b>${rows}`, e.clientX, e.clientY);
      };
      hit.addEventListener("pointermove", move);
      hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("visibility", "hidden");
        dots.forEach((d) => d.setAttribute("visibility", "hidden")); });
    });
  }

  /* --- Barres horizontales (avec intervalle de confiance facultatif) -------------------------- */
  function barH(container, o) {
    mount(container, (W) => {
      const rows = o.rows, need = Math.max(...rows.map((r) => textWidth(r.label, 12.5))) + 12;
      const stacked = need > W * 0.48 && W < 560;          // petit écran : libellé au-dessus de la barre
      const rowH = stacked ? 44 : o.rowH || 30;
      const labelW = stacked ? 0 : Math.min(W * 0.48, need);
      const valMax = Math.max(...rows.map((r) => Math.max(r.value, r.hi ?? 0)));
      const xMax = o.xMax ?? niceMax(valMax * 1.02, 4);
      const valW = Math.max(...rows.map((r) => textWidth(o.valueFmt(r), 12.5))) + 10;
      const top = 4, H = top + rows.length * rowH + 22;
      const iw = W - labelW - valW - 6;
      const X = (v) => labelW + (v / xMax) * iw;
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": o.label || "" }, container);
      const ticks = niceTicks(0, xMax, Math.max(2, Math.floor(iw / 80)));
      const xStep = ticks.length > 1 ? ticks[1] - ticks[0] : xMax;
      ticks.forEach((t) => {
        el("line", { class: "grid-line", x1: X(t), x2: X(t), y1: top, y2: H - 20 }, svg);
        el("text", { class: "lbl-muted", x: X(t), y: H - 6, "text-anchor": "middle", text: o.xTick ? o.xTick(t, xStep) : o.xFmt(t) }, svg);
      });
      rows.forEach((r, i) => {
        const y = top + i * rowH, cy = stacked ? y + 30 : y + rowH / 2, bh = Math.min(16, (stacked ? 30 : rowH) - 10);
        if (stacked) el("text", { class: "lbl", x: 0, y: y + 13, text: fit(r.label, W - 4, 12.5) }, svg);
        else el("text", { class: r.strong ? "lbl-strong" : "lbl", x: labelW - 10, y: cy + 4, "text-anchor": "end", text: fit(r.label, labelW - 12, 12.5) }, svg);
        const w = Math.max(1.5, X(r.value) - labelW);
        const bar = el("rect", { x: labelW, y: cy - bh / 2, width: w, height: bh, rx: 3,
                                 style: `fill:${r.color || o.color || "var(--s1)"};opacity:${r.muted ? 0.45 : 1}` }, svg);
        let end = X(r.value);
        if (F.ok(r.lo) && F.ok(r.hi)) {
          el("line", { x1: X(r.lo), x2: X(r.hi), y1: cy, y2: cy, style: "stroke:var(--ink);stroke-width:1.2" }, svg);
          [r.lo, r.hi].forEach((v) => el("line", { x1: X(v), x2: X(v), y1: cy - 4, y2: cy + 4, style: "stroke:var(--ink);stroke-width:1.2" }, svg));
          end = Math.max(end, X(r.hi));
        }
        el("text", { class: "lbl-strong", x: end + 6, y: cy + 4, text: o.valueFmt(r) }, svg);
        const hit = el("rect", { x: 0, y, width: W, height: rowH, style: "fill:transparent" }, svg);
        if (o.tip) bindTip(hit, () => o.tip(r));
        bar.style.pointerEvents = "none";
      });
    });
  }

  /* --- Colonnes ------------------------------------------------------------------------------------- */
  function columns(container, o) {
    mount(container, (W) => {
      const rows = o.rows, slot0 = (W - 60) / rows.length;
      const extra = rows.some((r) => wrap2(r.label, slot0 - 6).length > 1) ? 14 : 0;
      const H = (o.height || 260) + extra;
      const yMax = o.yMax ?? niceMax(Math.max(...rows.map((r) => Math.max(r.value, r.hi ?? 0)), o.ref?.value ?? 0) * 1.18, 4);
      const yT = niceTicks(0, yMax, 4), yStep = yT.length > 1 ? yT[1] - yT[0] : yMax;
      const yTick = (t) => (o.yTick ? o.yTick(t, yStep) : o.yFmt(t));
      const left = Math.max(...yT.map((t) => textWidth(yTick(t)))) + 14, right = 8, top = 8, bottom = (o.bottom || 30) + extra;
      const iw = W - left - right, ih = H - top - bottom;
      const Y = (v) => top + ih - (v / yMax) * ih;
      const slot = iw / rows.length, bw = Math.min(o.barW || 64, slot * 0.62);
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": o.label || "" }, container);
      yT.forEach((t) => {
        el("line", { class: "grid-line", x1: left, x2: W - right, y1: Y(t), y2: Y(t) }, svg);
        el("text", { class: "lbl", x: left - 8, y: Y(t) + 4, "text-anchor": "end", text: yTick(t) }, svg);
      });
      if (o.ref) {
        el("line", { x1: left, x2: W - right, y1: Y(o.ref.value), y2: Y(o.ref.value),
                     style: "stroke:var(--ink);stroke-width:1.3;stroke-dasharray:5 4" }, svg);
      }
      rows.forEach((r, i) => {
        const cx = left + slot * (i + 0.5), y = Y(r.value);
        const bar = el("path", { d: `M${cx - bw / 2},${Y(0)}V${y + 3}q0,-3 3,-3H${cx + bw / 2 - 3}q3,0 3,3V${Y(0)}Z`,
                                 style: `fill:${r.color || o.color || "var(--s1)"}` }, svg);
        let labY = y;
        if (F.ok(r.lo) && F.ok(r.hi)) {
          el("line", { x1: cx, x2: cx, y1: Y(r.lo), y2: Y(r.hi), style: "stroke:var(--ink);stroke-width:1.2" }, svg);
          [r.lo, r.hi].forEach((v) => el("line", { x1: cx - 4, x2: cx + 4, y1: Y(v), y2: Y(v), style: "stroke:var(--ink);stroke-width:1.2" }, svg));
          labY = Math.min(labY, Y(r.hi));
        }
        el("text", { class: "lbl-strong", x: cx, y: labY - 7, "text-anchor": "middle", text: o.valueFmt(r) }, svg);
        const nl = catLabel(svg, cx, H - bottom + 18, r.label, slot - 6);
        if (r.sub) el("text", { class: "lbl-muted", x: cx, y: H - bottom + 19 + nl * 14, "text-anchor": "middle", text: r.sub }, svg);
        if (o.tip) bindTip(bar, () => o.tip(r));
      });
      el("line", { class: "grid-line", x1: left, x2: W - right, y1: Y(0), y2: Y(0), style: "stroke:var(--line-2)" }, svg);
    });
  }

  /* --- Carte de chaleur (matrices) ------------------------------------------------------------------- */
  function heat(container, o) {
    mount(container, (W) => {
      const rl = Math.max(...o.rows.map((r) => textWidth(r, 12.5))) + 14;
      const minCell = Math.max(46, ...o.cols.map((c) => textWidth(c, 12) + 8));
      const cellW = Math.max(minCell, (W - rl) / o.cols.length), cellH = o.cellH || 34, top = 30;
      const width = rl + cellW * o.cols.length, H = top + cellH * o.rows.length + 4;
      container.style.overflowX = width > W + 1 ? "auto" : "";
      const c0 = cssVar("--heat-0") || "#F4F8FD", c1 = cssVar("--heat-1") || "#0D366B";
      const svg = el("svg", { viewBox: `0 0 ${width} ${H}`, height: width > W ? H : H * (W / width), role: "img", "aria-label": o.label || "" }, container);
      if (width > W + 1) { svg.style.width = `${width}px`; svg.style.maxWidth = "none"; }
      o.cols.forEach((c, j) => el("text", { class: "lbl", x: rl + cellW * (j + 0.5), y: 18, "text-anchor": "middle",
                                             text: c }, svg));
      o.rows.forEach((r, i) => {
        el("text", { class: "lbl", x: rl - 10, y: top + cellH * (i + 0.5) + 4, "text-anchor": "end", text: r }, svg);
        o.cols.forEach((c, j) => {
          const v = o.values[i][j];
          const has = F.ok(v) && v > 0, t = has ? Math.sqrt(Math.min(1, v)) : 0;
          const rect = el("rect", { x: rl + cellW * j + 1, y: top + cellH * i + 1, width: cellW - 2, height: cellH - 2, rx: 3,
                                    style: `fill:${has ? mix(c0, c1, t) : "var(--surface-2)"}` }, svg);
          if (has && o.highlight && o.highlight(i, j)) rect.setAttribute("style", rect.getAttribute("style") + ";stroke:var(--ink);stroke-width:1.2");
          if (has && v >= (o.minLabel ?? 0.005)) {
            el("text", { class: "cell-text", x: rl + cellW * (j + 0.5), y: top + cellH * (i + 0.5) + 4, "text-anchor": "middle",
                         style: `fill:${t > 0.62 ? "#fff" : "var(--ink)"}`, text: o.fmt(v) }, svg);
          } else if (has) {
            el("text", { class: "cell-text", x: rl + cellW * (j + 0.5), y: top + cellH * (i + 0.5) + 4, "text-anchor": "middle",
                         style: "fill:var(--muted)", text: "·" }, svg);
          }
          if (has) bindTip(rect, () => o.tip(i, j, v));
        });
      });
    });
  }

  /* --- Points sur échelle logarithmique (échelle de notation) ------------------------------------- */
  function dotsLog(container, o) {
    mount(container, (W) => {
      const H = o.height || 280, cats = o.cats;
      const vals = o.series.flatMap((s) => s.values).filter((v) => F.ok(v) && v > 0);
      let lo, hi, ticks = [];
      if (o.linear) { hi = niceMax(Math.max(...vals) * 1.1, 4); lo = 0; ticks = niceTicks(0, hi, 4); }
      else {
        lo = Math.pow(10, Math.floor(Math.log10(Math.min(...vals)))); hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...vals))));
        for (let v = lo; v <= hi * 1.0001; v *= 10) ticks.push(v);
      }
      const tStep = o.linear && ticks.length > 1 ? ticks[1] - ticks[0] : null;
      const yTick = (t) => (o.linear && o.yTick ? o.yTick(t, tStep) : o.yFmt(t));
      const slotG = (W - 60) / cats.length, extra = cats.some((c) => wrap2(c, slotG - 4).length > 1) ? 14 : 0;
      const left = Math.max(...ticks.map((t) => textWidth(yTick(t)))) + 14, right = 10, top = 10, bottom = 30 + extra;
      const iw = W - left - right, ih = H - top - bottom, slot = iw / cats.length;
      const Y = o.linear ? (v) => top + ih - (v / hi) * ih
                         : (v) => top + ih - ((Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * ih;
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": o.label || "" }, container);
      ticks.forEach((t) => {
        el("line", { class: "grid-line", x1: left, x2: W - right, y1: Y(t), y2: Y(t) }, svg);
        el("text", { class: "lbl", x: left - 8, y: Y(t) + 4, "text-anchor": "end", text: yTick(t) }, svg);
      });
      cats.forEach((c, i) => {
        const cx0 = left + slot * (i + 0.5), cx = cx0;
        catLabel(svg, cx, H - bottom + 18, c, slot - 4);
        const v = o.series.map((s) => s.values[i]).filter((x) => F.ok(x) && x > 0);
        if (v.length === 2) el("line", { x1: cx, x2: cx, y1: Y(v[0]), y2: Y(v[1]), style: "stroke:var(--line-2);stroke-width:2" }, svg);
        const ys = o.series.map((s) => (F.ok(s.values[i]) && s.values[i] > 0 ? Y(s.values[i]) : null));
        const close = ys.length === 2 && ys[0] !== null && ys[1] !== null && Math.abs(ys[0] - ys[1]) < 11;
        o.series.forEach((s, k) => {
          const x = s.values[i];
          if (!(F.ok(x) && x > 0)) return;
          const cx = close ? cx0 + (k ? 7 : -7) : cx0;
          const m = s.shape === "diamond"
            ? el("rect", { x: cx - 5, y: Y(x) - 5, width: 10, height: 10, transform: `rotate(45 ${cx} ${Y(x)})`,
                           style: `fill:var(--surface);stroke:${s.color};stroke-width:2` }, svg)
            : el("circle", { cx, cy: Y(x), r: 5.5, style: `fill:${s.color};stroke:var(--surface);stroke-width:1.5` }, svg);
          bindTip(m, () => o.tip(i));
        });
        const hit = el("rect", { x: cx - slot / 2, y: top, width: slot, height: ih, style: "fill:transparent" }, svg);
        bindTip(hit, () => o.tip(i));
        svg.insertBefore(hit, svg.firstChild.nextSibling);
      });
    });
  }

  /* --- Barres empilées à 100 % ---------------------------------------------------------------------- */
  function stack100(container, o) {
    mount(container, (W) => {
      const rowH = 46, labelW = Math.max(...o.bars.map((b) => textWidth(b.label, 12.5))) + 14;
      const H = o.bars.length * rowH + 4, iw = W - labelW;
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": o.label || "" }, container);
      o.bars.forEach((b, i) => {
        const y = i * rowH + 6, h = rowH - 16;
        el("text", { class: "lbl-strong", x: labelW - 10, y: y + h / 2 + 4, "text-anchor": "end", text: b.label }, svg);
        const tot = b.parts.reduce((a, p) => a + p.value, 0) || 1;
        let x = labelW;
        b.parts.forEach((p, j) => {
          const w = (p.value / tot) * iw;
          if (w <= 0) return;
          const r = el("rect", { x: x + (j ? 1 : 0), y, width: Math.max(0.5, w - (j ? 1 : 0)), height: h, rx: 3, style: `fill:${p.color}` }, svg);
          const label = o.fmt(p.value / tot);
          if (w > textWidth(label, 12) + 12)
            el("text", { class: "cell-text", x: x + w / 2, y: y + h / 2 + 4, "text-anchor": "middle",
                         style: "fill:#fff;font-weight:600", text: label }, svg);
          bindTip(r, () => o.tip(b, p, p.value / tot));
          x += w;
        });
      });
    });
  }

  /* --- Barres divergentes autour de zéro (contributions) ------------------------------------- */
  function divergeH(container, o) {
    mount(container, (W) => {
      const rows = o.rows, need = Math.max(...rows.map((r) => textWidth(r.label, 12.5))) + 12;
      const stacked = need > W * 0.4;
      const rowH = stacked ? 44 : 30, labelW = stacked ? 0 : need, top = 4;
      const H = top + rows.length * rowH + 4;
      const maxAbs = Math.max(1e-9, ...rows.map((r) => Math.abs(r.value)));
      const valW = 64, iw = W - labelW - 2 * valW, mid = labelW + valW + iw / 2;
      const X = (v) => mid + (v / maxAbs) * (iw / 2);
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": o.label || "" }, container);
      el("line", { x1: mid, x2: mid, y1: 0, y2: H, style: "stroke:var(--line-2);stroke-width:1" }, svg);
      rows.forEach((r, i) => {
        const y = top + i * rowH, cy = stacked ? y + 30 : y + rowH / 2, bh = 14;
        if (stacked) el("text", { class: "lbl", x: 0, y: y + 13, text: fit(r.label, W - 4, 12.5) }, svg);
        else el("text", { class: "lbl", x: labelW - 10, y: cy + 4, "text-anchor": "end", text: fit(r.label, labelW - 12, 12.5) }, svg);
        const x0 = Math.min(X(0), X(r.value)), w = Math.max(1.5, Math.abs(X(r.value) - X(0)));
        const bar = el("rect", { x: x0, y: cy - bh / 2, width: w, height: bh, rx: 3,
                                 style: `fill:${r.value >= 0 ? o.posColor : o.negColor}` }, svg);
        el("text", { class: "lbl-strong", x: r.value >= 0 ? X(r.value) + 6 : X(r.value) - 6, y: cy + 4,
                     "text-anchor": r.value >= 0 ? "start" : "end", text: o.fmt(r.value) }, svg);
        if (o.tip) bindTip(bar, () => o.tip(r));
      });
    });
  }

  window.Charts = { F, line, barH, columns, heat, dotsLog, stack100, divergeH, fit, showTip, hideTip, rerender: () => registry.forEach((e) => e.render()) };
})();
