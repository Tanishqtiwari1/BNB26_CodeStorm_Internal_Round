"""Training + evaluation for the dynamic-agent (graph) benchmark.

Methods compared on every split:
  gnn               graph neural network over the trace graph (production model)
  gbm               per-step gradient boosting with hand-made lineage features (v1 approach)
  pagerank          training-free personalized PageRank RCA
  first_suspicious  rule baseline (flagged steps in order, the rest shuffled)
  random
Splits: test (seen), heldout (unseen fault types), drift_loc (seen types at unseen
locations), drift_topo (seen types, unseen agent behaviour / graph shapes).
"""
import json
import random
import time
from collections import defaultdict

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from . import features as FT
from . import graph_model as GM
from . import model as M
from .faults_v2 import DESCRIPTIONS, HELDOUT_FAULTS
from .recorder import Recorder

SPLITS = ["test", "heldout", "drift_loc", "drift_topo"]
METHODS = ["gnn", "gbm", "pagerank", "first_suspicious", "random"]


def train(db="data/blackbox.db", out="data/model_v2.joblib", epochs=60):
    rec = Recorder(db)
    runs, steps = M.load_corpus(rec)
    # deterministic tools have ~zero historical variance, so a 1% floor keeps small drifts visible
    norms = FT.build_norms((steps[r] for r, m in runs.items() if m["split"] == "train" and m["success"]), floor=0.01)
    graphs, Xs, ys, Xr, yr = [], [], [], [], []
    for rid, m in runs.items():
        if m["split"] != "train":
            continue
        st = steps[rid]
        rows, sig, _ = FT.run_features(st, norms)
        Xr.append(FT.run_level(st, rows, sig))
        yr.append(0 if m["success"] else 1)
        if not m["success"] and m["fault_sid"]:
            truth = next(i for i, s in enumerate(st) if s["sid"] == m["fault_sid"])
            X, ps, cs, _ = GM.graph_of(st, norms)
            graphs.append((X, ps, cs, truth))
            Xs.extend(rows)
            ys.extend(int(i == truth) for i in range(len(st)))
    t0 = time.time()
    W = GM.train_gnn(graphs, epochs=epochs)
    print(f"trained GNN on {len(graphs)} failed traces in {time.time() - t0:.0f}s")
    clf = HistGradientBoostingClassifier(max_iter=350, learning_rate=0.06, max_leaf_nodes=31, l2_regularization=1.0,
                                         class_weight="balanced", random_state=0).fit(M._X(Xs), np.array(ys))
    run_clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, random_state=0).fit(
        np.array([[r[f] for f in FT.RUN_FEATURES] for r in Xr]), np.array(yr))
    bundle = {"kind": "v2", "gnn": W, "clf": clf, "run_clf": run_clf, "norms": norms, "features": FT.MODEL_FEATURES,
              "node_features": GM.NODE_FEATURES, "trained_at": f"v2-{time.time():.0f}"}
    joblib.dump(bundle, out)
    return bundle


def rank_with(method, bundle, st, dx, g, rng):
    X, ps, cs, sig = g
    n = len(st)
    if method == "gnn":
        return list(np.argsort(-GM.gnn_scores(bundle["gnn"], X, ps, cs)[1], kind="stable"))
    if method == "gbm":
        p = bundle["clf"].predict_proba(M._X(dx["rows"]))[:, 1]
        return list(np.argsort(-p, kind="stable"))
    if method == "pagerank":
        return list(np.argsort(-GM.pagerank_scores(sig, st, ps), kind="stable"))
    return M.baseline_rank(method, st, dx, rng)


