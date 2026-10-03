"""Drop-in tracer for any Python agent.

    from blackbox.sdk import Tracer
    tracer = Tracer("data/blackbox.db")
    with tracer.run("What is the refund for order 42?") as run:
        q   = run.llm("parse", {"question": ...}, lambda a: llm_parse(a))
        doc = run.retrieval("search", {"query": q.out["order_id"]}, search, parents=[q])
        ans = run.final("answer", {"total": doc.out["refund"]}, lambda a: a, parents=[doc])
        run.finish(success=checker(ans.out))

Every call is timed, errors are captured, and `parents` records the data-flow
edges that Black Box uses for lineage features and dependency-aware replay.
"""
import time
from contextlib import contextmanager
from dataclasses import dataclass

from .recorder import Recorder


@dataclass
class StepHandle:
    sid: str
    out: object


class _Run:
    def __init__(self, question):
        self.question, self.recs, self.final_output, self.success = question, [], None, None

    def _step(self, kind, name, args, fn, parents=(), sid=None):
        sid = sid or f"{name}#{len(self.recs)}"
        t0, err, retries = time.perf_counter(), None, 0
        try:
            out = fn(args)
        except Exception as e:
            out, err = {"error": f"{type(e).__name__}: {e}"}, "exception"
        self.recs.append({"idx": len(self.recs), "sid": sid, "kind": kind, "name": name, "role": name,
                          "parents": [p.sid if isinstance(p, StepHandle) else p for p in parents],
                          "args": args, "output": out, "latency_ms": (time.perf_counter() - t0) * 1000,
                          "error": err, "retries": retries, "reused": False})
        return StepHandle(sid, out)

    def llm(self, name, args, fn, parents=(), sid=None):
        return self._step("llm", name, args, fn, parents, sid)

    def tool(self, name, args, fn, parents=(), sid=None):
        return self._step("tool", name, args, fn, parents, sid)

    def retrieval(self, name, args, fn, parents=(), sid=None):
        return self._step("retrieval", name, args, fn, parents, sid)

    def final(self, name, args, fn, parents=(), sid=None):
        h = self._step("final", name, args, fn, parents, sid)
        self.final_output = h.out
        return h

    def finish(self, success, expected=None):
        self.success, self.expected = bool(success), expected


class Tracer:
    def __init__(self, path="data/blackbox.db"):
        self.rec = Recorder(path)

    @contextmanager
    def run(self, question, split="external", agent="external"):
        r = _Run(question)
        yield r
        self.last_run_id = self.rec.save_run({"question": question}, r.recs, r.final_output or {},
                                             bool(r.success), getattr(r, "expected", None) or {}, None, split,
                                             agent=agent)
        self.rec.commit()
