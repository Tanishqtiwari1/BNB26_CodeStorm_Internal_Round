/* BLACK BOX — AI Agent Flight Recorder.   DETECT → EXPLAIN → REPLAY → REPAIR → VERIFY
   Plain ES2020, no build step. Every number on screen comes from the API. */
"use strict";

// ================================================================== utils
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = () => $("#view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
const num = (x) => (x == null ? "—" : Number(x).toLocaleString());
const ms = (x) => (x == null ? "—" : x >= 1000 ? `${(x / 1000).toFixed(2)}s` : `${Math.round(x)}ms`);
const money = (x) => (x == null ? "—" : `$${Number(x).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const ago = (t) => { if (!t) return "—"; const s = Date.now() / 1000 - t; if (s < 60) return "just now"; if (s < 3600) return `${Math.floor(s / 60)} min ago`; if (s < 86400) return `${Math.floor(s / 3600)} hr ago`; return new Date(t * 1000).toLocaleDateString(); };
const rid = (id) => `#run_${String(id).slice(0, 6)}`;
const nn = (i) => String(i + 1).padStart(2, "0");
const go = (h) => { location.hash = h; };
const statusPill = (ok, repaired) => (repaired ? `<span class="st rep">✓ Repaired</span>` : ok ? `<span class="st ok">Success</span>` : `<span class="st fail">Failed</span>`);

const IC = {
  overview: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  runs: '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  trace: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
  replay: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  compare: '<path d="M7 7h11l-3-3M17 17H6l3 3"/>',
  eval: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 15l3-3 3 2 4-5"/>',
  demo: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4z"/>',
  connect: '<path d="M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5"/>',
  home: '<path d="m3 11 9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  upload: '<path d="M12 16V4M6 10l6-6 6 6M4 20h16"/>',
  about: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
  check: '<path d="m5 12 5 5 9-10"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>', alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16v.01"/>',
  bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>', arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>', ff: '<path d="m4 6 7 6-7 6zM13 6l7 6-7 6z"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>', down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  code: '<path d="m8 8-4 4 4 4M16 8l4 4-4 4"/>', graph: '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M7.5 7.8 11 16M16.5 7.8 13 16M8.5 6h7"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>', shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  wand: '<path d="m15 4 5 5L9 20H4v-5z"/><path d="m13 6 5 5"/>', term: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
};
const icon = (n, s = "") => `<svg class="i" viewBox="0 0 24 24" ${s}>${IC[n] || ""}</svg>`;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    const e = new Error(typeof msg === "string" ? msg : JSON.stringify(msg)); e.status = r.status; throw e;
  }
  return r.json();
}
function toast(m) { const t = document.createElement("div"); t.className = "toast"; t.textContent = m; document.body.appendChild(t); setTimeout(() => t.remove(), 5000); }
function jsonHtml(o) {
  return esc(JSON.stringify(o, null, 2)).replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false|null)\b|(-?\d+\.?\d*(?:e[+-]?\d+)?)/g,
    (m, s, c, b, n) => s ? (c ? `<span class="k">${s}</span>${c}` : `<span class="s">${s}</span>`) : b ? `<span class="b">${b}</span>` : `<span class="n">${n}</span>`);
}
function summarize(o) {
  if (o == null) return "—";
  if (typeof o !== "object") return String(o);
  if (o.error) return `error: ${o.error}`;
  if (o.tool && o.args) return `${o.tool}(${Object.values(o.args).map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(", ")})`;
  if (o.question) return `“${o.question.slice(0, 90)}…”`;
  if (o.total_usd !== undefined) return o.within_budget == null ? money(o.total_usd) : `${money(o.total_usd)} · ${o.within_budget ? "within" : "over"} budget`;
  if (o.text) return `“${o.text.slice(0, 70)}…”`;
  for (const k of ["value", "usd", "rate", "amount"]) if (o[k] != null) return `${k}: ${typeof o[k] === "number" ? o[k].toLocaleString(undefined, { maximumFractionDigits: 6 }) : o[k]}${o.currency ? " " + o.currency : ""}`;
  if (o.within_budget != null) return `within_budget: ${o.within_budget}`;
  if (o.legs) return `${o.legs.length} leg(s), ${o.travelers ?? "?"} traveler(s), budget ${o.budget ?? "?"}`;
  const s = JSON.stringify(o); return s.length > 80 ? s.slice(0, 80) + "…" : s;
}
const titleCase = (s) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
function stepName(s) {
  if (s.kind === "input") return "User Task";
  if (s.name === "final_answer") return "Final Answer";
  if (s.name.startsWith("call:")) return `Decide · ${titleCase(s.name.slice(5))}`;
  return titleCase(s.name);
}
const kindLabel = (s) => ({ llm: "LLM DECISION", retrieval: "RETRIEVAL", tool: "TOOL CALL", final: "LLM ANSWER", input: "INPUT" }[s.kind] || s.kind.toUpperCase());
const empty = (t, m, b = "") => `<div class="empty"><div class="t">${t}</div><div>${m}</div>${b ? `<div class="mt">${b}</div>` : ""}</div>`;
const loading = () => { view().innerHTML = `<div class="empty"><span class="spin"></span></div>`; };
function descendants(steps, sid) {
  const out = new Set([sid]); let grew = true;
  while (grew) { grew = false; for (const s of steps) if (!out.has(s.sid) && s.parents.some((p) => out.has(p))) { out.add(s.sid); grew = true; } }
  return out;
}
function diffFields(a, b) {
  const flat = (o) => (o && o.args && o.tool ? { tool: o.tool, ...o.args } : o || {});
  const A = flat(a), B = flat(b);
  return [...new Set([...Object.keys(A), ...Object.keys(B)])].filter((k) => JSON.stringify(A[k]) !== JSON.stringify(B[k])).map((k) => [k, A[k], B[k]]);
}
const MAIN = (L) => (L.test.gnn ? "gnn" : "model");
function agentName(run) {
  const m = run.meta || {};
  if (run.agent === "react-slm") return `${m.model || "model"} · ${(m.provider || "").toUpperCase()}`;
  if (run.agent === "react-sim") return `Benchmark agent (${m.policy || "standard"})`;
  if (run.agent === "external") return `${m.service || "External agent"} (OpenTelemetry)`;
  return "v1 fixed-plan agent";
}
let INFO = null, BADGE = 0;
// What a replay did not have to execute again (from the recorded steps it reused).
function savings(steps, reused) {
  const r = steps.filter((x) => reused(x));
  return { model: r.filter((x) => ["llm", "final"].includes(x.kind)).length, tools: r.filter((x) => ["tool", "retrieval"].includes(x.kind)).length,
    ms: r.reduce((a, x) => a + (x.latency_ms || 0), 0) };
}
const savingsLine = (sv) => `<b class="t1">${sv.model}</b> model call${sv.model === 1 ? "" : "s"} avoided · <b class="t1">${sv.tools}</b> tool call${sv.tools === 1 ? "" : "s"} avoided · <b class="t1">${ms(sv.ms)}</b> of recorded execution time not repeated`;

// ================================================================== shell
const NAV = [["overview", "#/", "Overview"], ["runs", "#/runs", "Runs"], ["trace", "#/investigate", "Trace Investigation"],
  ["replay", "#/repair", "Replay & Repair"], ["compare", "#/comparisons", "Comparisons"], ["eval", "#/eval", "Evaluation"],
  ["demo", "#/demo", "Live Demo"], ["connect", "#/connect", "Connect Your Agent"], ["sep"], ["about", "#/about", "How it works"], ["home", "/", "Home page"]];
function renderNav(active) {
  $("#nav").innerHTML = NAV.map(([k, h, l]) => (k === "sep" ? `<div class="sep"></div>`
    : `<a href="${h}" class="${k === active ? "on" : ""}">${icon(k)}${l}${k === "trace" && BADGE ? `<span class="badge">${BADGE} failure${BADGE > 1 ? "s" : ""}</span>` : ""}</a>`)).join("");
}
async function refreshShell() {
  try {
    INFO = await api("/api/info");
    const live = INFO.llm.slm_available;
    $("#rec").innerHTML = `<span class="rec"></span>REC · Recorder online`;
    $("#model").innerHTML = `<span class="rec ${live ? "green" : "amber"}"></span>${live ? `${esc(INFO.llm.slm)} · ${esc((INFO.llm.slm_provider || "").toUpperCase())}` : "Real model offline · benchmark agent"}`;
    $("#sidestatus").innerHTML = `<div><b>Recorder</b> · OpenTelemetry</div><div><b>Diagnosis</b> · ${INFO.model_version === "v2" ? "graph neural network" : "v1 model"}</div><div><b>Live agent</b> · ${live ? esc(INFO.llm.slm) : "benchmark policy"}</div>`;
    const [a, b] = await Promise.all([api("/api/runs?status=failed&split=demo&limit=1"), api("/api/runs?status=failed&split=live&limit=1")]);
    BADGE = a.total + b.total;
  } catch (_) { $("#rec").innerHTML = `<span class="rec off"></span>API offline`; }
}

// ---------------- command palette (real search over recorded runs)
function openPalette() {
  if ($(".pal-bg")) return;
  const bg = document.createElement("div");
  bg.className = "pal-bg";
  bg.innerHTML = `<div class="pal"><input placeholder="Search runs by id or task…   (try “Paris”, “failed”, a run id)" autofocus><div class="res"></div>
    <div class="ft"><span><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span><span class="sp"></span><span>pages: overview · runs · demo · eval</span></div></div>`;
  document.body.appendChild(bg);
  const inp = $("input", bg), res = $(".res", bg);
  let items = [], sel = 0, timer;
  const pages = [["Overview", "#/"], ["Live Demo", "#/demo"], ["Connect Your Agent", "#/connect"], ["Trace Investigation", "#/investigate"], ["Replay & Repair", "#/repair"], ["Comparisons", "#/comparisons"], ["Evaluation", "#/eval"], ["Runs", "#/runs"]];
  const draw = () => {
    res.innerHTML = items.map((it, i) => `<div class="it ${i === sel ? "on" : ""}" data-i="${i}">${it.left}<div style="min-width:0"><div class="t1" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${it.title}</div><div class="muted" style="font-size:12px">${it.sub}</div></div><span class="muted mono" style="font-size:11px">${it.right || ""}</span></div>`).join("") || `<div class="empty">No matches</div>`;
    $$(".it", res).forEach((el) => (el.onclick = () => pick(+el.dataset.i)));
  };
  const pick = (i) => { const it = items[i]; if (it) { close(); go(it.href); } };
  const close = () => bg.remove();
  const search = async () => {
    const q = inp.value.trim();
    const pg = pages.filter(([l]) => !q || l.toLowerCase().includes(q.toLowerCase())).map(([l, h]) => ({ left: icon("arrow"), title: l, sub: "page", href: h }));
    let runs = [];
    if (q) {
      const status = /fail/i.test(q) ? "&status=failed" : /pass|success/i.test(q) ? "&status=passed" : "";
      const term = q.replace(/fail(ed)?|pass(ed)?|success/ig, "").trim();
      const d = await api(`/api/runs?limit=8${status}${term ? `&q=${encodeURIComponent(term)}` : ""}`).catch(() => ({ runs: [] }));
      runs = d.runs.map((r) => ({ left: statusPill(r.success), title: esc(r.question), sub: `${rid(r.run_id)} · ${esc(r.split)} · ${r.n_steps} steps`, right: ago(r.created), href: `#/investigate/${r.run_id}` }));
    }
    items = [...runs, ...pg]; sel = 0; draw();
  };
  inp.oninput = () => { clearTimeout(timer); timer = setTimeout(search, 160); };
  inp.onkeydown = (e) => {
    if (e.key === "ArrowDown") { sel = Math.min(items.length - 1, sel + 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); draw(); e.preventDefault(); }
    else if (e.key === "Enter") pick(sel);
    else if (e.key === "Escape") close();
  };
  bg.onclick = (e) => { if (e.target === bg) close(); };
  search(); inp.focus();
}
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); }
  else if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); openPalette(); }
});

// ================================================================== router
let KEYHANDLER = null;
const routes = [
  [/^\/?$/, "overview", overview], [/^\/runs$/, "runs", runsView],
  [/^\/investigate$/, "trace", investigateLatest], [/^\/(?:investigate|run)\/([\w-]+)$/, "trace", investigate],
  [/^\/repair$/, "replay", repairPicker], [/^\/(?:repair|replay)\/([\w-]+)$/, "replay", repairView],
  [/^\/comparisons$/, "compare", comparisons], [/^\/compare\/([\w-]+)\/([\w-]+)$/, "compare", compareView],
  [/^\/eval$/, "eval", evalView], [/^\/demo$/, "demo", demoView], [/^\/connect$/, "connect", connectView], [/^\/about$/, "about", aboutView],
];
async function router() {
  const h = location.hash.slice(1) || "/";
  const [path, qs] = h.split("?");
  const q = Object.fromEntries(new URLSearchParams(qs || ""));
  if (KEYHANDLER) { document.removeEventListener("keydown", KEYHANDLER); KEYHANDLER = null; }
  for (const [re, nav, fn] of routes) {
    const m = path.match(re);
    if (!m) continue;
    renderNav(nav); loading();
    try { await fn(...m.slice(1), q); }
    catch (e) { view().innerHTML = `<div class="errbox"><div class="t">REQUEST FAILED${e.status ? ` · HTTP ${e.status}` : ""}</div><div class="mt">${esc(e.message)}</div><div class="mt"><button class="btn sm" onclick="router()">Retry</button></div></div>`; }
    window.scrollTo(0, 0);
    return;
  }
  renderNav(""); view().innerHTML = empty("NOT FOUND", "No such page.");
}
window.addEventListener("hashchange", router);
$("#search").onclick = openPalette;

