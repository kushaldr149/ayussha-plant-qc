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
    const P = readJSON("qc-payload", { materials: {}, calcs: {} });
    const payload = P.materials || {}, CALCS = P.calcs || {};
    const saved = readJSON("qc-values", {});
    const savedWork = readJSON("qc-workings", {});
    const csrf = $("input[name=csrf_token]", qcForm).value;
    const mat = $("#q_mat"), box = $("#q_params"), sup = $("#q_sup");
    const sieveLabel = (mm) => (mm < 1 ? `${Math.round(mm * 1000)} µm` : `${mm} mm`);
    const evalRow = (tr) => {
      const type = tr.dataset.type, periodic = tr.dataset.periodic === "1";
      let v;
      if (type === "passfail") { const x = $("select.pv", tr).value; v = x === "" ? null : (x === "pass" ? 1 : 0); }
      else v = num($("input.pv", tr).value);
      let s;
      if (v == null) s = periodic ? "skipped" : "missing";
      else if (type === "passfail") s = v >= 1 ? "pass" : "fail";
      else s = evaluate(v, tr.dataset.min === "" ? null : Number(tr.dataset.min), tr.dataset.max === "" ? null : Number(tr.dataset.max));
      $(".pres", tr).innerHTML = s === "skipped" ? '<span class="chip info">Not tested (periodic)</span>' : chip(s);
      return s;
    };
    const evalAll = () => {
      const st = $$("tr[data-pid]", box).map(evalRow).filter((s) => s !== "skipped");
      let overall = "incomplete";
      if (st.length) overall = st.includes("fail") || st.includes("bad") ? "fail" : st.includes("missing") ? "incomplete" : "pass";
      $("#q_overall").innerHTML = $$("tr[data-pid]", box).length ? chip(overall) : "—";
    };
    const post = async (data) => {
      const body = new URLSearchParams({ csrf_token: csrf, ...data });
      const r = await fetch("/qc/calc", { method: "POST", body, headers: { "Content-Type": "application/x-www-form-urlencoded" } });
      const j = await r.json().catch(() => ({ ok: false, error: "The worksheet could not be calculated." }));
      if (!j.ok) throw new Error(j.error || "The worksheet could not be calculated.");
      return j.result;
    };
    const setValue = (pid, value, work) => {
      const tr = $(`tr[data-pid="${pid}"]`, box);
      if (!tr) return;
      $("input.pv", tr).value = value == null ? "" : String(value);
      $(`input[name="w_${pid}"]`, qcForm).value = work ? JSON.stringify(work) : "";
    };
    /* Output key of a multi-result worksheet -> parameter, matched by the start of the parameter name. */
    const OUT_MATCH = { flakiness: /^flakiness/i, elongation: /^elongation/i, combined: /^combined/i,
      sg: /^specific gravity/i, apparent: /^apparent/i, absorption: /^water absorption/i };

    const worksheet = (key, params) => {
      const c = CALCS[key];
      const first = params[0];
      const prevWork = (() => { try { return JSON.parse(savedWork[first.id] || "null"); } catch (_) { return null; } })();
      const prev = (prevWork && prevWork.inputs) || {};
      return `<tr class="ws" data-ws="${key}" data-for="${params.map((p) => p.id).join(",")}" hidden><td colspan="4">
        <div class="worksheet">
          <div class="ws-head"><strong>${esc(c.title)}</strong><span class="muted small">${esc(c.method)}</span></div>
          <div class="fgrid">${c.inputs.map(([k, label]) => `<label class="f"><span>${esc(k)}: ${esc(label)}</span><input class="mono" data-in="${esc(k)}" inputmode="decimal" value="${esc(prev[k] ?? "")}"></label>`).join("")}</div>
          <div class="muted small mono">${c.formulas.map(esc).join("<br>")}</div>
          <div class="row"><button type="button" class="btn primary" data-run>Calculate and fill in</button><span class="small ws-msg"></span></div>
        </div></td></tr>`;
    };
    const sieveSheet = (params, fine) => {
      const sieves = params.filter((p) => p.sieve != null).map((p) => p.sieve).sort((a, b) => b - a);
      return `<tr class="ws" data-ws="sieve" data-fine="${fine ? 1 : 0}" hidden><td colspan="4">
        <div class="worksheet">
          <div class="ws-head"><strong>Sieve analysis</strong><span class="muted small">IS 2386 (Part 1): cumulative % passing to the nearest whole number</span></div>
          <div class="fgrid">
            <label class="f"><span>Total dry mass of sample, g</span><input class="mono" data-total inputmode="decimal"><span class="hint">Leave empty to use the sum of masses below including the pan.</span></label>
            ${sieves.map((mm) => `<label class="f"><span>Retained on ${esc(sieveLabel(mm))}, g</span><input class="mono" data-sieve="${mm}" inputmode="decimal"></label>`).join("")}
            <label class="f"><span>Passing the smallest sieve (pan), g</span><input class="mono" data-pan inputmode="decimal"></label>
          </div>
          <div class="muted small mono">% passing = 100 − cumulative mass retained / total mass × 100${fine ? "<br>Fineness modulus = sum of cumulative % retained on the sieves used (80 mm to 150 µm) ÷ 100" : ""}</div>
          <div class="row"><button type="button" class="btn primary" data-run>Calculate and fill in</button><span class="small ws-msg"></span></div>
          <div class="zone-out small"></div>
        </div></td></tr>`;
    };

    const load = (initial) => {
      const m = payload[mat.value];
      if (!m) { box.innerHTML = '<p class="muted">Select a material to load its test parameters.</p>'; evalAll(); return; }
      if (!initial && !sup.value) sup.value = m.supplier || "";
      if (!m.params.length) { box.innerHTML = '<p class="note-warn">No test parameters are set for this material. An administrator must add them in Setup first.</p>'; evalAll(); return; }
      const fine = m.category === "Fine aggregate";
      const groups = [];
      m.params.forEach((p) => { const g = p.group || "Tests"; let x = groups.find((y) => y.name === g); if (!x) { x = { name: g, params: [] }; groups.push(x); } x.params.push(p); });
      const sheetFor = new Set();
      box.innerHTML = groups.map((g) => {
        const rows = [];
        const hasSieve = g.params.some((p) => p.calc === "sieve");
        if (hasSieve) rows.push(sieveSheet(g.params, fine));
        g.params.forEach((p) => {
          const val = initial ? saved[p.id] ?? "" : "";
          const input = p.type === "passfail"
            ? `<select name="p_${p.id}" class="pv" aria-label="${esc(p.name)} result"><option value="">Not tested</option><option value="pass" ${val === "pass" ? "selected" : ""}>Pass</option><option value="fail" ${val === "fail" ? "selected" : ""}>Fail</option></select>`
            : `<input name="p_${p.id}" class="pv mono" inputmode="decimal" aria-label="${esc(p.name)} value" value="${esc(val)}">`;
          let wsBtn = "";
          if (p.calc && p.calc !== "sieve" && CALCS[p.calc]) wsBtn = `<button type="button" class="linkbtn small" data-open="${p.calc}">Worksheet</button>`;
          else if (p.calc === "sieve") wsBtn = '<button type="button" class="linkbtn small" data-open="sieve">Sieve worksheet</button>';
          rows.push(`<tr data-pid="${p.id}" data-min="${p.min ?? ""}" data-max="${p.max ?? ""}" data-type="${p.type}" data-periodic="${p.frequency !== "Every lot" ? 1 : 0}" data-calc="${esc(p.calc)}" data-sieve="${p.sieve ?? ""}" data-name="${esc(p.name)}">
            <td>${esc(p.name)}${p.frequency !== "Every lot" ? ` <span class="muted small">(${esc(p.frequency)})</span>` : ""}${p.method ? `<div class="muted small">${esc(p.method)}</div>` : ""}${p.note ? `<div class="small note-warn">${esc(p.note)}</div>` : ""}</td>
            <td class="mono nowrap">${p.type === "passfail" ? "Pass required" : esc(limitText(p.min, p.max, p.unit))}</td>
            <td>${input}<input type="hidden" name="w_${p.id}" value="${esc(initial ? savedWork[p.id] ?? "" : "")}"><div>${wsBtn}</div></td>
            <td class="pres"></td></tr>`);
          if (p.calc && p.calc !== "sieve" && CALCS[p.calc] && !sheetFor.has(p.calc)) {
            sheetFor.add(p.calc);
            const siblings = ["shape", "sg_basket", "sg_pycnometer"].includes(p.calc) ? m.params.filter((x) => x.calc === p.calc) : [p];
            rows.push(worksheet(p.calc, siblings));
          } else if (p.calc && p.calc !== "sieve" && CALCS[p.calc] && !["shape", "sg_basket", "sg_pycnometer"].includes(p.calc)) {
            rows.push(worksheet(p.calc, [p]).replace(`data-ws="${p.calc}"`, `data-ws="${p.calc}" data-own="${p.id}"`));
          }
        });
        return `<h3 class="sub" style="margin:14px 0 6px">${esc(g.name)}</h3><div class="tablewrap"><table class="ptable"><thead><tr><th>Parameter</th><th>Limit</th><th>Value</th><th>Result</th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
      }).join("");
      /* single-output worksheets: the first one for a calc key belongs to its first parameter */
      $$("tr.ws", box).forEach((ws) => {
        if (!ws.dataset.own && ws.dataset.for && ws.dataset.for.split(",").length === 1) ws.dataset.own = ws.dataset.for;
      });
      evalAll();
    };

    box.addEventListener("click", async (e) => {
      const open = e.target.closest("[data-open]");
      if (open) {
        const tr = open.closest("tr");
        const key = open.dataset.open;
        let ws = key === "sieve" ? $('tr.ws[data-ws="sieve"]', tr.closest("tbody"))
          : ($(`tr.ws[data-own="${tr.dataset.pid}"]`, box) || $(`tr.ws[data-ws="${key}"]`, box));
        if (ws) { ws.hidden = !ws.hidden; if (!ws.hidden) { const i = $("input", ws); if (i) i.focus(); } }
        return;
      }
      const run = e.target.closest("[data-run]");
      if (!run) return;
      const ws = run.closest("tr.ws"), msg = $(".ws-msg", ws), key = ws.dataset.ws;
      msg.textContent = "Calculating…"; msg.className = "small ws-msg muted";
      try {
        if (key === "sieve") {
          const data = { calc: "sieve", fine: ws.dataset.fine };
          const inputs = {};
          let pan = num($("[data-pan]", ws).value);
          $$("[data-sieve]", ws).forEach((i) => { if (i.value.trim() !== "") { data["r_" + i.dataset.sieve] = i.value; inputs[i.dataset.sieve] = i.value; } });
          const totalEl = $("[data-total]", ws);
          let total = num(totalEl.value);
          if (total == null) { const sum = Object.values(inputs).reduce((a, b) => a + (num(b) || 0), 0) + (pan || 0); total = sum; }
          data.total = String(total);
          const rows = $$("tr[data-pid]", ws.closest("tbody"));
          const r150 = rows.find((r) => r.dataset.sieve === "0.15");
          if (r150 && Number(r150.dataset.max) > 10) data.crushed = "1";
          const res = await post(data);
          const work = { calc: "sieve", inputs: { ...inputs, pan: pan ?? "", total }, results: res };
          rows.forEach((r) => {
            if (r.dataset.calc !== "sieve") return;
            if (r.dataset.sieve !== "") { const k = String(Number(r.dataset.sieve)); if (k in res.passing) setValue(r.dataset.pid, res.passing[k], work); }
            else if (/fineness modulus/i.test(r.dataset.name) && res.fm != null) setValue(r.dataset.pid, res.fm, work);
          });
          const z = $(".zone-out", ws);
          if (res.zones) {
            const within = res.zones.filter((x) => x.within).map((x) => x.zone);
            z.innerHTML = `<strong>IS 383 Table 9 zone check:</strong> ${within.length ? "within " + esc(within.join(", ")) : "does not fall within any zone"}` +
              res.zones.map((x) => x.notes.length ? `<div class="muted">${esc(x.zone)}: ${esc(x.notes.join("; "))}</div>` : "").join("");
          } else z.innerHTML = "";
        } else {
          const data = { calc: key };
          const inputs = {};
          $$("[data-in]", ws).forEach((i) => { data["in_" + i.dataset.in] = i.value; inputs[i.dataset.in] = i.value; });
          const res = await post(data);
          const work = { calc: key, inputs, results: res };
          if ("value" in res) {
            const own = ws.dataset.own || ws.dataset.for.split(",")[0];
            setValue(own, res.value, work);
          } else {
            ws.dataset.for.split(",").forEach((pid) => {
              const name = $(`tr[data-pid="${pid}"]`, box).dataset.name;
              const k = Object.keys(OUT_MATCH).find((o) => o in res && OUT_MATCH[o].test(name));
              if (k) setValue(pid, res[k], work);
            });
          }
        }
        msg.textContent = "Filled in. Check the values before saving."; msg.className = "small ws-msg";
        evalAll();
      } catch (err) { msg.textContent = err.message; msg.className = "small ws-msg note-bad"; }
    });

    /* Voids worksheet: prefill G and Y from values already on the form. */
    box.addEventListener("click", (e) => {
      const open = e.target.closest('[data-open="voids"]');
      if (!open) return;
      const find = (re) => $$("tr[data-pid]", box).find((r) => re.test(r.dataset.name));
      const g = find(/^specific gravity/i), y = find(/^bulk density, rodded/i);
      const ws = $('tr.ws[data-ws="voids"]', box);
      if (!ws) return;
      const gi = $('[data-in="G"]', ws), yi = $('[data-in="Y"]', ws);
      if (g && !gi.value) gi.value = $("input.pv", g).value;
      if (y && !yi.value) yi.value = $("input.pv", y).value;
    });

    mat.addEventListener("change", () => load(false));
    box.addEventListener("input", evalAll);
    box.addEventListener("change", evalAll);
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
    // Show only the bags packed for the selected order.
    const order = $("#d_order"), packRows = Array.from(document.querySelectorAll("#d_packs tbody tr[data-order]"));
    const filterPacks = () => packRows.forEach((tr) => {
      const show = !order.value || tr.dataset.order === order.value;
      tr.hidden = !show;
      if (!show) $("input", tr).checked = false;
    });
    if (order && packRows.length) { order.addEventListener("change", filterPacks); filterPacks(); }
  }
})();
