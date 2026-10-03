"""Diagnosis models, baselines, evaluation and explanations.

* Step model  : learns which step in a failed run is the root cause
                (pointwise gradient boosting, ranked per run).
* Run model   : learns to predict whether a run failed from its trace alone.
* Baselines   : random, last-step, max-anomaly, first-suspicious heuristic.
* Explanation : occlusion over feature groups -> evidence from the trace.
"""
import json
import math
import random
from collections import defaultdict

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from . import features as FT
from . import replay as RP
from .faults import DESCRIPTIONS, HELDOUT_FAULTS
from .recorder import Recorder


# ------------------------------------------------------------------ data
def load_corpus(rec):
    runs = {r["run_id"]: r for r in rec.runs_df().to_dict("records")}
    steps = defaultdict(list)
    cur = rec.db.execute("SELECT s.* FROM steps s JOIN runs r USING(run_id) WHERE r.parent_run_id IS NULL "
                         "ORDER BY s.run_id, s.idx")
    cols = [c[0] for c in cur.description]
    for row in cur:
        d = dict(zip(cols, row))
        d["parents"] = json.loads(d.pop("parents_json"))
        d["args"] = json.loads(d.pop("args_json"))
        d["output"] = json.loads(d.pop("output_json"))
        steps[d["run_id"]].append(d)
    return runs, steps


def _X(rows):
    return np.array([[r[f] for f in FT.MODEL_FEATURES] for r in rows], dtype=float)


def _Xr(r):
    return np.array([[r[f] for f in FT.RUN_FEATURES]], dtype=float)


# ------------------------------------------------------------------ train
def train(db="data/blackbox.db", out="data/model.joblib"):
    rec = Recorder(db)
    runs, steps = load_corpus(rec)
    norms = FT.build_norms(steps[r] for r, m in runs.items() if m["split"] == "train" and m["success"])
    Xs, ys, Xr, yr = [], [], [], []
    for rid, m in runs.items():
        if m["split"] != "train":
            continue
        rows, sig, _ = FT.run_features(steps[rid], norms)
        Xr.append(FT.run_level(steps[rid], rows, sig))
        yr.append(0 if m["success"] else 1)
        if not m["success"] and m["fault_sid"]:
            Xs.extend(rows)
            ys.extend(int(s["sid"] == m["fault_sid"]) for s in steps[rid])
    clf = HistGradientBoostingClassifier(max_iter=350, learning_rate=0.06, max_leaf_nodes=31,
                                         l2_regularization=1.0, class_weight="balanced", random_state=0)
    clf.fit(_X(Xs), np.array(ys))
    run_clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, random_state=0)
    run_clf.fit(np.array([[r[f] for f in FT.RUN_FEATURES] for r in Xr]), np.array(yr))
    import time
    bundle = {"clf": clf, "run_clf": run_clf, "norms": norms, "features": FT.MODEL_FEATURES,
              "trained_at": f"{time.time():.0f}"}
    joblib.dump(bundle, out)
    return bundle, len(Xs), sum(ys)


def load(path="data/model.joblib"):
    return joblib.load(path)


# ------------------------------------------------------------------ inference
def diagnose(bundle, steps):
    rows, sig, desc = FT.run_features(steps, bundle["norms"])
    p = bundle["clf"].predict_proba(_X(rows))[:, 1]
    p_fail = float(bundle["run_clf"].predict_proba(_Xr(FT.run_level(steps, rows, sig)))[0, 1])
    order = list(np.argsort(-p))
    return {"probs": p.tolist(), "ranking": [int(i) for i in order], "p_fail": p_fail,
            "rows": rows, "sig": sig, "desc": desc}


# local signal groups: neutralise the raw signal in the trace, recompute all features
LOCAL_GROUPS = {
    "value_anomaly": {"value_z": 0.0},
    "arg_grounding": {"arg_grounding": 1.0},
    "out_grounding": {"out_grounding": 1.0},
    "null_fields": {"null_fields": 0.0},
    "retrieval": {"retrieval_relevance": 1.0, "doc_len_z": 0.0, "doc_len_ratio": 1.0},
    "errors": {"error": 0.0, "exception": 0.0},
}
# structural groups: override features directly
ROW_GROUPS = {
    "downstream_impact": {"desc_mean_z": 0.0, "frac_desc_anom": 0.0, "desc_max_score": 0.0},
    "upstream_clean": {"max_anc_z": 10.0, "anc_ground_min": 0.0, "anc_susp": 2.0, "anc_max_score": 4.0,
                       "lineage_root": 0.0, "earliest_suspicious": 0.0, "n_suspicious_before": 3.0},
}


