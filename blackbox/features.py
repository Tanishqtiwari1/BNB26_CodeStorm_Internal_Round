"""Step-level features computed purely from the observable trace.

Nothing here looks at the injected-fault label: every signal is something a
real debugger could compute from logged history (grounding of values,
deviation from historical baselines, data-flow structure, timing, errors).
"""
import math
import re
from collections import defaultdict

NAMES = ["parse_task", "hotel_doc", "extract_rate", "fx_rate", "calc", "flight_price",
         "db_lookup", "policy_check", "reflect", "final_answer"]
KINDS = ["llm", "retrieval", "tool", "final"]
NUM_KEYS = ("value", "rate", "usd", "amount", "total_usd")
SKIP_ARGS = {"context", "question", "op", "model", "turn", "need"}


def primary_value(out):
    if isinstance(out, dict):
        for k in NUM_KEYS:
            v = out.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
    return None


def norm_key(s, all_tools=False):
    """Baseline key for a step's output value. `all_tools` (per-agent baselines for
    external agents) keys every tool call by its scalar arguments, e.g. get_price|item=bread."""
    a = s["args"] if isinstance(s["args"], dict) else {}
    if s["name"] in ("fx_rate", "flight_price", "db_lookup", "extract_rate", "per_diem", "taxi_fare") or \
            (all_tools and s["kind"] in ("tool", "retrieval")):
        sig = ",".join(f"{k}={a[k]}" for k in sorted(a) if k not in SKIP_ARGS and not isinstance(a[k], (list, dict)))
        return f"{s['name']}|{sig}"
    return s["role"]


def _atoms(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from _atoms(v)
    elif isinstance(x, list):
        for v in x:
            yield from _atoms(v)
    elif x is not None and not isinstance(x, bool):
        yield x


_EXPR = re.compile(r"[\d.\s()]+(?:[+\-*/][\d.\s()]+)+")


def _match(a, pool_nums, pool_strs):
    if isinstance(a, (int, float)):
        return any(abs(a - b) <= 1e-6 * max(1, abs(b)) for b in pool_nums)
    if str(a) in pool_strs:
        return True
    # An arithmetic expression ("2.5 * 2 + 1.25") is grounded when every number in it
    # (other than the constants 0 and 1) comes from an upstream output.
    if _EXPR.fullmatch(str(a)):
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(a))]
        return all(_match(x, pool_nums, pool_strs) for x in nums if x not in (0.0, 1.0))
    return False


