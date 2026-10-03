/* BLACK BOX — AI Agent Flight Recorder.  DETECT → EXPLAIN → REPLAY → REPAIR → VERIFY
   Plain ES2020, no build step. Every number shown comes from the API. */
"use strict";

// ------------------------------------------------------------------ utils
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = () => $("#view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
const num = (x) => (x == null ? "—" : Number(x).toLocaleString());
const ms = (x) => (x == null ? "—" : x >= 1000 ? `${(x / 1000).toFixed(2)}s` : `${Math.round(x)}ms`);
const money = (x) => (x == null ? "—" : `$${Number(x).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const ago = (t) => { if (!t) return "—"; const s = Date.now() / 1000 - t; if (s < 60) return "just now"; if (s < 3600) return `${Math.floor(s / 60)}m ago`; if (s < 86400) return `${Math.floor(s / 3600)}h ago`; return new Date(t * 1000).toLocaleDateString(); };
const st = (ok) => (ok ? `<span class="b ok">SUCCESS</span>` : `<span class="b fail">FAILED</span>`);
const kind = (k) => `<span class="kind ${esc(k)}">${esc((k || "").toUpperCase())}</span>`;
const short = (id) => `#${String(id).slice(0, 6).toUpperCase()}`;
const go = (h) => { location.hash = h; };

const ICON = {
  detect: '<path d="M12 3 2 21h20L12 3z"/><path d="M12 10v4"/><path d="M12 17.5v.01"/>',
  explain: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  replay: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  repair: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
  verify: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  overview: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
  runs: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  compare: '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="M6 9v6a3 3 0 0 0 3 3h6"/><path d="M18 15V9a3 3 0 0 0-3-3H9"/>',
  eval: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  demo: '<path d="m6 4 14 8-14 8z"/>',
  check: '<path d="m5 12 5 5 9-10"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>', arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
};
const icon = (n) => `<svg class="i" viewBox="0 0 24 24">${ICON[n] || ""}</svg>`;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    const e = new Error(typeof msg === "string" ? msg : JSON.stringify(msg)); e.status = r.status; throw e;
  }
  return r.json();
}
function toast(msg) { const t = document.createElement("div"); t.className = "toast"; t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), 6000); }
function jsonHtml(o) {
  return esc(JSON.stringify(o, null, 2)).replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false|null)\b|(-?\d+\.?\d*(?:e[+-]?\d+)?)/g,
    (m, s, c, b, n) => s ? (c ? `<span class="k">${s}</span>${c}` : `<span class="s">${s}</span>`) : b ? `<span class="bo">${b}</span>` : `<span class="n">${n}</span>`);
}
function summarize(o) {
  if (o == null) return "—";
  if (typeof o !== "object") return String(o);
  if (o.error) return `error: ${o.error}`;
  if (o.tool && o.args) return `${o.tool}(${Object.values(o.args).map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(", ")})`;
  if (o.question) return `"${o.question.slice(0, 50)}…"`;
  if (o.total_usd != null) return `${money(o.total_usd)} · ${o.within_budget ? "within" : "over"} budget`;
  if (o.text) return `"${o.text.slice(0, 44)}…"`;
  for (const k of ["value", "usd", "rate", "amount"]) if (o[k] != null) return `${k}: ${typeof o[k] === "number" ? o[k].toLocaleString(undefined, { maximumFractionDigits: 6 }) : o[k]}${o.currency ? " " + o.currency : ""}`;
  if (o.within_budget != null) return `within_budget: ${o.within_budget} (margin ${o.margin})`;
  if (o.legs) return `${o.legs.length} leg(s), ${o.travelers ?? "?"} traveler(s), budget ${o.budget ?? "?"}`;
  if (o.note) return o.note;
  const s = JSON.stringify(o); return s.length > 56 ? s.slice(0, 56) + "…" : s;
}
const empty = (t, msg, btn = "") => `<div class="empty"><div class="t">${t}</div><div>${msg}</div>${btn ? `<div class="mt">${btn}</div>` : ""}</div>`;
const loading = () => { view().innerHTML = `<div class="empty"><span class="spin"></span></div>`; };
function descendants(steps, sid) {
  const out = new Set([sid]); let grew = true;
  while (grew) { grew = false; for (const s of steps) if (!out.has(s.sid) && s.parents.some((p) => out.has(p))) { out.add(s.sid); grew = true; } }
  return out;
}
let INFO = null;
function agentBadge(run) {
  const a = run.agent, m = run.meta || {};
  if (a === "react-slm") return `<span class="b blue nodot" title="A real language model chose every tool call">REAL MODEL · ${esc(m.model)} (${esc((m.provider || "ollama").toUpperCase())})</span>`;
  if (a === "react-sim") return `<span class="b ghost nodot" title="Deterministic benchmark policy; same tools and trace format">BENCHMARK POLICY · ${esc(m.policy || "standard")}</span>`;
  if (a === "external") return `<span class="b blue nodot">EXTERNAL · ${esc(m.source === "otlp" ? "OPENTELEMETRY" : "SDK")}</span>`;
  if (a === "travel-llm") return m.provider === "anthropic" ? `<span class="b blue nodot">V1 LLM AGENT · ${esc(m.model)}</span>` : `<span class="b root nodot">V1 LLM AGENT · OFFLINE MOCK</span>`;
  return `<span class="b ghost nodot">V1 FIXED-PLAN AGENT</span>`;
}
const MAIN = (L) => (L.test.gnn ? "gnn" : "model");

// ------------------------------------------------------------------ workflow signature
const STAGES = [
  ["detect", "DETECT", "Flag failed or suspicious executions from the recorded trace.", "#/runs?status=failed"],
  ["explain", "EXPLAIN", "Rank the likely root-cause step and show the trace evidence behind it.", "#/investigate"],
  ["replay", "REPLAY", "Restore the checkpoint and re-execute only the steps that depend on it.", "#/repair"],
  ["repair", "REPAIR", "Re-run the step fresh, or patch its output or arguments, and test the change.", "#/repair"],
  ["verify", "VERIFY", "Diff original vs repaired execution and confirm the task check now passes.", "#/comparisons"],
];
/* state: map stage -> "done" | "now" | undefined */
function loop(state = {}, big = false) {
  return `<div class="loop ${big ? "big" : ""}">${STAGES.map(([k, n, d, href]) => `
    <${big ? `a href="${href}"` : "div"} class="st ${state[k] || ""}">
      <span class="ic">${icon(state[k] === "done" && !big ? "check" : k)}</span>
      <span><div class="nm">${n}</div>${big ? `<div class="ds">${d}</div>` : ""}</span>
      ${big ? `<span class="go">${{ detect: "Failed runs →", explain: "Investigate latest failure →", replay: "Replay workspace →", repair: "Repair workspace →", verify: "Repair verifications →" }[k]}</span>` : ""}
    </${big ? "a" : "div"}>`).join("")}</div>`;
}

