"""Application service: the single place the API (and tests) call into.

Owns the recorder and the trained model; delegates all ML to blackbox.model
and all re-execution to blackbox.replay, so routes contain no ML logic.
"""
import json
import os
import random
import threading

from . import demo
from . import faults as F
from . import faults_v2 as F2
from . import llm
from . import model as M
from . import replay as RP
from .agents import ADAPTERS, ReplayUnsupported, get_adapter
from .recorder import Recorder


IDENTIFIED_THRESHOLD = 0.5  # a failure counts as "root cause identified" when the top step scores >= this


class Service:
    def __init__(self, db="data/blackbox.db", model_path="data/model.joblib", metrics_path="data/metrics.json",
                 background=False):
        self.rec = Recorder(db)
        self.model_path, self.metrics_path = model_path, metrics_path
        self._bundle, self._mtime = None, None
        self._cache, self._lock = {}, threading.Lock()
        if background and os.path.exists(model_path):
            threading.Thread(target=self.diagnose_all, daemon=True).start()

    @property
    def model_tag(self):
        b = self.bundle
        return b.get("trained_at") or str(self._mtime)

    def diagnose_all(self):
        """Store the top suspect for every failed run not yet diagnosed by this model."""
        tag = self.model_tag
        n = 0
        for rid in self.rec.undiagnosed_failed(tag):
            self.top_suspect(rid)
            n += 1
        return n

    # ---------------------------------------------------------------- model
    @property
    def bundle(self):
        m = os.path.getmtime(self.model_path)
        if self._bundle is None or m != self._mtime:
            self._bundle, self._mtime = M.load(self.model_path), m
            self._cache.clear()
        return self._bundle

    def analysis(self, run_id):
        b = self.bundle
        with self._lock:
            if run_id in self._cache:
                return self._cache[run_id]
        steps = self.rec.steps(run_id)
        if not steps:
            raise KeyError(run_id)
        a = M.analyze(b, steps)
        with self._lock:
            self._cache[run_id] = a
        return a

    def top_suspect(self, run_id):
        """Cheap path (no explanations): top-ranked step and its score, stored per model version."""
        b, tag = self.bundle, self.model_tag
        hit = self.rec.get_diagnosis(run_id, tag)
        if hit:
            return {"sid": hit["top_sid"], "name": hit["top_name"], "score": hit["top_score"], "p_fail": hit["p_fail"]}
        steps = self.rec.steps(run_id)
        if not steps:
            raise KeyError(run_id)
        dx = M.diagnose(b, steps)
        i = dx["ranking"][0]
        out = {"sid": steps[i]["sid"], "name": steps[i]["name"], "score": round(dx["probs"][i], 4),
               "p_fail": round(dx["p_fail"], 4)}
        self.rec.save_diagnosis(run_id, tag, out["sid"], out["name"], out["score"], out["p_fail"])
        return out

    # ---------------------------------------------------------------- reads
    def _v2(self):
        return os.path.exists(self.model_path) and self.bundle.get("kind") == "v2"

    def info(self):
        from .react_agent import live_policy, provider_of
        slm = live_policy()
        slm_up = slm is not None
        slm_name = f"{slm.model} ({provider_of(slm)})" if slm else "none (start Ollama or set GROQ_API_KEY)"
        v2 = self._v2()
        FF = F2 if v2 else F
        agents = []
        if v2:
            agents = [{"name": "react-slm", "label": f"Tool-calling agent · {slm_name}", "available": slm_up,
                       "description": "A real small language model decides every tool call; the trace graph changes run to run."},
                      {"name": "react-sim", "label": "Tool-calling agent · benchmark policy", "available": True,
                       "description": "Deterministic stochastic policy used to build the labelled benchmark (no model download needed)."}]
        agents += [{"name": a.name, "label": a.label + " (v1, fixed plan)", "description": a.description, "available": True}
                   for a in ADAPTERS.values()]
        return {"llm": {**llm.describe(), "slm": slm.model if slm else "qwen2.5:7b", "slm_provider": provider_of(slm) if slm else None,
                        "slm_available": slm_up}, "agents": agents, "model_version": "v2" if v2 else "v1",
                "train_faults": FF.TRAIN_FAULTS, "heldout_faults": FF.HELDOUT_FAULTS, "tool_faults": list(getattr(FF, "TOOL_FAULTS", {})),
                "fault_descriptions": FF.DESCRIPTIONS, "model_ready": os.path.exists(self.model_path),
                "trained_at": self.bundle.get("trained_at") if os.path.exists(self.model_path) else None,
                "identified_threshold": IDENTIFIED_THRESHOLD}

    def stats(self):
        """Every number here is computed from recorded runs, stored model diagnoses or saved replays."""
        s = self.rec.stats()
        d = self.rec.diagnosis_stats(self.model_tag, IDENTIFIED_THRESHOLD)
        r = self.rec.replay_stats()
        s.update(failure_rate=s["failed"] / s["runs"] if s["runs"] else 0,
                 failures_detected=s["failed"], failures_analyzed=d["analyzed"] or 0,
                 root_causes_identified=int(d["identified"] or 0), identified_threshold=IDENTIFIED_THRESHOLD,
                 avg_diagnosis_score=d["avg_score"],
                 replay_attempts=r["replays"] or 0, repairs_verified=int(r["verified"] or 0),
                 steps_avoided=int(r["steps_avoided"] or 0), steps_reexecuted=int(r["steps_reexecuted"] or 0),
                 replay_steps_total=int(r["steps_total"] or 0))
        _, failed = self.rec.list_runs(status="failed", limit=8)
        s["recent_failed"] = [{**f, **{"root_" + k: v for k, v in self.top_suspect(f["run_id"]).items()}} for f in failed]
        _, reps = self.rec.list_runs(forks_only=True, limit=5)
        s["recent_replays"] = reps
        return s

    def list_runs(self, **kw):
        total, rows = self.rec.list_runs(**kw)
        for r in rows:  # attach the model's top suspect to failed top-level runs
            if not r["success"] and not r.get("parent_run_id"):
                r["root"] = self.top_suspect(r["run_id"])
        return {"total": total, "runs": rows}

    def get_run(self, run_id):
        run = self.rec.run(run_id)
        if run is None:
            raise KeyError(run_id)
        steps = self.rec.steps(run_id)
        replayable = run["agent"] in ADAPTERS or run["agent"].startswith("react")
        fault = run.get("fault")
        FF = F2 if run["agent"].startswith("react") else F
        out = {k: run.get(k) for k in ("run_id", "question", "split", "agent", "created", "parent_run_id",
                                       "fork_sid", "fork_mode", "n_reexecuted")}
        out.update(success=bool(run["success"]), final=run["final"], expected=run["expected"], meta=run.get("meta"),
                   replayable=replayable, steps=steps, n_steps=len(steps),
                   duration_ms=round(sum(s["latency_ms"] for s in steps), 1),
                   # ground-truth label: shown to humans on request, never given to the model
                   label=({"fault_type": fault["type"], "fault_sid": fault["sid"],
                           "heldout": fault["type"] in FF.HELDOUT_FAULTS,
                           "description": FF.DESCRIPTIONS.get(fault["type"]),
                           "note": fault.get("demo_note")} if fault else None))
        return out

    def explanation(self, run_id, sid):
        steps = self.rec.steps(run_id)
        idx = next((i for i, s in enumerate(steps) if s["sid"] == sid), None)
        if idx is None:
            raise KeyError(sid)
        dx = M.diagnose(self.bundle, steps)
        ex = M.explain(self.bundle, steps, dx, idx)
        return {"sid": sid, "score": round(dx["probs"][idx], 4), "rank": dx["ranking"].index(idx) + 1,
                "evidence": ex["evidence"], "contribs": {k: round(v, 4) for k, v in ex["contribs"].items()}}

    def metrics(self):
        if not os.path.exists(self.metrics_path):
            raise KeyError("metrics.json -- run `python -m blackbox.cli all` first")
        return json.load(open(self.metrics_path))

    def forks(self, run_id):
        return self.list_runs(parent=run_id, limit=100)

    def replays(self, limit=50, offset=0):
        return self.list_runs(forks_only=True, limit=limit, offset=offset)

    def compare(self, a, b):
        return RP.compare(self.rec, a, b)

    # ---------------------------------------------------------------- writes
    def replay(self, run_id, sid, mode, patch=None):
        res = RP.fork(self.rec, run_id, sid, mode, patch, save=True)
        # surface a step that crashed during re-execution (checkpoint restore itself succeeded)
        err = next((s for s in res["steps"] if not s.get("reused") and s.get("error") == "exception"), None)
        res["reexecution_error"] = ({"sid": err["sid"], "idx": err["idx"], "name": err["name"],
                                     "error": err["output"].get("error"), "args": err["args"]} if err else None)
        res["changed"] = [r["sid"] for r in res["diff"]["rows"] if r["changed"]]
        res["verified"] = (not res["orig_success"]) and res["success"]
        res.pop("steps")
        return res

    def run_agent(self, agent="react-slm", seed=None, fault_type=None):
        from . import agent as A
        if agent.startswith("react"):
            return self._run_react(agent, seed, fault_type)
        ad = get_adapter(agent)
        seed = random.randrange(10**6) if seed is None else int(seed)
        rng = random.Random(seed)
        task = A.make_task(rng)
        fault = None
        if fault_type:
            if fault_type not in F.ALL_FAULTS:
                raise ValueError(f"unknown fault type {fault_type}")
            fault = F.make_fault(fault_type, ad.build_plan(task), task, rng)
        recs = ad.execute(task, fault=fault, rng=rng)
        ok, gt = ad.judge(task, recs[-1]["output"])
        rid = self.rec.save_run(task, recs, recs[-1]["output"], ok, gt, fault, split="live", agent=agent,
                                meta={**ad.meta(), "seed": seed})
        self.rec.commit()
        return {"run_id": rid, "success": ok}

    def _run_react(self, agent, seed, fault_type):
        from . import agent as A
        from .react_agent import ScriptedPolicy, execute, live_policy, provider_of
        seed = random.randrange(10**6) if seed is None else int(seed)
        rng = random.Random(seed)
        task = A.make_task(rng)
        if agent == "react-slm":
            policy = live_policy()
            if policy is None:
                raise ValueError("no real model available: start Ollama locally or set GROQ_API_KEY")
        else:
            policy = ScriptedPolicy("standard")
        fault = None
        if fault_type:
            if fault_type not in F2.ALL_FAULTS:
                raise ValueError(f"unknown fault type {fault_type}")
            if agent == "react-slm" and fault_type not in F2.TOOL_FAULTS:
                raise ValueError("with a real model, inject environment (tool) faults; model mistakes happen on their own")
            fault = F2.make_fault(fault_type, 0, seed)
        steps, final, _, fsid = execute(task, policy, fault=fault, seed=seed)
        ok, gt = A.judge(task, final)
        if fault:
            fault["sid"] = fsid
            fault = fault if fsid else None
        rid = self.rec.save_run(task, steps, final, ok, gt, fault, split="live", agent=agent,
                                meta={"model": policy.model, "policy": getattr(policy, "variant", None), "seed": seed,
                                      "provider": provider_of(policy)})
        self.rec.commit()
        return {"run_id": rid, "success": ok}

    def killer_demo(self):
        return {"run_id": demo.run_killer(self.rec)}

    def demo_patch(self, run_id):
        """Suggested repair for the demo, derived from the trace and the model's top suspect."""
        root = self.analysis(run_id)["root_cause"]
        return demo.suggested_repair(self.rec.steps(run_id), root["sid"])

    def ingest_otlp(self, payload, success=None):
        """Store traces from any OpenTelemetry-instrumented agent (OTLP/HTTP JSON)."""
        from .otel import otlp_json_to_steps
        ids = []
        for tid, t in otlp_json_to_steps(payload).items():
            ok = success if success is not None else not any(s["error"] for s in t["steps"])
            ids.append(self.rec.save_run({"question": t["question"]}, t["steps"], {}, bool(ok), {}, None, split="external",
                                         agent="external", meta={"trace_id": tid, "source": "otlp"}))
        self.rec.commit()
        return {"runs": ids}


__all__ = ["Service", "ReplayUnsupported"]