SIGNAL_LABELS = {"value_anomaly": "Value anomaly", "arg_grounding": "Argument mismatch",
                 "out_grounding": "Ungrounded output", "null_fields": "Missing field",
                 "retrieval": "Retrieval inconsistency", "downstream_impact": "Downstream impact",
                 "upstream_clean": "Upstream healthy", "errors": "Step error"}


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.4g}" if abs(v) < 1 else f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


def explain(bundle, steps, dx, i):
    """Evidence for step i, ranked by how much each signal drives the model's score."""
    rows, sig = dx["rows"], dx["sig"]
    s, d, r = steps[i], dx["sig"][steps[i]["sid"]], rows[i]
    base = float(bundle["clf"].predict_proba(_X([r]))[0, 1])
    contribs = {}
    for g, neutral in LOCAL_GROUPS.items():
        sg = dict(sig)
        sg[s["sid"]] = FT.derive({**d, **neutral})
        rr, _ = FT.rows_from_signals(steps, sg)
        contribs[g] = base - float(bundle["clf"].predict_proba(_X([rr[i]]))[0, 1])
    # joint effect of all local signals (they often overlap, which hides each one alone)
    sg = dict(sig)
    allneutral = {k: v for g in LOCAL_GROUPS.values() for k, v in g.items()}
    sg[s["sid"]] = FT.derive({**d, **allneutral})
    rr, _ = FT.rows_from_signals(steps, sg)
    joint_local = base - float(bundle["clf"].predict_proba(_X([rr[i]]))[0, 1])
    for g, over in ROW_GROUPS.items():
        rr = {**r, **over}
        rr["new_anom"] = rr["value_z"] - rr["max_anc_z"]
        contribs[g] = base - float(bundle["clf"].predict_proba(_X([rr]))[0, 1])
    D = dx["desc"][s["sid"]]
    anom_d = [x for x in D if sig[x]["value_z"] > 3 or sig[x]["local_ground"] < 1]
    by = {x["sid"]: x for x in steps}
    parent_atoms = [a for p in s["parents"] if p in by for a in FT._atoms(by[p]["output"])]
    ev = []
    local_first = sorted(contribs.items(), key=lambda kv: (kv[0] in ROW_GROUPS, -kv[1]))
    for g, c in local_first:
        # local signals are facts about this step: always shown when present;
        # structural context only when it actually moves the score
        if g in ROW_GROUPS and c < 0.01:
            continue
        item = None
        if g == "value_anomaly" and d["value_z"] > 2:
            item = dict(text=(f"Output {_fmt(d['value'])} deviates {d['value_z']:.1f}σ from the historical baseline "
                              f"for `{d['norm_key']}` (typical ≈ {_fmt(d.get('typical', 0.0))})."),
                        expected=f"≈ {_fmt(d.get('typical', 0.0))} (historical baseline)", observed=_fmt(d["value"]))
        elif g == "arg_grounding" and d["arg_grounding"] < 1:
            ung = d["ungrounded_args"]
            same = sorted({str(a) for a in parent_atoms if isinstance(a, str) == isinstance(ung[0], str)
                           and len(str(a)) < 30}, key=str)
            item = dict(text=(f"Argument value(s) {', '.join(map(_fmt, ung))} do not appear in any upstream "
                              f"output ({', '.join(s['parents'])})."),
                        expected=("upstream provides " + ", ".join(same)) if 0 < len(same) <= 4 else "a value from upstream output",
                        observed=", ".join(map(_fmt, ung)))
        elif g == "out_grounding" and d["out_grounding"] < 1:
            src = s["args"].get("context") or s["args"].get("question") or ""
            import re as _re
            nums = list(dict.fromkeys(float(m.replace(",", "")) for m in _re.findall(r"\d[\d,]*(?:\.\d+)?", src)))
            item = dict(text=(f"Output value(s) {', '.join(map(_fmt, d['ungrounded_out']))} are not present in the step's "
                              f"input context, so they look fabricated."),
                        expected="a value present in the input" + (f" ({', '.join(_fmt(n) for n in nums[:6])})" if nums else ""),
                        observed=", ".join(map(_fmt, d["ungrounded_out"])))
        elif g == "null_fields" and d["null_fields"] > 0:
            item = dict(text=f"Output has empty field(s): {', '.join(d['null_paths'])}; downstream steps fell back to defaults.",
                        expected="value present", observed="null at " + ", ".join(d["null_paths"]))
        elif g == "retrieval":
            txt = str(s["output"].get("text", ""))
            if d["retrieval_relevance"] < 1:
                item = dict(text=f"Retrieved document does not mention the query “{s['args'].get('query')}”.",
                            expected=f"document about “{s['args'].get('query')}”",
                            observed=f"document about “{txt.split(',')[0][:40]}”")
            elif d["doc_len_z"] > 3:
                item = dict(text=(f"Retrieved document is {d['doc_len_ratio']:.0%} of its usual length "
                                  f"({d['doc_len_z']:.1f}σ from baseline), so content may be missing."),
                            expected=f"≈ {bundle['norms']['doclen'][0]:.0f} characters", observed=f"{len(txt)} characters")
        elif g == "downstream_impact" and anom_d:
            item = dict(text=f"{len(anom_d)} of {len(D)} downstream steps that consumed this output became anomalous.")
        elif g == "upstream_clean" and r["anc_ground_min"] >= 1 and r["max_anc_z"] <= 3:
            n_anc = int(sum(1 for x in steps[:i] if s["sid"] in dx["desc"][x["sid"]]))
            item = dict(text=(f"All {n_anc} upstream step(s) look normal, so the anomaly first appears here."
                              if n_anc else "This is a root step with no upstream dependencies; the anomaly originates here."))
        elif g == "errors" and s["error"]:
            item = dict(text=f"Step reported: {s['error']}.", observed=str(s["output"].get("error", s["error"]))[:120])
        if item:
            ev.append({"signal": g, "label": SIGNAL_LABELS[g], "weight": round(c, 3), **item})
    return {"score": base, "evidence": ev, "contribs": contribs, "joint_local": joint_local}


