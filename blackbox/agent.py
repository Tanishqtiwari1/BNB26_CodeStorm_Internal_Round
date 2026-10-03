"""Toy travel-expense agent.

A task is turned into a deterministic *plan*: a DAG of steps (LLM calls,
retrievals, tool calls, final answer). Each step has
  derive(task, pv) -> args    (reads parent outputs)
  run(args, task)  -> output  (pure, so it can be replayed exactly)
Faults are injected between derive/run (bad args) or after run (bad output).
"""
import random
import re
from dataclasses import dataclass, field
from typing import Callable

from . import world as W


# ---------------------------------------------------------------- tasks
def make_task(rng: random.Random):
    origin = rng.choice(W.ORIGINS)
    n_legs = rng.choices([1, 2, 3], weights=[4, 4, 2])[0]
    cities = rng.sample([c for c in W.CITIES if c != origin], n_legs)
    legs = [{"city": c, "hotel": rng.choice(W.hotels_in(c)), "nights": rng.randint(1, 5)} for c in cities]
    task = {
        "origin": origin,
        "travelers": rng.choices([1, 2, 3], weights=[5, 3, 2])[0],
        "legs": legs,
        "per_diem": rng.random() < 0.6,
        "taxi": rng.random() < 0.4,
        "reflect_after": [],
        "budget": None,
    }
    n_steps = len(build_plan(task))
    task["reflect_after"] = sorted(rng.sample(range(1, n_steps - 2), k=rng.randint(0, 2)))
    gt = ground_truth(task)
    task["budget"] = int(round(gt["total_usd"] * rng.uniform(0.85, 1.25), -2))
    task["question"] = question_text(task)
    return task


def question_text(t):
    legs = ", then ".join(f"{l['nights']} night{'s' * (l['nights'] > 1)} at {l['hotel']} in {l['city']}" for l in t["legs"])
    extras = [x for x, on in (("per-diem meals", t["per_diem"]), ("airport taxis", t["taxi"])) if on]
    ex = f" Include {' and '.join(extras)}." if extras else ""
    return (f"Estimate the total USD cost for {t['travelers']} traveler{'s' * (t['travelers'] > 1)} "
            f"flying from {t['origin']}: {legs}, and the flight back.{ex} "
            f"Is it within the ${t['budget']:,} budget?" if t["budget"] else "")


# ---------------------------------------------------------------- plan
@dataclass
class Step:
    sid: str
    kind: str            # llm | retrieval | tool | final
    name: str            # base operation name
    parents: list
    derive: Callable
    run: Callable
    role: str = ""       # semantic role, used for baselines/norms
    children: list = field(default_factory=list)


def _num(d):
    for k in ("value", "rate", "usd", "amount", "total_usd"):
        if isinstance(d, dict) and isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool):
            return float(d[k])
    return None


def calc(args, task=None):
    xs = [float(x) for x in args["xs"]]
    if args["op"] == "mul":
        v = 1.0
        for x in xs:
            v *= x
    else:
        v = sum(xs)
    return {"value": round(v, 2)}


def tool_fx(args, task=None):
    return {"rate": W.FX_TO_USD[args["base"]]}


def tool_flight(args, task=None):
    return {"usd": W.flight_price_usd(args["from"], args["to"])}


def tool_db(args, task=None):
    if args["table"] == "per_diem":
        return {"usd": float(W.PER_DIEM_USD[args["city"]])}
    return {"amount": float(W.TAXI_LOCAL[args["city"]]), "currency": W.CITIES[args["city"]]}


def retrieve_doc(args, task=None):
    return {"text": W.hotel_doc(args["query"])}


def llm_parse(args, task):
    # Simulated LLM: structured intent from the question
    return {"origin": task["origin"], "travelers": task["travelers"],
            "legs": [dict(l) for l in task["legs"]], "per_diem": task["per_diem"],
            "taxi": task["taxi"], "budget": task["budget"]}


def llm_extract(args, task=None):
    ctx = args["context"]
    m = re.search(r"Standard room: (\d+) ([A-Z]{3})", ctx)
    if not m:  # model grabs the first price-looking number it sees
        m = re.search(r"(\d+) ([A-Z]{3})", ctx)
    if not m:
        return {"amount": None, "currency": None}
    return {"amount": float(m.group(1)), "currency": m.group(2)}


def llm_check(args, task=None):
    return {"within_budget": bool(args["total"] <= args["budget"]), "margin": round(args["budget"] - args["total"], 2)}


def llm_reflect(args, task=None):
    return {"note": "plan on track"}


def final_answer(args, task=None):
    return {"total_usd": round(float(args["total"]), 2), "within_budget": args["within_budget"]}


def _leg(pv, i):
    return pv["parse"]["legs"][i]