// ================================================================== OVERVIEW
async function overview() {
  const [s, m] = await Promise.all([api("/api/stats"), api("/api/metrics").catch(() => null)]);
  const L = m?.localization, K = L ? MAIN(L) : null, cf = m?.counterfactual || {};
  const reusedPct = cf.reexec_ratio != null ? 1 - cf.reexec_ratio : null;
  view().innerHTML = `
    <section class="hero">
      <div class="tag"><span class="cap">Flight recorder</span>/ ${INFO?.llm?.slm_available ? `live agent: ${esc(INFO.llm.slm)}` : "live agent: benchmark policy"}</div>
      <h1>BLACK BOX — AI Agent Flight Recorder</h1>
      <div class="tl">“From Failure to Fix — Without Starting Over.”</div>
      <p>Understand where your AI agents fail, why they fail, and repair them without re-running the entire execution. Every step is an OpenTelemetry span; a graph neural network localizes the root cause; replay resumes from the failing checkpoint.</p>
      <div class="ctas"><a class="btn primary lg" href="#/investigate">${icon("search")}Investigate Runs</a><a class="btn lg" href="#/demo">${icon("demo")}Run Live Demo</a></div>
      <div class="hstats">
        <a href="#/runs"><div class="cap">Executions recorded</div><div class="v">${num(s.runs)}</div></a>
        <a href="#/runs?status=failed"><div class="cap">Failures detected</div><div class="v red">${num(s.failures_detected)}</div></a>
        <a href="#/investigate" title="Failed runs whose top-ranked step scores ≥ ${s.identified_threshold}"><div class="cap">Root causes identified</div><div class="v ind">${num(s.root_causes_identified)}</div></a>
        <a href="#/comparisons"><div class="cap">Repairs verified</div><div class="v green">${num(s.repairs_verified)}<span class="muted" style="font-size:13px;font-weight:500"> · ${num(s.replay_attempts)} replays</span></div></a>
      </div>
      <div class="loopline">${["Detect", "Explain", "Replay", "Repair", "Verify"].map((x, i) => `<a href="${["#/runs?status=failed", "#/investigate", "#/repair", "#/repair", "#/comparisons"][i]}">${x.toUpperCase()}</a>${i < 4 ? `<span class="ar">→</span>` : ""}`).join("")}</div>
    </section>

    ${m ? `<div class="sec"><span style="color:var(--indigo-3)">${icon("alert")}</span><h2>The problem Black Box solves</h2><span class="sp"></span><span class="muted" style="font-size:13px">averages over ${num(m.corpus.runs)} benchmark runs</span></div>
    <div class="vs">
      <div class="card vsno"><div class="bd"><div class="cap">Without Black Box</div>
        <ul><li>A failing run has <b>${cf.avg_steps?.toFixed(0)} steps</b>; the error only shows up at the end.</li>
        <li>An engineer reads the logs step by step to guess where it went wrong.</li>
        <li>To test a fix, <b>all ${cf.avg_steps?.toFixed(0)} steps</b> run again, including every model call.</li></ul></div></div>
      <div class="card vsyes"><div class="bd"><div class="cap">With Black Box</div>
        <ul><li>The step that caused it is ranked <b>#1 in ${pct(L.test[K].top1)}</b> of failures, with evidence.</li>
        <li>Replay starts at that step's checkpoint and re-runs <b>${cf.avg_reexec?.toFixed(1)} steps</b> on average (${pct(cf.reexec_ratio)}).</li>
        <li>The fix is checked automatically: <b>${pct(cf.confirm_top1)}</b> of failures pass after repairing the #1 suspect.</li></ul></div></div>
    </div>` : ""}

    <div class="sec"><span class="dotred"></span><h2>Recent failures</h2><span class="count">${num(s.failures_detected)} total</span><span class="sp"></span><a class="btn sm" href="#/runs?status=failed">View all</a></div>
    <div class="card"><div class="wrap"><table>
      <thead><tr><th>Status</th><th>Run ID</th><th>Task</th><th>Diagnosed root cause</th><th class="num">Duration</th><th>Recorded</th><th class="num"></th></tr></thead>
      <tbody>${s.recent_failed.map((r, i) => `<tr class="click" data-go="#/investigate/${r.run_id}">
        <td>${statusPill(false)}</td><td><span class="idlink">${rid(r.run_id)}</span></td>
        <td><div class="trunc t1" style="max-width:260px" title="${esc(r.question)}">${esc(r.question)}</div><div class="muted" style="font-size:11.5px">${r.agent === "react-slm" ? "real model" : r.agent === "react-sim" ? "benchmark agent" : esc(r.agent)} · ${esc(r.split)}</div></td>
        <td><span class="rc"><span class="stepn">${esc(r.root_sid.split(".")[0])}</span><span class="why">${esc(stepName({ name: r.root_name, kind: "" }))}</span><span class="muted mono" style="font-size:11.5px">${pct(r.root_score)}</span></span></td>
        <td class="num muted">${ms(r.duration_ms)}</td><td class="muted">${ago(r.created)}</td>
        <td class="num"><span class="btn sm ${i === 0 ? "primary" : ""}">Investigate ${icon("arrow")}</span></td></tr>`).join("") || `<tr><td colspan="7">${empty("NO FAILED RUNS", "Your agent executions are healthy.", `<a class="btn primary" href="#/demo">Run Live Demo</a>`)}</td></tr>`}</tbody></table></div></div>

    ${m ? `<div class="sec"><span style="color:var(--indigo-3)">${icon("eval")}</span><h2>Diagnosis & replay effectiveness</h2><span class="sp"></span><span class="muted" style="font-size:13px">benchmark: ${num(m.corpus.runs)} runs, evaluated on held-out runs</span></div>
    <div class="grid g2">
      <div class="card"><div class="bd">
        <div class="cap">Graph neural network</div><h2 style="margin-top:4px">Root-cause localization accuracy</h2>
        <div class="row mt2" style="gap:34px">
          <div><div class="big">${pct(L.test[K].top1, 1)}</div><div class="muted">Top-1 · seen faults</div></div>
          <div><div class="big">${pct(L.test[K].top3, 1)}</div><div class="muted">Top-3 · seen faults</div></div>
          <div><div class="big">${pct(L.heldout[K].top1, 1)}</div><div class="muted">Top-1 · unseen fault types</div></div>
        </div>
        <div class="row mt2"><span class="muted" style="font-size:13px">Top-1 by scenario</span><span class="sp"></span><a class="muted" href="#/eval" style="font-size:12.5px">details →</a></div>
        <div class="bars mt">${[["test", "seen"], ["heldout", "unseen types"], ["drift_loc", "source moved"], ["drift_topo", "new behaviour"]].filter(([k]) => L[k]).map(([k, l]) => `<div class="b" title="${l}: ${pct(L[k][K].top1, 1)} top-1, n=${L[k][K].n}"><b>${pct(L[k][K].top1)}</b><i style="height:${Math.max(6, L[k][K].top1 * 100)}%"></i><span>${l}</span></div>`).join("")}</div>
      </div></div>
      <div class="card"><div class="bd">
        <div class="cap">Checkpoint replay</div><h2 style="margin-top:4px">Repair without starting over</h2>
        <div class="row mt2" style="gap:34px">
          <div><div class="big">${pct(reusedPct, 1)}</div><div class="muted">Avg steps reused</div></div>
          <div><div class="big">${pct(cf.confirm_top1, 1)}</div><div class="muted">Fixed by repairing #1 suspect</div></div>
          <div><div class="big">${pct(cf.fixed_within_3, 1)}</div><div class="muted">Fixed within 3 replays</div></div>
        </div>
        <div class="row mt2"><span class="muted" style="font-size:13px">Steps per verified repair (avg ${cf.avg_steps?.toFixed(1)})</span><span class="sp"></span><span class="ind mono" style="font-size:12.5px">reused ${cf.avg_reused?.toFixed(1) ?? "—"} · re-executed ${cf.avg_reexec?.toFixed(1)}</span></div>
        <div class="ratio mt"><div class="ru" style="width:${(reusedPct || 0) * 100}%">REUSED FROM RECORDING (${pct(reusedPct)})</div><div class="rx" style="width:${(1 - (reusedPct || 0)) * 100}%">RE-EXECUTED (${pct(cf.reexec_ratio)})</div></div>
        <div class="row mt2" style="font-size:13px"><span class="muted">This deployment</span><span class="sp"></span><span class="t1 mono">${num(s.replay_attempts)} replays · ${num(s.repairs_verified)} verified · ${num(s.steps_avoided)} steps avoided</span></div>
        <div class="kpis mt" style="grid-template-columns:repeat(3,1fr)">
          <div class="kpi"><div class="cap">Model calls avoided</div><div class="v" style="color:var(--green-2)">${num(s.model_calls_avoided)}</div></div>
          <div class="kpi"><div class="cap">Tool calls avoided</div><div class="v">${num(s.tool_calls_avoided)}</div></div>
          <div class="kpi"><div class="cap">Execution time not repeated</div><div class="v">${ms(s.time_saved_ms)}</div></div></div>
      </div></div>
    </div>` : ""}`;
  $$("[data-go]").forEach((el) => (el.onclick = () => go(el.dataset.go)));
}

// ================================================================== RUNS
async function runsView(q) {
  const p = new URLSearchParams({ limit: 40, offset: q.offset || 0 });
  ["status", "split", "agent", "q"].forEach((k) => q[k] && p.set(k, q[k]));
  const d = await api(`/api/runs?${p}`); const off = +(q.offset || 0);
  const seg = (k, opts) => `<div class="seg">${opts.map(([v, l]) => `<button data-k="${k}" data-v="${v}" class="${(q[k] || "") === v ? "on" : ""}">${l}</button>`).join("")}</div>`;
  view().innerHTML = `
    <div class="row mb"><div><h1>Runs</h1><div class="sub" style="margin:4px 0 0">Every recorded execution. Failed runs carry Black Box's diagnosed root cause.</div></div></div>
    <div class="row mb">${seg("status", [["", "All"], ["failed", "Failed"], ["passed", "Passed"]])}
      ${seg("split", [["", "All sources"], ["demo", "Demo"], ["live", "Live"], ["test", "Benchmark"], ["heldout", "Unseen faults"], ["drift_topo", "New behaviour"]])}
      <input id="q" placeholder="Filter by task or id…" value="${esc(q.q || "")}" style="min-width:220px"><span class="sp"></span><span class="muted mono">${num(d.total)} runs</span></div>
    <div class="card"><div class="wrap"><table>
      <thead><tr><th>Status</th><th>Run ID</th><th>Task</th><th>Agent</th><th class="num">Steps</th><th class="num">Duration</th><th>Diagnosed root cause</th><th>Recorded</th></tr></thead>
      <tbody>${d.runs.map((r) => `<tr class="click" data-go="#/investigate/${r.run_id}">
        <td>${statusPill(r.success)}</td><td><span class="idlink">${rid(r.run_id)}</span></td><td><div class="trunc t1">${esc(r.question)}</div></td>
        <td class="muted" style="font-size:12.5px">${esc(r.agent)}</td><td class="num">${r.n_steps}</td><td class="num muted">${ms(r.duration_ms)}</td>
        <td>${r.root ? `<span class="rc"><span class="stepn">${esc(r.root.sid.split(".")[0])}</span><span class="why">${esc(stepName({ name: r.root.name, kind: "" }))}</span><span class="muted mono" style="font-size:11px">${pct(r.root.score)}</span></span>` : `<span class="dim">—</span>`}</td>
        <td class="muted">${ago(r.created)}</td></tr>`).join("") || `<tr><td colspan="8">${empty("NO RUNS", "Nothing matches these filters.")}</td></tr>`}</tbody></table></div></div>
    <div class="row mt"><span class="sp"></span><button class="btn sm" id="prev" ${off <= 0 ? "disabled" : ""}>← Prev</button><span class="muted mono">${d.total ? off + 1 : 0}–${Math.min(off + 40, d.total)}</span><button class="btn sm" id="next" ${off + 40 >= d.total ? "disabled" : ""}>Next →</button></div>`;
  const nav = (o) => { const n = { ...q, offset: o }; Object.keys(n).forEach((k) => !n[k] && delete n[k]); go(`/runs?${new URLSearchParams(n)}`); };
  $$("[data-k]").forEach((b) => (b.onclick = () => { q[b.dataset.k] = b.dataset.v; nav(0); }));
  let t; $("#q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { q.q = e.target.value; nav(0); }, 350); };
  $$("[data-go]").forEach((el) => (el.onclick = () => go(el.dataset.go)));
  $("#prev").onclick = () => nav(Math.max(0, off - 40)); $("#next").onclick = () => nav(off + 40);
}

// ================================================================== TRACE INVESTIGATION
async function investigateLatest() {
  // Prefer a replayable run (demo first); uploaded/external traces can't be replayed.
  const demo = await api("/api/runs?status=failed&split=demo&limit=1");
  const any = await api("/api/runs?status=failed&limit=40");
  const d = { runs: demo.runs.length ? demo.runs : any.runs.filter((r) => r.agent !== "external").slice(0, 1) };
  if (!d.runs.length) d.runs = any.runs.slice(0, 1);
  if (!d.runs.length) { view().innerHTML = empty("NO FAILED RUNS", "Your agent executions are healthy.", `<a class="btn primary" href="#/demo">Run Live Demo</a>`); return; }
  location.replace(`#/investigate/${d.runs[0].run_id}`);
}