def analyze(bundle, steps, top_k=3):
    """Everything the UI/API needs about one trace: per-step scores, signals,
    root-cause ranking with evidence, downstream impact and step statuses.
    Uses only the observable steps -- never run-level fault labels."""
    dx = diagnose(bundle, steps)
    probs, ranking = dx["probs"], dx["ranking"]
    children = defaultdict(list)
    for s in steps:
        for p in s["parents"]:
            children[p].append(s["sid"])
    root = ranking[0] if steps else None
    root_sid = steps[root]["sid"] if root is not None else None
    impacted = dx["desc"].get(root_sid, set()) if root_sid else set()
    per_step = []
    for i, s in enumerate(steps):
        d = dx["sig"][s["sid"]]
        per_step.append({"sid": s["sid"], "score": round(probs[i], 4), "rank": ranking.index(i) + 1,
                         "flags": FT.signal_flags(d), "suspicious": d["suspicious"],
                         "children": children[s["sid"]]})
    suspects = []
    for i in ranking[:top_k]:
        ex = explain(bundle, steps, dx, i)
        suspects.append({"sid": steps[i]["sid"], "idx": i, "name": steps[i]["name"], "kind": steps[i]["kind"],
                         "score": round(probs[i], 4), "evidence": ex["evidence"],
                         "joint_local": round(ex["joint_local"], 4),
                         "contribs": {k: round(v, 4) for k, v in ex["contribs"].items()}})
    anc = [x["sid"] for x in steps if root_sid and root_sid in dx["desc"][x["sid"]]]
    upstream = {"steps": anc, "anomalous": [x for x in anc if dx["sig"][x]["suspicious"]]}
    upstream["healthy"] = not upstream["anomalous"]
    return {"p_fail": round(dx["p_fail"], 4), "root_cause": suspects[0] if suspects else None, "upstream": upstream,
            "suspects": suspects, "steps": per_step, "impacted": sorted(impacted, key=lambda x: [s["sid"] for s in steps].index(x)),
            "impacted_anomalous": [x for x in impacted if dx["sig"][x]["suspicious"]]}