def _d(v, default=1):
    return default if v is None else v


def build_plan(task):
    S = []

    def add(sid, kind, name, parents, derive, run, role=""):
        S.append(Step(sid, kind, name, parents, derive, run, role or name))

    add("parse", "llm", "parse_task", [], lambda t, pv: {"question": t.get("question", "")}, llm_parse)
    trav = task["travelers"]
    prev_city = task["origin"]
    leg_totals = []
    for i, leg in enumerate(task["legs"]):
        p = f"L{i}."
        add(p + "doc", "retrieval", "hotel_doc", ["parse"],
            lambda t, pv, i=i: {"query": _leg(pv, i)["hotel"], "city": _leg(pv, i)["city"]}, retrieve_doc)
        add(p + "rate", "llm", "extract_rate", [p + "doc", "parse"],
            lambda t, pv, p=p, i=i: {"hotel": _leg(pv, i)["hotel"], "context": pv[p + "doc"]["text"]}, llm_extract)
        add(p + "fx", "tool", "fx_rate", [p + "rate"],
            lambda t, pv, p=p: {"base": pv[p + "rate"]["currency"], "quote": "USD"}, tool_fx)
        add(p + "hotel_local", "tool", "calc", [p + "rate", "parse"],
            lambda t, pv, p=p, i=i: {"op": "mul", "xs": [pv[p + "rate"]["amount"], _d(_leg(pv, i)["nights"])]}, calc, "calc_hotel_local")
        add(p + "hotel_usd", "tool", "calc", [p + "hotel_local", p + "fx"],
            lambda t, pv, p=p: {"op": "mul", "xs": [pv[p + "hotel_local"]["value"], pv[p + "fx"]["rate"]]}, calc, "calc_hotel_usd")
        comp = [p + "hotel_usd"]
        if trav > 1:
            add(p + "hotel_rooms", "tool", "calc", [p + "hotel_usd", "parse"],
                lambda t, pv, p=p: {"op": "mul", "xs": [pv[p + "hotel_usd"]["value"], _d(pv["parse"]["travelers"])]}, calc, "calc_hotel_rooms")
            comp = [p + "hotel_rooms"]
        add(p + "flight", "tool", "flight_price", ["parse"],
            lambda t, pv, i=i, pc=prev_city: {"from": pc if i == 0 else _leg(pv, i - 1)["city"], "to": _leg(pv, i)["city"]}, tool_flight)
        if i == 0:  # origin comes from the parsed intent
            S[-1].derive = lambda t, pv: {"from": pv["parse"]["origin"], "to": _leg(pv, 0)["city"]}
        fl = p + "flight"
        if trav > 1:
            add(p + "flight_all", "tool", "calc", [p + "flight", "parse"],
                lambda t, pv, p=p: {"op": "mul", "xs": [pv[p + "flight"]["usd"], _d(pv["parse"]["travelers"])]}, calc, "calc_flight_all")
            fl = p + "flight_all"
        comp.append(fl)
        if task["per_diem"]:
            add(p + "pd", "tool", "db_lookup", ["parse"],
                lambda t, pv, i=i: {"table": "per_diem", "city": _leg(pv, i)["city"]}, tool_db, "db_per_diem")
            add(p + "pd_total", "tool", "calc", [p + "pd", "parse"],
                lambda t, pv, p=p, i=i: {"op": "mul", "xs": [pv[p + "pd"]["usd"], _d(_leg(pv, i)["nights"]), _d(pv["parse"]["travelers"])]}, calc, "calc_per_diem")
            comp.append(p + "pd_total")
        if task["taxi"]:
            add(p + "taxi", "tool", "db_lookup", ["parse"],
                lambda t, pv, i=i: {"table": "taxi", "city": _leg(pv, i)["city"]}, tool_db, "db_taxi")
            add(p + "taxi_usd", "tool", "calc", [p + "taxi", p + "fx"],
                lambda t, pv, p=p: {"op": "mul", "xs": [pv[p + "taxi"]["amount"], pv[p + "fx"]["rate"]]}, calc, "calc_taxi_usd")
            comp.append(p + "taxi_usd")
        add(p + "total", "tool", "calc", list(comp),
            lambda t, pv, comp=tuple(comp): {"op": "add", "xs": [_num(pv[c]) for c in comp]}, calc, "calc_leg_total")
        leg_totals.append(p + "total")
        prev_city = leg["city"]

    add("R.flight", "tool", "flight_price", ["parse"],
        lambda t, pv: {"from": pv["parse"]["legs"][-1]["city"], "to": pv["parse"]["origin"]}, tool_flight, "flight_price")
    back = "R.flight"
    if trav > 1:
        add("R.flight_all", "tool", "calc", ["R.flight", "parse"],
            lambda t, pv: {"op": "mul", "xs": [pv["R.flight"]["usd"], _d(pv["parse"]["travelers"])]}, calc, "calc_flight_all")
        back = "R.flight_all"
    parts = leg_totals + [back]
    add("T.total", "tool", "calc", list(parts),
        lambda t, pv, parts=tuple(parts): {"op": "add", "xs": [pv[x]["value"] if "value" in pv[x] else pv[x]["usd"] for x in parts]}, calc, "calc_trip_total")
    add("T.check", "llm", "policy_check", ["T.total", "parse"],
        lambda t, pv: {"total": pv["T.total"]["value"], "budget": pv["parse"]["budget"] or 0}, llm_check)
    add("T.final", "final", "final_answer", ["T.total", "T.check"],
        lambda t, pv: {"total": pv["T.total"]["value"], "within_budget": pv["T.check"]["within_budget"]}, final_answer)

    # distractor "reflection" steps (no downstream effect) inserted deterministically
    for k, pos in enumerate(task.get("reflect_after", [])):
        if pos < len(S) - 1:
            prev = S[pos].sid
            S.insert(pos + 1 + k, Step(f"X{k}.reflect", "llm", "reflect", [prev],
                                       lambda t, pv: {}, llm_reflect, "reflect"))
    by = {s.sid: s for s in S}
    for s in S:
        for p in s.parents:
            by[p].children.append(s.sid)
    return S


