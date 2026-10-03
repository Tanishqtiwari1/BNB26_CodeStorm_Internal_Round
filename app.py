"""Black Box -- flight recorder & debugger for AI agents (Streamlit dashboard).

    streamlit run app.py
"""
import json
import random

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from blackbox import agent as A
from blackbox import faults as F
from blackbox import model as M
from blackbox import replay as RP
from blackbox.recorder import Recorder

st.set_page_config(page_title="Black Box · Agent Flight Recorder", page_icon="🟧", layout="wide",
                   initial_sidebar_state="collapsed")

ORANGE, RED, GREEN, GREY, BLUE = "#FF7A1A", "#E5484D", "#30A46C", "#8B8D98", "#3E9BFF"
st.markdown("""
<style>
.block-container {padding-top: 3.4rem; max-width: 1400px;}
.kpi {background: #16181D; border: 1px solid #2A2D35; border-radius: 12px; padding: 14px 16px;}
.kpi .v {font-size: 1.9rem; font-weight: 700; color: #FF7A1A; line-height: 1.1;}
.kpi .l {font-size: .82rem; color: #A7A9B4; margin-top: 4px;}
.ev {background: #16181D; border-left: 0; border: 1px solid #2A2D35; border-radius: 10px; padding: 10px 14px; margin: 6px 0;}
.pill {display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600;}
.pass {background: #12351F; color: #3DD68C;} .fail {background: #3B1219; color: #FF6369;}
.muted {color: #A7A9B4; font-size: .85rem;}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ resources
@st.cache_resource
def rec():
    return Recorder("data/blackbox.db")


@st.cache_resource
def bundle():
    return M.load("data/model.joblib")


@st.cache_data
def metrics():
    return json.load(open("data/metrics.json"))


def runs_df():
    return rec().runs_df("parent_run_id IS NULL")


def kpi(col, value, label):
    col.markdown(f'<div class="kpi"><div class="v">{value}</div><div class="l">{label}</div></div>', unsafe_allow_html=True)


def pill(ok):
    return f'<span class="pill {"pass" if ok else "fail"}">{"PASS" if ok else "FAIL"}</span>'


def short(o, n=90):
    s = json.dumps(o)
    return s if len(s) <= n else s[:n] + "…"


# ------------------------------------------------------------------ visuals
def dag_figure(steps, probs=None, highlight=None, rerun=None, height=420):
    by = {s["sid"]: s for s in steps}
    depth = {}
    for s in steps:
        depth[s["sid"]] = 1 + max([depth[p] for p in s["parents"] if p in depth] or [-1])
    cols = {}
    for s in steps:
        cols.setdefault(depth[s["sid"]], []).append(s["sid"])
    pos = {}
    for d, sids in cols.items():
        for j, sid in enumerate(sids):
            pos[sid] = (d, -(j - (len(sids) - 1) / 2))
    ex, ey = [], []
    for s in steps:
        for p in s["parents"]:
            if p in pos:
                ex += [pos[p][0], pos[s["sid"]][0], None]
                ey += [pos[p][1], pos[s["sid"]][1], None]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ex, y=ey, mode="lines", line=dict(color="#3A3D46", width=1), hoverinfo="skip"))
    xs = [pos[s["sid"]][0] for s in steps]
    ys = [pos[s["sid"]][1] for s in steps]
    if rerun is not None:
        color = [ORANGE if s["sid"] in rerun else "#3A3D46" for s in steps]
        line = ["#FFFFFF" if s["sid"] == highlight else color[i] for i, s in enumerate(steps)]
        marker = dict(size=20, color=color, line=dict(color=line, width=2))
    else:
        p = probs or [0] * len(steps)
        marker = dict(size=[14 + 22 * v for v in p], color=p, colorscale=[[0, "#2A2D35"], [0.5, "#B54A0B"], [1, ORANGE]],
                      cmin=0, cmax=1, line=dict(color=["#FFFFFF" if s["sid"] == highlight else "#0E1117" for s in steps], width=2),
                      colorbar=dict(title="suspicion", thickness=10))
    hover = [f"<b>{s['sid']}</b> · {s['name']}<br>out: {short(s['output'], 60)}" +
             (f"<br>suspicion: {probs[i]:.2f}" if probs else "") for i, s in enumerate(steps)]
    if probs:
        keep = set(sorted(range(len(steps)), key=lambda i: -probs[i])[:4])
    else:
        keep = {i for i, s in enumerate(steps) if s["sid"] == highlight or s["kind"] == "final"}
    labels = [s["sid"] if (i in keep or s["sid"] == highlight) else "" for i, s in enumerate(steps)]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", marker=marker, text=labels,
                             textposition="top center", textfont=dict(size=11, color="#EDEEF0"),
                             hovertext=hover, hoverinfo="text"))
    fig.update_layout(height=height, showlegend=False, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(visible=False), yaxis=dict(visible=False),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def timeline_figure(steps, probs, truth_idx=None):
    colors = [ORANGE if p == max(probs) else "#5A3A26" if p > 0.2 else "#2F323A" for p in probs]
    fig = go.Figure(go.Bar(x=[f"{i}·{s['sid']}" for i, s in enumerate(steps)], y=probs, marker_color=colors,
                           hovertext=[f"{s['name']}: {short(s['output'], 60)}" for s in steps]))
    if truth_idx is not None:
        fig.add_annotation(x=f"{truth_idx}·{steps[truth_idx]['sid']}", y=probs[truth_idx], text="injected fault",
                           showarrow=True, arrowcolor=GREEN, font=dict(color=GREEN), yshift=6)
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=20, b=10), yaxis=dict(title="P(root cause)", range=[0, 1.1]),
                      xaxis=dict(tickangle=-60, tickfont=dict(size=9)),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


# ------------------------------------------------------------------ pages
def page_overview():
    m = metrics()
    L, cf = m["localization"], m.get("counterfactual", {})
    st.markdown("#### A flight recorder for AI agents: find the step that broke the run, show the evidence, verify the fix.")
    c = st.columns(5)
    kpi(c[0], f"{L['test']['model']['top1']:.0%}", "Top-1 root-cause accuracy<br>seen failure types")
    kpi(c[1], f"{L['heldout']['model']['top1']:.0%}", "Top-1 accuracy on<br><b>unseen</b> failure types")
    kpi(c[2], f"{cf.get('fixed_within_3', 0):.0%}", "Failures fixed & verified<br>within 3 replays")
    kpi(c[3], f"{1 - cf.get('reexec_ratio', 0):.0%}", "Steps skipped by<br>dependency-aware replay")
    kpi(c[4], f"{m['run_failure_auc']:.2f}", "Run-failure prediction<br>AUC (trace only)")
    st.write("")
    a, b = st.columns([1.15, 1])
    with a:
        st.subheader("Model vs. baselines")
        rows = []
        for sp, lab in (("test", "Seen types"), ("heldout", "Unseen types")):
            for meth in M.METHODS:
                rows.append({"split": lab, "method": meth, "Top-1": L[sp][meth]["top1"], "Top-3": L[sp][meth]["top3"]})
        df = pd.DataFrame(rows)
        fig = go.Figure()
        palette = {"model": ORANGE, "first_suspicious": BLUE, "max_anomaly": "#8E4EC6", "last_step": GREY, "random": "#45474F"}
        for meth in M.METHODS:
            d = df[df.method == meth]
            fig.add_trace(go.Bar(name=meth.replace("_", " "), x=d.split, y=d["Top-1"], marker_color=palette[meth],
                                 text=[f"{v:.0%}" for v in d["Top-1"]], textposition="outside"))
        fig.update_layout(barmode="group", height=360, yaxis=dict(tickformat=".0%", range=[0, 1.1], title="Top-1 accuracy"),
                          margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.15),
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")
    with b:
        st.subheader("Accuracy by failure type")
        bt = pd.DataFrame([{"fault": k, "Top-1": v["top1"], "Top-3": v["top3"], "n": v["n"],
                            "set": "unseen" if v["heldout"] else "seen", "what": v["desc"]}
                           for k, v in m["by_fault_type"].items()]).sort_values(["set", "Top-1"])
        fig = go.Figure(go.Bar(y=bt.fault, x=bt["Top-1"], orientation="h",
                               marker_color=[ORANGE if s == "seen" else BLUE for s in bt.set],
                               text=[f"{v:.0%}" for v in bt["Top-1"]], textposition="outside", hovertext=bt.what))
        fig.update_layout(height=360, xaxis=dict(tickformat=".0%", range=[0, 1.25]), margin=dict(l=10, r=10, t=10, b=10),
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch")
        st.markdown('<span class="muted">🟧 seen in training · 🟦 never seen in training</span>', unsafe_allow_html=True)
    cc = m["corpus"]
    st.markdown(f'<span class="muted">Corpus: {cc["runs"]:,} recorded runs · {cc["steps"]:,} steps · {cc["failed"]:,} failures. '
                f'Avg run {cf.get("avg_steps", 0):.0f} steps; a verifying replay re-executes {cf.get("avg_reexec", 0):.1f} '
                f'vs {cf.get("avg_suffix", 0):.1f} for a naive re-run from the suspect step.</span>', unsafe_allow_html=True)


def pick_run():
    df = runs_df()
    c1, c2, c3 = st.columns([1, 1, 2])
    which = c1.selectbox("Runs", ["Failed · unseen types", "Failed · seen types (test)", "Failed · live", "All test runs"])
    if which.startswith("Failed · unseen"):
        d = df[(df.split == "heldout") & (df.success == 0)]
    elif which.startswith("Failed · seen"):
        d = df[(df.split == "test") & (df.success == 0) & df.fault_type.notna()]
    elif which.startswith("Failed · live"):
        d = df[(df.split == "live") & (df.success == 0)]
    else:
        d = df[df.split.isin(["test", "heldout"])]
    types = sorted(t for t in d.fault_type.dropna().unique())
    ft = c2.selectbox("Failure type", ["any"] + types)
    if ft != "any":
        d = d[d.fault_type == ft]
    if d.empty:
        st.info("No runs match.")
        return None
    ids = d.run_id.tolist()
    default = st.session_state.get("run_id")
    idx = ids.index(default) if default in ids else 0
    rid = c3.selectbox("Run", ids, index=idx, format_func=lambda r: f"{r} · {d.set_index('run_id').loc[r, 'question'][:70]}…")
    st.session_state["run_id"] = rid
    return rid


def page_investigate():
    st.title("🔎 Investigate a failed run")
    rid = pick_run()
    if not rid:
        return
    run, steps = rec().run(rid), rec().steps(rid)
    dx = M.diagnose(bundle(), steps)
    probs = dx["probs"]
    top = dx["ranking"][0]
    st.markdown(f"**Task:** {run['question']}")
    c = st.columns(4)
    kpi(c[0], pill(bool(run["success"])), "Outcome (vs. task checker)")
    kpi(c[1], f"${run['final'].get('total_usd', 0) or 0:,.0f}", f"Agent answer · expected ${run['expected']['total_usd']:,.0f}")
    kpi(c[2], f"{dx['p_fail']:.0%}", "Predicted failure risk (trace only)")
    kpi(c[3], f"{steps[top]['sid']}", f"Most likely root cause · {probs[top]:.0%}")
    show_truth = st.toggle("Reveal injected fault (ground truth)", value=False)
    truth_idx = next((i for i, s in enumerate(steps) if s["sid"] == run["fault_sid"]), None) if show_truth else None
    if show_truth and run["fault"]:
        rank = dx["ranking"].index(truth_idx) + 1
        verdict = "✅ Black Box ranked it #1." if rank == 1 else f"Black Box ranked it #{rank}."
        unseen = " (failure type never seen in training)" if run["fault_type"] in F.HELDOUT_FAULTS else ""
        st.markdown(f"Injected **{run['fault_type']}** at **{run['fault_sid']}**: "
                    f"{F.DESCRIPTIONS[run['fault_type']]}. {verdict}{unseen}")
    st.plotly_chart(timeline_figure(steps, probs, truth_idx), width="stretch")
    a, b = st.columns([1.1, 1])
    with a:
        st.subheader("Execution graph")
        st.plotly_chart(dag_figure(steps, probs, highlight=steps[top]["sid"]), width="stretch")
    with b:
        st.subheader("Top suspects & evidence")
        for rank, i in enumerate(dx["ranking"][:3]):
            ex = M.explain(bundle(), steps, dx, i)
            with st.container(border=True):
                st.markdown(f"**#{rank + 1} · {steps[i]['sid']}** `{steps[i]['name']}` · suspicion **{probs[i]:.0%}**")
                for e in ex["evidence"][:3] or [{"text": "Weak signals only.", "weight": 0}]:
                    st.markdown(f"- {e['text']}")
                if st.button(f"Replay from {steps[i]['sid']} →", key=f"rp{i}"):
                    st.session_state["fork_sid"] = steps[i]["sid"]
                    st.session_state["page"] = "Replay Lab"
                    st.rerun()
    with st.expander("Step inspector (full trace)"):
        tdf = pd.DataFrame([{"#": s["idx"], "step": s["sid"], "kind": s["kind"], "op": s["name"],
                             "suspicion": round(probs[i], 3), "args": short(s["args"], 70),
                             "output": short(s["output"], 70), "latency ms": s["latency_ms"], "error": s["error"]}
                            for i, s in enumerate(steps)])
        st.dataframe(tdf, width="stretch", hide_index=True)


def page_replay():
    st.title("⏪ Replay Lab")
    st.markdown('<span class="muted">Restore the checkpoint before a step, change it, and re-execute <b>only</b> the steps that '
                'depend on it. Everything else is reused from the recording.</span>', unsafe_allow_html=True)
    rid = pick_run()
    if not rid:
        return
    run, steps = rec().run(rid), rec().steps(rid)
    dx = M.diagnose(bundle(), steps)
    sids = [s["sid"] for s in steps]
    default = st.session_state.get("fork_sid") or steps[dx["ranking"][0]]["sid"]
    c1, c2 = st.columns([1, 1])
    sid = c1.selectbox("Fork at step", sids, index=sids.index(default) if default in sids else 0,
                       format_func=lambda x: f"{x} · {steps[sids.index(x)]['name']} · suspicion {dx['probs'][sids.index(x)]:.0%}")
    mode = c2.radio("Alternative execution", ["repair", "patch_output", "patch_args"], horizontal=True,
                    captions=["re-derive & re-run fresh", "edit the step's output", "edit the step's arguments"])
    s = steps[sids.index(sid)]
    patch = None
    if mode != "repair":
        src = s["output"] if mode == "patch_output" else s["args"]
        txt = st.text_area("Patch (JSON)", json.dumps(src, indent=1), height=140)
        try:
            patch = json.loads(txt)
        except json.JSONDecodeError:
            st.error("Invalid JSON")
            return
    b1, b2, _ = st.columns([1, 1.3, 3])
    go_fork = b1.button("▶ Run fork", type="primary")
    auto = b2.button("⚡ Auto-verify top-3 suspects")
    if go_fork:
        st.session_state["fork"] = (rid, RP.fork(rec(), rid, sid, mode, patch))
    if auto:
        log = []
        for k in dx["ranking"][:3]:
            f = RP.fork(rec(), rid, steps[k]["sid"], "repair")
            log.append((steps[k]["sid"], f))
            if f["success"]:
                break
        st.session_state["auto"] = log
        st.session_state["fork"] = (rid, log[-1][1])
    if st.session_state.get("auto") and auto:
        for sid_k, f in st.session_state["auto"]:
            st.markdown(f"Repair **{sid_k}** → {pill(f['success'])} · re-executed {f['n_reexecuted']}/{f['n_total']} steps",
                        unsafe_allow_html=True)
    src, f = st.session_state.get("fork", (None, None))
    if not f or src != rid:
        return
    st.divider()
    c = st.columns(4)
    kpi(c[0], f"{pill(f['orig_success'])} → {pill(f['success'])}", "Outcome: original → fork")
    kpi(c[1], f"{f['n_reexecuted']}/{f['n_total']}", "Steps re-executed (dependency-aware)")
    kpi(c[2], f"{f['n_suffix']}", "Naive re-run from the step would need")
    kpi(c[3], f"${(f['final'] or {}).get('total_usd', 0) or 0:,.0f}", f"New answer · expected ${f['expected']['total_usd']:,.0f}")
    a, b = st.columns([1, 1.2])
    with a:
        st.subheader("What was re-executed")
        fsid = f["rerun"][0] if f["rerun"] else None
        st.plotly_chart(dag_figure(f["steps"], highlight=fsid, rerun=set(f["rerun"]), height=380), width="stretch")
        st.markdown('<span class="muted">🟧 re-executed · ⬛ reused from recording</span>', unsafe_allow_html=True)
    with b:
        st.subheader("Trace comparison")
        dd = f["diff"]
        st.markdown(f"First divergence: **{dd['first_divergence']}** · {dd['n_changed']} step(s) changed")
        df = pd.DataFrame([{"step": r["sid"], "changed": "●" if r["changed"] else "", "reused": "✓" if r["reused"] else "",
                            "original": short(r["before"], 48), "fork": short(r["after"], 48)} for r in dd["rows"]])
        st.dataframe(df.style.apply(lambda row: ["background-color: #3A2412" if row.changed else "" for _ in row], axis=1),
                     width="stretch", hide_index=True, height=380)


def page_live():
    st.title("🛫 Live: record a brand-new run")
    st.markdown('<span class="muted">Generate a new task, optionally break one step, execute the agent under the recorder, '
                'and diagnose it immediately.</span>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1.4, 1])
    seed = c1.number_input("Task seed", 0, 10**6, random.randint(0, 99999))
    ftype = c2.selectbox("Inject fault", ["none"] + F.TRAIN_FAULTS + [f + " (unseen)" for f in F.HELDOUT_FAULTS])
    if c3.button("✈ Execute & record", type="primary"):
        rng = random.Random(int(seed))
        task = A.make_task(rng)
        fault = None
        if ftype != "none":
            fault = F.make_fault(ftype.replace(" (unseen)", ""), A.build_plan(task), task, rng)
        recs = A.execute(task, fault=fault, rng=rng)
        ok, gt = A.judge(task, recs[-1]["output"])
        rid = rec().save_run(task, recs, recs[-1]["output"], ok, gt, fault, split="live")
        rec().commit()
        st.session_state["run_id"] = rid
        st.session_state["live"] = rid
    rid = st.session_state.get("live")
    if rid:
        run, steps = rec().run(rid), rec().steps(rid)
        dx = M.diagnose(bundle(), steps)
        top = dx["ranking"][0]
        st.markdown(f"**Task:** {run['question']}")
        c = st.columns(3)
        kpi(c[0], pill(bool(run["success"])), f"Outcome · fault: {run['fault_type'] or 'none'} @ {run['fault_sid'] or '—'}")
        kpi(c[1], f"{dx['p_fail']:.0%}", "Predicted failure risk")
        kpi(c[2], steps[top]["sid"], f"Top suspect · {dx['probs'][top]:.0%}")
        st.plotly_chart(timeline_figure(steps, dx["probs"]), width="stretch")
        if not run["success"]:
            for e in M.explain(bundle(), steps, dx, top)["evidence"][:3]:
                st.markdown(f"- {e['text']}")
            if st.button("Investigate this run →"):
                st.session_state["page"] = "Investigate"
                st.rerun()


def page_how():
    st.title("⚙️ How Black Box works")
    st.graphviz_chart("""
digraph G { rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", fillcolor="#16181D", color="#FF7A1A", fontcolor="white", fontname="Helvetica"]; edge [color="#8B8D98"];
agent [label="AI agent\\n(LLM · tools · retrieval)"]; rec [label="Flight recorder\\nappend-only SQLite\\nargs · outputs · data-flow"];
feat [label="Trace features\\ngrounding · baselines\\nlineage · timing"]; model [label="Diagnosis model\\nroot-cause ranking\\n+ failure risk"];
exp [label="Evidence\\n(occlusion → trace facts)"]; rep [label="Checkpointed replay\\nre-run only dependents"]; cmp [label="Trace comparison\\nfirst divergence · outcome"];
inj [label="Fault injector\\nknown root causes", color="#3E9BFF"]; agent -> rec -> feat -> model -> exp; model -> rep -> cmp; inj -> agent [style=dashed]; rep -> model [label=" verifies", style=dashed]; }
""")
    st.markdown("""
- **Record:** every model call, retrieval and tool call is logged with its arguments, output, timing, errors and *which earlier steps it read from*. State at any step is the fold of outputs up to it (event sourcing), so any point can be restored.
- **Learn:** a fault injector breaks exactly one step per run, which gives labelled root causes for free. A gradient-boosted model learns *fault-agnostic* signals: values not grounded in inputs, deviation from historical baselines, the earliest anomaly in a step's lineage, and how far damage spread downstream.
- **Generalise:** three failure types (truncated context, off-by-one, stale cache) are **never** shown in training and are used to test generalisation.
- **Explain:** each verdict is backed by occlusion over feature groups and translated into concrete facts from the trace.
- **Verify:** replay re-executes only the suspect step and its data-flow descendants. Black Box automatically repairs the top suspects until the run passes, so the diagnosis is confirmed rather than just guessed.
""")


PAGES = {"Overview": page_overview, "Investigate": page_investigate, "Replay Lab": page_replay,
         "Live run": page_live, "How it works": page_how}
cur = st.session_state.get("page", "Overview")
nav = st.columns([1.3, 5])
nav[0].markdown("#### 🟧 Black Box")
choice = nav[1].segmented_control("Navigate", list(PAGES), default=cur, label_visibility="collapsed",
                                  key=f"nav_{cur}")
if choice and choice != cur:
    st.session_state["page"] = choice
    st.rerun()
PAGES[st.session_state.get("page", "Overview")]()