# ------------------------------------------------------------------ baselines
def baseline_rank(name, steps, dx, rng):
    n = len(steps)
    idx = list(range(n))
    if name == "random":
        rng.shuffle(idx)
        return idx
    if name == "last_step":
        return list(range(n - 2, -1, -1)) + [n - 1]
    z = [dx["sig"][s["sid"]]["value_z"] for s in steps]
    if name == "max_anomaly":
        return sorted(idx, key=lambda i: -z[i])
    if name == "first_suspicious":  # flagged steps in order; unflagged ones are unordered
        sus = [i for i in idx if dx["sig"][steps[i]["sid"]]["suspicious"]]
        rest = [i for i in idx if i not in sus]
        rng.shuffle(rest)
        return sus + rest
    raise ValueError(name)


METHODS = ["model", "first_suspicious", "max_anomaly", "last_step", "random"]


def evaluate(db="data/blackbox.db", model="data/model.joblib", out="data/metrics.json", replay_eval=True):
    rec = Recorder(db)
    bundle = load(model)
    runs, steps = load_corpus(rec)
    rng = random.Random(0)
    res = {sp: {m: {"top1": [], "top3": [], "rr": []} for m in METHODS} for sp in ("test", "heldout")}
    by_type = defaultdict(lambda: {"top1": [], "top3": []})
    yt, yp = [], []
    cf = {"confirm1": [], "fix3": [], "replays": [], "reexec": [], "suffix": [], "total": []}
    for rid, m in runs.items():
        if m["split"] not in ("test", "heldout"):
            continue
        st = steps[rid]
        dx = diagnose(bundle, st)
        yt.append(0 if m["success"] else 1)
        yp.append(dx["p_fail"])
        if m["success"] or not m["fault_sid"]:
            continue
        truth = next(i for i, s in enumerate(st) if s["sid"] == m["fault_sid"])
        for meth in METHODS:
            rk = dx["ranking"] if meth == "model" else baseline_rank(meth, st, dx, rng)
            pos = rk.index(truth)
            R = res[m["split"]][meth]
            R["top1"].append(pos == 0)
            R["top3"].append(pos < 3)
            R["rr"].append(1 / (pos + 1))
        pos = dx["ranking"].index(truth)
        by_type[m["fault_type"]]["top1"].append(pos == 0)
        by_type[m["fault_type"]]["top3"].append(pos < 3)
        if replay_eval:
            fixed, tries, reex = False, 0, 0
            for k in dx["ranking"][:3]:
                tries += 1
                f = RP.fork(rec, rid, st[k]["sid"], "repair", save=False)
                reex += f["n_reexecuted"]
                if tries == 1:
                    cf["confirm1"].append(f["success"])
                    cf["suffix"].append(f["n_suffix"])
                    cf["total"].append(f["n_total"])
                    cf["reexec"].append(f["n_reexecuted"])
                if f["success"]:
                    fixed = True
                    break
            cf["fix3"].append(fixed)
            cf["replays"].append(tries)
    mean = lambda xs: float(np.mean(xs)) if xs else 0.0
    metrics = {
        "localization": {sp: {meth: {k: mean(v) for k, v in R.items()} | {"n": len(R["top1"])}
                              for meth, R in d.items()} for sp, d in res.items()},
        "by_fault_type": {t: {"top1": mean(v["top1"]), "top3": mean(v["top3"]), "n": len(v["top1"]),
                              "heldout": t in HELDOUT_FAULTS, "desc": DESCRIPTIONS[t]} for t, v in by_type.items()},
        "run_failure_auc": float(roc_auc_score(yt, yp)),
    }
    if replay_eval:
        metrics["counterfactual"] = {
            "confirm_top1": mean(cf["confirm1"]), "fixed_within_3": mean(cf["fix3"]),
            "avg_replays": mean(cf["replays"]),
            "reexec_ratio": mean(cf["reexec"]) / max(1e-9, mean(cf["total"])),
            "suffix_ratio": mean(cf["suffix"]) / max(1e-9, mean(cf["total"])),
            "avg_steps": mean(cf["total"]), "avg_reexec": mean(cf["reexec"]), "avg_suffix": mean(cf["suffix"])}
    corpus = {"runs": len(runs), "failed": int(sum(1 for m in runs.values() if not m["success"])),
              "steps": int(sum(len(v) for v in steps.values()))}
    metrics["corpus"] = corpus
    json.dump(metrics, open(out, "w"), indent=2)
    return metrics
