/* Visite guidée : un projecteur sur l'élément expliqué, une bulle fléchée à côté. */
(function () {
  const KEY = "cre-tour-done-v1";
  const $ = (id) => document.getElementById(id);
  let steps = [], i = 0, active = false, lastFocus = null;

  const store = {
    get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } },
    set() { try { localStorage.setItem(KEY, "1"); } catch (e) { /* navigation privée : on ignore */ } },
  };

  function place() {
    if (!active) return;
    const s = steps[i], spot = $("tour-spot"), card = $("tour-card"), arrow = $("tour-arrow");
    const target = s.target ? document.querySelector(s.target) : null;
    const vw = window.innerWidth, vh = window.innerHeight, m = 12;
    const cw = card.offsetWidth, ch = card.offsetHeight;
    if (!target) {
      spot.classList.add("is-center");
      Object.assign(spot.style, { left: `${vw / 2}px`, top: `${vh / 2}px`, width: "0px", height: "0px" });
      Object.assign(card.style, { left: `${(vw - cw) / 2}px`, top: `${Math.max(16, (vh - ch) / 2)}px` });
      arrow.hidden = true;
      return;
    }
    spot.classList.remove("is-center");
    const r = target.getBoundingClientRect(), pad = s.pad ?? 8;
    const top = Math.max(4, r.top - pad), bottom = Math.min(vh - 4, r.bottom + pad);
    const left = Math.max(4, r.left - pad), right = Math.min(vw - 4, r.right + pad);
    Object.assign(spot.style, { left: `${left}px`, top: `${top}px`, width: `${right - left}px`, height: `${bottom - top}px` });

    // Bulle : sous la cible si la place le permet, sinon au-dessus, sinon à l'intérieur en bas.
    let cy, side;
    if (bottom + m + ch < vh - 8) { cy = bottom + m; side = "below"; }
    else if (top - m - ch > 8) { cy = top - m - ch; side = "above"; }
    else { cy = vh - ch - 16; side = "inside"; }
    const tx = Math.min(Math.max((left + right) / 2, 24), vw - 24);
    const cx = Math.min(Math.max(tx - cw / 2, 12), vw - cw - 12);
    Object.assign(card.style, { left: `${cx}px`, top: `${cy}px` });
    arrow.hidden = side === "inside";
    if (side !== "inside") {
      const ax = Math.min(Math.max(tx - cx - 7, 18), cw - 32);
      Object.assign(arrow.style, { left: `${ax}px`, top: side === "below" ? "-7px" : `${ch - 7}px` });
    }
  }

  function show(n) {
    i = Math.max(0, Math.min(steps.length - 1, n));
    const s = steps[i];
    $("tour-step").textContent = `${i + 1} / ${steps.length}`;
    $("tour-title").textContent = s.title;
    $("tour-text").innerHTML = s.text;
    $("tour-prev").hidden = i === 0;
    $("tour-next").textContent = i === steps.length - 1 ? "Terminer" : "Suivant";
    const target = s.target ? document.querySelector(s.target) : null;
    if (target) {
      const r = target.getBoundingClientRect();
      const tall = r.height > window.innerHeight * 0.55;
      // Défilement immédiat : le projecteur se place sur la position finale.
      target.scrollIntoView({ block: tall ? "start" : "center", behavior: "instant" });
      if (tall) window.scrollBy({ top: -90, behavior: "instant" });
    }
    requestAnimationFrame(() => requestAnimationFrame(place));
    $("tour-next").focus({ preventScroll: true });
  }

  function end() {
    active = false; $("tour").hidden = true; store.set();
    document.removeEventListener("keydown", onKey);
    if (lastFocus) lastFocus.focus({ preventScroll: true });
  }
  function onKey(e) {
    if (e.key === "Escape") end();
    else if (e.key === "ArrowRight") next();
    else if (e.key === "ArrowLeft" && i > 0) show(i - 1);
  }
  function next() { if (i >= steps.length - 1) end(); else show(i + 1); }

  window.Tour = {
    start(list) {
      steps = list.filter((s) => !s.target || document.querySelector(s.target));
      if (!steps.length) return;
      lastFocus = document.activeElement; active = true; $("tour").hidden = false;
      document.addEventListener("keydown", onKey);
      show(0);
    },
    shouldAutoStart() { return !store.get(); },
  };

  document.addEventListener("DOMContentLoaded", () => {
    $("tour-next").addEventListener("click", next);
    $("tour-prev").addEventListener("click", () => show(i - 1));
    $("tour-skip").addEventListener("click", end);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, { passive: true });
  });
})();