def _nulls(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _nulls(v, f"{path}.{k}" if path else k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _nulls(v, f"{path}[{i}]")
    elif x is None:
        yield path


def _text_numbers(t):
    return {float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", t or "")}


def _pool(s, by):
    pn, ps = [], set()
    for p in s["parents"]:
        for a in (_atoms(by[p]["output"]) if p in by else []):
            if isinstance(a, (int, float)):
                pn.append(float(a))
            else:
                ps.add(str(a))
    return pn, ps


# ------------------------------------------------------------------ norms
def build_norms(runs_steps, floor=0.05, all_tools=False):
    """runs_steps: iterable of step-lists from *successful training* runs."""
    vals, lat, doclen = defaultdict(list), defaultdict(list), []
    arg_hits = defaultdict(lambda: [0, 0])
    for steps in runs_steps:
        by = {s["sid"]: s for s in steps}
        for s in steps:
            if s["parents"] and isinstance(s["args"], dict):
                pn, ps = _pool(s, by)
                for k, a in s["args"].items():
                    if k in SKIP_ARGS:
                        continue
                    for x in _atoms(a):
                        arg_hits[(s["name"], k)][0] += _match(x, pn, ps)
                        arg_hits[(s["name"], k)][1] += 1
            v = primary_value(s["output"])
            if v is not None and v != 0:
                lv = math.log(abs(v))
                vals[norm_key(s, all_tools)].append(lv)
                vals["role:" + s["role"]].append(lv)
            lat[s["kind"]].append(s["latency_ms"])
            if s["kind"] == "retrieval" and isinstance(s["output"], dict) and "text" in s["output"]:
                doclen.append(len(s["output"].get("text", "")))

    def ms(xs, floor):
        m = sum(xs) / len(xs)
        sd = math.sqrt(sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1))
        return (m, max(sd, floor), len(xs))
    literal = sorted(f"{n}.{k}" for (n, k), (h, t) in arg_hits.items() if t and h / t < 0.5)
    return {"literal_args": literal,
            "vals": {k: ms(v, floor) for k, v in vals.items() if len(v) >= 2},
            "lat": {k: ms(v, 1.0) for k, v in lat.items()},
            "doclen": ms(doclen, 1.0) if doclen else (150, 20, 1)}


# ------------------------------------------------------------------ features
FEATURES = (["kind_" + k for k in KINDS] + ["name_code", "pos_ratio", "steps_to_end", "run_len",
            "n_parents", "n_children", "n_desc", "desc_ratio", "has_value", "value_z", "norm_known",
            "arg_grounding", "out_grounding", "null_fields", "retrieval_relevance", "doc_len_ratio", "doc_len_z",
            "error", "retries", "latency_z", "max_par_z", "max_anc_z", "new_anom", "anc_ground_min",
            "anc_null", "desc_mean_z", "frac_desc_anom", "earliest_suspicious", "n_suspicious_before",
            "local_score", "n_local_signals", "anc_susp", "lineage_root", "anc_max_score", "desc_max_score"])


# The model sees only fault-agnostic signals: no step identity or absolute position,
# so it cannot memorise "extract_rate is usually the culprit".
# Timing is excluded too: real API latencies differ from the simulated corpus
# and no failure mode we model changes timing, so it would only add noise.
MODEL_FEATURES = [f for f in FEATURES if not f.startswith("kind_")
                  and f not in ("name_code", "pos_ratio", "steps_to_end", "run_len", "latency_z")]


def signal_flags(d):
    """Human-readable anomaly signals for one step (shown in the trace viewer)."""
    flags = []
    if d["value_z"] > 3:
        flags.append({"signal": "baseline_deviation", "severity": "high" if d["value_z"] > 8 else "medium",
                      "text": f"value {d['value']:,.4g} is {d['value_z']:.1f}σ from its historical baseline"})
    if d["arg_grounding"] < 1:
        flags.append({"signal": "ungrounded_args", "severity": "high",
                      "text": "argument(s) not traceable to upstream outputs: " + ", ".join(map(str, d["ungrounded_args"]))})
    if d["out_grounding"] < 1:
        flags.append({"signal": "ungrounded_output", "severity": "high",
                      "text": "output value(s) not present in the input: " + ", ".join(f"{x:g}" if isinstance(x, float) else str(x) for x in d["ungrounded_out"])})
    if d["null_fields"] > 0:
        flags.append({"signal": "null_fields", "severity": "high", "text": "empty field(s): " + ", ".join(d["null_paths"])})
    if d["retrieval_relevance"] < 1:
        flags.append({"signal": "irrelevant_retrieval", "severity": "high", "text": "document does not mention the query"})
    if d["doc_len_z"] > 3:
        flags.append({"signal": "short_document", "severity": "medium",
                      "text": f"document is {d['doc_len_ratio']:.0%} of usual length"})
    if d["exception"]:
        flags.append({"signal": "exception", "severity": "high", "text": "step raised an exception"})
    return flags


def _obs_values(x):
    from .react_agent import _values
    return _values(x)


def _texts(x):
    if isinstance(x, dict):
        return [t for v in x.values() for t in _texts(v)]
    if isinstance(x, list):
        return [t for v in x for t in _texts(v)]
    return [x] if isinstance(x, str) else []


def _is_decision(s):
    return s["name"].startswith("call:") or (s["kind"] == "final" and s["name"] == "final_answer" and "tool" not in s["output"]
                                              and "total" not in s["args"])


def step_signals(steps, norms):
    """First pass: local per-step signals + evidence details."""
    by = {s["sid"]: s for s in steps}
    sig = {}
    react = any(s["kind"] == "input" for s in steps)
    pool_n, pool_s, pool_t = set(), set(), []  # everything observed so far (task + tool outputs), for decision grounding
    for s in steps:
        d = {}
        v = primary_value(s["output"])
        key = norm_key(s, norms.get("all_tools", False))
        nm = norms["vals"].get(key) or norms["vals"].get("role:" + s["role"])
        d["value"], d["norm_key"] = v, key
        d["norm_known"] = 1.0 if key in norms["vals"] else (0.5 if nm else 0.0)
        if v is not None and nm:
            lv = math.log(abs(v)) if v != 0 else nm[0] - 10 * nm[1]
            d["value_z"] = min(abs(lv - nm[0]) / nm[1], 50.0)
            d["typical"] = math.exp(nm[0])
        else:
            d["value_z"] = 0.0
        # argument grounding: are args traceable to parent outputs?
        args = s["args"] if isinstance(s["args"], dict) else {}
        lit = set(norms.get("literal_args", []))
        atoms = [a for k, a in args.items() if k not in SKIP_ARGS and f"{s['name']}.{k}" not in lit
                 for a in _atoms(a)]
        pn, ps = _pool(s, by)
        if s["parents"] and atoms:
            ung = [a for a in atoms if not _match(a, pn, ps)]
            d["arg_grounding"] = 1 - len(ung) / len(atoms)
            d["ungrounded_args"] = ung
        else:
            d["arg_grounding"], d["ungrounded_args"] = 1.0, []
        # output grounding for LLM steps: numbers must come from the prompt/context
        if react and _is_decision(s):
            used = s["output"].get("args", {}) if s["name"].startswith("call:") else {"total_usd": s["output"].get("total_usd")}
            un, us = _obs_values(used)
            ung = [v for v in un if v not in (0.0, 1.0) and not any(abs(v - b) <= 1e-6 * max(1, abs(b)) for b in pool_n)]
            ung += [v for v in us if not re.fullmatch(r"[\d.\s+\-*/()]+", v) and v not in pool_s
                    and not any(v in t for t in pool_t)]
            d["out_grounding"] = 1 - len(ung) / max(1, len(un) + len(us)) if (un or us) else 1.0
            d["ungrounded_out"] = ung
        elif s["name"] in ("parse_task", "extract_rate"):
            src = args.get("question") if s["name"] == "parse_task" else args.get("context")
            nums = _text_numbers(src)
            outn = [float(a) for a in _atoms(s["output"]) if isinstance(a, (int, float))]
            ung = [a for a in outn if not any(abs(a - b) < 1e-6 for b in nums)]
            d["out_grounding"] = 1 - len(ung) / len(outn) if outn else 1.0
            d["ungrounded_out"] = ung
        else:
            d["out_grounding"], d["ungrounded_out"] = 1.0, []
        d["null_paths"] = list(_nulls(s["output"]))
        d["null_fields"] = float(len(d["null_paths"]))
        if s["kind"] == "retrieval" and isinstance(s["output"], dict) and "text" in s["output"]:
            txt = s["output"].get("text", "")
            q = str(args.get("query") or args.get("hotel") or "")
            d["retrieval_relevance"] = 1.0 if q in txt else 0.0
            d["doc_len_ratio"] = len(txt) / norms["doclen"][0]
            d["doc_len_z"] = min(abs(len(txt) - norms["doclen"][0]) / norms["doclen"][1], 50.0)
        else:
            d["retrieval_relevance"], d["doc_len_ratio"], d["doc_len_z"] = 1.0, 1.0, 0.0
        ln = norms["lat"].get(s["kind"], (s["latency_ms"], 1, 1))
        d["latency_z"] = (s["latency_ms"] - ln[0]) / ln[1]
        d["error"] = 1.0 if s["error"] else 0.0
        d["exception"] = 1.0 if s["error"] == "exception" else 0.0
        sig[s["sid"]] = derive(d)
        if react and not _is_decision(s) and not s.get("error"):
            n, st = _obs_values(s["output"])
            pool_n |= n
            pool_s |= st
            pool_t.extend(_texts(s["output"]))
    return sig


def derive(d):
    """Combine raw local signals into summary signals (recomputed during explanation)."""
    d["local_ground"] = min(d["arg_grounding"], d["out_grounding"], d["retrieval_relevance"])
    d["n_signals"] = float(sum([d["value_z"] > 3, d["arg_grounding"] < 1, d["out_grounding"] < 1,
                                d["retrieval_relevance"] < 1, d["null_fields"] > 0,
                                d["doc_len_z"] > 3, bool(d["exception"])]))
    d["score"] = max(min(d["value_z"], 12.0) / 3, (1 - d["local_ground"]) * 3, 3.0 * (d["null_fields"] > 0),
                     min(d["doc_len_z"], 12.0) / 3, 3.0 * d["exception"])
    d["suspicious"] = bool(d["value_z"] > 3 or d["local_ground"] < 1 or d["null_fields"] > 0
                           or d["doc_len_z"] > 3 or d["exception"])
    return d


def run_features(steps, norms):
    """Returns (feature_rows, signals, descendants). One row per step, in order."""
    sig = step_signals(steps, norms)
    rows, desc = rows_from_signals(steps, sig)
    return rows, sig, desc


def rows_from_signals(steps, sig):
    by = {s["sid"]: s for s in steps}
    children = defaultdict(list)
    for s in steps:
        for p in s["parents"]:
            children[p].append(s["sid"])

    def closure(sid, nxt):
        out, st = set(), [sid]
        while st:
            for c in nxt(st.pop()):
                if c not in out:
                    out.add(c)
                    st.append(c)
        return out
    anc = {s["sid"]: closure(s["sid"], lambda x: by[x]["parents"] if x in by else []) for s in steps}
    desc = {s["sid"]: closure(s["sid"], lambda x: children[x]) for s in steps}
    n = len(steps)
    rows, seen_susp = [], 0
    first_susp = next((s["sid"] for s in steps if sig[s["sid"]]["suspicious"]), None)
    for i, s in enumerate(steps):
        d, sid = sig[s["sid"]], s["sid"]
        A, D = anc[sid], desc[sid]
        r = {f"kind_{k}": float(s["kind"] == k) for k in KINDS}
        r.update(
            name_code=float(NAMES.index(s["name"]) if s["name"] in NAMES else -1),
            pos_ratio=i / max(1, n - 1), steps_to_end=float(n - 1 - i), run_len=float(n),
            n_parents=float(len(s["parents"])), n_children=float(len(children[sid])),
            n_desc=float(len(D)), desc_ratio=len(D) / n,
            has_value=float(d["value"] is not None), value_z=d["value_z"], norm_known=d["norm_known"],
            arg_grounding=d["arg_grounding"], out_grounding=d["out_grounding"], null_fields=d["null_fields"],
            retrieval_relevance=d["retrieval_relevance"], doc_len_ratio=d["doc_len_ratio"], doc_len_z=d["doc_len_z"],
            error=d["error"], retries=float(s["retries"]), latency_z=d["latency_z"],
            max_par_z=max([sig[p]["value_z"] for p in s["parents"] if p in sig] or [0.0]),
            max_anc_z=max([sig[a]["value_z"] for a in A] or [0.0]),
            anc_ground_min=min([sig[a]["local_ground"] for a in A] or [1.0]),
            anc_null=float(sum(sig[a]["null_fields"] for a in A)),
            desc_mean_z=(sum(sig[x]["value_z"] for x in D) / len(D)) if D else 0.0,
            frac_desc_anom=(sum(sig[x]["value_z"] > 3 or sig[x]["local_ground"] < 1 for x in D) / len(D)) if D else 0.0,
            earliest_suspicious=float(sid == first_susp), n_suspicious_before=float(seen_susp),
        )
        r["new_anom"] = r["value_z"] - r["max_anc_z"]
        n_anc_susp = sum(sig[a]["suspicious"] for a in A)
        r.update(local_score=d["score"], n_local_signals=d["n_signals"], anc_susp=float(n_anc_susp),
                 lineage_root=float(d["suspicious"] and n_anc_susp == 0),
                 anc_max_score=max([sig[a]["score"] for a in A] or [0.0]),
                 desc_max_score=max([sig[x]["score"] for x in D] or [0.0]))
        seen_susp += d["suspicious"]
        rows.append(r)
    return rows, desc


RUN_FEATURES = ["run_len", "max_z", "n_z3", "min_ground", "n_null", "min_rel", "min_doclen",
                "n_err", "n_exc", "n_susp", "max_latency_z", "margin_ratio"]


def run_level(steps, rows, sig):
    s = list(sig.values())
    fin = steps[-1]["output"] if steps else {}
    chk = next((x["output"] for x in steps if x["name"] == "policy_check"), {}) or {}
    tot = primary_value(fin) or 1.0
    return {"run_len": float(len(steps)), "max_z": max(d["value_z"] for d in s),
            "n_z3": float(sum(d["value_z"] > 3 for d in s)), "min_ground": min(d["local_ground"] for d in s),
            "n_null": float(sum(d["null_fields"] for d in s)), "min_rel": min(d["retrieval_relevance"] for d in s),
            "min_doclen": min(d["doc_len_ratio"] for d in s), "n_err": float(sum(d["error"] for d in s)),
            "n_exc": float(sum(d["exception"] for d in s)), "n_susp": float(sum(d["suspicious"] for d in s)),
            "max_latency_z": max(d["latency_z"] for d in s),
            "margin_ratio": float(chk.get("margin", 0) or 0) / max(1.0, abs(tot))}