function graphSvg(steps, statusOf, { selected, onClick } = {}) {
  const depth = {}, cols = {};
  steps.forEach((s) => { depth[s.sid] = 1 + Math.max(-1, ...s.parents.filter((p) => p in depth).map((p) => depth[p])); (cols[depth[s.sid]] ||= []).push(s); });
  const W = 150, H = 32, GX = 44, GY = 10, P = 16;
  const nC = Object.keys(cols).length, maxR = Math.max(...Object.values(cols).map((c) => c.length));
  const pos = {};
  Object.entries(cols).forEach(([d, list]) => list.forEach((s, j) => { pos[s.sid] = { x: P + d * (W + GX), y: P + (maxR - list.length) * (H + GY) / 2 + j * (H + GY) }; }));
  const w = P * 2 + nC * (W + GX) - GX, h = P * 2 + maxR * (H + GY) - GY;
  const col = { ok: ["#131a23", "#2f3846", "#10b981"], warn: ["#1f1a0e", "#7a5a12", "#f59e0b"], root: ["#3a0f13", "#e5484d", "#ef4444"], hit: ["#211316", "#7f2a2f", "#f4a3a6"], reused: ["#121823", "#2f3846", "#5d6a80"], rerun: ["#17163a", "#7c76ff", "#c3c0ff"], input: ["#131a23", "#2f3846", "#8a93a3"] };
  const edges = steps.flatMap((s) => s.parents.filter((p) => pos[p]).map((p) => {
    const a = pos[p], b = pos[s.sid], x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
    const hot = ["root", "hit"].includes(statusOf(p)) && statusOf(s.sid) === "hit";
    return `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke="${hot ? "#e5484d" : "#2f3846"}" stroke-width="${hot ? 1.6 : 1}" ${hot ? 'stroke-dasharray="4 3"' : ""}/>`;
  })).join("");
  const nodes = steps.map((s) => {
    const k = statusOf(s.sid), [f, b, d] = col[k] || col.ok, p = pos[s.sid], sel = s.sid === selected;
    const lab = stepName(s);
    return `<g class="node" data-sid="${esc(s.sid)}"><rect x="${p.x}" y="${p.y}" width="${W}" height="${H}" rx="6" fill="${f}" stroke="${sel ? "#7c76ff" : b}" stroke-width="${sel || k === "root" ? 1.8 : 1}"/><circle cx="${p.x + 12}" cy="${p.y + H / 2}" r="3.5" fill="${d}"/><text x="${p.x + 23}" y="${p.y + 20}">${esc(lab.length > 19 ? lab.slice(0, 18) + "…" : lab)}</text><title>${esc(s.sid)}\n${esc(summarize(s.output))}</title></g>`;
  }).join("");
  return { html: `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${edges}${nodes}</svg>`, bind: (root) => onClick && $$(".node", root).forEach((g) => (g.onclick = () => onClick(g.dataset.sid))) };
}

