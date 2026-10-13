/* Ayussha Plant QC: small enhancements for the server-rendered pages. Everything still submits as plain forms. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v) => { const t = String(v ?? "").trim().replace(/,/g, ""); if (!t) return null; const n = Number(t); return Number.isFinite(n) ? n : NaN; };
  const fmt = (n, d = 4) => (n == null ? "—" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d }));
  const readJSON = (id, fallback) => { const el = document.getElementById(id); if (!el) return fallback; try { return JSON.parse(el.textContent); } catch (_) { return fallback; } };

  const LABEL = { pass: "Within limits", fail: "Out of limit", incomplete: "Incomplete", missing: "Not entered", nolimit: "No limit set", bad: "Not a number" };
  const CLS = { pass: "pass", fail: "fail", incomplete: "hold", missing: "info", nolimit: "info", bad: "fail" };
  const chip = (s) => `<span class="chip ${CLS[s] || "info"}">${esc(LABEL[s] || s)}</span>`;
  const limitText = (min, max, unit) => {
    const u = unit ? " " + unit : "";
    if (min != null && max != null) return `${fmt(min)} – ${fmt(max)}${u}`;
    if (min != null) return `≥ ${fmt(min)}${u}`;
    if (max != null) return `≤ ${fmt(max)}${u}`;
    return "No limit set";
  };
  const evaluate = (v, min, max) => {
    if (v == null) return "missing";
    if (Number.isNaN(v)) return "bad";
    if (min == null && max == null) return "nolimit";
    if (min != null && v < min) return "fail";
    if (max != null && v > max) return "fail";
    return "pass";
  };

  /* Two-step delete buttons */
  $$("form[data-confirm]").forEach((form) => {
    let armed = false;
    form.addEventListener("submit", (e) => {
      if (armed) return;
      e.preventDefault();
      armed = true;
      const b = $("button", form);
      b.textContent = "Confirm: " + b.dataset.label.toLowerCase();
      $("[data-note]", form).textContent = "This cannot be undone.";
    });
  });

  /* Filters apply as soon as a select or date changes */
  $$("form[data-autosubmit]").forEach((form) => {
    $$("select, input[type=date]", form).forEach((el) => el.addEventListener("change", () => form.submit()));
  });

  /* Long-running submits (AI review) */
  $$("form[data-busy]").forEach((form) => {
    form.addEventListener("submit", () => {
      const b = $("button[type=submit]", form);
      if (b) { b.disabled = true; b.textContent = form.dataset.busy; }
    });
  });

  /* ---------------- New material test ---------------- */
  const qcForm = $("#qc-form");
  if (qcForm) {
    const payload = readJSON("qc-payload", {});
    const saved = readJSON("qc-values", {});
    const mat = $("#q_mat"), box = $("#q_params"), sup = $("#q_sup");
    const evalAll = () => {
      const st = $$("tr[data-pid]", box).map((tr) => {
        const s = evaluate(num($("input", tr).value), tr.dataset.min === "" ? null : Number(tr.dataset.min), tr.dataset.max === "" ? null : Number(tr.dataset.max));
        $(".pres", tr).innerHTML = chip(s);
        return s;
      });
      let overall = "incomplete";
      if (st.length) overall = st.includes("fail") || st.includes("bad") ? "fail" : st.includes("missing") ? "incomplete" : "pass";
      $("#q_overall").innerHTML = st.length ? chip(overall) : "—";
    };
    const load = (initial) => {
      const m = payload[mat.value];
      if (!m) { box.innerHTML = '<p class="muted">Select a material to load its test parameters.</p>'; evalAll(); return; }
      if (!initial && !sup.value) sup.value = m.supplier || "";
      if (!m.params.length) { box.innerHTML = '<p class="note-warn">No test parameters are set for this material. An administrator must add them in Setup first.</p>'; evalAll(); return; }
      box.innerHTML = `<div class="tablewrap"><table class="ptable"><thead><tr><th>Parameter</th><th>Limit</th><th>Value</th><th>Result</th></tr></thead><tbody>${
        m.params.map((p) => `<tr data-pid="${p.id}" data-min="${p.min ?? ""}" data-max="${p.max ?? ""}">
          <td>${esc(p.name)}${p.method ? `<div class="muted small">${esc(p.method)}</div>` : ""}</td>
          <td class="mono nowrap">${esc(limitText(p.min, p.max, p.unit))}</td>
          <td><input name="p_${p.id}" class="mono" inputmode="decimal" aria-label="${esc(p.name)} value" value="${esc(initial ? saved[p.id] ?? "" : "")}"></td>
          <td class="pres"></td></tr>`).join("")
      }</tbody></table></div>`;
      evalAll();
    };
    mat.addEventListener("change", () => load(false));
    box.addEventListener("input", evalAll);
    load(true);
  }

  /* ---------------- New production record ---------------- */
  const prodForm = $("#prod-form");
  if (prodForm) {
    const P = readJSON("prod-payload", { materials: [], lots: {}, recipes: {}, tolerance: null });
    const initial = readJSON("prod-comps", []);
    const box = $("#p_comps");
    let seq = 0;
    const units = ["kg", "t", "L", "mL", "bags", "m³"];
    const matOpts = (sel) => '<option value="">Select material</option>' + P.materials.map((m) => `<option value="${m.id}" ${String(m.id) === String(sel) ? "selected" : ""}>${esc(m.name)}</option>`).join("");
    const lotInfo = (mid, lot) => {
      const t = String(lot || "").trim().toLowerCase();
      if (!mid || !t) return null;
      const hit = (P.lots[mid] || []).find((l) => l.lot.toLowerCase() === t);
      return hit || { decision: "none" };
    };
    const update = (row) => {
      const planned = num($('[data-f="planned"]', row).value), actual = num($('[data-f="actual"]', row).value);
      const dev = planned && actual != null && !Number.isNaN(planned) && !Number.isNaN(actual) ? ((actual - planned) / planned) * 100 : null;
      const out = $(".c-dev", row);
      out.textContent = dev == null ? "—" : (dev > 0 ? "+" : "") + dev.toFixed(2) + "%";
      out.classList.toggle("bad", dev != null && P.tolerance != null && Math.abs(dev) > P.tolerance);
      const mid = $('[data-f="material_id"]', row).value, info = lotInfo(mid, $('[data-f="lot_no"]', row).value), note = $(".c-note", row);
      if (!info) note.innerHTML = "";
      else if (info.decision === "none") note.innerHTML = '<span class="note-warn">No QC record found for this lot.</span>';
      else if (info.decision !== "Accepted") note.innerHTML = `<span class="note-bad">This lot is ${esc(info.decision.toLowerCase())} (test on ${esc(info.date)}).</span>`;
      else note.innerHTML = `<span class="muted">Lot accepted (test on ${esc(info.date)}).</span>`;
    };
    const fillLots = (row) => {
      const mid = $('[data-f="material_id"]', row).value;
      $("datalist", row).innerHTML = (P.lots[mid] || []).slice(0, 40).map((l) => `<option value="${esc(l.lot)}">${esc(l.decision + " · " + l.date)}</option>`).join("");
    };
    const add = (c = {}) => {
      const n = seq++;
      const row = document.createElement("div");
      row.className = "comp";
      row.innerHTML = `
        <select name="c-${n}-material_id" data-f="material_id" aria-label="Material">${matOpts(c.material_id)}</select>
        <input name="c-${n}-lot_no" data-f="lot_no" class="mono" list="lots-${n}" placeholder="Lot no." aria-label="Lot number" autocomplete="off" value="${esc(c.lot_no ?? "")}"><datalist id="lots-${n}"></datalist>
        <input name="c-${n}-planned" data-f="planned" class="mono" inputmode="decimal" placeholder="Planned" aria-label="Planned quantity" value="${esc(c.planned ?? "")}">
        <input name="c-${n}-actual" data-f="actual" class="mono" inputmode="decimal" placeholder="Actual" aria-label="Actual quantity" value="${esc(c.actual ?? "")}">
        <select name="c-${n}-unit" data-f="unit" aria-label="Unit">${units.map((u) => `<option ${u === (c.unit || "kg") ? "selected" : ""}>${u}</option>`).join("")}</select>
        <div class="row" style="flex-wrap:nowrap;gap:6px"><span class="c-dev">—</span><button type="button" class="btn ghost" data-remove aria-label="Remove component">Remove</button></div>
        <div class="c-note"></div>`;
      box.appendChild(row);
      fillLots(row);
      update(row);
      return row;
    };
    (initial.length ? initial : [{}]).forEach(add);
    $("#p_add").addEventListener("click", () => $("select", add()).focus());
    box.addEventListener("input", (e) => { const r = e.target.closest(".comp"); if (r) update(r); });
    box.addEventListener("change", (e) => { const r = e.target.closest(".comp"); if (!r) return; if (e.target.dataset.f === "material_id") fillLots(r); update(r); });
    box.addEventListener("click", (e) => { if (e.target.hasAttribute("data-remove")) { e.target.closest(".comp").remove(); if (!box.children.length) add(); } });
    $("#p_rec").addEventListener("change", (e) => {
      const rec = P.recipes[e.target.value];
      if (!rec) return;
      box.innerHTML = "";
      (rec.components.length ? rec.components : [{}]).forEach(add);
      const line = $("#p_line");
      if (rec.line && line && !line.value) line.value = rec.line;
    });
  }

  /* ---------------- Recipe form ---------------- */
  const recipeForm = $("#recipe-form");
  if (recipeForm) {
    const tpl = $("#recipe-row"), box = $("#r_comps");
    let seq = 0;
    const add = (c = {}) => {
      const n = seq++;
      const row = tpl.content.firstElementChild.cloneNode(true);
      $$("[data-name]", row).forEach((el) => {
        el.name = `c-${n}-${el.dataset.name}`;
        const v = c[el.dataset.name];
        if (v != null && v !== "") el.value = String(v);
      });
      box.appendChild(row);
      return row;
    };
    const initial = readJSON("recipe-comps", [{}]);
    (initial.length ? initial : [{}]).forEach(add);
    $("#r_add").addEventListener("click", () => $("select", add()).focus());
    box.addEventListener("click", (e) => { if (e.target.hasAttribute("data-remove")) { e.target.closest(".comp").remove(); if (!box.children.length) add(); } });
  }

  /* ---------------- Order form: sites follow the customer ---------------- */
  const orderForm = $("#order-form");
  if (orderForm) {
    const sites = readJSON("sites-payload", {});
    const cust = $("#o_cust"), site = $("#o_site");
    const fill = () => {
      const cur = site.dataset.current || site.value;
      const list = sites[cust.value] || [];
      site.innerHTML = '<option value="">' + (list.length ? "Select site" : "No sites for this customer") + "</option>" +
        list.map((x) => `<option value="${x.id}" ${String(x.id) === String(cur) ? "selected" : ""}>${esc(x.name)}</option>`).join("");
      site.dataset.current = "";
    };
    cust.addEventListener("change", fill);
    fill();
  }

  /* ---------------- Dispatch form: bag lines from stock ---------------- */
  const dispForm = $("#dispatch-form");
  if (dispForm) {
    const stock = readJSON("stock-payload", []);
    const initial = readJSON("items-initial", []);
    const box = $("#d_items");
    let seq = 0;
    const opts = (sel) => '<option value="">Select production record</option>' + stock.map((r) =>
      `<option value="${r.id}" ${String(r.id) === String(sel) ? "selected" : ""}>${esc(r.label)}${r.flagged ? " · flagged" : ""}</option>`).join("");
    const update = (row) => {
      const rec = stock.find((r) => String(r.id) === $("select", row).value);
      const bags = num($("input", row).value);
      $(".c-dev", row).textContent = rec ? rec.available + " bags" : "—";
      const note = $(".c-note", row);
      if (!rec) note.innerHTML = "";
      else if (bags != null && !Number.isNaN(bags) && bags > rec.available) note.innerHTML = `<span class="note-bad">Only ${rec.available} bags in stock.</span>`;
      else if (rec.flagged) note.innerHTML = '<span class="note-warn">This record is flagged (lot not accepted or over tolerance). A remark is required.</span>';
      else note.innerHTML = "";
    };
    const add = (it = {}) => {
      const n = seq++;
      const row = document.createElement("div");
      row.className = "comp disp";
      row.innerHTML = `
        <select name="i-${n}-production_id" aria-label="Production record">${opts(it.production_id)}</select>
        <input name="i-${n}-bags" class="mono" inputmode="numeric" placeholder="Bags" aria-label="Bags" value="${esc(it.bags ?? "")}">
        <span class="c-dev">—</span>
        <button type="button" class="btn ghost" data-remove aria-label="Remove line">Remove</button>
        <div class="c-note"></div>`;
      box.appendChild(row);
      update(row);
      return row;
    };
    if (!stock.length) box.innerHTML = '<p class="note-warn">No filled bags are in stock. Bags come from the "Bags filled" field on production records.</p>';
    else (initial.length ? initial : [{}]).forEach(add);
    $("#d_add").addEventListener("click", () => { if (stock.length) $("select", add()).focus(); });
    box.addEventListener("input", (e) => { const r = e.target.closest(".comp"); if (r) update(r); });
    box.addEventListener("change", (e) => { const r = e.target.closest(".comp"); if (r) update(r); });
    box.addEventListener("click", (e) => { if (e.target.hasAttribute("data-remove")) { e.target.closest(".comp").remove(); if (!box.children.length) add(); } });
  }
})();
