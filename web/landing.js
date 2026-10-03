/* Black Box landing page. Every number and every step shown here is read from the live API. */
"use strict";
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null ? "—" : `${(x * 100).toFixed(d)}%`);
const num = (x) => (x == null ? "—" : Number(x).toLocaleString());
const money = (x) => `$${Number(x).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const nn = (i) => String(i + 1).padStart(2, "0");
const titleCase = (s) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (_) {} throw new Error(m); }
  return r.json();
}
function stepName(s) {
  if (s.kind === "input") return "User task";
  if (s.name === "final_answer") return "Final answer";
  if (s.name.startsWith("call:")) return `Decide: ${titleCase(s.name.slice(5))}`;
  return titleCase(s.name);
}
function summarize(o) {
  if (o == null || typeof o !== "object") return String(o ?? "—");
  if (o.tool && o.args) return `${o.tool}(${Object.values(o.args).map((v) => (typeof v === "string" ? v : JSON.stringify(v))).join(", ")})`;
  if (o.question) return `“${o.question.slice(0, 60)}…”`;
  if (o.total_usd !== undefined) return `${money(o.total_usd)}${o.within_budget == null ? "" : o.within_budget ? " · within budget" : " · over budget"}`;
  if (o.text) return `“${o.text.slice(0, 60)}…”`;
  for (const k of ["value", "usd", "rate", "amount"]) if (o[k] != null) return `${k}: ${typeof o[k] === "number" ? o[k].toLocaleString() : o[k]}`;
  const s = JSON.stringify(o); return s.length > 60 ? s.slice(0, 60) + "…" : s;
}
function descendants(steps, sid) {
  const out = new Set([sid]); let grew = true;
  while (grew) { grew = false; for (const s of steps) if (!out.has(s.sid) && s.parents.some((p) => out.has(p))) { out.add(s.sid); grew = true; } }
  return out;
}

// ------------------------------------------------------------------ pick a real failed run to show
async function showcaseRun() {
  const demo = await api("/api/runs?split=demo&status=failed&limit=1");
  if (demo.runs.length) return demo.runs[0].run_id;
  const t = await api("/api/runs?split=test&status=failed&limit=60");
  const good = t.runs.filter((r) => r.root && r.root.sid === r.fault_sid && r.root.score > 0.9 && r.n_steps >= 8 && r.n_steps <= 16);
  return (good[0] || t.runs[0]).run_id;
}

let RUN, DX, M, INFO;
const status = (sid) => (sid === DX.root_cause.sid ? "root" : DX.impacted.includes(sid) ? "hit" : "ok");

// ------------------------------------------------------------------ hero debugger
function renderNodes(sel, replay) {
  $("#dbgnodes").innerHTML = RUN.steps.map((s) => {
    let k = status(s.sid), tag = k === "root" ? `<span class="tag root">ROOT CAUSE · ${pct(DX.root_cause.score)}</span>` : k === "hit" ? `<span class="tag hit">IMPACTED</span>` : `<span class="tag ok">OK</span>`;
    if (replay) { const rr = replay.rerun.includes(s.sid); k = rr ? "rerun" : "reused"; tag = rr ? `<span class="tag rerun">RE-EXECUTED</span>` : `<span class="tag reused">REUSED</span>`; }
    return `<div class="node ${k} ${s.sid === sel ? "sel" : ""}" data-sid="${esc(s.sid)}"><span class="n">${nn(s.idx)}</span><span class="t">${esc(stepName(s))}<small>${esc(summarize(s.output))}</small></span>${tag}</div>`;
  }).join("");
  document.querySelectorAll("#dbgnodes .node").forEach((n) => (n.onclick = () => inspect(n.dataset.sid)));
}
function rootDiag() {
  const rc = DX.root_cause, st = RUN.steps.find((s) => s.sid === rc.sid);
  const ev = rc.evidence.find((e) => !["upstream_clean", "downstream_impact"].includes(e.signal)) || rc.evidence[0];
  $("#dbgdiag").className = "diag";
  $("#dbgdiag").innerHTML = `<div class="h"><span>⚠ ROOT CAUSE: STEP ${nn(st.idx)} · ${esc(stepName(st).toUpperCase())}</span><span>${DX.impacted.length} STEPS IMPACTED</span></div>${esc(ev?.text || "")}`;
}
function inspect(sid) {
  const s = RUN.steps.find((x) => x.sid === sid);
  if (sid === DX.root_cause.sid) { rootDiag(); }
  else {
    const k = status(sid);
    $("#dbgdiag").className = k === "ok" ? "diag ok" : "diag";
    $("#dbgdiag").innerHTML = `<div class="h"><span>STEP ${nn(s.idx)} · ${esc(stepName(s).toUpperCase())}</span><span>${k === "hit" ? "CONSUMED THE BAD VALUE" : "LOOKS NORMAL"}</span></div>Output: <b>${esc(summarize(s.output))}</b>`;
  }
  document.querySelectorAll("#dbgnodes .node").forEach((n) => n.classList.toggle("sel", n.dataset.sid === sid));
}
async function heroReplay() {
  const b = $("#dbgreplay"); b.disabled = true; b.innerHTML = `<span class="spin"></span> Replaying…`;
  try {
    let body = { sid: DX.root_cause.sid, mode: "repair", patch: null };
    if (RUN.split === "demo") { const p = await api(`/api/demo/patch/${RUN.run_id}`); body = { sid: p.sid, mode: p.mode, patch: p.patch }; }
    const r = await api(`/api/runs/${RUN.run_id}/replay`, { method: "POST", body: JSON.stringify(body) });
    renderNodes(null, r);
    $("#dbgdiag").className = r.success ? "diag ok" : "diag";
    $("#dbgdiag").innerHTML = `<div class="h"><span>${r.verified ? "✓ REPAIR VERIFIED" : r.success ? "✓ REPLAY PASSED" : "✕ NOT FIXED"}</span><span>${r.n_reused} REUSED · ${r.n_reexecuted} RE-EXECUTED</span></div>
      <b>${esc(summarize(RUN.final))}</b> → <b>${esc(summarize(r.final))}</b>. Only the root-cause step and what depends on it ran again. <a href="/app#/compare/${RUN.run_id}/${r.run_id}" style="color:var(--indigo-3);font-weight:600">Full comparison →</a>`;
    $("#dbgstatus").className = `badge ${r.success ? "ok" : "fail"}`; $("#dbgstatus").textContent = r.success ? "REPAIRED" : "STILL FAILING";
    b.innerHTML = "↺ Reset"; b.disabled = false; b.onclick = () => { renderHero(); };
  } catch (e) { $("#dbgdiag").innerHTML = `<div class="h"><span>REPLAY FAILED</span></div>${esc(e.message)}`; b.innerHTML = "↻ Replay from root cause"; b.disabled = false; }
}
function renderHero() {
  const agent = RUN.agent === "react-slm" ? `${RUN.meta?.model || "real model"}` : RUN.agent === "react-sim" ? "benchmark agent" : RUN.agent;
  $("#dbgtitle").textContent = `RUN #${RUN.run_id.slice(0, 6)} · ${agent}`;
  $("#dbgstatus").className = "badge fail"; $("#dbgstatus").textContent = `FAILED · ${RUN.n_steps} STEPS`;
  renderNodes(DX.root_cause.sid); rootDiag();
  const box = $("#dbgnodes"), rn = box.querySelector(".node.root");
  if (rn) box.scrollTop = Math.max(0, rn.offsetTop - box.offsetTop - box.clientHeight / 2 + rn.clientHeight / 2);
  $("#dbgnote").textContent = RUN.split === "demo" ? "real recorded run · injected tool bug" : "recorded benchmark run · injected fault";
  const b = $("#dbgreplay"); b.disabled = !RUN.replayable; b.innerHTML = "↻ Replay from root cause"; b.onclick = heroReplay;
}

