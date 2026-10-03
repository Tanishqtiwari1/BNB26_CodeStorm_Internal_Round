"""Checkpointed, dependency-aware replay and alternative execution.

fork(run, step k, mode):
  * restore the recorded state (outputs of every step not affected by k)
  * re-execute ONLY step k and its data-flow descendants
  * everything else is reused verbatim from the recording

modes
  repair        re-derive k's args from its parents and execute it fresh
  patch_output  replace k's output with a user-supplied value
  patch_args    re-run k's real step function with user-supplied args
Faults injected elsewhere in the run persist (we only change step k).
Re-execution calls the agent's real step functions through its adapter.
"""
import json
import random
import zlib

from . import agent as A
from .agents import ReplayUnsupported, get_adapter

MODES = ("repair", "patch_output", "patch_args")


def fork(rec, run_id, sid, mode="repair", patch=None, save=True):
    run = rec.run(run_id)
    if run is None:
        raise KeyError(run_id)
    if str(run.get("agent", "")).startswith("react"):
        from . import replay_v2
        return replay_v2.fork(rec, run_id, sid, mode, patch, save)
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode != "repair" and not isinstance(patch, dict):
        raise ValueError("patch must be a JSON object")
    adapter = get_adapter(run["agent"])
    steps = rec.steps(run_id)
    task, fault = run["task"], run["fault"]
    plan = adapter.build_plan(task)
    order = [s.sid for s in plan]
    if [s["sid"] for s in steps] != order:
        raise ReplayUnsupported("recorded trace no longer matches the agent's plan")
    if sid not in order:
        raise KeyError(sid)
    rerun = {sid} | A.descendants(plan, sid)
    overrides = {}
    if mode == "patch_output":
        overrides[sid] = {"output": patch}
    elif mode == "patch_args":
        overrides[sid] = {"args": patch}
    eff_fault = None if (fault and fault["sid"] == sid) else fault
    seed = zlib.crc32(f"{run_id}|{sid}|{mode}".encode())
    recs = adapter.execute(task, fault=eff_fault, rng=random.Random(seed),
                           start_pv={s["sid"]: s for s in steps}, rerun=rerun, overrides=overrides)
    final = recs[-1]["output"]
    ok, gt = adapter.judge(task, final)
    res = {"success": ok, "final": final, "expected": gt, "orig_success": bool(run["success"]),
           "source_run_id": run_id, "fork_sid": sid, "mode": mode,
           "n_total": len(order), "n_reexecuted": len(rerun), "n_reused": len(order) - len(rerun),
           "n_suffix": len(order) - order.index(sid), "rerun": sorted(rerun, key=order.index),
           "steps": recs, "diff": diff(steps, recs)}
    if save:
        res["run_id"] = rec.save_run(task, recs, final, ok, gt, fault, split="fork", parent_run_id=run_id,
                                     fork_sid=sid, fork_mode=mode, n_reexecuted=len(rerun),
                                     agent=run["agent"], meta=run.get("meta"))
        rec.commit()
    return res


def diff(a, b):
    """Align two executions. Same plan -> by step id; dynamic traces whose shape
    changed -> sequence alignment on (operation, arguments)."""
    if [(s["sid"], s["name"]) for s in a] != [(s["sid"], s["name"]) for s in b] and any(s["kind"] == "input" for s in a):
        return _diff_aligned(a, b)
    bb = {s["sid"]: s for s in b}
    rows, first = [], None
    for s in a:
        t = bb.get(s["sid"])
        changed = t is None or s["output"] != t["output"] or s["args"] != t["args"]
        if changed and first is None:
            first = s["sid"]
        rows.append({"idx": s["idx"], "sid": s["sid"], "name": s["name"], "kind": s["kind"], "changed": changed,
                     "reused": bool(t and t.get("reused")), "rerun": bool(t and not t.get("reused")),
                     "before": s["output"], "after": t["output"] if t else None,
                     "args_before": s["args"], "args_after": t["args"] if t else None})
    return {"rows": rows, "first_divergence": first, "n_changed": sum(r["changed"] for r in rows)}


def compare(rec, run_a, run_b):
    ra, rb = rec.run(run_a), rec.run(run_b)
    if ra is None or rb is None:
        raise KeyError(run_a if ra is None else run_b)
    d = diff(rec.steps(run_a), rec.steps(run_b))
    d.update(a={"run_id": run_a, "success": bool(ra["success"]), "final": ra["final"]},
             b={"run_id": run_b, "success": bool(rb["success"]), "final": rb["final"],
                "fork_sid": rb.get("fork_sid"), "fork_mode": rb.get("fork_mode")},
             expected=ra["expected"], n_rerun=sum(r["rerun"] for r in d["rows"]),
             n_reused=sum(r["reused"] for r in d["rows"]),
             fixed=(not ra["success"]) and bool(rb["success"]))
    return d


def _diff_aligned(a, b):
    import difflib
    sig = lambda s: (s["name"], json.dumps(s["args"] if s["kind"] not in ("llm", "final") else s["output"], sort_keys=True, default=str))
    sm = difflib.SequenceMatcher(a=[sig(s) for s in a], b=[sig(s) for s in b], autojunk=False)
    rows, first = [], None

    def row(x, y, status):
        nonlocal first
        changed = x is None or y is None or x["output"] != y["output"] or x["args"] != y["args"]
        if changed and first is None:
            first = (y or x)["sid"]
        ref = y or x
        rows.append({"idx": ref["idx"], "sid": ref["sid"], "name": ref["name"], "kind": ref["kind"], "changed": changed,
                     "reused": bool(y and y.get("reused")), "rerun": bool(y and not y.get("reused")), "status": status,
                     "before": x["output"] if x else None, "after": y["output"] if y else None,
                     "args_before": x["args"] if x else None, "args_after": y["args"] if y else None})
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for x, y in zip(a[i1:i2], b[j1:j2]):
                row(x, y, "same")
        else:
            xs, ys = a[i1:i2], b[j1:j2]
            for t in range(max(len(xs), len(ys))):
                x = xs[t] if t < len(xs) else None
                y = ys[t] if t < len(ys) else None
                row(x, y, "changed" if x and y else ("added" if y else "removed"))
    return {"rows": rows, "first_divergence": first, "n_changed": sum(r["changed"] for r in rows)}