def descendants(plan, sid):
    by = {s.sid: s for s in plan}
    out, stack = set(), [sid]
    while stack:
        for c in by[stack.pop()].children:
            if c not in out:
                out.add(c)
                stack.append(c)
    return out


# ---------------------------------------------------------------- execution
def _latency(kind, rng):
    return {"llm": rng.uniform(300, 900), "retrieval": rng.uniform(80, 220),
            "tool": rng.uniform(15, 120), "final": rng.uniform(1, 5)}[kind]


def execute(task, fault=None, rng=None, start_pv=None, rerun=None, overrides=None,
            plan_fn=None, latency_fn=None):
    """Run the plan. Returns list of step records.

    start_pv/rerun: replay support -- steps not in `rerun` reuse start_pv outputs.
    overrides: {sid: {"args": {...}} or {"output": {...}}} applied during replay.
    plan_fn: builds the step DAG (defaults to the simulated travel agent).
    latency_fn(kind, measured_ms, rng): latency to record (default: simulated).
    """
    import time

    from . import faults as F
    rng = rng or random.Random(0)
    plan = (plan_fn or build_plan)(task)
    pv, recs = {}, []
    for idx, s in enumerate(plan):
        if rerun is not None and s.sid not in rerun:
            rec = dict(start_pv[s.sid])
            rec["idx"], rec["reused"] = idx, True
            pv[s.sid] = rec["output"]
            recs.append(rec)
            continue
        ov = (overrides or {}).get(s.sid, {})
        faulty = bool(fault and fault["sid"] == s.sid and not ov)
        err, retries, args = None, 0, {}
        t0 = time.perf_counter()
        try:
            args = ov["args"] if "args" in ov else s.derive(task, pv)
            if faulty:
                args = F.mutate_args(fault, s, args, task)
            out = ov["output"] if "output" in ov else s.run(args, task)
            if faulty:
                out = F.mutate_output(fault, s, out, task, args)
        except Exception as e:  # a crash is also observable behaviour
            out, err = {"error": f"{type(e).__name__}: {e}"}, "exception"
        measured = (time.perf_counter() - t0) * 1000
        lat = latency_fn(s.kind, measured, rng) if latency_fn else _latency(s.kind, rng)
        if err is None and s.kind in ("tool", "retrieval") and s.name != "calc" and rng.random() < 0.05:
            err, retries, lat = "timeout (recovered)", 1, lat + rng.uniform(800, 1500)
        pv[s.sid] = out
        recs.append({"idx": idx, "sid": s.sid, "kind": s.kind, "name": s.name, "role": s.role,
                     "parents": list(s.parents), "args": args, "output": out,
                     "latency_ms": round(lat, 1), "error": err, "retries": retries, "reused": False})
    return recs


def ground_truth(task):
    t = dict(task)
    t["budget"] = t.get("budget") or 10**9
    recs = execute(t)
    return recs[-1]["output"]


def judge(task, final):
    """Task-level success check (the 'test suite' for the agent)."""
    gt = ground_truth(task)
    if not isinstance(final, dict) or final.get("total_usd") is None:
        return False, gt
    ok_total = abs(final["total_usd"] - gt["total_usd"]) <= 0.02 * gt["total_usd"]
    return bool(ok_total and final.get("within_budget") == gt["within_budget"]), gt