// ------------------------------------------------------------------ problem cascade
function renderChain() {
  const st = RUN.steps, ri = st.findIndex((s) => s.sid === DX.root_cause.sid), last = st.length - 1;
  const keep = new Set([0, 1, Math.max(0, ri - 1), ri, last]);
  DX.impacted.slice(0, 3).forEach((sid) => keep.add(st.findIndex((s) => s.sid === sid)));
  const idx = [...keep].filter((i) => i >= 0).sort((a, b) => a - b);
  let html = "", prev = -1;
  idx.forEach((i, j) => {
    if (j) html += `<div class="arrow ${i > ri && prev >= ri ? "hot" : ""}">${i - prev > 1 ? "⋯" : "→"}</div>`;
    const s = st[i], k = status(s.sid);
    html += `<div class="cn ${k} ${i === last ? "end" : ""}" title="${esc(summarize(s.output))}"><span class="n">STEP ${nn(i)}</span><b>${esc(stepName(s))}</b><span class="muted" style="font-size:11.5px">${k === "root" ? "bad value created" : k === "hit" ? "passes it on" : i === last ? "error visible" : "fine"}</span></div>`;
    prev = i;
  });
  $("#chain").innerHTML = html;
  const rs = st[ri], ev = DX.root_cause.evidence.find((e) => e.observed) || {};
  $("#chaincap").innerHTML = `<div><b>Step ${nn(ri)}: where it went wrong.</b> ${esc(stepName(rs))} returned ${esc(summarize(rs.output))}${ev.expected ? ` (normally ${esc(ev.expected)})` : ""}.</div>
    <div><b>${DX.impacted.length} steps passed it along.</b> Each one looked fine on its own, so nothing raised an error.</div>
    <div><b>Step ${nn(last)}: where you notice.</b> The final answer was ${esc(summarize(RUN.final))}; the correct one was ${esc(summarize(RUN.expected))}.</div>`;
}

