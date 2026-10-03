"""Checkpointed replay for the dynamic (ReAct) agent.

fork(run, step k, mode):
  1. restore the checkpoint: every step before k plus the agent's state
     (its observation history) at that point
  2. apply the alternative execution at k:
       tool step      repair = re-run the tool fresh · patch_output = forced observation
                      patch_args = re-run the real tool with new arguments
       decision step  repair = let the policy decide again · patch_output = forced tool call
  3. let the agent continue on its own. It may take a different path; tool
     calls whose (tool, args) match the recording are served from the
     recording (reused), everything new is executed.
Injected faults elsewhere persist; a fault at step k is removed by the repair.
"""
import json
import zlib

from .agents import ReplayUnsupported
from .react_agent import GroqPolicy, OllamaPolicy, ScriptedPolicy, execute


def policy_for(run):
    meta = run.get("meta") or {}
    if run["agent"] == "react-slm":
        if meta.get("provider") == "groq":
            p = GroqPolicy(model=meta.get("model"))
            if not p.available():
                raise ReplayUnsupported("replaying this run needs GROQ_API_KEY to be set")
            return p
        p = OllamaPolicy(model=meta.get("model"))
        if not p.available():
            raise ReplayUnsupported(f"replaying this run needs the local model {p.model} (start Ollama: `ollama serve`)")
        return p
    return ScriptedPolicy(meta.get("policy", "standard"))


def history_from_steps(steps):
    """Rebuild the agent's observation history from recorded steps."""
    by_parent = {}
    for s in steps:
        if s["kind"] in ("tool", "retrieval") and s["parents"]:
            by_parent[s["parents"][0]] = s
    hist = []
    for i, s in enumerate(steps):
        if not s["name"].startswith("call:"):
            continue
        need = s["args"].get("need")
        t = by_parent.get(s["sid"])
        act = {"tool": s["output"].get("tool"), "args": s["output"].get("args", {})}
        if t is None:
            hist.append({"action": act, "obs": {"error": "invalid tool call"}, "error": "exception", "need": None,
                         "dec_sid": s["sid"], "tool_sid": None, "pos": i})
        else:
            hist.append({"action": act, "obs": t["output"], "error": t["error"], "need": tuple(need) if need else None,
                         "dec_sid": s["sid"], "tool_sid": t["sid"], "pos": i})
    return hist


def fork(rec, run_id, sid, mode="repair", patch=None, save=True):
    from . import agent as A
    from .replay import diff
    run = rec.run(run_id)
    if run is None:
        raise KeyError(run_id)
    if mode not in ("repair", "patch_output", "patch_args"):
        raise ValueError("mode must be repair, patch_output or patch_args")
    if mode != "repair" and not isinstance(patch, dict):
        raise ValueError("patch must be a JSON object")
    steps = rec.steps(run_id)
    k = next((i for i, s in enumerate(steps) if s["sid"] == sid), None)
    if k is None:
        raise KeyError(sid)
    s = steps[k]
    if s["kind"] == "input":
        raise ValueError("the task input can't be replayed; pick a decision or tool step")
    task, fault = run["task"], run["fault"]
    fault_cont = None if (fault and fault.get("sid") == sid) else fault
    policy = policy_for(run)
    hist = history_from_steps(steps)
    memo = {(t["name"], json.dumps(t["args"], sort_keys=True)): t["output"]
            for t in steps if t["kind"] in ("tool", "retrieval") and not t["error"] and t["sid"] != sid}
    resume = {"memo": memo}
    if s["kind"] in ("tool", "retrieval"):
        dec = next(x for x in steps if x["sid"] == s["parents"][0])
        resume["steps"] = steps[:k]
        resume["history"] = [h for h in hist if h["pos"] < steps.index(dec)]
        need = dec["args"].get("need")
        resume["tool_action"] = {"tool": s["name"], "args": patch if mode == "patch_args" else s["args"],
                                 "need": tuple(need) if need else None}
        if mode == "patch_output":
            resume["tool_output"] = patch
    else:
        if mode == "patch_args":
            raise ValueError("a model decision has no arguments to patch; patch its output (the tool call) instead")
        resume["steps"] = steps[:k]
        resume["history"] = [h for h in hist if h["pos"] < k]
        if mode == "patch_output":
            if s["kind"] == "final":
                resume["action"] = {"tool": "final_answer", "args": patch, "need": ("final", 0)}
            else:
                need = s["args"].get("need")
                resume["action"] = {"tool": patch.get("tool", s["output"].get("tool")), "args": patch.get("args", patch),
                                    "need": tuple(need) if need else None}
    seed = zlib.crc32(f"{run_id}|{sid}|{mode}|{json.dumps(patch, sort_keys=True)}".encode())
    new, final, _, _ = execute(task, policy, fault=fault_cont, seed=seed, resume=resume)
    ok, gt = A.judge(task, final)
    n_reused = sum(1 for x in new if x.get("reused"))
    d = diff(steps, new)
    res = {"success": ok, "final": final, "expected": gt, "orig_success": bool(run["success"]),
           "source_run_id": run_id, "fork_sid": sid, "mode": mode,
           "n_total": len(new), "n_original": len(steps), "n_reexecuted": len(new) - n_reused, "n_reused": n_reused,
           "n_suffix": len(new) - k, "rerun": [x["sid"] for x in new if not x.get("reused")],
           "path_changed": [x["name"] for x in new[k:]] != [x["name"] for x in steps[k:]],
           "steps": new, "diff": d}
    if save:
        res["run_id"] = rec.save_run(task, new, final, ok, gt, fault, split="fork", parent_run_id=run_id, fork_sid=sid,
                                     fork_mode=mode, n_reexecuted=res["n_reexecuted"], agent=run["agent"], meta=run.get("meta"))
        rec.commit()
    return res