async function investigate(id, q) {
  const [run, dx, forks] = await Promise.all([api(`/api/runs/${id}`), api(`/api/runs/${id}/diagnosis`), api(`/api/runs/${id}/forks`).catch(() => ({ runs: [] }))]);
  const failed = !run.success, isFork = !!run.parent_run_id, rc = failed && !isFork ? dx.root_cause : null;
  const by = Object.fromEntries(dx.steps.map((s) => [s.sid, s]));
  const impacted = new Set(rc ? dx.impacted : []);
  const status = (sid) => {
    const s = run.steps.find((x) => x.sid === sid);
    if (isFork) return s?.reused ? "reused" : "rerun";
    if (s?.kind === "input") return "input";
    if (rc && sid === rc.sid) return "root";
    if (impacted.has(sid)) return "hit";
    return by[sid]?.suspicious ? "warn" : "ok";
  };
  const BADGES = { ok: `<span class="st ok">✓ Success</span>`, warn: `<span class="st warn">Anomaly</span>`, hit: `<span class="st hit">Impacted</span>`, reused: `<span class="st reused">↩ Reused</span>`, rerun: `<span class="st rerun">↻ Re-executed</span>`, input: `<span class="st ghost">Input</span>` };
  const rcStep = rc && run.steps.find((s) => s.sid === rc.sid);
  const rcIdx = rcStep ? rcStep.idx : -1;
  const plan = rc ? descendants(run.steps, rc.sid) : new Set();
  let sel = q.step || rc?.sid || run.steps[run.steps.length - 1].sid, tab = "rca", filter = "all";
  const open = new Set(rc ? [rc.sid] : []);
  const total = run.steps.reduce((a, s) => a + s.latency_ms, 0) || 1;
  const localEv = rc ? rc.evidence.filter((e) => !["upstream_clean", "downstream_impact"].includes(e.signal)) : [];
  const deltaEv = localEv.find((e) => e.expected || e.observed);
  const latestFork = forks.runs[0];
  const repairHref = (sid, mode = "repair") => `#/repair/${run.run_id}?sid=${encodeURIComponent(sid)}&mode=${mode}`;

  view().innerHTML = `
    <div class="runbar">
      <span class="rid">RUN ${rid(run.run_id)}<button title="Copy run id" id="cp">${icon("copy")}</button></span>
      ${isFork ? `<span class="st rep">Replay</span>` : statusPill(run.success)}
      <span class="kv">AGENT: <b>${esc(agentName(run))}</b></span><span class="kv">DUR: <b>${ms(run.duration_ms)}</b></span>
      <span class="kv">STEPS: <b>${run.n_steps}</b></span><span class="kv">RECORDED: <b>${ago(run.created)}</b></span><span class="kv muted">${esc(run.split)}</span>
      ${dx.baseline ? `<span class="kv" title="External agents are compared with their own earlier passing runs, never with Black Box's built-in agent.">BASELINE: <b style="color:${dx.baseline.active ? "var(--green-2)" : "var(--amber-2)"}">${dx.baseline.active ? `${dx.baseline.healthy_runs} healthy runs of ${esc(dx.baseline.service)}` : `learning (${dx.baseline.healthy_runs}/${dx.baseline.needed} healthy runs)`}</b></span>` : ""}
    </div>
    <div class="row mt">
      ${rc && run.replayable ? `<a class="btn primary" href="${repairHref(rc.sid)}">${icon("replay")}Replay From Root Cause</a>` : ""}
      ${isFork ? `<a class="btn primary" href="#/compare/${run.parent_run_id}/${run.run_id}">${icon("compare")}Compare With Original</a>` : latestFork ? `<a class="btn" href="#/compare/${run.run_id}/${latestFork.run_id}">${icon("compare")}Compare Executions</a>` : `<button class="btn" disabled title="Run a replay first">${icon("compare")}Compare Executions</button>`}
      <span class="sp"></span><span class="muted" style="font-size:12px"><kbd>↑</kbd><kbd>↓</kbd> steps · <kbd>↵</kbd> expand · <kbd>R</kbd> replay</span>
    </div>
    <div class="kpis mt">
      <div class="kpi"><div class="cap">Root-cause confidence</div><div class="v" style="color:${rc ? "#ff9b9f" : "var(--green-2)"}">${rc ? pct(rc.score, 1) : isFork ? "replay" : "none"}<small>${rc ? `Step ${nn(rcIdx)}` : failed ? "" : "run passed"}</small></div></div>
      <div class="kpi"><div class="cap">Failure risk (trace only)</div><div class="v">${pct(dx.p_fail)}</div></div>
      <div class="kpi"><div class="cap">Blast radius</div><div class="v">${rc ? `${impacted.size} steps` : "—"}<small>${rc ? `${dx.impacted_anomalous.length} anomalous` : ""}</small></div></div>
      <div class="kpi"><div class="cap">Upstream state</div><div class="v" style="color:${!rc || dx.upstream.healthy ? "var(--green-2)" : "#ff9b9f"}">${!rc ? "—" : dx.upstream.healthy ? "Healthy" : `${dx.upstream.anomalous.length} anomalous`}</div></div>
      <div class="kpi"><div class="cap">Final answer</div><div class="v" style="color:${failed ? "#ff9b9f" : "var(--green-2)"};font-size:15px">${esc(summarize(run.final))}</div>${run.expected && Object.keys(run.expected).length ? `<div class="muted" style="font-size:11.5px">expected ${esc(summarize(run.expected))}</div>` : ""}</div>
    </div>
    <div class="split mt">
      <div class="card"><div class="hd"><div class="row"><span style="color:var(--indigo-3)">${icon("list")}</span><h2>EXECUTION TIMELINE</h2><span class="st ghost">${run.n_steps} spans</span></div>
        <div class="filters" id="filters"></div></div>
        <div class="bd"><div class="cap" style="margin-bottom:2px">${esc(run.question)}</div><div class="tlbar" id="tlbar"></div>
          <div class="tlaxis"><span>T+0ms</span>${rc ? `<span>root cause @ T+${Math.round(run.steps.slice(0, rcIdx).reduce((a, s) => a + s.latency_ms, 0))}ms</span>` : ""}<span>${ms(total)} (end)</span></div>
          <div class="steps" id="steps"></div></div></div>
      <div class="card" id="rp"></div>
    </div>`;

  const counts = { all: run.steps.length, anomalies: dx.steps.filter((s) => s.suspicious).length, impacted: impacted.size + (rc ? 1 : 0) };
  const renderFilters = () => {
    $("#filters").innerHTML = [["all", `All steps (${counts.all})`], ["anomalies", `Anomalies (${counts.anomalies})`], ...(rc ? [["impacted", `Root + impacted (${counts.impacted})`]] : [])]
      .map(([k, l]) => `<button data-f="${k}" class="${filter === k ? "on" : ""}">${l}${k === "anomalies" && counts.anomalies ? '<span class="dot"></span>' : ""}</button>`).join("");
    $$("#filters button").forEach((b) => (b.onclick = () => { filter = b.dataset.f; renderFilters(); renderSteps(); }));
  };
  const visible = (s) => filter === "all" || (filter === "anomalies" && by[s.sid]?.suspicious) || (filter === "impacted" && (s.sid === rc?.sid || impacted.has(s.sid)));
  const renderBar = () => {
    $("#tlbar").innerHTML = run.steps.map((s) => `<i class="${status(s.sid)}" data-sid="${esc(s.sid)}" style="width:${Math.max(0.6, (s.latency_ms / total) * 100)}%" title="${esc(stepName(s))} · ${ms(s.latency_ms)}"></i>`).join("");
    $$("#tlbar i").forEach((el) => (el.onclick = () => pick(el.dataset.sid, true)));
  };
  const renderSteps = () => {
    $("#steps").innerHTML = run.steps.map((s) => {
      const k = status(s.sid), isOpen = open.has(s.sid);
      const flag = by[s.sid]?.flags?.[0];
      return `<div class="stp ${k} ${s.sid === sel ? "sel" : ""} ${visible(s) ? "" : "faded"}" data-sid="${esc(s.sid)}">
        <div class="h"><span class="n">${nn(s.idx)}</span>
          <span class="tt"><b>${esc(stepName(s))}</b>${k === "root" ? `<span class="st root">● Root cause identified · ${pct(rc.score, 1)}</span>` : BADGES[k] || ""}${s.error ? `<span class="st hit">${esc(s.error)}</span>` : ""}</span>
          <span class="meta"><span class="tool">${kindLabel(s).toLowerCase()}:${esc(s.name.replace("call:", ""))}</span><span>${ms(s.latency_ms)}</span></span></div>
        <div class="sum">${esc(summarize(s.kind === "llm" ? s.output : s.output))}</div>
        ${k === "root" ? `${deltaEv ? `<div class="anom"><b>${esc(deltaEv.label)}:</b> expected ${esc(deltaEv.expected || "—")} · observed <b>${esc(deltaEv.observed || "—")}</b></div>` : localEv[0] ? `<div class="anom"><b>${esc(localEv[0].label)}:</b> ${esc(localEv[0].text)}</div>` : ""}
          <div class="prop">↳ Downstream failure propagation (${impacted.size} step${impacted.size === 1 ? "" : "s"} impacted)</div>` : ""}
        ${k === "warn" && flag ? `<div class="anom" style="font-size:12.5px"><b>Signal:</b> ${esc(flag.text)}</div>` : ""}
        ${isOpen ? `<div class="det"><div><div class="cap">Input / arguments</div><pre class="json">${jsonHtml(s.args)}</pre></div><div><div class="cap">Output</div><pre class="json">${jsonHtml(s.output)}</pre></div></div>` : ""}
      </div>`;
    }).join("");
    $$("#steps .stp .h").forEach((h) => (h.onclick = () => { const sid = h.parentElement.dataset.sid; open.has(sid) ? open.delete(sid) : open.add(sid); pick(sid); }));
  };

  const renderPanel = () => {
    const tabs = [["rca", "trace", "Root Cause Analysis"], ["insp", "code", "Step Inspector"], ["graph", "graph", "Graph"], ["raw", "list", "Raw Trace"]];
    let body = "";
    if (tab === "rca") body = rc ? rcaPanel() : `<div class="bd">${isFork ? `<div class="banner ok"><span class="ic">${icon("ff")}</span><div><div class="ttl">Replay of ${rid(run.parent_run_id)} from <em>${esc(run.fork_sid)}</em></div><div class="muted" style="font-size:13px">${run.n_reexecuted}/${run.n_steps} steps re-executed (${esc(run.fork_mode)}); the rest reused from the recording.</div></div></div><a class="btn primary mt" href="#/compare/${run.parent_run_id}/${run.run_id}">Original vs repaired</a>`
      : `<div class="banner ok"><span class="ic">${icon("check")}</span><div><div class="ttl">No failure detected</div><div class="muted" style="font-size:13px">This run passed the task check. Black Box still scored every step; see the inspector.</div></div></div>`}</div>`;
    if (tab === "insp") body = inspector();
    if (tab === "graph") { const g = graphSvg(run.steps, status, { selected: sel, onClick: (x) => pick(x) }); body = `<div class="bd"><div class="graph">${g.html}</div><div class="legend mt"><span><i style="background:#ef4444"></i>root cause</span><span><i style="background:#f4a3a6"></i>impacted</span><span><i style="background:#f59e0b"></i>anomaly</span><span><i style="background:#10b981"></i>ok</span></div><div class="muted mt" style="font-size:12px">Edges are OpenTelemetry span links (data flow) and parent spans (control flow).</div></div>`; setTimeout(() => g.bind($("#rp")), 0); }
    if (tab === "raw") body = `<div class="bd"><div class="row"><span class="muted" style="font-size:13px">${run.n_steps} spans recorded via OpenTelemetry</span><span class="sp"></span><button class="btn sm" id="dl">Download JSON</button></div><pre class="json" style="max-height:600px">${jsonHtml(run.steps.map(({ sid, kind, name, parents, args, output, latency_ms, error }) => ({ sid, kind, name, parents, args, output, latency_ms, error })))}</pre></div>`;
    $("#rp").innerHTML = `<div class="tabs">${tabs.map(([k, ic, l]) => `<button data-t="${k}" class="${tab === k ? "on" : ""}">${icon(ic)}${l}</button>`).join("")}</div>${body}`;
    $$("#rp .tabs button").forEach((b) => (b.onclick = () => { tab = b.dataset.t; renderPanel(); }));
    $$("#rp [data-pick]").forEach((c) => (c.onclick = () => pick(c.dataset.pick, true)));
    const dl = $("#dl"); if (dl) dl.onclick = () => { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(run, null, 2)], { type: "application/json" })); a.download = `blackbox_${run.run_id}.json`; a.click(); };
    const rv = $("#reveal"); if (rv) rv.onclick = reveal;
  };
  const rcaPanel = () => {
    const why = localEv.map((e) => e.text).join(" ") || "The model ranked this step highest from the trace signals.";
    return `<div class="bd">
      <div class="rcd"><div class="top2"><span class="lbl">${icon("alert")}LIKELY ROOT CAUSE DETECTED</span><span class="conf">${pct(rc.score, 1)} confidence</span></div>
        <h2>Step ${nn(rcIdx)} — ${esc(stepName(rcStep))}</h2><div class="row"><span class="muted mono" style="font-size:12px">${kindLabel(rcStep)} · ${esc(rc.sid)}</span></div>
        <p class="mono" style="font-size:13px">output → ${esc(summarize(rcStep.output))}</p></div>
      <h3 class="mt2" style="display:flex;gap:8px;align-items:center">${icon("search")}Why this step?</h3>
      <p style="margin:8px 0 0;font-size:14px;color:var(--text-2)">${esc(why)} ${dx.upstream.healthy ? `Every upstream step (${dx.upstream.steps.length}) looks normal, so the problem first appears here.` : ""}</p>
      ${deltaEv ? `<div class="cap mt2">State delta inspection</div><div class="delta"><div class="e"><div class="cap">✓ Expected</div><div class="val">${esc(deltaEv.expected || "—")}</div></div><div class="o"><div class="cap">✕ Observed</div><div class="val">${esc(deltaEv.observed || "—")}</div></div></div>` : ""}
      <div class="row mt2"><h3 style="display:flex;gap:8px;align-items:center">${icon("eye")}Evidence signals</h3><span class="sp"></span><span class="muted" style="font-size:12px">${rc.evidence.length} items · local signals explain ${pct(rc.joint_local)} of the score</span></div>
      ${rc.evidence.map((e, i) => `<div class="ev ${["upstream_clean", "downstream_impact"].includes(e.signal) ? "ctx" : ""}"><span class="num">${i + 1}</span><div><b>${esc(e.label)}</b><div>${esc(e.text)}</div></div></div>`).join("")}
      ${impacted.size ? `<div class="cap mt2">Downstream impact breakdown</div>${[...impacted].slice(0, 6).map((sid) => { const s = run.steps.find((x) => x.sid === sid); return `<div class="impact"><span class="chip" data-pick="${esc(sid)}">Step ${nn(s.idx)} (${esc(stepName(s))})</span><span class="muted">→ ${dx.impacted_anomalous.includes(sid) ? "became anomalous" : "consumed the bad value"}</span></div>`; }).join("")}${impacted.size > 6 ? `<div class="muted mt" style="font-size:12.5px">+${impacted.size - 6} more</div>` : ""}` : ""}
      ${dx.suspects.length > 1 ? `<div class="cap mt2">Other suspects</div><div class="row mt">${dx.suspects.slice(1).map((x) => `<span class="chip" data-pick="${esc(x.sid)}">${esc(stepName(run.steps.find((s) => s.sid === x.sid)))} · ${pct(x.score)}</span>`).join("")}</div>` : ""}
      ${run.replayable ? `<div class="cta mt2"><h3 style="display:flex;gap:8px;align-items:center">${icon("wand")}Ready to patch and verify?</h3>
        <p>Restore the checkpoint at Step ${nn(rcIdx)}, change it, and re-execute only what depends on it: <b class="t1">${run.steps.length - plan.size} steps reused</b>, <b class="t1">${plan.size} re-executed</b>.</p>
        <div class="row"><a class="btn primary" href="${repairHref(rc.sid)}">${icon("ff")}Replay From Here (Step ${nn(rcIdx)})</a><a class="btn" href="${repairHref(rc.sid, "patch_output")}">${icon("code")}Patch output</a></div></div>` : `<div class="muted mt2" style="font-size:12.5px">Recorded from an external agent: diagnosable, not replayable.</div>`}
      ${run.label ? `<div class="mt"><button class="btn sm ghost" id="reveal">Reveal ground-truth label</button><div id="label"></div></div>` : ""}
    </div>`;
  };
  const inspector = () => {
    const s = run.steps.find((x) => x.sid === sel), a = by[sel], k = status(sel);
    return `<div class="bd">
      <div class="row"><span class="n mono" style="color:var(--muted)">STEP ${nn(s.idx)}</span><h2>${esc(stepName(s))}</h2>${k === "root" ? `<span class="st root">Root cause</span>` : BADGES[k] || ""}</div>
      <div class="kpis mt" style="grid-template-columns:repeat(3,1fr)">
        <div class="kpi"><div class="cap">Root-cause score</div><div class="v">${pct(a.score, 1)}<small>rank #${a.rank}</small></div></div>
        <div class="kpi"><div class="cap">Latency</div><div class="v">${ms(s.latency_ms)}</div></div>
        <div class="kpi"><div class="cap">Type</div><div class="v" style="font-size:14px">${kindLabel(s)}</div></div></div>
      <div class="cap mt2">Depends on</div><div class="row mt">${s.parents.map((p) => `<span class="chip" data-pick="${esc(p)}">${esc(stepName(run.steps.find((x) => x.sid === p) || { name: p, kind: "" }))}</span>`).join("") || `<span class="dim">entry step</span>`}</div>
      <div class="cap mt">Used by</div><div class="row mt">${a.children.map((c) => `<span class="chip" data-pick="${esc(c)}">${esc(stepName(run.steps.find((x) => x.sid === c) || { name: c, kind: "" }))}</span>`).join("") || `<span class="dim">—</span>`}</div>
      <div class="cap mt2">Anomaly signals</div>${a.flags.length ? a.flags.map((f) => `<div class="ev"><span class="num" style="background:${f.severity === "high" ? "#9b1c22" : "#8a5a0b"}">!</span><div>${esc(f.text)}</div></div>`).join("") : `<div class="muted mt" style="font-size:13px">No anomaly signals on this step.</div>`}
      <div class="grid g2 mt2"><div><div class="cap">Input / arguments</div><pre class="json">${jsonHtml(s.args)}</pre></div><div><div class="cap">Output</div><pre class="json">${jsonHtml(s.output)}</pre></div></div>
      ${run.replayable && !isFork && s.kind !== "input" ? `<div class="row mt2"><a class="btn primary sm" href="${repairHref(s.sid)}">${icon("replay")}Replay from here</a><a class="btn sm" href="${repairHref(s.sid, "patch_output")}">Patch output</a>${["tool", "retrieval"].includes(s.kind) ? `<a class="btn sm" href="${repairHref(s.sid, "patch_args")}">Patch arguments</a>` : ""}</div>` : ""}
    </div>`;
  };
  const reveal = () => {
    const L = run.label, rank = dx.steps.find((s) => s.sid === L.fault_sid)?.rank;
    $("#label").innerHTML = `<div class="ev ctx mt"><span class="num">i</span><div><b>Ground truth (never shown to the model)</b><div>Injected <span class="mono">${esc(L.fault_type)}</span> at <span class="mono">${esc(L.fault_sid)}</span>${L.heldout ? " · fault type never seen in training" : ""}. ${esc(L.note || L.description)} <b style="color:${rank === 1 ? "var(--green-2)" : "var(--amber-2)"}">Black Box ranked it #${rank}.</b></div></div></div>`;
    $("#reveal").remove();
  };
  function pick(sid, scroll) {
    sel = sid;
    if (tab === "rca" && sid !== rc?.sid) tab = "insp";
    renderSteps(); renderPanel();
    if (scroll) $(`#steps .stp[data-sid="${CSS.escape(sid)}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  KEYHANDLER = (e) => {
    if (/input|textarea|select/i.test(document.activeElement.tagName) || $(".pal-bg")) return;
    const i = run.steps.findIndex((s) => s.sid === sel);
    if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); pick(run.steps[Math.min(run.steps.length - 1, i + 1)].sid, true); }
    else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); pick(run.steps[Math.max(0, i - 1)].sid, true); }
    else if (e.key === "Enter") { open.has(sel) ? open.delete(sel) : open.add(sel); renderSteps(); }
    else if (e.key.toLowerCase() === "r" && rc && run.replayable) go(repairHref(rc.sid));
  };
  document.addEventListener("keydown", KEYHANDLER);
  $("#cp").onclick = () => { navigator.clipboard?.writeText(run.run_id); toast(`Copied ${run.run_id}`); };
  renderFilters(); renderBar(); renderSteps(); renderPanel();
}

// ================================================================== REPLAY & REPAIR
async function repairPicker() {
  const [f0, r] = await Promise.all([api("/api/runs?status=failed&limit=60"), api("/api/replays?limit=6")]);
  const f = { runs: f0.runs.filter((x) => x.agent !== "external").slice(0, 10) };  // only replayable runs
  view().innerHTML = `
    <h1>Replay & Repair</h1><div class="sub">Pick a failed execution. Black Box restores the checkpoint at its diagnosed root cause; you change that step and only its dependents re-run.</div>
    <div class="grid" style="grid-template-columns:minmax(0,1.5fr) minmax(0,1fr)">
      <div class="card"><div class="hd"><h2>Failed executions</h2></div>${f.runs.length ? `<div class="wrap"><table><tbody>${f.runs.map((x) => `<tr class="click" data-go="#/repair/${x.run_id}?sid=${encodeURIComponent(x.root?.sid || "")}">
        <td>${statusPill(false)}</td><td><span class="idlink">${rid(x.run_id)}</span></td><td><div class="trunc t1" style="max-width:280px">${esc(x.question)}</div></td>
        <td><span class="rc"><span class="stepn">${esc((x.root?.sid || "").split(".")[0])}</span><span class="why">${esc(stepName({ name: x.root?.name || "", kind: "" }))}</span></span></td><td class="num"><span class="btn sm">Open ${icon("arrow")}</span></td></tr>`).join("")}</tbody></table></div>`
        : empty("NO FAILED RUNS", "Your agent executions are healthy.", `<a class="btn primary" href="#/demo">Run Live Demo</a>`)}</div>
      <div class="card"><div class="hd"><h2>Recent replays</h2></div>${r.runs.length ? `<div class="wrap"><table><tbody>${r.runs.map((x) => `<tr class="click" data-go="#/compare/${x.parent_run_id}/${x.run_id}"><td><span class="idlink">${rid(x.parent_run_id)}</span></td><td class="muted mono" style="font-size:12px">${esc(x.fork_sid)}</td><td>${x.parent_success === 0 && x.success ? `<span class="st rep">✓ Verified</span>` : statusPill(x.success)}</td></tr>`).join("")}</tbody></table></div>`
        : empty("NO REPLAY YET", "Select a suspicious step to replay from its checkpoint.", `<a class="btn" href="#/investigate">Investigate Trace</a>`)}</div>
    </div>`;
  $$("[data-go]").forEach((el) => (el.onclick = () => go(el.dataset.go)));
}

function codeLines(obj, changedKeys = []) {
  const lines = JSON.stringify(obj, null, 2).split("\n");
  return lines.map((l, i) => { const del = changedKeys.some((k) => l.trim().startsWith(`"${k}"`)); return `<div class="ln ${del ? "del" : ""}"><span>${del ? "−" : ""}${i + 1}</span><span>${esc(l)}</span></div>`; }).join("");
}

async function repairView(id, q) {
  const [run, dx] = await Promise.all([api(`/api/runs/${id}`), api(`/api/runs/${id}/diagnosis`)]);
  if (!run.replayable) { view().innerHTML = empty("REPLAY UNAVAILABLE", "This run came from an external agent; it can be diagnosed but not replayed.", `<a class="btn" href="#/investigate/${id}">Back to investigation</a>`); return; }
  const by = Object.fromEntries(dx.steps.map((s) => [s.sid, s]));
  const rc = run.success ? null : dx.root_cause;
  let sid = q.sid && by[q.sid] ? q.sid : rc?.sid || run.steps[1]?.sid || run.steps[0].sid;
  let mode = q.mode || "repair", draft = null, result = null, error = null, busy = false, note = "";
  const log = [];
  const t0 = performance.now();
  const stamp = () => `[${((performance.now() - t0) / 1000).toFixed(3).padStart(7, "0")}]`;
  const addLog = (cls, txt) => log.push(`<span class="t">${stamp()}</span> <span class="${cls}">${esc(txt)}</span>`);
  const step = () => run.steps.find((s) => s.sid === sid);
  const recorded = () => (mode === "patch_args" ? step().args : step().output);
  addLog("", `Trace ${rid(run.run_id)} loaded: ${run.n_steps} recorded spans.`);

  const shell = () => {
    const s = step(), rerun = descendants(run.steps, sid), reused = run.steps.filter((x) => !rerun.has(x.sid));
    const before = reused.filter((x) => x.idx < s.idx), after = reused.filter((x) => x.idx > s.idx), down = run.steps.filter((x) => rerun.has(x.sid) && x.sid !== sid);
    const isRoot = rc && sid === rc.sid;
    const ev = isRoot ? rc.evidence.find((e) => e.observed) : null;
    const cur = recorded();
    const changed = draft ? diffFields(cur, draft).map((d) => d[0]) : [];
    const banner = result
      ? `<div class="banner ${result.verified || (result.success && result.orig_success) ? "ok" : "bad"}"><span class="ic">${icon(result.success ? "check" : "x")}</span><div class="sp"><div class="ttl">${result.verified ? "Repair verified" : result.success ? "Replay succeeded" : "Repair not verified"} — <em>${result.n_reused} steps reused</em>, <em>${result.n_reexecuted} re-executed</em>${result.path_changed ? ", agent took a new path" : ""}.</div><div class="muted" style="font-size:13px">Original ${esc(summarize(run.final))} → repaired ${esc(summarize(result.final))} · task check expects ${esc(summarize(result.expected))}</div><div class="muted mt" style="font-size:13px">${savingsLine(savings(run.steps, (x) => !result.rerun.includes(x.sid)))}</div></div><a class="btn ${result.verified ? "primary" : ""}" href="#/compare/${id}/${result.run_id}">${icon("compare")}Original vs repaired</a></div>`
      : `<div class="banner"><span class="ic">${icon("ff")}</span><div class="sp"><div class="ttl">Without starting over: <em>${reused.length} steps reused</em>, <em>1 step patched</em>, <em>${down.length} downstream steps</em> scheduled for re-execution.</div><div class="muted" style="font-size:13px">Checkpoint = state after step ${nn(s.idx - 1 < 0 ? 0 : s.idx - 1)}, restored from the recording (event-sourced). ${run.agent.startsWith("react") ? "The agent re-plans after the patch, so the downstream path may change." : ""}</div></div><span class="pill-st">${run.steps.length} total · ${reused.length} reused · ${rerun.size} re-executing</span></div>`;
    view().innerHTML = `
      <div class="crumbs"><span style="color:var(--indigo-3)">${icon("replay")}</span><b class="t1">REPLAY & REPAIR WORKSPACE</b><a href="#/investigate/${id}">RUN ${rid(id)}</a><span>·</span><span>checkpoint at <b class="t1">Step ${nn(s.idx)} (${esc(stepName(s))})</b></span></div>
      ${banner}
      <div class="ws mt">
        <div class="card"><div class="hd"><div class="row"><span style="color:var(--indigo-3)">${icon("graph")}</span><h2>EXECUTION CHECKPOINT TREE</h2></div><span class="muted" style="font-size:12px">click a step to move the checkpoint</span></div>
          <div class="bd tree">
            <div class="grp"><div class="gh"><span class="cap">${icon("check")}Before checkpoint — reused state</span><span class="muted" style="font-size:12px">from recording</span></div>
              ${before.map((x) => `<div class="tnode reused" data-s="${esc(x.sid)}"><span class="n">${nn(x.idx)}</span><div><b>${esc(stepName(x))}</b><small>${esc(summarize(x.output))}</small></div><span class="st reused">✓ Reused</span></div>`).join("") || `<div class="muted" style="font-size:13px">none</div>`}</div>
            <div class="conn">${icon("bolt")}State restored at checkpoint</div>
            <div class="grp"><div class="gh"><span class="cap">${icon("wand")}Checkpoint — active patch target</span><span class="st rerun">Current focus</span></div>
              <div class="tnode focus"><span class="n">${nn(s.idx)}</span><div><b>${esc(stepName(s))} ${isRoot ? `<span class="st root" style="margin-left:6px">Root cause</span>` : ""}</b><small>${mode === "repair" ? "re-run fresh" : mode === "patch_output" ? "output will be patched" : "arguments will be patched"}</small></div><span class="st rerun">${result ? "↻ Replayed" : "Ready"}</span></div></div>
            ${down.length ? `<div class="conn">${icon("down")}Cascading re-execution</div><div class="grp"><div class="gh"><span class="cap">${icon("replay")}Downstream — scheduled for re-execution</span></div>
              ${down.map((x) => `<div class="tnode" data-s="${esc(x.sid)}"><span class="n">${nn(x.idx)}</span><div><b>${esc(stepName(x))}</b><small>${esc(summarize(x.output))}</small></div><span class="st rerun">↻ Re-execute</span></div>`).join("")}</div>` : ""}
            ${after.length ? `<div class="grp"><div class="gh"><span class="cap">${icon("check")}Independent — preserved</span></div>${after.map((x) => `<div class="tnode reused" data-s="${esc(x.sid)}"><span class="n">${nn(x.idx)}</span><div><b>${esc(stepName(x))}</b><small>does not depend on the checkpoint</small></div><span class="st reused">Preserved</span></div>`).join("")}</div>` : ""}
            <div class="cap mt2">Replay effort</div><div class="ratio mt"><div class="ru" style="width:${(reused.length / run.steps.length) * 100}%">${Math.round((reused.length / run.steps.length) * 100)}% REUSED</div><div class="rx" style="width:${(rerun.size / run.steps.length) * 100}%">${Math.round((rerun.size / run.steps.length) * 100)}% RE-RUN</div></div>
          </div></div>
        <div class="grid" style="gap:16px">
          <div class="card"><div class="hd"><div class="row"><span style="color:var(--indigo-3)">${icon("code")}</span><h2>PATCH EDITOR & REPLAY RUNNER</h2></div><span class="st rerun">Step ${nn(s.idx)}: ${esc(stepName(s))}</span></div>
            <div class="bd">
              <div class="row"><div class="seg" id="modes">${[["repair", "Re-run fresh"], ["patch_output", "Patch output"], ["patch_args", "Patch arguments"]].filter(([k]) => k !== "patch_args" || ["tool", "retrieval"].includes(s.kind)).map(([k, l]) => `<button data-m="${k}" class="${mode === k ? "on" : ""}">${l}</button>`).join("")}</div>
                <span class="sp"></span>${run.split === "demo" ? `<button class="btn sm" id="suggest">${icon("wand")}Suggested repair</button>` : ""}</div>
              <div class="row mt"><button class="btn primary" id="run" ${busy ? "disabled" : ""}>${busy ? `<span class="spin"></span> Replaying…` : `${icon("ff")}${mode === "repair" ? "Run Replay" : "Apply Patch & Run Replay"}`}</button>
                ${mode !== "repair" ? `<button class="btn" id="discard">${icon("x")}Discard changes</button>` : ""}<span class="muted" style="font-size:12.5px">${esc(note)}</span></div>
              ${mode === "repair" ? `<div class="editor mt" style="grid-template-columns:1fr"><div><div class="eh"><span>${icon("eye", 'style="vertical-align:-3px"')} Recorded ${s.kind === "llm" ? "decision" : "output"} (will be re-computed)</span><span class="muted">read-only</span></div><pre class="code">${codeLines(s.output)}</pre>
                  ${ev ? `<div class="note r">${icon("alert", 'style="vertical-align:-3px"')} ${esc(ev.label)}: observed ${esc(ev.observed)}${ev.expected ? `, expected ${esc(ev.expected)}` : ""}.</div>` : ""}<div class="note b">Re-run fresh: ${s.kind === "llm" ? "the model makes this decision again from the restored state" : "the real tool is called again with the same inputs"}, then the agent continues.</div></div></div>`
              : `<div class="editor mt">
                  <div class="cur"><div class="eh"><span>⊖ Current ${mode === "patch_args" ? "arguments" : "output"} (recorded)</span><span class="muted">read-only</span></div><pre class="code">${codeLines(cur, changed)}</pre>
                    ${ev ? `<div class="note r">${icon("alert", 'style="vertical-align:-3px"')} ${esc(ev.label)}: observed ${esc(ev.observed)}${ev.expected ? ` · expected ${esc(ev.expected)}` : ""}</div>` : ""}</div>
                  <div class="new"><div class="eh"><span>⊕ Patched ${mode === "patch_args" ? "arguments" : "output"} (proposed fix)</span><span class="muted">editable</span></div><textarea id="patch" spellcheck="false">${esc(JSON.stringify(draft ?? cur, null, 2))}</textarea>
                    <div class="note ${changed.length ? "g" : "b"}" id="vnote">${changed.length ? `Valid JSON · ${changed.length} field(s) change: ${changed.map(esc).join(", ")}` : "Edit the JSON on the left's twin; changed fields are highlighted."}</div></div></div>`}
            </div></div>
          <div class="console"><div class="eh"><span class="cap">${icon("term", 'style="vertical-align:-3px"')} Execution status console</span><button class="btn sm ghost" id="clr">Clear</button></div><pre id="log">${log.join("\n")}</pre></div>
          ${error ? `<div class="errbox"><div class="t">REPLAY FAILED${error.status ? ` · HTTP ${error.status}` : ""}</div><div class="mt">${esc(error.message)}</div><div class="mt"><button class="btn sm" id="retry">Retry</button></div></div>` : ""}
          ${result?.reexecution_error ? `<div class="errbox"><div class="t">CHECKPOINT RESTORED, BUT STEP ${nn(result.reexecution_error.idx)} FAILED DURING RE-EXECUTION</div><div class="mt mono" style="font-size:12.5px">${esc(result.reexecution_error.sid)}: ${esc(result.reexecution_error.error)}</div><pre class="json">${jsonHtml(result.reexecution_error.args)}</pre></div>` : ""}
        </div>
      </div>`;
    bind();
    const lg = $("#log"); if (lg) lg.scrollTop = lg.scrollHeight;
  };
  async function runReplay() {
    let patch = null;
    if (mode !== "repair") {
      try { patch = JSON.parse($("#patch").value); if (typeof patch !== "object" || Array.isArray(patch) || !patch) throw new Error("patch must be a JSON object"); }
      catch (e) { toast(`Patch is not valid: ${e.message}`); return; }
      draft = patch;
    }
    busy = true; error = null;
    const plan = descendants(run.steps, sid);
    addLog("", `Restoring checkpoint before step ${nn(step().idx)} (${run.steps.length - plan.size} recorded steps)…`);
    addLog("", mode === "repair" ? `Re-running ${step().name} fresh.` : `Applying ${mode === "patch_output" ? "output" : "argument"} patch to ${step().name}: ${diffFields(recorded(), patch).map((d) => d[0]).join(", ") || "no field changes"}.`);
    shell();
    try {
      result = await api(`/api/runs/${id}/replay`, { method: "POST", body: JSON.stringify({ sid, mode, patch }) });
      addLog("okk", `Checkpoint restored · ${result.n_reused} steps reused from the recording.`);
      addLog("", `Re-executed ${result.n_reexecuted} steps: ${result.rerun.slice(0, 8).join(", ")}${result.rerun.length > 8 ? "…" : ""}`);
      if (result.path_changed) addLog("", "The agent took a different path after the patch.");
      addLog(result.success ? "okk" : "err", `Task check: ${result.success ? "PASSED" : "FAILED"} · final ${summarize(result.final)}`);
      addLog(result.verified ? "okk" : "", result.verified ? `REPAIR VERIFIED · saved as ${rid(result.run_id)}` : `Saved as ${rid(result.run_id)}`);
    } catch (e) { error = e; addLog("err", `Replay failed: ${e.message}`); }
    busy = false; shell();
  }
  function bind() {
    $$(".tnode[data-s]").forEach((n) => (n.onclick = () => { if (busy) return; sid = n.dataset.s; draft = null; result = null; error = null; note = ""; if (mode === "patch_args" && !["tool", "retrieval"].includes(step().kind)) mode = "repair"; addLog("", `Checkpoint moved to step ${nn(step().idx)} (${step().name}).`); shell(); }));
    $$("#modes button").forEach((b) => (b.onclick = () => { mode = b.dataset.m; draft = null; result = null; error = null; shell(); }));
    $("#run").onclick = runReplay;
    const rt = $("#retry"); if (rt) rt.onclick = runReplay;
    const ds = $("#discard"); if (ds) ds.onclick = () => { draft = null; note = ""; shell(); };
    $("#clr").onclick = () => { log.length = 0; shell(); };
    const ta = $("#patch");
    if (ta) ta.oninput = () => {
      try { const v = JSON.parse(ta.value); const ch = diffFields(recorded(), v); $("#vnote").className = `note ${ch.length ? "g" : "b"}`; $("#vnote").textContent = ch.length ? `Valid JSON · ${ch.length} field(s) change: ${ch.map((d) => d[0]).join(", ")}` : "Valid JSON · no change from the recorded value yet"; }
      catch (e) { $("#vnote").className = "note r"; $("#vnote").textContent = `Invalid JSON: ${e.message}`; }
    };
    const sg = $("#suggest");
    if (sg) sg.onclick = async () => {
      try { const p = await api(`/api/demo/patch/${id}`); sid = p.sid; mode = p.mode; draft = p.patch; note = `suggested from the trace: ${p.source}`; addLog("", `Suggested repair loaded (${p.mode}) — ${p.source}`); shell(); }
      catch (e) { toast(e.message); }
    };
  }
  shell();
}

// ================================================================== COMPARISONS
async function comparisons() {
  const d = await api("/api/replays?limit=100");
  view().innerHTML = `<h1>Comparisons</h1><div class="sub">Every replay next to its original execution. A repair is verified when a failed run passes the task check after replay.</div>
    <div class="card">${d.runs.length ? `<div class="wrap"><table><thead><tr><th>Original</th><th>Replay</th><th>Checkpoint</th><th>Mode</th><th>Outcome</th><th class="num">Re-executed</th><th>Verification</th><th>When</th></tr></thead>
      <tbody>${d.runs.map((r) => `<tr class="click" data-go="#/compare/${r.parent_run_id}/${r.run_id}"><td><span class="idlink">${rid(r.parent_run_id)}</span></td><td class="muted mono" style="font-size:12.5px">${rid(r.run_id)}</td>
        <td class="mono" style="font-size:12.5px">${esc(r.fork_sid)}</td><td class="muted">${esc((r.fork_mode || "").replace("_", " "))}</td><td>${statusPill(r.parent_success)} <span class="dim">→</span> ${statusPill(r.success)}</td>
        <td class="num">${r.n_reexecuted}/${r.n_steps}</td><td>${r.parent_success === 0 && r.success ? `<span class="st rep">✓ Repair verified</span>` : r.success ? `<span class="st ghost">No-op</span>` : `<span class="st fail">Not verified</span>`}</td><td class="muted">${ago(r.created)}</td></tr>`).join("")}</tbody></table></div>`
      : empty("NO REPLAY YET", "Select a suspicious step to replay from its checkpoint.", `<a class="btn primary" href="#/investigate">Investigate Trace</a>`)}</div>`;
  $$("[data-go]").forEach((el) => (el.onclick = () => go(el.dataset.go)));
}

async function compareView(a, b) {
  const [c, ra, rb] = await Promise.all([api(`/api/compare?a=${a}&b=${b}`), api(`/api/runs/${a}`), api(`/api/runs/${b}`)]);
  const dxa = await api(`/api/runs/${a}/diagnosis`).catch(() => null);
  const rootSid = !ra.success && dxa ? dxa.root_cause?.sid : null;
  const latA = ra.steps.reduce((x, s) => x + s.latency_ms, 0), latB = rb.steps.filter((s) => !s.reused).reduce((x, s) => x + s.latency_ms, 0);
  let vp = "side";
  const draw = () => {
    const rows = c.rows;
    view().innerHTML = `
      <div class="crumbs"><span style="color:var(--indigo-3)">${icon("shield")}</span><a href="#/comparisons">COMPARISONS</a><span>/</span><span>diff:${rid(a)}..${rid(b)}</span><span class="sp"></span>${c.b.fork_sid ? `<span>CHECKPOINT: <b class="t1">${esc(c.b.fork_sid)}</b> (${esc((c.b.fork_mode || "").replace("_", " "))})</span>` : ""}</div>
      <div class="row"><div><h1>REPAIR VERIFICATION — ORIGINAL VS REPAIRED</h1><div class="sub" style="margin:4px 0 0">Step-aligned diff of the recorded execution and the replay, with checkpoint reuse.</div></div><span class="sp"></span><a class="btn" href="#/investigate/${a}">Open original</a><a class="btn" href="#/investigate/${b}">Open replay trace</a></div>
      <div class="banner mt ${c.fixed ? "ok" : c.b.success ? "ok" : "bad"}"><span class="ic">${icon(c.fixed || c.b.success ? "check" : "x")}</span>
        <div class="sp"><div class="ttl">${c.fixed ? "✓ REPAIR VERIFIED" : c.b.success ? "Replay succeeded" : "Repair not verified"} · <em>${c.n_rerun} steps re-executed</em> · <em>${c.n_reused} reused</em> · diverged at ${esc(c.first_divergence || "—")}</div>
          <div class="muted" style="font-size:13px">Work to test the fix: <b class="t1">${ms(latB)}</b> of re-executed steps vs <b class="t1">${ms(latA)}</b> for the whole original run${latA ? ` (${Math.round((1 - latB / latA) * 100)}% less)` : ""}.</div><div class="muted" style="font-size:13px">${savingsLine(savings(rb.steps, (x) => x.reused))}</div></div>
        <div class="seg" id="vp"><button data-v="side" class="${vp === "side" ? "on" : ""}">Side-by-side</button><button data-v="table" class="${vp === "table" ? "on" : ""}">Unified</button></div></div>
      ${vp === "side" ? `<div class="cols mt">
        <div class="card"><div class="colh"><h2>${icon("x", 'style="color:#ff9b9f"')}ORIGINAL EXECUTION</h2><div class="row"><span class="st fail">Status: ${ra.success ? "success" : "failed"}</span><span class="muted mono" style="font-size:12px">${ms(latA)}</span></div></div>
          <div style="padding:6px 0">${rows.map((r) => r.before == null ? `<div class="cstep empty">not in original</div>` : `<div class="cstep ${r.sid === rootSid ? "bad" : ""}"><div class="h"><span class="n">${nn(r.idx)}</span><b>${esc(stepName(r))}</b>${r.sid === rootSid ? `<span class="st root">Root cause</span>` : r.changed ? `<span class="st hit">Changed</span>` : `<span class="st ok">OK</span>`}</div>${r.changed ? `<div class="body">${esc(summarize(r.before))}</div>` : ""}</div>`).join("")}</div>
          <div class="colh" style="border-top:1px solid var(--line);border-bottom:0"><span class="muted" style="font-size:13px">${icon("x", 'style="vertical-align:-3px"')} Result: ${esc(summarize(c.a.final))}</span></div></div>
        <div class="card"><div class="colh"><h2>${icon("check", 'style="color:var(--green-2)"')}REPAIRED EXECUTION</h2><div class="row"><span class="st rep">Status: ${c.b.success ? "success ✓" : "failed"}</span><span class="muted mono" style="font-size:12px">${ms(latB)} re-executed</span></div></div>
          <div style="padding:6px 0">${rows.map((r) => r.after == null ? `<div class="cstep empty">removed in replay</div>` : `<div class="cstep ${r.changed && !r.reused ? "good" : ""}"><div class="h"><span class="n">${nn(r.idx)}</span><b>${esc(stepName(r))}</b>${r.reused ? `<span class="st reused">Reused [checkpoint]</span>` : r.status === "added" ? `<span class="st rerun">New path</span>` : r.changed ? `<span class="st rep">${r.sid === c.b.fork_sid ? "Patched & success" : "Re-executed · changed"}</span>` : `<span class="st rerun">Re-executed · same</span>`}</div>${r.changed && !r.reused ? `<div class="body">${esc(summarize(r.after))}</div>` : ""}</div>`).join("")}</div>
          <div class="colh" style="border-top:1px solid var(--line);border-bottom:0"><span class="muted" style="font-size:13px">${icon("check", 'style="vertical-align:-3px"')} Result: ${esc(summarize(c.b.final))} · expected ${esc(summarize(c.expected))}</span></div></div>
      </div>` : `<div class="card mt"><div class="wrap"><table><thead><tr><th>#</th><th>Step</th><th>Original</th><th>Repaired</th><th>Status</th></tr></thead><tbody>${rows.map((r) => `<tr><td class="muted mono">${nn(r.idx)}</td><td class="t1">${esc(stepName(r))}</td><td class="mono" style="font-size:12px;color:${r.changed ? "#ff9b9f" : "var(--muted)"}">${esc(summarize(r.before))}</td><td class="mono" style="font-size:12px;color:${r.changed && !r.reused ? "var(--green-2)" : "var(--muted)"}">${r.reused ? "↩ same (reused)" : esc(summarize(r.after))}</td><td>${r.reused ? `<span class="st reused">Reused</span>` : r.status === "added" ? `<span class="st rerun">Added</span>` : r.status === "removed" ? `<span class="st hit">Removed</span>` : r.changed ? `<span class="st rep">Changed</span>` : `<span class="st rerun">Same</span>`}</td></tr>`).join("")}</tbody></table></div></div>`}
      <div class="card mt"><div class="hd"><div class="row"><span style="color:var(--indigo-3)">${icon("ff")}</span><h2>LATENCY WATERFALL & CHECKPOINT REUSE</h2></div><span class="legend"><span><i style="background:#2a4b8c"></i>original</span><span><i style="background:#b4232a"></i>root cause</span><span><i style="background:#2b3342"></i>reused</span><span><i style="background:#5b54f0"></i>re-executed</span></span></div><div class="bd">
        <div class="wf"><span>${rid(a)}</span><div class="bar">${ra.steps.map((s) => `<i class="${s.sid === rootSid ? "x" : "o"}" style="width:${(s.latency_ms / Math.max(latA, 1)) * 100}%" title="${esc(stepName(s))} · ${ms(s.latency_ms)}">${s.latency_ms / Math.max(latA, 1) > 0.08 ? esc(stepName(s).replace("Decide · ", "")) : ""}</i>`).join("")}</div><b class="t1 mono">${ms(latA)}</b></div>
        <div class="wf"><span class="t1">${rid(b)}</span><div class="bar">${rb.steps.map((s) => `<i class="${s.reused ? "u" : "r"}" style="width:${(s.latency_ms / Math.max(latA, 1)) * 100}%" title="${esc(stepName(s))} · ${s.reused ? "reused (0 ms)" : ms(s.latency_ms)}">${s.latency_ms / Math.max(latA, 1) > 0.08 ? (s.reused ? "reused" : esc(stepName(s).replace("Decide · ", ""))) : ""}</i>`).join("")}</div><b class="t1 mono">${ms(latB)}</b></div>
        <div class="muted" style="font-size:12.5px">Reused segments are drawn at their original length but cost nothing to replay; only the indigo segments were executed again.</div>
      </div></div>`;
    $$("#vp button").forEach((x) => (x.onclick = () => { vp = x.dataset.v; draw(); }));
  };
  draw();
}

// ================================================================== EVALUATION
async function evalView() {
  const [m, info] = await Promise.all([api("/api/metrics"), INFO || api("/api/info")]);
  const L = m.localization, cf = m.counterfactual || {}, v2 = m.version === "v2-graph", K = MAIN(L);
  const SPL = v2 ? [["test", "Seen faults"], ["heldout", "Unseen fault types"], ["drift_loc", "Error source moved"], ["drift_topo", "New agent behaviour"]] : [["test", "Seen faults"], ["heldout", "Unseen fault types"]];
  const names = v2 ? { gnn: "Graph neural network (production)", gbm: "Gradient boosting + lineage features", pagerank: "Personalized PageRank (no training)", first_suspicious: "Rule: first suspicious step", random: "Random step" }
    : { model: "Black Box model", first_suspicious: "Rule: first suspicious step", max_anomaly: "Highest-anomaly step", last_step: "Last step", random: "Random step" };
  const bt = Object.entries(m.by_fault_type).sort((x, y) => (x[1].heldout - y[1].heldout) || (y[1].top1 - x[1].top1));
  view().innerHTML = `<h1>Evaluation</h1><div class="sub">All numbers are read from <code>data/metrics.json</code>, produced by <code>python -m blackbox.cli all</code> on runs never used for training.</div>
    <div class="kpis mb" style="grid-template-columns:repeat(${SPL.length + 2},1fr)">
      ${SPL.map(([k, l]) => `<div class="kpi"><div class="cap">${l}</div><div class="v" style="color:var(--indigo-3);font-size:22px">${pct(L[k][K].top1, 1)}</div><div class="muted" style="font-size:12px">top-1 · top-3 ${pct(L[k][K].top3, 1)} · n=${L[k][K].n}</div></div>`).join("")}
      <div class="kpi"><div class="cap">Fixed by #1 suspect</div><div class="v" style="color:var(--green-2);font-size:22px">${pct(cf.confirm_top1, 1)}</div></div>
      <div class="kpi"><div class="cap">Fixed ≤ 3 replays</div><div class="v" style="color:var(--green-2);font-size:22px">${pct(cf.fixed_within_3, 1)}</div></div></div>
    <div class="card"><div class="hd"><h2>Root-cause localization · top-1 (top-3)</h2><span class="muted mono" style="font-size:12px">run-failure AUC ${m.run_failure_auc.toFixed(3)}</span></div><div class="wrap"><table>
      <thead><tr><th>Method</th>${SPL.map(([, l]) => `<th class="num">${l}</th>`).join("")}</tr></thead>
      <tbody>${Object.keys(names).filter((k) => L.test[k]).map((k) => `<tr ${k === K ? 'style="background:var(--indigo-t)"' : ""}><td>${k === K ? `<b class="t1">${names[k]}</b>` : names[k]}</td>${SPL.map(([sp]) => `<td class="num">${pct(L[sp][k].top1, 1)} <span class="dim">(${pct(L[sp][k].top3)})</span></td>`).join("")}</tr>`).join("")}</tbody></table></div>
      ${v2 ? `<div class="bd muted" style="font-size:13px"><b class="t1">Error source moved:</b> training fault types injected at locations never faulted in training. <b class="t1">New agent behaviour:</b> a different policy, so graph shapes never seen in training. The GNN is best or tied on 3 of 4 splits; gradient boosting is slightly ahead when the error source moves.</div>` : ""}</div>
    <div class="grid g2 mt">
      <div class="card"><div class="hd"><h2>Top-1 by failure type</h2><span class="legend"><span><i style="background:var(--indigo-2)"></i>seen</span><span><i style="background:var(--amber)"></i>never seen</span></span></div><div class="bd">
        ${bt.map(([k, v]) => `<div class="hbar" title="${esc(v.desc)}"><span class="mono" style="font-size:12.5px">${esc(k)}</span><div class="track"><i class="${v.heldout ? "amber" : ""}" style="width:${v.top1 * 100}%"></i></div><b>${pct(v.top1)}</b></div>`).join("")}</div></div>
      <div class="card"><div class="hd"><h2>Replay · reuse instead of re-running</h2></div><div class="bd">
        <div class="hbar"><span>Steps per repaired run</span><div class="track"><i class="gray" style="width:100%"></i></div><b>${cf.avg_steps?.toFixed(1)}</b></div>
        <div class="hbar"><span class="t1">Re-executed by Black Box</span><div class="track"><i style="width:${(cf.reexec_ratio || 0) * 100}%"></i></div><b>${cf.avg_reexec?.toFixed(1)}</b></div>
        ${cf.avg_reused != null ? `<div class="hbar"><span>Reused from recording</span><div class="track"><i class="green" style="width:${(1 - (cf.reexec_ratio || 0)) * 100}%"></i></div><b>${cf.avg_reused?.toFixed(1)}</b></div>` : ""}
        <div class="cap mt2">Methodology</div><div class="mt" style="font-size:13.5px">${num(m.corpus.runs)} runs (${num(m.corpus.steps)} steps), one injected fault per faulty run. Features come only from the observable trace; labels are never shown to the model.</div>
        <div class="row mt"><span class="cap">Training</span>${info.train_faults.map((f) => `<span class="chip">${f}</span>`).join("")}</div>
        <div class="row mt"><span class="cap">Held-out</span>${info.heldout_faults.map((f) => `<span class="chip" style="color:var(--amber-2)">${f}</span>`).join("")}</div></div></div>
    </div>`;
}

// ================================================================== LIVE DEMO
async function demoView() {
  const S = {};
  const STEPS = [["Run the agent", "detect"], ["Agent fails", "detect"], ["Black Box detects the failure", "detect"], ["Root cause identified", "explain"], ["Why it was flagged", "explain"],
    ["Replay from checkpoint", "replay"], ["Patch applied", "repair"], ["Only affected steps re-executed", "repair"], ["Original vs repaired", "verify"], ["Repair verified", "verify"]];
  let i = 0, auto = false, busy = false;
  const cards = [];
  const evHtml = (rc) => rc.evidence.map((e, k) => `<div class="ev ${["upstream_clean", "downstream_impact"].includes(e.signal) ? "ctx" : ""}"><span class="num">${k + 1}</span><div><b>${esc(e.label)}</b><div>${esc(e.text)}</div></div></div>`).join("");
  const actions = [
    async () => { const r = await api("/api/demo/killer", { method: "POST" }); S.id = r.run_id; S.run = await api(`/api/runs/${S.id}`);
      return `<div class="t1" style="font-size:15px">${esc(S.run.question)}</div><div class="row mt"><span class="st ${S.run.agent === "react-slm" ? "rep" : "ghost"}">${esc(agentName(S.run))}</span><span class="st rerun">OpenTelemetry trace · ${S.run.n_steps} spans</span></div>${S.run.meta?.note ? `<div class="muted mt" style="font-size:12.5px">${esc(S.run.meta.note)}</div>` : ""}`; },
    async () => `<div class="delta"><div class="o"><div class="cap">Agent answer</div><div class="val">${esc(summarize(S.run.final))}</div></div><div class="e"><div class="cap">Task check expects</div><div class="val">${esc(summarize(S.run.expected))}</div></div></div>`,
    async () => { S.dx = await api(`/api/runs/${S.id}/diagnosis`); return `<div class="row"><span class="st fail">Task check failed</span><span class="muted">failure risk from the trace alone: <b class="t1">${pct(S.dx.p_fail)}</b> · ${S.dx.steps.filter((s) => s.suspicious).length} step(s) carry anomaly signals</span></div>`; },
    async () => { S.rc = S.dx.root_cause; const s = S.run.steps.find((x) => x.sid === S.rc.sid); return `<div class="rcd"><div class="top2"><span class="lbl">${icon("alert")}LIKELY ROOT CAUSE DETECTED</span><span class="conf">${pct(S.rc.score, 1)} confidence</span></div><h2>Step ${nn(s.idx)} — ${esc(stepName(s))}</h2></div>`; },
    async () => { const d = S.rc.evidence.find((e) => e.expected || e.observed); return `${d ? `<div class="delta"><div class="e"><div class="cap">✓ Expected</div><div class="val">${esc(d.expected || "—")}</div></div><div class="o"><div class="cap">✕ Observed</div><div class="val">${esc(d.observed || "—")}</div></div></div>` : ""}${evHtml(S.rc)}`; },
    async () => { const re = descendants(S.run.steps, S.rc.sid); return `<div class="ratio"><div class="ru" style="width:${((S.run.steps.length - re.size) / S.run.steps.length) * 100}%">${S.run.steps.length - re.size} REUSED</div><div class="rx" style="width:${(re.size / S.run.steps.length) * 100}%">${re.size} RE-RUN</div></div><div class="muted mt" style="font-size:13px">Checkpoint restored at <b class="t1">${esc(S.rc.sid)}</b>; unaffected steps come straight from the recording.</div>`; },
    async () => { S.patch = await api(`/api/demo/patch/${S.id}`); if (S.patch.mode === "repair") return `<div class="row"><span class="st rerun">Re-run fresh</span><span class="mono t1" style="font-size:13px">${esc(S.patch.source)}</span></div>`;
      const cur = S.run.steps.find((x) => x.sid === S.patch.sid).output; return `${diffFields(cur, S.patch.patch).map(([k, a, b]) => `<div class="row mono" style="font-size:13px"><span class="muted" style="width:110px">${esc(k)}</span><span style="color:#ff9b9f;text-decoration:line-through">${esc(JSON.stringify(a))}</span><span class="dim">→</span><span style="color:var(--green-2)">${esc(JSON.stringify(b))}</span></div>`).join("")}<div class="muted mt" style="font-size:12.5px">Fix derived from the trace: “${esc(S.patch.source)}”</div>`; },
    async () => { S.res = await api(`/api/runs/${S.id}/replay`, { method: "POST", body: JSON.stringify({ sid: S.patch.sid, mode: S.patch.mode, patch: S.patch.patch }) });
      return `<div class="row"><span class="st rerun">${S.res.n_reexecuted} re-executed</span><span class="st reused">${S.res.n_reused} reused</span>${S.res.path_changed ? `<span class="st warn">Agent took a new path</span>` : ""}<span class="muted" style="font-size:12.5px">a full re-run would execute ${S.res.n_total}</span></div><div class="muted mt" style="font-size:13px">${savingsLine(savings(S.run.steps, (x) => !S.res.rerun.includes(x.sid)))}</div>`; },
    async () => { S.cmp = await api(`/api/compare?a=${S.id}&b=${S.res.run_id}`); return `<div class="muted" style="font-size:13px">Execution diverged at <b class="t1 mono">${esc(S.cmp.first_divergence)}</b> · ${S.cmp.n_changed} steps changed</div>${S.cmp.rows.filter((r) => r.changed).slice(0, 6).map((r) => `<div class="row mono mt" style="font-size:12.5px"><span class="t1" style="width:180px">${esc(stepName(r))}</span><span style="color:#ff9b9f">${esc(summarize(r.before))}</span><span class="dim">→</span><span style="color:var(--green-2)">${esc(summarize(r.after))}</span></div>`).join("")}`; },
    async () => `<div class="banner ${S.res.verified ? "ok" : "bad"}"><span class="ic">${icon(S.res.verified ? "check" : "x")}</span><div class="sp"><div class="ttl">${S.res.verified ? "REPAIR VERIFIED" : "Repair not verified"} — <em>${esc(summarize(S.run.final))}</em> → <em>${esc(summarize(S.res.final))}</em></div><div class="muted" style="font-size:13px">From failure to fix without starting over: ${S.res.n_reexecuted} of ${S.res.n_total} steps re-run.</div></div><a class="btn primary" href="#/compare/${S.id}/${S.res.run_id}">Full comparison</a><a class="btn" href="#/investigate/${S.id}">Investigate</a></div>`,
  ];
  const render = () => {
    view().innerHTML = `<div class="row mb"><div><h1>Live Demo</h1><div class="sub" style="margin:4px 0 0">${INFO?.llm?.slm_available ? `A real model (${esc(INFO.llm.slm)}) drives the agent.` : "The benchmark agent drives the run (no real model configured here)."} Every step below calls the live backend.</div></div><span class="sp"></span>
        ${i >= STEPS.length ? `<button class="btn primary" id="restart">${icon("replay")}Restart</button>` : `<button class="btn" id="all" ${busy ? "disabled" : ""}>${auto ? "Running…" : "Run all"}</button><button class="btn primary" id="next" ${busy ? "disabled" : ""}>${busy ? `<span class="spin"></span>` : i === 0 ? `${icon("demo")}Start demo` : "Next step →"}</button>`}</div>
      <div class="grid" style="grid-template-columns:300px minmax(0,1fr);align-items:start">
        <div class="card" style="position:sticky;top:76px"><ul class="dlist">${STEPS.map(([t, st], j) => `<li class="${j < i ? "done" : j === i ? "now" : ""}"><span class="n">${j < i ? "✓" : j + 1}</span><span>${t}<div class="dim mono" style="font-size:10.5px">${st.toUpperCase()}</div></span></li>`).join("")}</ul></div>
        <div id="cards">${cards.length ? cards.join("") : `<div class="card">${empty("READY", "Press <b>Start demo</b>: a tool-calling travel agent estimates a trip, a tool returns bad data, and the run fails. Then watch Black Box detect, explain, replay, repair and verify.")}</div>`}</div>
      </div>`;
    const n = $("#next"); if (n) n.onclick = next;
    const a = $("#all"); if (a) a.onclick = runAll;
    const restart = () => { i = 0; cards.length = 0; auto = false; Object.keys(S).forEach((k) => delete S[k]); render(); };
    const r = $("#restart"); if (r) r.onclick = restart;
    $$("[data-restart]").forEach((b) => (b.onclick = restart));
  };
  async function next() {
    if (busy || i >= STEPS.length) return;
    busy = true; render();
    try { const html = await actions[i](); cards.push(`<div class="dcard"><div class="dh"><span class="cap">STEP ${nn(i)} · ${STEPS[i][1].toUpperCase()}</span><h3>${STEPS[i][0]}</h3></div>${html}</div>`); i++; }
    catch (e) {
      if (e.status === 404 && S.id && !S.recovered) {
        // Free hosting wipes runtime data when the server restarts: start the demo again from Step 1.
        Object.keys(S).forEach((k) => delete S[k]); S.recovered = true;
        cards.length = 0; i = 0;
        cards.push(`<div class="banner"><span class="ic">${icon("replay")}</span><div><div class="ttl">The server restarted and lost this run</div><div class="muted" style="font-size:13px">Free hosting resets its data on restart. Re-running the demo from Step 1…</div></div></div>`);
        busy = false; render();
        if (!auto) setTimeout(runAll, 400);
        return;
      }
      if (cards.length && cards[cards.length - 1].startsWith('<div class="errbox"')) cards.pop();
      cards.push(`<div class="errbox"><div class="t">STEP ${i + 1} FAILED${e.status ? ` · HTTP ${e.status}` : ""}</div><div class="mt">${esc(e.message)}</div><div class="mt"><button class="btn sm" data-restart>${icon("replay")}Restart demo</button></div></div>`);
      auto = false;
    }
    busy = false; render();
    $$("#cards > *").pop()?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  async function runAll() { auto = true; while (auto && i < STEPS.length) { await next(); await new Promise((r) => setTimeout(r, 700)); } auto = false; render(); }
  render();
}

// ================================================================== CONNECT YOUR AGENT
async function connectView() {
  const opt = await api("/api/connect/options");
  const origin = location.origin;
  let strategy = "running_total", bug = "cents", snip = "python", busy = false;
  const SNIP = {
    python: `# Any agent, any framework: send one JSON trace per run (standard library only)
import json, urllib.request

trace = {
    "question": "Refund order A-1042",
    "service": "my-support-bot",          # Black Box learns a baseline per service
    "success": False,                     # did your own check pass?
    "steps": [
        {"id": "task", "name": "task", "kind": "input", "output": {"order_id": "A-1042"}},
        {"id": "t1", "name": "get_order", "kind": "tool", "parents": ["task"],
         "args": {"order_id": "A-1042"}, "output": {"total": 59.99}},
        {"id": "d1", "name": "call:issue_refund", "kind": "llm", "parents": ["t1", "task"],
         "output": {"tool": "issue_refund", "args": {"amount": 599.9}}},
    ],
}
req = urllib.request.Request("${origin}/api/traces", data=json.dumps(trace).encode(),
                             headers={"Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req)))   # {"runs": ["<run id>"]}`,
    curl: `curl -X POST ${origin}/api/traces \\
  -H "Content-Type: application/json" \\
  -d @trace.json
# -> {"runs": ["<run id>"]}   then open ${origin}/app#/investigate/<run id>`,
    otel: `// OpenTelemetry (OTLP/HTTP JSON). Node.js example:
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";   // sends JSON
const exporter = new OTLPTraceExporter({ url: "${origin}/api/otlp/v1/traces" });

// Span conventions Black Box reads:
//   gen_ai.operation.name = "chat" (model decision) | "execute_tool" (tool call)
//   gen_ai.tool.name, blackbox.args / blackbox.output (JSON strings)
//   span parent = control flow, span links = data flow

# Python / other languages: route through an OpenTelemetry Collector
exporters:
  otlphttp/blackbox:
    endpoint: ${origin}/api/otlp
    encoding: json`,
  };
  view().innerHTML = `
    <h1>Connect your agent</h1><div class="sub">Black Box is not tied to its demo agent. Any agent that can send a trace (one JSON object per run, or OpenTelemetry spans) gets the same diagnosis. Try it three ways, no account needed.</div>
    <div class="steps3">
      <div class="card"><div class="hd"><div class="row"><span class="n3">1</span><h2>Try a different agent</h2></div><span class="st ghost">no setup</span></div><div class="bd">
        <p class="muted" style="margin:0 0 12px;font-size:13.5px">A grocery-budget agent that has nothing to do with the travel demo. Pick how it works and what goes wrong. It sends a real OpenTelemetry trace to this server.</p>
        <div class="cap">Strategy (changes the trace graph)</div>
        <div class="seg mt" id="strat">${Object.entries(opt.strategies).map(([k, d]) => `<button data-v="${k}" title="${esc(d)}" class="${k === strategy ? "on" : ""}">${titleCase(k)}</button>`).join("")}</div>
        <div class="muted mt" style="font-size:12.5px" id="sdesc"></div>
        <div class="cap mt2">Bug to inject</div>
        <div class="seg mt" id="bugs">${Object.keys(opt.bugs).map((k) => `<button data-v="${k}" class="${k === bug ? "on" : ""}">${k === "none" ? "No bug" : titleCase(k)}</button>`).join("")}</div>
        <div class="muted mt" style="font-size:12.5px" id="bdesc"></div>
        <button class="btn primary mt2" id="runs">${icon("demo")}Run sample agent</button>
        <div id="sres"></div>
      </div></div>
      <div class="card"><div class="hd"><div class="row"><span class="n3">2</span><h2>Upload a trace</h2></div><span class="st ghost">JSON</span></div><div class="bd">
        <p class="muted" style="margin:0 0 12px;font-size:13.5px">Drop a trace file from your own agent, or load the example: a support bot that refunds <b class="t1">$599.90</b> for a <b class="t1">$59.99</b> order.</p>
        <label class="drop" id="drop"><input type="file" id="file" accept=".json,application/json" hidden>${icon("upload")}<span>Drop a .json trace here or <u>choose a file</u></span></label>
        <textarea id="tjson" spellcheck="false" placeholder='{"question": "...", "steps": [{"name": "...", "kind": "tool", "args": {}, "output": {}}]}'></textarea>
        <div class="row mt"><button class="btn sm" id="ex">Load example</button><a class="btn sm ghost" href="/static/example_trace.json" download>Download example</a><span class="sp"></span><button class="btn primary" id="up">${icon("search")}Diagnose trace</button></div>
        <div class="muted mt" style="font-size:12px">Accepted: Black Box's simple format (above) or OTLP/HTTP JSON (<code>resourceSpans</code>). Step kinds: <code>input</code>, <code>llm</code>, <code>tool</code>, <code>retrieval</code>, <code>final</code>. <code>parents</code> lists the earlier steps whose output this step used.</div>
        <div id="ures"></div>
      </div></div>
    </div>
    <div class="card mt"><div class="hd"><div class="row"><span class="n3">3</span><h2>Send traces from your code</h2></div><div class="seg" id="snips"><button data-v="python" class="on">Python</button><button data-v="curl">curl</button><button data-v="otel">OpenTelemetry</button></div></div>
      <div class="bd"><div class="row" style="font-size:13px"><span class="muted">Endpoint</span><code class="ep">${origin}/api/traces</code><button class="btn sm ghost" id="cpep">${icon("copy")}Copy</button><span class="sp"></span><a class="muted" href="/docs" target="_blank">API reference →</a></div>
        <div style="position:relative"><pre class="json mt" id="snip"></pre><button class="btn sm cpbtn" id="cpsn">${icon("copy")}Copy</button></div>
        <div class="muted" style="font-size:12.5px">How accuracy works for a new agent: rules that need no history (made-up values, missing inputs, errors) work from the first trace. Value checks such as "this price is 100× its usual value" switch on after ${3} passing runs of the same <code>service</code>, because Black Box compares each agent only with its own history. Replay from a checkpoint is available for the built-in agent; uploaded traces are diagnosis-only.</div></div></div>`;
  const desc = () => { $("#sdesc").textContent = opt.strategies[strategy]; $("#bdesc").textContent = opt.bugs[bug]; };
  const segs = (id, set) => $$(`#${id} button`).forEach((b) => (b.onclick = () => { $$(`#${id} button`).forEach((x) => x.classList.toggle("on", x === b)); set(b.dataset.v); desc(); }));
  segs("strat", (v) => (strategy = v)); segs("bugs", (v) => (bug = v));
  segs("snips", (v) => { snip = v; $("#snip").textContent = SNIP[v]; });
  $("#snip").textContent = SNIP[snip]; desc();
  const copy = (t) => { navigator.clipboard?.writeText(t); toast("Copied"); };
  $("#cpep").onclick = () => copy(`${origin}/api/traces`); $("#cpsn").onclick = () => copy(SNIP[snip]);

  const diagCard = async (rid, head) => {
    const [run, dx] = await Promise.all([api(`/api/runs/${rid}`), api(`/api/runs/${rid}/diagnosis`)]);
    const rc = dx.root_cause, st = run.steps.find((x) => x.sid === rc.sid), ev = rc.evidence.find((e) => !["upstream_clean", "downstream_impact"].includes(e.signal)) || rc.evidence[0];
    const base = dx.baseline;
    return `<div class="rescard mt2">${head}
      ${run.success ? `<div class="banner ok mt"><span class="ic">${icon("check")}</span><div><div class="ttl">Run passed: no failure to diagnose</div><div class="muted" style="font-size:13px">It still counts toward this agent's baseline (${base ? base.healthy_runs : 0} healthy runs so far).</div></div></div>`
      : `<div class="rcd mt"><div class="top2"><span class="lbl">${icon("alert")}ROOT CAUSE</span><span class="conf">${pct(rc.score, 1)} confidence</span></div><h2>Step ${nn(st.idx)} — ${esc(stepName(st))}</h2><p>${esc(ev?.text || "")}</p></div>`}
      <div class="row mt" style="font-size:12.5px"><span class="muted">${run.n_steps} steps · baseline: ${base ? (base.active ? `${base.healthy_runs} healthy runs of ${esc(base.service)}` : `learning (${base.healthy_runs}/${base.needed})`) : "—"}</span><span class="sp"></span><a class="btn sm primary" href="#/investigate/${rid}">Investigate full trace ${icon("arrow")}</a></div></div>`;
  };
  $("#runs").onclick = async () => {
    if (busy) return; busy = true; const b = $("#runs"); b.disabled = true; b.innerHTML = `<span class="spin"></span> Running agent…`;
    try {
      const r = await api("/api/connect/sample", { method: "POST", body: JSON.stringify({ strategy, bug }) });
      $("#sres").innerHTML = await diagCard(r.run_id, `<div class="row" style="font-size:13px">${r.success ? `<span class="st ok">Passed</span>` : `<span class="st fail">Failed</span>`}<span class="muted">answer <b class="t1">${money(r.total)}</b> · correct <b class="t1">${money(r.expected)}</b> · ${r.n_spans} spans</span></div>
        ${r.bug_item ? `<div class="muted mt" style="font-size:12.5px">Ground truth (hidden from Black Box): the bug hit <b class="t1">${esc(r.bug_item)}</b>.</div>` : ""}
        ${r.warmup_runs ? `<div class="muted mt" style="font-size:12.5px">First use: ${r.warmup_runs} clean runs were recorded first so Black Box knows this agent's normal.</div>` : ""}`);
    } catch (e) { $("#sres").innerHTML = `<div class="errbox mt2"><div class="t">RUN FAILED</div><div class="mt">${esc(e.message)}</div></div>`; }
    busy = false; b.disabled = false; b.innerHTML = `${icon("demo")}Run sample agent`;
  };
  $("#ex").onclick = async () => { $("#tjson").value = await (await fetch("/static/example_trace.json")).text(); };
  const loadFile = (f) => { if (!f) return; if (f.size > 2e6) return toast("File too large (max 2 MB)"); f.text().then((t) => ($("#tjson").value = t)); };
  $("#file").onchange = (e) => loadFile(e.target.files[0]);
  const dz = $("#drop");
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("over"); };
  dz.ondragleave = () => dz.classList.remove("over");
  dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("over"); loadFile(e.dataTransfer.files[0]); };
  $("#up").onclick = async () => {
    let payload;
    try { payload = JSON.parse($("#tjson").value); } catch (e) { $("#ures").innerHTML = `<div class="errbox mt2"><div class="t">NOT VALID JSON</div><div class="mt">${esc(e.message)}</div></div>`; return; }
    const b = $("#up"); b.disabled = true; b.innerHTML = `<span class="spin"></span> Diagnosing…`;
    try { const r = await api("/api/traces", { method: "POST", body: JSON.stringify(payload) }); $("#ures").innerHTML = await diagCard(r.runs[0], ""); }
    catch (e) { $("#ures").innerHTML = `<div class="errbox mt2"><div class="t">TRACE REJECTED${e.status ? ` · HTTP ${e.status}` : ""}</div><div class="mt">${esc(e.message)}</div></div>`; }
    b.disabled = false; b.innerHTML = `${icon("search")}Diagnose trace`;
  };
}

// ================================================================== HOW IT WORKS
async function aboutView() {
  view().innerHTML = `<h1>How Black Box works</h1><div class="sub">Observability tells you what happened. Black Box is designed to turn it into an actionable debugging workflow.</div>
    <div class="grid g3">${[["1 · Record", "trace", "Every model decision and tool call is an OpenTelemetry span (GenAI conventions). Parent spans give control flow; span links give data flow. Any instrumented agent can send OTLP traces to /api/otlp/v1/traces."],
      ["2 · Localize", "graph", "A graph neural network passes messages along the trace graph using only per-step facts (grounding, deviation from history, errors) and ranks the likely root cause. It is evaluated on unseen fault types, moved error sources and new agent behaviour."],
      ["3 · Explain", "eye", "Evidence comes from re-scoring with each signal removed, shown as expected vs observed values taken from the trace."],
      ["4 · Replay", "replay", "State at any step is the fold of recorded outputs, so the checkpoint is restored without re-running anything before it."],
      ["5 · Repair", "wand", "Re-run the step fresh, patch its output or its arguments. The agent continues on its own and may take a new path; unchanged tool calls are reused."],
      ["6 · Verify", "shield", "The repaired run is judged against the task check and diffed step-by-step against the original."]].map(([t, ic, d]) => `<div class="card"><div class="bd"><div class="row"><span style="color:var(--indigo-3)">${icon(ic)}</span><h2>${t}</h2></div><p class="muted" style="margin:10px 0 0;font-size:13.5px;line-height:1.6">${d}</p></div></div>`).join("")}</div>
    <div class="card mt"><div class="bd muted" style="font-size:13px">Scope: the model is trained and evaluated on one travel-expense workflow with injected faults. The live agent is a real model (Ollama locally, Groq when hosted) or the benchmark policy; each run is labelled with what drove it.</div></div>`;
}

// ================================================================== boot
(async () => { await refreshShell(); router(); })();