// ------------------------------------------------------------------ without vs with
function renderVs() {
  const L = M.localization, K = L.test.gnn ? "gnn" : "model", cf = M.counterfactual;
  const steps = Math.round(cf.avg_steps);
  $("#vs").innerHTML = `
    <div class="vcol no"><div class="vh">✕ WITHOUT BLACK BOX</div>
      <div class="vrow"><span class="ic">1</span><span>The run fails. The error shows up in the <b>final answer</b>, not where it started.</span></div>
      <div class="vrow"><span class="ic">2</span><span>An engineer reads the logs of all <b>${steps} steps</b> and guesses which one broke.</span></div>
      <div class="vrow"><span class="ic">3</span><span>To test a fix, the agent runs <b>from the beginning</b>, repeating every model call.</span></div>
      <div class="vrow"><span class="ic">4</span><span>If the guess was wrong, repeat from step 2.</span></div>
      <div class="vres">${steps} of ${steps} steps re-run per attempt</div></div>
    <div class="vcol yes"><div class="vh">✓ WITH BLACK BOX</div>
      <div class="vrow"><span class="ic">1</span><span>Every step is <b>recorded</b> as an OpenTelemetry trace as the agent runs.</span></div>
      <div class="vrow"><span class="ic">2</span><span>The step that caused the failure is ranked <b>#1 in ${pct(L.test[K].top1)}</b> of cases, with evidence.</span></div>
      <div class="vrow"><span class="ic">3</span><span>Replay starts at that step's <b>checkpoint</b>; everything before it is reused.</span></div>
      <div class="vrow"><span class="ic">4</span><span>The repaired run is <b>checked and compared</b> automatically: ${pct(cf.confirm_top1)} pass after repairing the #1 suspect.</span></div>
      <div class="vres">${cf.avg_reexec.toFixed(1)} of ${steps} steps re-run on average (${pct(cf.reexec_ratio)})</div></div>`;
}