// ------------------------------------------------------------------ router
const NAV = [
  ["overview", "#/", "Overview"], ["runs", "#/runs", "Runs"], ["investigate", "#/investigate", "Trace Investigation"],
  ["repair", "#/repair", "Replay & Repair"], ["compare", "#/comparisons", "Comparisons"], ["sep"],
  ["eval", "#/eval", "Evaluation"], ["demo", "#/demo", "Live Demo"],
];
function renderNav(active) {
  $("#nav").innerHTML = NAV.map(([k, h, l]) => k === "sep" ? `<div class="sep"></div>`
    : `<a href="${h}" class="${k === active ? "on" : ""}">${icon({ investigate: "explain", repair: "replay" }[k] || k)}${l}</a>`).join("");
}
const routes = [
  [/^\/?$/, "overview", overview], [/^\/runs$/, "runs", runsView],
  [/^\/investigate$/, "investigate", investigateLatest], [/^\/(?:investigate|run)\/([\w-]+)$/, "investigate", investigate],
  [/^\/repair$/, "repair", repairPicker], [/^\/(?:repair|replay)\/([\w-]+)$/, "repair", repairView],
  [/^\/comparisons$/, "compare", comparisons], [/^\/compare\/([\w-]+)\/([\w-]+)$/, "compare", compareView],
  [/^\/eval$/, "eval", evalView], [/^\/demo$/, "demo", demoView], [/^\/about$/, "overview", aboutView],
];
async function router() {
  const h = location.hash.slice(1) || "/";
  const [path, qs] = h.split("?");
  const q = Object.fromEntries(new URLSearchParams(qs || ""));
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

// ------------------------------------------------------------------ graph (layered DAG)
const GSTYLE = {
  ok: ["#161b22", "#30363d", "#10b981"], warn: ["#161b22", "#6b4a12", "#fbbf24"], root: ["#2a1f0b", "#f59e0b", "#f59e0b"],
  hit: ["#1c1214", "#7f2a2f", "#ef4444"], reused: ["#12151b", "#30363d", "#64748b"], rerun: ["#0f1a2e", "#3b82f6", "#60a5fa"],
};
function graphSvg(steps, statusOf, { selected, onClick } = {}) {
  const depth = {}, cols = {};
  steps.forEach((s) => { depth[s.sid] = 1 + Math.max(-1, ...s.parents.filter((p) => p in depth).map((p) => depth[p])); (cols[depth[s.sid]] ||= []).push(s); });
  const W = 140, H = 30, GX = 46, GY = 9, P = 14;
  const nC = Object.keys(cols).length, maxR = Math.max(...Object.values(cols).map((c) => c.length));
  const pos = {};
  Object.entries(cols).forEach(([d, list]) => list.forEach((s, j) => { pos[s.sid] = { x: P + d * (W + GX), y: P + (maxR - list.length) * (H + GY) / 2 + j * (H + GY) }; }));
  const w = P * 2 + nC * (W + GX) - GX, h = P * 2 + maxR * (H + GY) - GY;
  const edges = steps.flatMap((s) => s.parents.filter((p) => pos[p]).map((p) => {
    const a = pos[p], b = pos[s.sid], x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
    const hot = ["root", "hit"].includes(statusOf(p)) && statusOf(s.sid) === "hit";
    const re = statusOf(p) === "rerun" && statusOf(s.sid) === "rerun";
    return `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" fill="none" stroke="${hot ? "#ef4444" : re ? "#3b82f6" : "#30363d"}" stroke-width="${hot || re ? 1.5 : 1}" ${hot ? 'stroke-dasharray="4 3"' : ""}/>`;
  })).join("");
  const nodes = steps.map((s) => {
    const k = statusOf(s.sid), [f, b, d] = GSTYLE[k] || GSTYLE.ok, p = pos[s.sid], sel = s.sid === selected;
    return `<g class="node" data-sid="${esc(s.sid)}"><rect x="${p.x}" y="${p.y}" width="${W}" height="${H}" rx="4" fill="${f}" stroke="${sel ? "#3b82f6" : b}" stroke-width="${sel || k === "root" ? 1.6 : 1}"/>
      <circle cx="${p.x + 11}" cy="${p.y + H / 2}" r="3.5" fill="${d}"/>
      <text x="${p.x + 21}" y="${p.y + 19}">${esc(s.sid.length > 17 ? s.sid.slice(0, 16) + "…" : s.sid)}</text>
      <title>${esc(s.sid)} · ${esc(s.name)}\n${esc(summarize(s.output))}</title></g>`;
  }).join("");
  return { html: `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${edges}${nodes}</svg>`,
    bind: (root) => onClick && $$(".node", root).forEach((g) => (g.onclick = () => onClick(g.dataset.sid))) };
}

// ------------------------------------------------------------------ evidence block (shared)
function evidenceHtml(rc) {
  if (!rc) return "";
  return rc.evidence.map((e) => {
    const ctx = ["upstream_clean", "downstream_impact"].includes(e.signal);
    return `<div class="ev"><div class="h ${ctx ? "ctx" : ""}"><span>${esc(e.label)}</span>${ctx ? "" : `<span class="dim">signal</span>`}</div>
      <div class="x">${esc(e.text)}</div>
      ${e.expected || e.observed ? `<div class="eo">${e.expected ? `<span class="k">EXPECTED</span><span class="exp">${esc(e.expected)}</span>` : ""}${e.observed ? `<span class="k">OBSERVED</span><span class="obs">${esc(e.observed)}</span>` : ""}</div>` : ""}</div>`;
  }).join("");
}
const confLine = (score) => `<div class="row" style="align-items:flex-end;gap:12px"><span class="conf">${pct(score, 1)}</span><span class="muted" style="padding-bottom:6px">confidence<br><span class="dim" style="font-size:11px">step-ranking model score</span></span></div><div class="bar mt"><i style="width:${score * 100}%"></i></div>`;

// ------------------------------------------------------------------ OVERVIEW
async function overview() {
  const [s, m] = await Promise.all([api("/api/stats"), api("/api/metrics").catch(() => null)]);
  view().innerHTML = `
    <div class="hero">
      <div>
        <div class="cap" style="color:var(--blue-2)">AI AGENT FLIGHT RECORDER</div>
        <h1 class="mt">BLACK BOX</h1>
        <div class="tl">From Failure to Fix — Without Starting Over.</div>
        <p>Trace every agent execution, identify likely root causes, replay from the failure checkpoint, test repairs, and verify the result.</p>
        <div class="row">
          <a class="btn primary lg" href="#/investigate">${icon("explain")}Investigate a Failure</a>
          <a class="btn lg" href="#/demo">${icon("demo")}Run Demo</a>
        </div>
      </div>
      <div>
        <div class="cap mb">WHAT CHANGES</div>
        <div class="vs">
          <div class="col"><div class="cap">TRADITIONAL OBSERVABILITY</div><ol>
            <li>Agent fails</li><li>Read logs</li><li>Investigate manually</li><li>Restart the agent</li><li>Try again</li></ol></div>
          <div class="col bb"><div class="cap" style="color:var(--blue-2)">BLACK BOX</div><ol>
            <li>Agent fails</li><li><b>DETECT</b>&nbsp;failure</li><li><b>EXPLAIN</b>&nbsp;likely root cause</li><li><b>REPLAY</b>&nbsp;from checkpoint</li><li><b>REPAIR</b>&nbsp;the step</li><li><b>VERIFY</b>&nbsp;original vs repaired</li></ol></div>
        </div>
        <div class="muted mt" style="font-size:12px">Observability tells you what happened. Black Box is designed to turn it into an actionable debugging workflow: where it likely went wrong, and a tested repair without re-running everything.</div>
      </div>
    </div>
    ${loop({}, true)}
    <div class="metrics mt">
      <div class="metric"><div class="cap">EXECUTIONS</div><div class="v">${num(s.runs)}</div><div class="s">recorded runs</div></div>
      <div class="metric"><div class="cap">FAILURES DETECTED</div><div class="v red">${num(s.failures_detected)}</div><div class="s">${pct(s.failure_rate, 1)} of runs failed the task check</div></div>
      <div class="metric"><div class="cap">ROOT CAUSES IDENTIFIED</div><div class="v amber">${num(s.root_causes_identified)}</div><div class="s" title="Failed runs whose top-ranked step scores at least ${s.identified_threshold}">top step ≥ ${s.identified_threshold} · ${num(s.failures_analyzed)} analyzed</div></div>
      <div class="metric"><div class="cap">REPLAY ATTEMPTS</div><div class="v blue">${num(s.replay_attempts)}</div><div class="s">checkpoint replays run</div></div>
      <div class="metric"><div class="cap">REPAIRS VERIFIED</div><div class="v green">${num(s.repairs_verified)}</div><div class="s">failed → success after replay</div></div>
      <div class="metric"><div class="cap">STEPS AVOIDED</div><div class="v">${num(s.steps_avoided)}</div><div class="s">${s.replay_steps_total ? `${pct(s.steps_avoided / s.replay_steps_total)} of replayed steps reused` : "reused instead of re-run"}</div></div>
    </div>
    <div class="grid mt" style="grid-template-columns: minmax(0,1.5fr) minmax(0,1fr)">
      <div class="panel"><div class="hd"><h2>Recent failures</h2><a class="btn sm" href="#/runs?status=failed">All failed runs</a></div>
        ${s.recent_failed.length ? `<div class="tablewrap"><table><thead><tr><th>Run</th><th>Task</th><th>Likely root cause</th><th class="num">Conf.</th><th></th></tr></thead><tbody>
        ${s.recent_failed.map((r) => `<tr class="click" data-go="#/investigate/${r.run_id}"><td class="mono t1">${short(r.run_id)}<div class="dim" style="font-size:11px">${esc(r.split)} · ${ago(r.created)}</div></td>
          <td><div class="trunc" style="max-width:260px">${esc(r.question)}</div></td>
          <td><span class="b root nodot">${esc(r.root_sid)}</span> <span class="muted mono" style="font-size:11px">${esc(r.root_name)}</span></td>
          <td class="num">${pct(r.root_score)}</td><td class="num"><span class="btn sm">Investigate</span></td></tr>`).join("")}</tbody></table></div>`
        : empty("NO FAILED RUNS", "Your agent executions are healthy.", `<a class="btn primary" href="#/demo">Run Demo</a>`)}
      </div>
      <div class="panel"><div class="hd"><h2>Recent repair verifications</h2><a class="btn sm" href="#/comparisons">All</a></div>
        ${s.recent_replays.length ? `<table><tbody>${s.recent_replays.map((r) => `<tr class="click" data-go="#/compare/${r.parent_run_id}/${r.run_id}">
          <td class="mono t1">${short(r.parent_run_id)}</td><td class="mono muted">${esc(r.fork_sid)}</td>
          <td>${r.parent_success === 0 && r.success ? `<span class="b ok">VERIFIED</span>` : r.success ? `<span class="b ok">SUCCESS</span>` : `<span class="b fail">STILL FAILS</span>`}</td>
          <td class="num muted">${r.n_reexecuted}/${r.n_steps} re-run</td></tr>`).join("")}</tbody></table>`
        : empty("NO REPLAY YET", "Select a suspicious step to replay from its checkpoint.", `<a class="btn" href="#/investigate">Investigate Trace</a>`)}
        ${m ? `<div class="bd" style="border-top:1px solid var(--border)"><div class="cap mb">BENCHMARK · HELD-OUT RUNS</div>
          ${[["test", "Top-1, seen failure types"], ["heldout", "Top-1, unseen failure types"], ["drift_loc", "Top-1, error source moved"], ["drift_topo", "Top-1, new agent behaviour"]].filter(([k]) => m.localization[k]).map(([k, l]) => `<div class="hbar"><span>${l}</span><div class="bar blue"><i style="width:${m.localization[k][MAIN(m.localization)].top1 * 100}%"></i></div><b>${pct(m.localization[k][MAIN(m.localization)].top1, 1)}</b></div>`).join("")}
          <div class="hbar"><span>Fixed & verified ≤ 3 replays</span><div class="bar green"><i style="width:${(m.counterfactual?.fixed_within_3 || 0) * 100}%"></i></div><b>${pct(m.counterfactual?.fixed_within_3, 1)}</b></div>
          <a class="btn sm mt" href="#/eval">Evaluation details</a></div>` : ""}
      </div>
    </div>`;
  $$("[data-go]").forEach((el) => (el.onclick = () => go(el.dataset.go)));
}

// ------------------------------------------------------------------ RUNS
async function runsView(q) {
  const p = new URLSearchParams({ limit: 50, offset: q.offset || 0 });
  ["status", "split", "agent", "q"].forEach((k) => q[k] && p.set(k, q[k]));
  const d = await api(`/api/runs?${p}`); const off = +(q.offset || 0);
  const sel = (n, opts) => `<select data-f="${n}">${opts.map(([v, l]) => `<option value="${v}" ${q[n] === v ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  view().innerHTML = `
    <div class="row mb"><div><h1>Runs</h1><div class="sub" style="margin-bottom:0">Every recorded execution. Failed runs carry Black Box's likely root cause.</div></div></div>
    <div class="row mb">
      ${sel("status", [["", "All statuses"], ["failed", "Failed"], ["passed", "Passed"]])}
      ${sel("split", [["", "All sources"], ["demo", "Live demo"], ["live", "Live runs"], ["train", "Benchmark · train"], ["test", "Benchmark · test (seen faults)"], ["heldout", "Benchmark · held-out (unseen faults)"]])}
      ${sel("agent", [["", "All agents"], ["travel-llm", "LLM agent"], ["travel-sim", "Simulated agent"]])}
      <input data-f="q" placeholder="run id or task…" value="${esc(q.q || "")}" style="min-width:220px"><span class="sp"></span><span class="muted mono">${num(d.total)} runs</span></div>
    <div class="panel">${d.runs.length ? `<div class="tablewrap"><table>
      <thead><tr><th>Run</th><th>Status</th><th>Task</th><th>Agent</th><th>Source</th><th class="num">Steps</th><th class="num">Duration</th><th>Likely root cause</th><th>Recorded</th></tr></thead>
      <tbody>${d.runs.map((r) => `<tr class="click" data-go="#/investigate/${r.run_id}">
        <td class="mono t1">${short(r.run_id)}</td><td>${st(r.success)}</td><td><div class="trunc">${esc(r.question)}</div></td>
        <td>${r.agent === "travel-llm" ? `<span class="kind llm">LLM</span>` : `<span class="kind">SIM</span>`}</td><td class="muted mono" style="font-size:11px">${esc(r.split)}</td>
        <td class="num">${r.n_steps}</td><td class="num">${ms(r.duration_ms)}</td>
        <td>${r.root ? `<span class="b root nodot">${esc(r.root.sid)}</span> <span class="mono muted" style="font-size:11px">${pct(r.root.score)}</span>` : `<span class="dim">—</span>`}</td>
        <td class="muted">${ago(r.created)}</td></tr>`).join("")}</tbody></table></div>`
      : empty(q.status === "failed" ? "NO FAILED RUNS" : "NO RUNS", q.status === "failed" ? "Your agent executions are healthy." : "Nothing matches these filters.", `<a class="btn primary" href="#/demo">Run Demo</a>`)}</div>
    <div class="row mt"><span class="sp"></span><button class="btn sm" id="prev" ${off <= 0 ? "disabled" : ""}>← Prev</button>
      <span class="muted mono">${d.total ? off + 1 : 0}–${Math.min(off + 50, d.total)}</span><button class="btn sm" id="next" ${off + 50 >= d.total ? "disabled" : ""}>Next →</button></div>`;
  const nav = (o) => { const n = { ...q, offset: o }; Object.keys(n).forEach((k) => !n[k] && delete n[k]); go(`/runs?${new URLSearchParams(n)}`); };
  $$("[data-f]").forEach((el) => (el.onchange = () => { q[el.dataset.f] = el.value; nav(0); }));
  $$("[data-go]").forEach((el) => (el.onclick = () => go(el.dataset.go)));
  $("#prev").onclick = () => nav(Math.max(0, off - 50)); $("#next").onclick = () => nav(off + 50);
}

// ------------------------------------------------------------------ TRACE INVESTIGATION
async function investigateLatest() {
  const d = await api("/api/runs?status=failed&limit=1");
  if (!d.runs.length) { view().innerHTML = empty("NO FAILED RUNS", "Your agent executions are healthy.", `<a class="btn primary" href="#/demo">Run Demo</a>`); return; }
  location.replace(`#/investigate/${d.runs[0].run_id}`);
}

async function investigate(id, q) {
  const [run, dx] = await Promise.all([api(`/api/runs/${id}`), api(`/api/runs/${id}/diagnosis`)]);
  const failed = !run.success, isFork = !!run.parent_run_id, rc = failed ? dx.root_cause : null;
  const by = Object.fromEntries(dx.steps.map((s) => [s.sid, s]));
  const impacted = new Set(failed ? dx.impacted : []);
  const status = (sid) => {
    if (isFork) return run.steps.find((s) => s.sid === sid)?.reused ? "reused" : "rerun";
    if (rc && sid === rc.sid) return "root"; if (impacted.has(sid)) return "hit";
    return by[sid]?.suspicious ? "warn" : "ok";
  };
  const LBL = { ok: ["ok", "OK"], warn: ["root", "ANOMALY"], root: ["root", "ROOT CAUSE"], hit: ["fail", "IMPACTED"], reused: ["slate", "REUSED"], rerun: ["blue", "RE-EXECUTED"] };
  let sel = q.step || rc?.sid || run.steps[0].sid, tab = "signals";
  const rcStep = rc && run.steps.find((s) => s.sid === rc.sid);
  const repairHref = (sid, mode = "repair") => `#/repair/${run.run_id}?sid=${encodeURIComponent(sid)}&mode=${mode}`;

  view().innerHTML = `
    <div class="crumbs"><a href="#/runs">Runs</a><span>/</span><span class="t1">${short(run.run_id)}</span>${st(run.success)}
      ${agentBadge(run)}
      <span class="b ghost nodot">${esc(run.split)}</span><span class="sp"></span>
      ${rc && run.replayable ? `<a class="btn amber" href="${repairHref(rc.sid)}">${icon("replay")}Replay From Step ${String(rcStep.idx + 1).padStart(2, "0")} (Root Cause)</a>` : ""}
    </div>
    ${isFork ? `<div class="banner blue"><span class="big">REPLAY RUN</span><span>Forked from <a class="mono t1" href="#/investigate/${run.parent_run_id}"><u>${short(run.parent_run_id)}</u></a> at <b class="mono">${esc(run.fork_sid)}</b> (${esc(run.fork_mode)}) · ${run.n_reexecuted}/${run.n_steps} steps re-executed</span><span class="sp"></span><a class="btn sm" href="#/compare/${run.parent_run_id}/${run.run_id}">Original vs repaired →</a></div>`
      : failed ? `<div class="banner"><span class="big">BLACK BOX FOUND A LIKELY ROOT CAUSE</span><span class="t1">Step ${String(rcStep.idx + 1).padStart(2, "0")} · <span class="mono">${esc(rc.sid)}</span> · ${pct(rc.score, 1)} confidence</span><span class="muted">· ${impacted.size} downstream step(s) affected</span></div>`
      : `<div class="banner ok"><span class="big">NO FAILURE DETECTED</span><span>This run passed the task check. Black Box still scores every step.</span></div>`}
    ${failed && !isFork ? `<div class="mb">${loop({ detect: "done", explain: "done", replay: "now" })}</div>` : ""}
    <div class="taskbar">
      <div><div class="cap">TASK OBJECTIVE</div><div class="mt t1" style="font-size:13.5px;line-height:19px">${esc(run.question)}</div>
        <div class="muted mono mt" style="font-size:11px">${run.n_steps} steps · ${ms(run.duration_ms)} · failure risk ${pct(dx.p_fail)}${run.meta?.model ? ` · model ${esc(run.meta.model)}` : ""}</div></div>
      <div><div class="cap">AGENT ANSWER</div><div class="val" style="color:${failed ? "var(--red-2)" : "var(--green-2)"}">${money(run.final?.total_usd)}</div>
        <div class="muted" style="font-size:12px">${run.final?.within_budget == null ? esc(summarize(run.final)) : run.final.within_budget ? "says within budget" : "says over budget"}</div></div>
      <div><div class="cap">EXPECTED · TASK CHECK</div><div class="val">${money(run.expected?.total_usd)}</div><div class="muted" style="font-size:12px">${run.expected?.within_budget ? "within budget" : "over budget"}</div></div>
    </div>
    <div class="three">
      <div class="panel"><div class="hd"><h2>Execution steps</h2><span class="mono muted" style="font-size:11px">${run.n_steps} · ${failed ? `${impacted.size + 1} affected` : "all ok"}</span></div><ul class="steps" id="steps"></ul></div>
      <div class="grid" style="gap:12px">
        <div class="panel"><div class="hd"><h2>Causal execution graph</h2><span class="legend">${isFork ? `<span><i style="background:#3b82f6"></i>re-executed</span><span><i style="background:#64748b"></i>reused</span>` : `<span><i style="background:#f59e0b"></i>root cause</span><span><i style="background:#ef4444"></i>impacted</span><span><i style="background:#10b981"></i>ok</span>`}</span></div><div class="bd"><div class="graph" id="graph"></div></div></div>
        <div class="panel" id="insp"></div>
      </div>
      <div class="rcol">${rc ? `
        <div class="panel"><div class="hd"><h2>Likely root cause</h2><span class="b root">EXPLAIN</span></div><div class="bd">
          <div class="row"><span class="mono t1" style="font-size:15px">Step ${String(rcStep.idx + 1).padStart(2, "0")} · ${esc(rc.sid)}</span>${kind(rc.kind)}<span class="muted mono" style="font-size:11px">${esc(rc.name)}</span></div>
          <div class="mt">${confLine(rc.score)}</div>
          <div class="cap mt2">EVIDENCE</div>${evidenceHtml(rc)}
          ${rc.joint_local ? `<div class="dim mt" style="font-size:11px">Local signals account for ${pct(rc.joint_local)} of the score (measured by removing them and re-scoring).</div>` : ""}
          <div class="grid g2 mt2">
            <div><div class="cap">UPSTREAM STATE</div><div class="mt">${dx.upstream.healthy ? `<span class="b ok">HEALTHY</span> <span class="muted" style="font-size:12px">${dx.upstream.steps.length} step(s)</span>` : `<span class="b fail">${dx.upstream.anomalous.length} ANOMALOUS</span>`}</div></div>
            <div><div class="cap">DOWNSTREAM EFFECT</div><div class="mt"><span class="b fail">${impacted.size} AFFECTED</span></div></div>
          </div>
          <div class="chips mt">${dx.impacted.map((s) => `<span class="chip ${dx.impacted_anomalous.includes(s) ? "hot" : ""}" data-pick="${esc(s)}">${esc(s)}</span>`).join("")}</div>
          ${run.replayable ? `<a class="btn primary mt2" style="width:100%;justify-content:center" href="${repairHref(rc.sid)}">${icon("replay")}Replay From This Step</a>` : `<div class="muted mt2" style="font-size:12px">Recorded via SDK without a replay adapter: diagnosable, not replayable.</div>`}
          ${dx.suspects.length > 1 ? `<div class="cap mt2">OTHER SUSPECTS</div>${dx.suspects.slice(1).map((x) => `<div class="row mt"><span class="chip" data-pick="${esc(x.sid)}">${esc(x.sid)}</span><div class="bar slate sp"><i style="width:${x.score * 100}%"></i></div><span class="mono muted" style="font-size:11px">${pct(x.score)}</span></div>`).join("")}` : ""}
          ${run.label ? `<button class="btn sm mt2" id="reveal">Reveal ground-truth label</button><div id="label"></div>` : ""}
        </div></div>` : `<div class="panel"><div class="hd"><h2>${isFork ? "Replay run" : "Diagnosis"}</h2></div><div class="bd muted">${isFork ? "This execution is a replay. Compare it with the original to verify the repair." : "No failure to explain. Step scores are still shown in the inspector for reference."}
          ${isFork ? `<div><a class="btn primary mt" href="#/compare/${run.parent_run_id}/${run.run_id}">Original vs repaired</a></div>` : ""}</div></div>`}
      </div>
    </div>`;

  const renderSteps = () => {
    $("#steps").innerHTML = run.steps.map((s) => {
      const k = status(s.sid), [c, l] = LBL[k];
      return `<li data-sid="${esc(s.sid)}" class="${s.sid === sel ? "sel" : ""} ${k === "root" ? "root" : ""}">
        <span class="dot ${k}"></span><span style="min-width:0"><div class="t"><span class="nb">${String(s.idx + 1).padStart(2, "0")}</span> ${esc(s.sid)}</div><div class="m">${esc(s.kind.toUpperCase())} · ${esc(s.name)} · ${ms(s.latency_ms)}</div></span>
        <span class="b ${c} nodot">${l}</span></li>`;
    }).join("");
    $$("#steps li").forEach((li) => (li.onclick = () => pick(li.dataset.sid)));
  };
  const renderGraph = () => { const g = graphSvg(run.steps, status, { selected: sel, onClick: pick }); $("#graph").innerHTML = g.html; g.bind($("#graph")); };
  const renderInsp = () => {
    const s = run.steps.find((x) => x.sid === sel), a = by[sel], k = status(sel);
    $("#insp").innerHTML = `<div class="hd"><div class="row">${kind(s.kind)}<h2 class="mono">${esc(s.sid)}</h2><span class="b ${LBL[k][0]} nodot">${LBL[k][1]}</span></div>
        <span class="mono muted" style="font-size:11px">step ${s.idx + 1}/${run.steps.length} · score ${pct(a.score, 1)} · rank #${a.rank}</span></div>
      <div class="tabs">${[["signals", "Signals & telemetry"], ["input", "Input JSON"], ["output", "Output JSON"]].map(([t, l]) => `<button data-t="${t}" class="${t === tab ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="bd">${tab === "signals" ? `<div class="kv">
          <span class="k">OPERATION</span><span class="mono">${esc(s.name)}${s.role && s.role !== s.name ? ` <span class="dim">(${esc(s.role)})</span>` : ""}</span>
          <span class="k">LATENCY</span><span class="mono">${ms(s.latency_ms)}${s.retries ? ` <span class="b root nodot">${s.retries} RETRY</span>` : ""}</span>
          <span class="k">ERROR</span><span>${s.error ? `<span class="b fail nodot">${esc(s.error)}</span>` : `<span class="dim">none</span>`}</span>
          <span class="k">DEPENDS ON</span><span class="chips">${s.parents.map((p) => `<span class="chip" data-pick="${esc(p)}">${esc(p)}</span>`).join("") || `<span class="dim">entry step</span>`}</span>
          <span class="k">USED BY</span><span class="chips">${a.children.map((c) => `<span class="chip" data-pick="${esc(c)}">${esc(c)}</span>`).join("") || `<span class="dim">—</span>`}</span>
          <span class="k">OUTPUT</span><span class="mono t1">${esc(summarize(s.output))}</span></div>
          <div class="cap mt2">ANOMALY SIGNALS</div>
          ${a.flags.length ? a.flags.map((f) => `<div class="row mt" style="flex-wrap:nowrap;align-items:flex-start"><span class="dot ${f.severity === "high" ? "hit" : "warn"}" style="margin-top:5px"></span><span style="font-size:12.5px">${esc(f.text)}</span></div>`).join("") : `<div class="muted mt" style="font-size:12.5px">No anomaly signals on this step.</div>`}
          ${run.replayable && !isFork ? `<div class="row mt2"><a class="btn sm" href="${repairHref(s.sid)}">${icon("replay")}Replay from here</a><a class="btn sm" href="${repairHref(s.sid, "patch_output")}">Patch output</a>${["tool", "retrieval"].includes(s.kind) ? `<a class="btn sm" href="${repairHref(s.sid, "patch_args")}">Patch arguments</a>` : ""}</div>` : ""}`
        : `<pre class="json">${jsonHtml(tab === "input" ? s.args : s.output)}</pre>`}</div>`;
    $$("[data-t]", $("#insp")).forEach((b) => (b.onclick = () => { tab = b.dataset.t; renderInsp(); }));
    $$("[data-pick]", $("#insp")).forEach((c) => (c.onclick = () => pick(c.dataset.pick)));
  };
  function pick(sid) { sel = sid; renderSteps(); renderGraph(); renderInsp(); }
  $$(".rcol [data-pick]").forEach((c) => (c.onclick = () => pick(c.dataset.pick)));
  const rv = $("#reveal");
  if (rv) rv.onclick = () => {
    const L = run.label, rank = dx.steps.find((s) => s.sid === L.fault_sid)?.rank;
    $("#label").innerHTML = `<div class="card mt"><div class="cap">GROUND-TRUTH LABEL (NOT USED BY THE MODEL)</div><div class="mt">Injected <b class="mono">${esc(L.fault_type)}</b> at <b class="mono">${esc(L.fault_sid)}</b> ${L.heldout ? `<span class="b blue nodot">NEVER SEEN IN TRAINING</span>` : ""}</div>
      <div class="muted mt" style="font-size:12px">${esc(L.note || L.description)}</div><div class="mt">${rank === 1 ? `<span class="b ok">BLACK BOX RANKED IT #1</span>` : `<span class="b root">BLACK BOX RANKED IT #${rank}</span>`}</div></div>`;
    rv.remove();
  };
  renderSteps(); renderGraph(); renderInsp();
}

// ------------------------------------------------------------------ REPLAY & REPAIR
async function repairPicker() {
  const [f, r] = await Promise.all([api("/api/runs?status=failed&limit=12"), api("/api/replays?limit=6")]);
  view().innerHTML = `
    <h1>Replay &amp; Repair</h1><div class="sub">Pick a failed execution. Black Box restores the checkpoint at its likely root cause so you can repair that step and re-run only what depends on it.</div>
    <div class="mb">${loop({ detect: "done", explain: "done", replay: "now" })}</div>
    <div class="grid" style="grid-template-columns:minmax(0,1.5fr) minmax(0,1fr)">
      <div class="panel"><div class="hd"><h2>Failed executions</h2></div>
        ${f.runs.length ? `<div class="tablewrap"><table><thead><tr><th>Run</th><th>Task</th><th>Checkpoint (likely root cause)</th><th></th></tr></thead><tbody>${f.runs.map((x) => `<tr class="click" data-go="#/repair/${x.run_id}?sid=${encodeURIComponent(x.root?.sid || "")}">
          <td class="mono t1">${short(x.run_id)}</td><td><div class="trunc" style="max-width:300px">${esc(x.question)}</div></td>
          <td><span class="b root nodot">${esc(x.root?.sid)}</span> <span class="mono muted" style="font-size:11px">${pct(x.root?.score)}</span></td><td class="num"><span class="btn sm">Open</span></td></tr>`).join("")}</tbody></table></div>`
        : empty("NO FAILED RUNS", "Your agent executions are healthy.", `<a class="btn primary" href="#/demo">Run Demo</a>`)}</div>
      <div class="panel"><div class="hd"><h2>Recent replays</h2></div>
        ${r.runs.length ? `<table><tbody>${r.runs.map((x) => `<tr class="click" data-go="#/compare/${x.parent_run_id}/${x.run_id}"><td class="mono">${short(x.parent_run_id)}</td><td class="mono muted">${esc(x.fork_sid)}</td><td>${x.parent_success === 0 && x.success ? `<span class="b ok">VERIFIED</span>` : st(x.success)}</td></tr>`).join("")}</tbody></table>`
        : empty("NO REPLAY YET", "Select a suspicious step to replay from its checkpoint.", `<a class="btn" href="#/investigate">Investigate Trace</a>`)}</div>
    </div>`;
  $$("[data-go]").forEach((el) => (el.onclick = () => go(el.dataset.go)));
}

function diffFields(a, b) {
  const keys = [...new Set([...Object.keys(a || {}), ...Object.keys(b || {})])];
  return keys.filter((k) => JSON.stringify(a?.[k]) !== JSON.stringify(b?.[k])).map((k) => [k, a?.[k], b?.[k]]);
}

async function repairView(id, q) {
  const [run, dx] = await Promise.all([api(`/api/runs/${id}`), api(`/api/runs/${id}/diagnosis`)]);
  if (!run.replayable) { view().innerHTML = empty("REPLAY UNAVAILABLE", "This run was recorded through the SDK without a replay adapter, so it can be diagnosed but not replayed.", `<a class="btn" href="#/investigate/${id}">Back to investigation</a>`); return; }
  const by = Object.fromEntries(dx.steps.map((s) => [s.sid, s]));
  const rc = dx.root_cause;
  let sid = q.sid && by[q.sid] ? q.sid : rc?.sid || run.steps[0].sid, mode = q.mode || "repair", staged = null, result = null, error = null, busy = false, srcNote = "";
  const step = () => run.steps.find((s) => s.sid === sid);
  const recorded = () => (mode === "patch_args" ? step().args : step().output);

  const verifyHtml = () => {
    if (busy) return `<div class="panel"><div class="bd row"><span class="spin"></span><span>Restoring checkpoint at <b class="mono">${esc(sid)}</b> and re-executing dependent steps…</span></div></div>`;
    if (error) return `<div class="errbox"><div class="t">REPLAY FAILED${error.status ? ` · HTTP ${error.status}` : ""}</div><div class="mt">${esc(error.message)}</div><div class="row mt"><button class="btn sm" id="retry">Retry</button><a class="btn sm" href="#/investigate/${id}">Back to trace</a></div></div>`;
    if (!result) return `<div class="panel"><div class="hd"><h2>3 · Verify</h2></div>${empty("NO REPLAY YET", "Choose the checkpoint, prepare a repair, then run the replay. Black Box verifies the outcome against the task check.")}</div>`;
    const r = result, x = r.reexecution_error, good = r.verified || (r.success && r.orig_success);
    return `<div class="panel verify ${good ? "" : "no"}"><div class="hd"><h2>3 · Verify</h2><a class="btn ${r.verified ? "green" : ""}" href="#/compare/${id}/${r.run_id}">${icon("compare")}View Comparison</a></div><div class="bd">
      <div class="vh">${r.verified ? `${icon("verify")}REPAIR VERIFIED` : r.success ? `${icon("check")}REPLAY SUCCEEDED` : `${icon("x")}REPAIR NOT VERIFIED`}</div>
      ${x ? `<div class="errbox mt"><div class="t">CHECKPOINT RESTORED, BUT STEP ${String(x.idx + 1).padStart(2, "0")} FAILED DURING RE-EXECUTION</div>
        <div class="kv mt"><span class="k">STEP</span><span class="mono">${esc(x.sid)} · ${esc(x.name)}</span><span class="k">ERROR</span><span class="mono">${esc(x.error)}</span><span class="k">ARGUMENTS</span><span><pre class="json" style="margin:0">${jsonHtml(x.args)}</pre></span></div>
        <div class="row mt"><button class="btn sm" id="retry">Retry</button><a class="btn sm" href="#/investigate/${r.run_id}">Open replay trace</a></div></div>`
        : !r.success ? `<div class="muted mt" style="font-size:12.5px">The replay ran, but the repaired execution still fails the task check. Try another checkpoint or patch.</div>` : ""}
      <div class="outc mt">
        <div class="o"><div class="cap">ORIGINAL EXECUTION</div><div class="mt">${st(r.orig_success)}</div><div class="val">${esc(summarize(run.final))}</div></div>
        <div class="muted" style="text-align:center">${icon("arrow")}</div>
        <div class="o"><div class="cap">REPAIRED EXECUTION</div><div class="mt">${st(r.success)}</div><div class="val">${esc(summarize(r.final))}</div></div>
      </div>
      <div class="metrics mt" style="grid-template-columns:repeat(5,1fr)">
        <div class="metric"><div class="cap">ORIGINAL</div><div class="v">${r.n_total}</div><div class="s">steps</div></div>
        <div class="metric"><div class="cap">REPAIRED</div><div class="v">${r.n_total}</div><div class="s">logical steps</div></div>
        <div class="metric"><div class="cap">RE-EXECUTED</div><div class="v blue">${r.n_reexecuted}</div><div class="s">naive re-run from here: ${r.n_suffix}</div></div>
        <div class="metric"><div class="cap">REUSED</div><div class="v">${r.n_reused}</div><div class="s">restored from checkpoint</div></div>
        <div class="metric"><div class="cap">CHANGED</div><div class="v green">${r.changed.length}</div><div class="s">diverged at ${esc(r.diff.first_divergence || "—")}</div></div>
      </div>
      <div class="muted mt" style="font-size:12px">Task check expects <span class="t1">${esc(summarize(r.expected))}</span> · changed: <span class="mono">${r.changed.map(esc).join(", ") || "none"}</span> · saved as <a class="mono t1" href="#/investigate/${r.run_id}"><u>${short(r.run_id)}</u></a></div>
    </div></div>`;
  };

  const shell = () => {
    const rerun = descendants(run.steps, sid), ck = step().idx;
    const tag = (s) => s.sid === sid ? ["ck", "RE-EXECUTED · CHECKPOINT", "b root"] : rerun.has(s.sid) ? ["re", "RE-EXECUTED", "b blue"]
      : s.idx < ck ? ["", "REUSED", "b slate"] : ["", "PRESERVED", "b ghost"];
    const stage = result ? { detect: "done", explain: "done", replay: "done", repair: "done", verify: result.verified ? "done" : "now" }
      : staged || mode === "repair" ? { detect: "done", explain: "done", replay: "done", repair: "now" } : { detect: "done", explain: "done", replay: "now" };
    const isRoot = rc && sid === rc.sid && !run.success;
    const cur = recorded();
    const obsEv = isRoot ? rc.evidence.find((e) => e.observed) : null;
    view().innerHTML = `
      <div class="crumbs"><a href="#/runs">Runs</a><span>/</span><a href="#/investigate/${id}">${short(id)}</a><span>/</span><span class="t1">replay &amp; repair</span>${st(run.success)}</div>
      <div class="row mb"><h1>Replay &amp; Repair</h1><span class="sp"></span><a class="btn sm" href="#/investigate/${id}">${icon("explain")}Back to investigation</a></div>
      <div class="mb">${loop(stage)}</div>
      <div class="grid g2">
        <div class="panel"><div class="hd"><h2>1 · Checkpoint</h2><span class="b ${result ? "ok" : "blue"}">${result ? "CHECKPOINT RESTORED" : "REPLAY PLAN"}</span></div><div class="bd">
          <div class="cap">REPLAY FROM STEP</div>
          <select id="sid" class="mt" style="width:100%">${run.steps.map((s) => `<option value="${esc(s.sid)}" ${s.sid === sid ? "selected" : ""}>${String(s.idx + 1).padStart(2, "0")} · ${esc(s.sid)} · ${esc(s.name)} — score ${pct(by[s.sid].score)}${rc && s.sid === rc.sid ? "  ◆ likely root cause" : ""}</option>`).join("")}</select>
          <div class="versus mt2">
            <div class="vrow"><span class="lb">FULL EXECUTION</span><span class="cells">${run.steps.map(() => `<i class="full"></i>`).join("")}</span><span class="num">${run.steps.length} steps</span></div>
            <div class="vrow"><span class="lb" style="color:var(--blue-2)">BLACK BOX REPLAY</span><span class="cells">${run.steps.map((s) => `<i class="${rerun.has(s.sid) ? "re" : "us"}" title="${esc(s.sid)}"></i>`).join("")}</span><span class="num"><span style="color:var(--blue-2)">${rerun.size}</span> re-run · ${run.steps.length - rerun.size} reused</span></div>
          </div>
          <ul class="plan mt2">${run.steps.map((s) => { const [cls, l, b] = tag(s); return `<li class="${cls}"><span class="mono muted">${String(s.idx + 1).padStart(2, "0")}</span><span class="t">${esc(s.sid)} <span class="muted">${esc(s.name)}</span></span><span class="${b} nodot">${l}</span></li>`; }).join("")}</ul>
        </div></div>
        <div class="panel"><div class="hd"><h2>2 · Repair</h2>${isRoot ? `<span class="b root">LIKELY ROOT CAUSE · ${pct(rc.score)}</span>` : `<span class="b ghost nodot">SCORE ${pct(by[sid].score)}</span>`}</div><div class="bd">
          <div class="row"><span class="mono t1" style="font-size:15px">Step ${String(step().idx + 1).padStart(2, "0")} · ${esc(sid)}</span>${kind(step().kind)}<span class="muted mono" style="font-size:11px">${esc(step().name)}</span></div>
          ${obsEv ? `<div class="eo mt"><span class="k">EVIDENCE</span><span>${esc(obsEv.label)}</span>${obsEv.expected ? `<span class="k">EXPECTED</span><span class="exp">${esc(obsEv.expected)}</span>` : ""}<span class="k">OBSERVED</span><span class="obs">${esc(obsEv.observed)}</span></div>` : ""}
          <div class="cap mt2">CURRENT ${mode === "patch_args" ? "ARGUMENTS" : "VALUE"}</div>
          <div class="mono t1 mt" style="font-size:13px">${esc(summarize(cur))}</div>
          <details><summary class="cap" style="cursor:pointer;margin-top:8px">recorded JSON</summary><pre class="json">${jsonHtml(cur)}</pre></details>
          <div class="cap mt2">ALTERNATIVE EXECUTION</div>
          <div class="seg mt" id="modes">${[["repair", "Re-run step fresh"], ["patch_output", "Patch output"], ["patch_args", "Patch arguments"]].filter(([k]) => k !== "patch_args" || ["tool", "retrieval"].includes(step().kind)).map(([k, l]) => `<button data-m="${k}" class="${k === mode ? "on" : ""}">${l}</button>`).join("")}</div>
          <div class="muted mt" style="font-size:12px">${{ repair: "Re-derive this step's inputs from its parents and call the real tool or LLM again.", patch_output: "Replace this step's output with your value; every dependent step re-runs.", patch_args: "Call this step's real function with your arguments; every dependent step re-runs." }[mode]}</div>
          ${mode !== "repair" ? `
            <div class="row mt2"><span class="cap">PROPOSED FIX (JSON)</span><span class="sp"></span>${run.split === "demo" ? `<button class="btn sm" id="docfix">Use suggested repair</button>` : ""}</div>
            <textarea id="patch" rows="7" class="mt">${esc(JSON.stringify(staged ?? cur, null, 2))}</textarea>
            <div id="srcnote" class="dim" style="font-size:11px">${esc(srcNote)}</div>
            ${staged ? `<div class="card mt"><div class="row"><span class="b blue">PATCH APPLIED</span><span class="muted" style="font-size:12px">${diffFields(cur, staged).length} field(s) change · ready to replay</span></div>
              ${diffFields(cur, staged).map(([k, a, b]) => `<div class="diffline"><span class="muted">${esc(k)}</span><span class="from">${esc(JSON.stringify(a))}</span><span class="dim">→</span><span class="to">${esc(JSON.stringify(b))}</span></div>`).join("") || `<div class="muted mt" style="font-size:12px">No change from the recorded value.</div>`}</div>` : ""}
            <div class="row mt">
              <button class="btn" id="apply">${icon("check")}Apply Patch</button>
              <button class="btn primary" id="run" ${staged ? "" : "disabled"} title="${staged ? "" : "Apply the patch first"}">${icon("replay")}Run Replay</button>
              <button class="btn" id="cancel">Cancel</button></div>`
          : `<div class="row mt2"><button class="btn primary" id="run">${icon("replay")}Run Replay</button>${run.split === "demo" ? `<button class="btn sm" id="docfix">Use suggested repair</button>` : ""}<span class="dim" style="font-size:11px">${esc(srcNote)}</span></div>`}
        </div></div>
      </div>
      <div class="mt" id="verify">${verifyHtml()}</div>`;
    bind();
  };
  async function runReplay() {
    busy = true; error = null; $("#verify").innerHTML = verifyHtml();
    try { result = await api(`/api/runs/${id}/replay`, { method: "POST", body: JSON.stringify({ sid, mode, patch: mode === "repair" ? null : staged }) }); }
    catch (e) { error = e; }
    busy = false; shell();
    $("#verify").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function bind() {
    $("#sid").onchange = (e) => { sid = e.target.value; staged = null; result = null; error = null; srcNote = ""; shell(); };
    $$("#modes button").forEach((b) => (b.onclick = () => { mode = b.dataset.m; staged = null; result = null; error = null; shell(); }));
    $("#run").onclick = runReplay;
    const rt = $("#retry"); if (rt) rt.onclick = runReplay;
    const ap = $("#apply"); if (ap) ap.onclick = () => {
      try { const v = JSON.parse($("#patch").value); if (typeof v !== "object" || Array.isArray(v) || v === null) throw new Error("patch must be a JSON object"); staged = v; result = null; shell(); }
      catch (e) { toast(`Patch not applied: ${e.message}`); }
    };
    const cn = $("#cancel"); if (cn) cn.onclick = () => { staged = null; result = null; error = null; shell(); };
    const df = $("#docfix"); if (df) df.onclick = async () => {
      try {
        const p = await api(`/api/demo/patch/${id}`);
        if (p.sid !== sid || p.mode !== mode) { sid = p.sid; mode = p.mode; staged = p.patch; srcNote = `suggested: ${p.source}`; shell(); return; }
        $("#patch").value = JSON.stringify(p.patch, null, 2); srcNote = `suggested from the trace: "${p.source}"`; $("#srcnote").textContent = srcNote;
      }
      catch (e) { toast(e.message); }
    };
  }
  shell();
}

// ------------------------------------------------------------------ COMPARISONS
async function comparisons() {
  const d = await api(`/api/replays?limit=100`);
  view().innerHTML = `<h1>Comparisons</h1><div class="sub">Every replay, compared with its original execution. A repair is verified when a failed run passes the task check after replay.</div>
    <div class="mb">${loop({ detect: "done", explain: "done", replay: "done", repair: "done", verify: "now" })}</div>
    <div class="panel">${d.runs.length ? `<div class="tablewrap"><table><thead><tr><th>Original</th><th>Replay</th><th>Checkpoint</th><th>Mode</th><th>Original</th><th></th><th>Repaired</th><th class="num">Re-executed</th><th>Verification</th><th>When</th></tr></thead>
      <tbody>${d.runs.map((r) => `<tr class="click" data-go="#/compare/${r.parent_run_id}/${r.run_id}">
        <td class="mono t1">${short(r.parent_run_id)}</td><td class="mono muted">${short(r.run_id)}</td><td class="mono">${esc(r.fork_sid)}</td><td class="muted">${esc((r.fork_mode || "").replace("_", " "))}</td>
        <td>${st(r.parent_success)}</td><td class="dim">→</td><td>${st(r.success)}</td><td class="num">${r.n_reexecuted}/${r.n_steps}</td>
        <td>${r.parent_success === 0 && r.success ? `<span class="b ok">REPAIR VERIFIED</span>` : r.success ? `<span class="b ghost nodot">NO-OP</span>` : `<span class="b fail">NOT VERIFIED</span>`}</td><td class="muted">${ago(r.created)}</td></tr>`).join("")}</tbody></table></div>`
      : empty("NO REPLAY YET", "Select a suspicious step to replay from its checkpoint.", `<a class="btn primary" href="#/investigate">Investigate Trace</a>`)}</div>`;
  $$("[data-go]").forEach((el) => (el.onclick = () => go(el.dataset.go)));
}

async function compareView(a, b) {
  const c = await api(`/api/compare?a=${a}&b=${b}`);
  view().innerHTML = `
    <div class="crumbs"><a href="#/comparisons">Comparisons</a><span>/</span><span class="t1">${short(a)} vs ${short(b)}</span></div>
    <div class="row mb"><h1>Repair verification</h1>${c.fixed ? `<span class="b ok">REPAIR VERIFIED</span>` : c.b.success ? `<span class="b ok">SUCCESS</span>` : `<span class="b fail">NOT VERIFIED</span>`}<span class="sp"></span><a class="btn sm" href="#/investigate/${b}">Open replay trace</a></div>
    <div class="mb">${loop({ detect: "done", explain: "done", replay: "done", repair: "done", verify: c.fixed ? "done" : "now" })}</div>
    <div class="vsHead">
      <div class="side2"><div class="cap">ORIGINAL</div><div class="row mt">${st(c.a.success)}<a class="mono muted" href="#/investigate/${a}">${short(a)}</a></div><div class="mono t1 mt" style="font-size:18px">${esc(summarize(c.a.final))}</div></div>
      <div class="mid">VS</div>
      <div class="side2 ${c.fixed ? "fix" : ""}"><div class="cap">REPAIRED${c.b.fork_sid ? ` · FROM ${esc(c.b.fork_sid)} (${esc((c.b.fork_mode || "").replace("_", " "))})` : ""}</div><div class="row mt">${st(c.b.success)}<a class="mono muted" href="#/investigate/${b}">${short(b)}</a></div><div class="mono t1 mt" style="font-size:18px">${esc(summarize(c.b.final))}</div></div>
    </div>
    <div class="metrics mb" style="grid-template-columns:repeat(5,1fr)">
      <div class="metric"><div class="cap">EXECUTION DIVERGED AT</div><div class="v" style="font-size:16px">${esc(c.first_divergence || "—")}</div></div>
      <div class="metric"><div class="cap">CHANGED</div><div class="v green">${c.n_changed}</div><div class="s">steps</div></div>
      <div class="metric"><div class="cap">RE-EXECUTED</div><div class="v blue">${c.n_rerun}</div><div class="s">steps</div></div>
      <div class="metric"><div class="cap">REUSED</div><div class="v">${c.n_reused}</div><div class="s">steps</div></div>
      <div class="metric"><div class="cap">TASK CHECK EXPECTS</div><div class="v" style="font-size:15px">${esc(summarize(c.expected))}</div></div>
    </div>
    <div class="panel"><div class="tablewrap"><table class="cmp"><thead><tr><th>#</th><th>Step</th><th>Original</th><th>Repaired</th><th>Status</th></tr></thead><tbody>
      ${c.rows.map((r, i) => `<tr class="click ${r.changed ? "chg" : ""}" data-i="${i}">
        <td class="dim">${String(r.idx + 1).padStart(2, "0")}</td><td>${kind(r.kind)} <span class="t1">${esc(r.sid)}</span> <span class="muted">${esc(r.name)}</span></td>
        <td>${r.changed ? `<span style="color:var(--red-2)">${esc(summarize(r.before))}</span>` : `<span class="muted">${esc(summarize(r.before))}</span>`}</td>
        <td>${r.reused ? `<span class="muted">↩ same (reused)</span>` : r.changed ? `<span style="color:var(--green-2)">${esc(summarize(r.after))}</span>` : `<span class="muted">${esc(summarize(r.after))}</span>`}</td>
        <td>${r.status === "added" ? `<span class="b blue nodot">NEW PATH · ADDED</span>` : r.status === "removed" ? `<span class="b fail nodot">NOT IN REPLAY</span>` : r.reused ? `<span class="b slate nodot">REUSED</span>` : r.changed ? `<span class="b ok nodot">CHANGED · RE-EXECUTED</span>` : `<span class="b blue nodot">RE-EXECUTED · SAME</span>`}</td></tr>
        <tr class="det" data-d="${i}" style="display:none"><td></td><td colspan="4"><div class="grid g2"><div><div class="cap">ORIGINAL OUTPUT</div><pre class="json">${jsonHtml(r.before)}</pre></div><div><div class="cap">REPAIRED OUTPUT</div><pre class="json">${jsonHtml(r.after)}</pre></div></div></td></tr>`).join("")}
    </tbody></table></div></div>`;
  $$("tr[data-i]").forEach((tr) => (tr.onclick = () => { const d = $(`tr[data-d="${tr.dataset.i}"]`); d.style.display = d.style.display === "none" ? "" : "none"; }));
}

// ------------------------------------------------------------------ EVALUATION
async function evalView() {
  const [m, info] = await Promise.all([api("/api/metrics"), INFO || api("/api/info")]);
  const L = m.localization, cf = m.counterfactual || {}, v2 = m.version === "v2-graph";
  const K = MAIN(L);
  const SPL = v2 ? [["test", "Seen faults"], ["heldout", "Unseen fault types"], ["drift_loc", "Error source moved"], ["drift_topo", "New agent behaviour"]]
                 : [["test", "Seen faults"], ["heldout", "Unseen fault types"]];
  const names = v2 ? { gnn: "Graph neural network (production)", gbm: "Gradient boosting + hand-made lineage features", pagerank: "Personalized PageRank (no training)", first_suspicious: "Rule: first suspicious step", random: "Random step" }
                   : { model: "Black Box model", first_suspicious: "Rule: first suspicious step", max_anomaly: "Highest-anomaly step", last_step: "Last step", random: "Random step" };
  const bt = Object.entries(m.by_fault_type).sort((x, y) => (x[1].heldout - y[1].heldout) || (y[1].top1 - x[1].top1));
  view().innerHTML = `<h1>Evaluation</h1><div class="sub">Does the loop actually work? Numbers are read from <code>data/metrics.json</code>, produced by <code>python -m blackbox.cli all</code> on runs never used for training.${v2 ? " Traces come from a dynamic tool-calling agent via OpenTelemetry, so every run has its own graph shape." : ""}</div>
    <div class="mb">${loop({ detect: "done", explain: "done", replay: "done", repair: "done", verify: "done" })}</div>
    <div class="metrics mb">
      ${SPL.map(([k, l]) => `<div class="metric"><div class="cap">EXPLAIN · ${l.toUpperCase()}</div><div class="v blue">${pct(L[k][K].top1, 1)}</div><div class="s">top-3 ${pct(L[k][K].top3, 1)} · n=${L[k][K].n}</div></div>`).join("")}
      <div class="metric"><div class="cap">REPAIR · TOP-1 FIXES</div><div class="v green">${pct(cf.confirm_top1, 1)}</div><div class="s">repairing #1 suspect</div></div>
      <div class="metric"><div class="cap">VERIFY · FIXED ≤ 3 REPLAYS</div><div class="v green">${pct(cf.fixed_within_3, 1)}</div><div class="s">avg ${cf.avg_replays?.toFixed(2)} replays</div></div>
    </div>
    <div class="panel"><div class="hd"><h2>Root-cause localization · top-1 (top-3)</h2><span class="muted mono" style="font-size:11px">DETECT · run-failure AUC ${m.run_failure_auc.toFixed(3)}</span></div><div class="tablewrap"><table>
      <thead><tr><th>Method</th>${SPL.map(([, l]) => `<th class="num">${l}</th>`).join("")}</tr></thead>
      <tbody>${Object.keys(names).filter((k) => L.test[k]).map((k) => `<tr ${k === K ? 'style="background:var(--blue-t)"' : ""}><td>${k === K ? `<b class="t1">${names[k]}</b>` : names[k]}</td>${SPL.map(([sp]) => `<td class="num">${pct(L[sp][k].top1, 1)} <span class="dim">(${pct(L[sp][k].top3)})</span></td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="bd muted" style="font-size:12px">${v2 ? "<b>Error source moved</b>: training fault types injected at later occurrences than any training example. <b>New agent behaviour</b>: a different policy (other ordering, extra verification calls), i.e. graph shapes never seen in training. The GNN only sees per-step facts and learns propagation along trace edges; it is best or tied on 3 of 4 splits, gradient boosting is slightly ahead when the error source moves." : ""}</div></div>
    <div class="grid g2 mt">
      <div class="panel"><div class="hd"><h2>Top-1 by failure type</h2><span class="legend"><span><i style="background:var(--blue)"></i>seen</span><span><i style="background:var(--amber)"></i>never seen</span></span></div><div class="bd">
        ${bt.map(([k, v]) => `<div class="hbar" title="${esc(v.desc)}"><span class="mono" style="font-size:12px">${esc(k)}</span><div class="bar ${v.heldout ? "" : "blue"}"><i style="width:${v.top1 * 100}%"></i></div><b>${pct(v.top1)}</b></div>`).join("")}</div></div>
      <div class="panel"><div class="hd"><h2>Replay · reuse instead of re-running</h2></div><div class="bd">
        ${v2 ? `<div class="hbar"><span>Steps per repaired run</span><div class="bar red"><i style="width:100%"></i></div><b>${cf.avg_steps?.toFixed(1)}</b></div>
        <div class="hbar"><span class="t1">Re-executed by Black Box</span><div class="bar blue"><i style="width:${(cf.reexec_ratio || 0) * 100}%"></i></div><b>${cf.avg_reexec?.toFixed(1)}</b></div>
        <div class="hbar"><span>Reused (checkpoint + recorded tool calls)</span><div class="bar slate"><i style="width:${(1 - (cf.reexec_ratio || 0)) * 100}%"></i></div><b>${cf.avg_reused?.toFixed(1)}</b></div>
        <div class="muted mt" style="font-size:12px">After a repair the agent re-plans and may take a different path; tool calls with unchanged inputs are served from the recording.</div>`
        : `<div class="hbar"><span>Full re-run</span><div class="bar red"><i style="width:100%"></i></div><b>${cf.avg_steps?.toFixed(1)}</b></div><div class="hbar"><span class="t1">Black Box replay</span><div class="bar blue"><i style="width:${(cf.reexec_ratio || 0) * 100}%"></i></div><b>${cf.avg_reexec?.toFixed(1)}</b></div>`}
        <div class="cap mt2">METHODOLOGY</div>
        <div class="mt" style="font-size:12.5px">${num(m.corpus.runs)} runs (${num(m.corpus.steps)} steps), one fault per faulty run.</div>
        <div class="mt"><span class="cap">TRAINING</span> <span class="chips mt">${info.train_faults.map((f) => `<span class="chip">${f}</span>`).join("")}</span></div>
        <div class="mt"><span class="cap">HELD-OUT</span> <span class="chips mt">${info.heldout_faults.map((f) => `<span class="chip root">${f}</span>`).join("")}</span></div></div></div>
    </div>`;
}

// ------------------------------------------------------------------ LIVE DEMO (guided loop)
async function demoView() {
  const S = {};
  const STEPS = [
    ["Run agent", "detect"], ["Agent fails", "detect"], ["Black Box detects failure", "detect"], ["Root cause identified", "explain"], ["Why it was flagged", "explain"],
    ["Replay from checkpoint", "replay"], ["Patch applied", "repair"], ["Only affected steps re-executed", "repair"], ["Original vs repaired", "verify"], ["Repair verified", "verify"],
  ];
  let i = 0, auto = false, busy = false;
  const cards = [];
  const actions = [
    async () => { const r = await api("/api/demo/killer", { method: "POST" }); S.id = r.run_id; S.run = await api(`/api/runs/${S.id}`);
      return `<div class="t1" style="font-size:14px">${esc(S.run.question)}</div><div class="row mt">${agentBadge(S.run)}<span class="b blue">OPENTELEMETRY TRACE · ${S.run.n_steps} SPANS</span></div>
        <div class="muted mt" style="font-size:12px">The agent decides every tool call itself (search hotel, FX, flights, calculator, final answer). Each decision and tool call is an OpenTelemetry span; data-flow links become graph edges.</div>`; },
    async () => `<div class="outc"><div class="o"><div class="cap">AGENT ANSWER</div><div class="val" style="color:var(--red-2)">${money(S.run.final.total_usd)}</div><div class="muted">says ${S.run.final.within_budget ? "within" : "over"} budget</div></div><div class="muted" style="text-align:center">≠</div>
      <div class="o"><div class="cap">TASK CHECK EXPECTS</div><div class="val">${money(S.run.expected.total_usd)}</div><div class="muted">${S.run.expected.within_budget ? "within" : "over"} budget</div></div></div>`,
    async () => { S.dx = await api(`/api/runs/${S.id}/diagnosis`);
      return `<div class="row"><span class="b fail">TASK CHECK FAILED</span><span class="muted">Failure risk from the trace alone: <b class="t1 mono">${pct(S.dx.p_fail)}</b> · ${S.dx.steps.filter((s) => s.suspicious).length} step(s) carry anomaly signals.</span></div>`; },
    async () => { const rc = S.dx.root_cause, s = S.run.steps.find((x) => x.sid === rc.sid); S.rc = rc;
      return `<div class="row"><span class="mono t1" style="font-size:16px">Step ${String(s.idx + 1).padStart(2, "0")} · ${esc(rc.sid)}</span>${kind(rc.kind)}<span class="muted mono" style="font-size:11px">${esc(rc.name)}</span></div><div class="mt" style="max-width:520px">${confLine(rc.score)}</div>`; },
    async () => `${evidenceHtml(S.rc)}<div class="row mt"><span class="b ${S.dx.upstream.healthy ? "ok" : "fail"}">UPSTREAM ${S.dx.upstream.healthy ? "HEALTHY" : "ANOMALOUS"}</span><span class="b fail">${S.dx.impacted.length} DOWNSTREAM STEPS AFFECTED</span></div>`,
    async () => { const re = descendants(S.run.steps, S.rc.sid);
      return `<div class="versus"><div class="vrow"><span class="lb">FULL EXECUTION</span><span class="cells">${S.run.steps.map(() => `<i class="full"></i>`).join("")}</span><span class="num">${S.run.steps.length} steps</span></div>
        <div class="vrow"><span class="lb" style="color:var(--blue-2)">BLACK BOX REPLAY</span><span class="cells">${S.run.steps.map((s) => `<i class="${re.has(s.sid) ? "re" : "us"}" title="${esc(s.sid)}"></i>`).join("")}</span><span class="num">${re.size} re-run · ${S.run.steps.length - re.size} reused</span></div></div>
        <div class="muted mt" style="font-size:12px">Checkpoint at <b class="mono">${esc(S.rc.sid)}</b>: unaffected steps are restored from the recording, not re-run.</div>`; },
    async () => { S.patch = await api(`/api/demo/patch/${S.id}`); const cur = S.run.steps.find((x) => x.sid === S.patch.sid).output;
      if (S.patch.mode === "repair") return `<div class="cap">ROOT CAUSE · ${esc(S.patch.sid)}</div><div class="mt">Repair: <span class="mono t1">${esc(S.patch.source)}</span></div><div class="muted mt" style="font-size:12px">The agent then continues on its own from the restored checkpoint.</div>`;
      const flat = (o) => (o && o.args ? { ...o.args } : o);
      return `<div class="cap">ROOT CAUSE · ${esc(S.patch.sid)}</div>${diffFields(flat(cur), flat(S.patch.patch)).map(([k, a, b]) => `<div class="diffline"><span class="muted">${esc(k)}</span><span class="from">${esc(JSON.stringify(a))}</span><span class="dim">→</span><span class="to">${esc(JSON.stringify(b))}</span></div>`).join("")}
        <div class="muted mt" style="font-size:12px">Fix derived from the retrieved page: <span class="mono t1">"${esc(S.patch.source)}"</span></div>`; },
    async () => { S.res = await api(`/api/runs/${S.id}/replay`, { method: "POST", body: JSON.stringify({ sid: S.patch.sid, mode: S.patch.mode, patch: S.patch.patch }) });
      return `<div class="row"><span class="b blue">${S.res.n_reexecuted} RE-EXECUTED</span><span class="b slate">${S.res.n_reused} REUSED</span>${S.res.path_changed ? `<span class="b root nodot">AGENT TOOK A NEW PATH</span>` : ""}<span class="muted" style="font-size:12px">a full re-run would execute ${S.res.n_total}</span></div>
        <div class="chips mt">${S.res.rerun.map((x) => `<span class="chip" style="border-color:var(--blue);color:var(--blue-2)">▶ ${esc(x)}</span>`).join("")}${S.run.steps.filter((s) => !S.res.rerun.includes(s.sid)).map((s) => `<span class="chip">↩ ${esc(s.sid)}</span>`).join("")}</div>`; },
    async () => { S.cmp = await api(`/api/compare?a=${S.id}&b=${S.res.run_id}`);
      return `<div class="muted" style="font-size:12px">Execution diverged at <b class="mono t1">${esc(S.cmp.first_divergence)}</b> · ${S.cmp.n_changed} steps changed</div>
        ${S.cmp.rows.filter((r) => r.changed).map((r) => `<div class="diffline"><span class="mono">${esc(r.sid)}</span><span class="from">${esc(summarize(r.before))}</span><span class="dim">→</span><span class="to">${esc(summarize(r.after))}</span></div>`).join("")}`; },
    async () => `<div class="verify panel ${S.res.verified ? "" : "no"}" style="border-radius:4px"><div class="bd"><div class="vh">${S.res.verified ? `${icon("verify")}REPAIR VERIFIED` : `${icon("x")}REPAIR NOT VERIFIED`}</div>
      <div class="outc mt"><div class="o"><div class="cap">ORIGINAL</div><div class="mt">${st(false)}</div><div class="val">${esc(summarize(S.run.final))}</div></div><div class="muted" style="text-align:center">${icon("arrow")}</div>
      <div class="o"><div class="cap">REPAIRED</div><div class="mt">${st(S.res.success)}</div><div class="val">${esc(summarize(S.res.final))}</div></div></div>
      <div class="row mt"><a class="btn green" href="#/compare/${S.id}/${S.res.run_id}">${icon("compare")}Full comparison</a><a class="btn" href="#/investigate/${S.id}">Open investigation</a><span class="muted" style="font-size:12px">From failure to fix, without starting over: ${S.res.n_reexecuted} of ${S.res.n_total} steps re-run.</span></div></div></div>`,
  ];
  const render = () => {
    const stage = {};
    STEPS.forEach(([, k], j) => { if (j < i) stage[k] = "done"; });
    if (i < STEPS.length) stage[STEPS[i][1]] = "now";
    view().innerHTML = `<div class="row mb"><div><h1>Live demo</h1><div class="sub" style="margin-bottom:0">A real agent run fails; Black Box detects, explains, replays, repairs and verifies. Every step calls the live backend.</div></div><span class="sp"></span>
        ${i === 0 && !busy ? `<button class="btn" id="all">Run all</button><button class="btn primary" id="next">${icon("demo")}Start demo</button>`
          : i < STEPS.length ? `<button class="btn" id="all" ${busy ? "disabled" : ""}>${auto ? "Running…" : "Run all"}</button><button class="btn primary" id="next" ${busy ? "disabled" : ""}>${busy ? '<span class="spin"></span>' : "Next step →"}</button>`
          : `<button class="btn primary" id="restart">${icon("replay")}Restart demo</button>`}</div>
      <div class="mb">${loop(stage)}</div>
      <div class="demo">
        <div class="panel"><ul class="dsteps">${STEPS.map(([t], j) => `<li class="${j < i ? "done" : j === i ? "now" : ""}"><span class="n">${j < i ? "✓" : j + 1}</span><span>${t}</span></li>`).join("")}</ul></div>
        <div id="cards">${cards.length ? cards.join("") : `<div class="panel">${empty("READY", "Press <b>Start demo</b>. A tool-calling travel agent will estimate a trip and get it wrong; then watch the loop.")}</div>
          <div class="panel mt"><div class="hd"><h2>Or record your own execution</h2><span class="muted mono" style="font-size:11px">${INFO?.llm?.slm_available ? `SLM ${esc(INFO.llm.slm)} ready` : "SLM not running · benchmark policy available"}</span></div><div class="bd row">
            <select id="ra">${(INFO?.agents || []).filter((a) => a.name.startsWith("react")).map((a) => `<option value="${a.name}" ${!a.available ? "disabled" : ""}>${esc(a.label)}${a.available ? "" : " (not running)"}</option>`).join("")}</select>
            <select id="rf"><option value="">no injected fault</option>${(INFO?.train_faults || []).concat(INFO?.heldout_faults || []).map((f) => `<option value="${f}">${f}${(INFO.heldout_faults || []).includes(f) ? " (unseen)" : ""}</option>`).join("")}</select>
            <button class="btn" id="rgo">Run &amp; investigate</button></div></div>`}</div>
      </div>`;
    const n = $("#next"); if (n) n.onclick = next;
    const a = $("#all"); if (a) a.onclick = runAll;
    const r = $("#restart"); if (r) r.onclick = () => { i = 0; cards.length = 0; Object.keys(S).forEach((k) => delete S[k]); render(); };
    const rg = $("#rgo"); if (rg) rg.onclick = async () => {
      rg.disabled = true; rg.innerHTML = '<span class="spin"></span> Running…';
      try { const x = await api("/api/agent/run", { method: "POST", body: JSON.stringify({ agent: $("#ra").value, fault_type: $("#rf").value || null }) }); go(`/investigate/${x.run_id}`); }
      catch (e) { toast(e.message); rg.disabled = false; rg.textContent = "Run & investigate"; }
    };
  };
  async function next() {
    if (busy || i >= STEPS.length) return;
    busy = true; render();
    try {
      const html = await actions[i]();
      cards.push(`<div class="dcard"><div class="dh"><span class="n">STEP ${String(i + 1).padStart(2, "0")} · ${STEPS[i][1].toUpperCase()}</span><h2>${STEPS[i][0]}</h2></div>${html}</div>`);
      i++;
    } catch (e) {
      cards.push(`<div class="errbox"><div class="t">STEP ${i + 1} FAILED${e.status ? ` · HTTP ${e.status}` : ""}</div><div class="mt">${esc(e.message)}</div></div>`); auto = false;
    }
    busy = false; render();
    const last = $$("#cards > *").pop(); if (last) last.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  async function runAll() { auto = true; while (auto && i < STEPS.length) { await next(); await new Promise((r) => setTimeout(r, 900)); } auto = false; render(); }
  render();
}

// ------------------------------------------------------------------ ABOUT
async function aboutView() {
  view().innerHTML = `<h1>How Black Box works</h1><div class="sub">TRACE → RECORD → ANALYZE → LOCALIZE → EXPLAIN → CHECKPOINT → REPLAY → PATCH → COMPARE → VERIFY</div>
    <div class="grid g2">${[["Record", "Every LLM call, retrieval and tool call is logged to an append-only SQLite recorder with arguments, output, timing, errors and data-flow parents. State at any step is the fold of recorded outputs, so it can be restored."],
      ["Localize & explain", "A gradient-boosted model ranks steps using trace-only signals (grounding, baseline deviation, lineage, blast radius). Evidence is measured by removing signals and re-scoring."],
      ["Replay & repair", "Re-execute only the checkpoint step and its descendants through the agent's real step functions; reuse everything else. Re-run fresh, patch the output, or patch the arguments."],
      ["Compare & verify", "A step-aligned diff of original and repaired runs; the repair is verified when the task check passes."]].map(([t, d]) => `<div class="panel"><div class="bd"><h2>${t}</h2><div class="muted mt">${d}</div></div></div>`).join("")}</div>
    <div class="panel mt"><div class="bd muted" style="font-size:12.5px">Scope: the model is trained on traces from the reference travel-expense agent (simulated and LLM variants). Any Python agent can be recorded through <code>blackbox.sdk</code>; replay requires an adapter that can re-invoke its steps.</div></div>`;
}

// ------------------------------------------------------------------ boot
(async () => {
  try {
    INFO = await api("/api/info");
    $("#api-st").innerHTML = `<span class="dot ok"></span>RECORDER ONLINE`;
    $("#llm-st").innerHTML = INFO.model_version === "v2"
      ? `<span class="dot ${INFO.llm.slm_available ? "ok" : "warn"}"></span>MODEL · ${esc(INFO.llm.slm)}${INFO.llm.slm_provider ? " (" + esc(INFO.llm.slm_provider.toUpperCase()) + ")" : ""} ${INFO.llm.slm_available ? "READY" : "NOT RUNNING"}`
      : `LLM · ${esc(INFO.llm.provider === "anthropic" ? INFO.llm.model : "OFFLINE MOCK")}`;
  } catch (_) { $("#api-st").innerHTML = `<span class="dot hit"></span>API OFFLINE`; }
  router();
})();