def evaluate(db="data/blackbox.db", model="data/model_v2.joblib", out="data/metrics.json", replay_eval=True):
    from . import replay_v2 as RP2
    rec = Recorder(db)
    bundle = joblib.load(model)
    runs, steps = M.load_corpus(rec)
    rng = random.Random(0)
    res = {sp: {m: {"top1": [], "top3": [], "rr": []} for m in METHODS} for sp in SPLITS}
    by_type = defaultdict(lambda: {"top1": [], "top3": [], "split": set()})
    yt, yp = [], []
    cf = {"confirm1": [], "fix3": [], "replays": [], "reexec": [], "total": [], "reused": []}
    for rid, m in runs.items():
        if m["split"] not in SPLITS:
            continue
        st = steps[rid]
        dx = diagnose(bundle, st)
        yt.append(0 if m["success"] else 1)
        yp.append(dx["p_fail"])
        if m["success"] or not m["fault_sid"]:
            continue
        truth = next(i for i, s in enumerate(st) if s["sid"] == m["fault_sid"])
        g = (dx["X"], dx["parents"], dx["children"], dx["sig"])
        for meth in METHODS:
            rk = rank_with(meth, bundle, st, dx, g, rng)
            pos = rk.index(truth)
            R = res[m["split"]][meth]
            R["top1"].append(pos == 0)
            R["top3"].append(pos < 3)
            R["rr"].append(1 / (pos + 1))
        pos = dx["ranking"].index(truth)
        bt = by_type[m["fault_type"]]
        bt["top1"].append(pos == 0)
        bt["top3"].append(pos < 3)
        bt["split"].add(m["split"])
        if replay_eval and m["split"] in ("test", "heldout", "drift_loc", "drift_topo"):
            fixed, tries = False, 0
            for k in dx["ranking"][:3]:
                tries += 1
                f = RP2.fork(rec, rid, st[k]["sid"], "repair", save=False)
                if tries == 1:
                    cf["confirm1"].append(f["success"])
                    cf["reexec"].append(f["n_reexecuted"])
                    cf["reused"].append(f["n_reused"])
                    cf["total"].append(f["n_total"])
                if f["success"]:
                    fixed = True
                    break
            cf["fix3"].append(fixed)
            cf["replays"].append(tries)
    mean = lambda xs: float(np.mean(xs)) if xs else 0.0
    loc = {sp: {meth: {k: mean(v) for k, v in R.items()} | {"n": len(R["top1"])} for meth, R in d.items()} for sp, d in res.items()}
    metrics = {
        "version": "v2-graph",
        "localization": loc,
        "by_fault_type": {t: {"top1": mean(v["top1"]), "top3": mean(v["top3"]), "n": len(v["top1"]), "heldout": t in HELDOUT_FAULTS,
                              "splits": sorted(v["split"]), "desc": DESCRIPTIONS[t]} for t, v in by_type.items()},
        "run_failure_auc": float(roc_auc_score(yt, yp)),
        "corpus": {"runs": len(runs), "failed": int(sum(1 for m in runs.values() if not m["success"])),
                   "steps": int(sum(len(v) for v in steps.values()))},
    }
    if replay_eval:
        metrics["counterfactual"] = {"confirm_top1": mean(cf["confirm1"]), "fixed_within_3": mean(cf["fix3"]),
                                     "avg_replays": mean(cf["replays"]), "avg_steps": mean(cf["total"]),
                                     "avg_reexec": mean(cf["reexec"]), "avg_reused": mean(cf["reused"]),
                                     "reexec_ratio": mean(cf["reexec"]) / max(1e-9, mean(cf["total"]))}
    json.dump(metrics, open(out, "w"), indent=2)
    return metrics


def diagnose(bundle, steps):
    """Same contract as model.diagnose, ranked by the GNN."""
    X, ps, cs, sig = GM.graph_of(steps, bundle["norms"])
    rows, desc = FT.rows_from_signals(steps, sig)
    logits, p = GM.gnn_scores(bundle["gnn"], X, ps, cs)
    p_fail = float(bundle["run_clf"].predict_proba(M._Xr(FT.run_level(steps, rows, sig)))[0, 1])
    return {"probs": p.tolist(), "logits": logits.tolist(), "ranking": [int(i) for i in np.argsort(-p, kind="stable")],
            "p_fail": p_fail, "rows": rows, "sig": sig, "desc": desc, "X": X, "parents": ps, "children": cs}


def contribs(bundle, steps, dx, i):
    """Occlusion for the GNN: neutralise a signal group in the trace, rebuild node features, re-score node i."""
    base = dx["probs"][i]
    sid = steps[i]["sid"]
    d = dx["sig"][sid]

    def score_with(sig_over):
        Xn = dx["X"].copy()
        for j, s in enumerate(steps):
            if s["sid"] in sig_over:
                dd = sig_over[s["sid"]]
                Xn[j, :10] = [min(dd["value_z"], 20) / 5, dd["arg_grounding"], dd["out_grounding"], float(dd["null_fields"] > 0),
                              dd["retrieval_relevance"], min(dd["doc_len_z"], 20) / 5, dd["error"], dd["exception"], dd["n_signals"], dd["score"] / 4]
        return float(GM.gnn_scores(bundle["gnn"], Xn, dx["parents"], dx["children"])[1][i])
    out = {}
    for g, neutral in M.LOCAL_GROUPS.items():
        out[g] = base - score_with({sid: FT.derive({**d, **neutral})})
    allneutral = {k: v for g in M.LOCAL_GROUPS.values() for k, v in g.items()}
    joint = base - score_with({sid: FT.derive({**d, **allneutral})})
    D = dx["desc"][sid]
    out["downstream_impact"] = base - score_with({x: FT.derive({**dx["sig"][x], **allneutral}) for x in D}) if D else 0.0
    anc = [s["sid"] for s in steps if sid in dx["desc"][s["sid"]]]
    out["upstream_clean"] = base - score_with({x: FT.derive({**dx["sig"][x], "value_z": 10.0}) for x in anc}) if anc else 0.0
    out["errors"] = out.get("errors", 0.0)
    return out, base, joint