// ------------------------------------------------------------------ lifecycle tabs
function renderTabs() {
  const rc = DX.root_cause, rs = RUN.steps.find((s) => s.sid === rc.sid), cf = M.counterfactual;
  const plan = descendants(RUN.steps, rc.sid), reused = RUN.steps.length - plan.size;
  const ev = rc.evidence.filter((e) => !["upstream_clean", "downstream_impact"].includes(e.signal));
  const d = rc.evidence.find((e) => e.observed);
  const T = [
    ["DETECT", "Record every step and catch the failure",
      "Each model decision and tool call becomes an OpenTelemetry span: inputs, outputs, timing, and which earlier step each value came from. The task check flags the wrong answer, and a model estimates failure risk from the trace alone.",
      `<div class="row"><span class="k">ANSWER</span><code style="color:var(--red-2)">${esc(summarize(RUN.final))}</code></div><div class="row"><span class="k">EXPECTED</span><code style="color:var(--green-2)">${esc(summarize(RUN.expected))}</code></div><div class="row"><span class="k">SPANS</span><code>${RUN.n_steps}</code></div><div class="row"><span class="k">RISK</span><code>${pct(DX.p_fail)} from the trace alone</code></div>`, "/app#/runs?status=failed", "See failed runs"],
    ["EXPLAIN", "Point at the cause, with evidence",
      "A graph neural network reads the trace as a graph and ranks every step. It learns how errors travel through data flow, so it finds the first bad step even when the agent's path changes. The evidence uses facts from the trace: expected versus observed values.",
      `<div class="row"><span class="k">ROOT CAUSE</span><code>Step ${nn(rs.idx)} · ${esc(stepName(rs))}</code></div><div class="row"><span class="k">CONFIDENCE</span><code>${pct(rc.score, 1)}</code></div>${d ? `<div class="row"><span class="k">EXPECTED</span><code style="color:var(--green-2)">${esc(d.expected)}</code></div><div class="row"><span class="k">OBSERVED</span><code style="color:var(--red-2)">${esc(d.observed)}</code></div>` : ""}<div class="row"><span class="k">WHY</span><span style="color:var(--text-2)">${esc((ev[0] || rc.evidence[0]).text)}</span></div>`, `/app#/investigate/${RUN.run_id}`, "Open this investigation"],
    ["REPLAY", "Restart from the checkpoint, not from zero",
      "The state just before the root-cause step is rebuilt from the recording. Only that step and the steps that used its output run again; the agent can even choose a new path from there.",
      `<div class="row"><span class="k">REUSED</span><div class="bar"><i style="width:${(reused / RUN.steps.length) * 100}%;background:#2b3342"></i></div><code>${reused}</code></div><div class="row"><span class="k">RE-RUN</span><div class="bar"><i style="width:${(plan.size / RUN.steps.length) * 100}%;background:var(--indigo)"></i></div><code>${plan.size}</code></div><div class="row"><span class="k">AVERAGE</span><code>${pct(1 - cf.reexec_ratio)} of steps reused across the benchmark</code></div>`, `/app#/repair/${RUN.run_id}?sid=${encodeURIComponent(rc.sid)}`, "Open the replay workspace"],
    ["REPAIR", "Change one step and try again",
      "Re-run the step fresh, edit its output, or edit its arguments in the patch editor. Changes are validated before the replay starts, and a console shows each replay event.",
      `<div class="row"><span class="k">MODE 1</span><code>Re-run fresh</code><span class="muted">call the tool or model again</span></div><div class="row"><span class="k">MODE 2</span><code>Patch output</code><span class="muted">correct the bad value</span></div><div class="row"><span class="k">MODE 3</span><code>Patch arguments</code><span class="muted">fix what was sent to a tool</span></div>`, `/app#/repair/${RUN.run_id}?sid=${encodeURIComponent(rc.sid)}&mode=patch_output`, "Try the patch editor"],
    ["VERIFY", "Prove the fix holds",
      "The repaired run goes through the same task check and is diffed step by step against the original, so you see exactly where the two executions diverged and what it cost to test the fix.",
      `<div class="row"><span class="k">FIXED (#1)</span><code>${pct(cf.confirm_top1, 1)} of failures pass after repairing the top suspect</code></div><div class="row"><span class="k">WITHIN 3</span><code>${pct(cf.fixed_within_3, 1)} fixed within three replays</code></div><div class="row"><span class="k">DIFF</span><code>step-aligned, first divergence, latency waterfall</code></div>`, "/app#/comparisons", "See comparisons"],
  ];
  let on = 0;
  const draw = () => {
    $("#tabs").innerHTML = T.map((t, i) => `<button class="${i === on ? "on" : ""}" data-i="${i}"><i>0${i + 1}</i>${t[0]}</button>`).join("");
    document.querySelectorAll("#tabs button").forEach((b) => (b.onclick = () => { on = +b.dataset.i; draw(); }));
    const t = T[on];
    $("#tabpanel").outerHTML = `<div class="tabpanel" id="tabpanel"><div><h3 style="font-size:22px">${t[1]}</h3><p>${t[2]}</p><a class="link" href="${t[4]}">${t[5]} →</a></div><div class="mini">${t[3]}</div></div>`;
  };
  draw();
}

// ------------------------------------------------------------------ results
function renderResults() {
  const L = M.localization, K = L.test.gnn ? "gnn" : "model", cf = M.counterfactual;
  $("#ressub").textContent = `${num(M.corpus.runs)} recorded agent runs with one injected, labelled fault per failing run. Every number below is measured on runs held out from training and read from the same metrics file the app's Evaluation page uses.`;
  $("#stats").innerHTML = [
    [pct(L.test[K].top1, 1), "root cause ranked #1 (seen fault types)", "var(--indigo-3)"],
    [pct(L.heldout[K].top1, 1), "ranked #1 on fault types never seen in training", "var(--indigo-3)"],
    [pct(cf.confirm_top1, 1), "of failures fixed by repairing the #1 suspect", "var(--green-2)"],
    [pct(1 - cf.reexec_ratio), "of steps reused instead of re-run", "var(--green-2)"],
  ].map(([v, l, c]) => `<div class="stat"><div class="v" style="color:${c}">${v}</div><div class="l">${l}</div></div>`).join("");
  const names = { gnn: "Black Box (graph neural network)", gbm: "Gradient boosting", first_suspicious: "Rule: first suspicious step", pagerank: "PageRank (no learning)", random: "Random step" };
  $("#methods").innerHTML = Object.keys(names).filter((k) => L.test[k]).map((k) => `<div class="mrow ${k === K ? "me" : ""}"><span>${names[k]}</span><div class="bar"><i style="width:${L.test[k].top1 * 100}%;background:${k === K ? "linear-gradient(90deg,var(--indigo),var(--cyan))" : "#3a4558"}"></i></div><b>${pct(L.test[k].top1)}</b></div>`).join("");
  $("#splits").innerHTML = [["heldout", "Fault types never seen"], ["drift_loc", "Error source moved"], ["drift_topo", "Agent behaves differently"]].filter(([k]) => L[k])
    .map(([k, l]) => `<div class="mrow"><span>${l}</span><div class="bar"><i style="width:${L[k][K].top1 * 100}%;background:var(--indigo)"></i></div><b>${pct(L[k][K].top1)}</b></div>`).join("");
  $("#honest").textContent = "Honest scope: the benchmark is one travel-expense workflow with injected faults. On a completely different sample agent, Black Box ranked the true cause first in 9 of 18 failures; accuracy on a new agent improves as it builds up that agent's own history.";
}

function renderSnippet() {
  const o = location.origin;
  $("#snippet").innerHTML = `<span class="c"># Send one trace per run from any agent (Python, standard library)</span>
<span class="k">import</span> json, urllib.request

trace = {
  <span class="s">"question"</span>: <span class="s">"Refund order A-1042"</span>,
  <span class="s">"service"</span>:  <span class="s">"my-support-bot"</span>,
  <span class="s">"success"</span>:  <span class="k">False</span>,
  <span class="s">"steps"</span>: [
    {<span class="s">"id"</span>: <span class="s">"t1"</span>, <span class="s">"name"</span>: <span class="s">"get_order"</span>, <span class="s">"kind"</span>: <span class="s">"tool"</span>,
     <span class="s">"output"</span>: {<span class="s">"total"</span>: <span class="n">59.99</span>}},
    {<span class="s">"id"</span>: <span class="s">"d1"</span>, <span class="s">"name"</span>: <span class="s">"call:issue_refund"</span>, <span class="s">"kind"</span>: <span class="s">"llm"</span>,
     <span class="s">"parents"</span>: [<span class="s">"t1"</span>],
     <span class="s">"output"</span>: {<span class="s">"tool"</span>: <span class="s">"issue_refund"</span>, <span class="s">"args"</span>: {<span class="s">"amount"</span>: <span class="n">599.9</span>}}},
  ],
}
req = urllib.request.Request(<span class="s">"${esc(o)}/api/traces"</span>,
        data=json.dumps(trace).encode(),
        headers={<span class="s">"Content-Type"</span>: <span class="s">"application/json"</span>})
print(json.load(urllib.request.urlopen(req)))  <span class="c"># → {"runs": ["…"]}</span>`;
}

// ------------------------------------------------------------------ boot
(async () => {
  renderSnippet();
  try {
    [INFO, M] = await Promise.all([api("/api/info"), api("/api/metrics")]);
    const live = INFO.llm.slm_available;
    $("#status").innerHTML = `<i class="dot"></i>Recorder online${live ? ` · ${esc(INFO.llm.slm)}` : ""}`;
    $("#proof").innerHTML = `<span>OpenTelemetry traces</span><span>Graph neural network diagnosis</span><span>${live ? `Live agent: ${esc(INFO.llm.slm)}` : "Live agent: benchmark policy"}</span>`;
    renderVs(); renderResults();
  } catch (e) { $("#status").innerHTML = `<i class="dot off"></i>API offline`; }
  try {
    const id = await showcaseRun();
    [RUN, DX] = await Promise.all([api(`/api/runs/${id}`), api(`/api/runs/${id}/diagnosis`)]);
    renderHero(); renderChain(); if (M) renderTabs();
  } catch (e) {
    $("#dbgtitle").textContent = "Could not load a recorded run";
    $("#dbgnodes").innerHTML = `<div class="muted" style="font-size:13px">${esc(e.message)}. <a href="/app" style="color:var(--indigo-3)">Open the app →</a></div>`;
  }
})();
