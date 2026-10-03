"""Fault injection: break exactly one step per run so we know the root cause.

TRAIN_FAULTS are used to train the diagnosis model.
HELDOUT_FAULTS are never seen in training -> generalisation test.
"""
import random

from . import world as W

TRAIN_FAULTS = ["wrong_arg", "unit_mixup", "irrelevant_retrieval",
                "hallucinated_value", "dropped_field", "wrong_operation"]
HELDOUT_FAULTS = ["truncated_context", "off_by_one", "stale_cache"]
ALL_FAULTS = TRAIN_FAULTS + HELDOUT_FAULTS

DESCRIPTIONS = {
    "wrong_arg": "Tool called with an argument that doesn't match upstream data",
    "unit_mixup": "Numeric output off by a unit factor (cents vs dollars)",
    "irrelevant_retrieval": "Retriever returned a document for the wrong entity",
    "hallucinated_value": "LLM extracted a number that is not in its context",
    "dropped_field": "LLM parse silently dropped a required field",
    "wrong_operation": "Calculator used the wrong operation (add vs multiply)",
    "truncated_context": "Retrieved document truncated; key sentence missing",
    "off_by_one": "LLM parse produced a count off by one",
    "stale_cache": "Tool served a stale cached value",
}


def applicable(ftype, step, task):
    n, k = step.name, step.kind
    if ftype == "wrong_arg":
        return n in ("fx_rate", "flight_price", "db_lookup")
    if ftype == "unit_mixup":
        return n in ("flight_price", "db_lookup") or (n == "calc" and step.role != "calc_trip_total")
    if ftype in ("irrelevant_retrieval", "truncated_context"):
        return n == "hotel_doc"
    if ftype == "hallucinated_value":
        return n == "extract_rate"
    if ftype in ("dropped_field", "off_by_one"):
        return n == "parse_task"
    if ftype == "wrong_operation":
        return n == "calc"
    if ftype == "stale_cache":
        return n == "fx_rate"
    return False


def make_fault(ftype, plan, task, rng: random.Random):
    cands = [s for s in plan if applicable(ftype, s, task)]
    if not cands:
        return None
    s = rng.choice(cands)
    p = {"seed": rng.randrange(10**9)}
    return {"type": ftype, "sid": s.sid, "params": p}


def _r(fault):
    return random.Random(fault["params"]["seed"])


def mutate_args(fault, step, args, task):
    t, r = fault["type"], _r(fault)
    args = dict(args)
    if t == "wrong_arg":
        if step.name == "fx_rate":
            args["base"] = r.choice([c for c in W.FX_TO_USD if c not in (args["base"], "USD")])
        elif step.name == "flight_price":
            args["to"] = r.choice([c for c in W.CITIES if c not in (args["to"], args["from"])])
        else:
            args["city"] = r.choice([c for c in W.CITIES if c != args["city"]])
    elif t == "wrong_operation":
        args["op"] = "add" if args["op"] == "mul" else "mul"
    return args


def mutate_output(fault, step, out, task, args):
    t, r = fault["type"], _r(fault)
    out = dict(out)
    if t == "unit_mixup":
        for k in ("value", "usd", "amount"):
            if k in out:
                out[k] = round(out[k] * (100 if r.random() < 0.6 else 0.01), 2)
                break
    elif t == "irrelevant_retrieval":
        city = W.HOTELS[args["query"]][0]
        same = [h for h in W.hotels_in(city) if h != args["query"]]
        pool = same if (same and r.random() < 0.5) else [h for h in W.HOTELS if h != args["query"]]
        out["text"] = W.hotel_doc(r.choice(pool))
    elif t == "truncated_context":
        full = out["text"]
        head = full.split(". ")[0] + ". "
        rest = full[full.index("City tax"):] if r.random() < 0.5 else full[full.index("Breakfast"):]
        out["text"] = head + rest
    elif t == "hallucinated_value":
        a = out["amount"]
        if "value" in fault["params"]:  # pinned value (used by the scripted demo)
            out["amount"] = float(fault["params"]["value"])
            return out
        while True:
            v = float(round(a * r.choice([r.uniform(0.55, 0.85), r.uniform(1.2, 1.7)])))
            if str(int(v)) not in args["context"]:
                break
        out["amount"] = v
    elif t in ("dropped_field", "off_by_one"):
        out["legs"] = [dict(l) for l in out["legs"]]
        i = r.randrange(len(out["legs"]))
        use_trav = out["travelers"] > 1 and r.random() < 0.4
        if t == "dropped_field":
            if use_trav:
                out["travelers"] = None
            else:
                out["legs"][i]["nights"] = None
        else:
            if use_trav:
                out["travelers"] -= 1
            elif out["legs"][i]["nights"] > 1 and r.random() < 0.5:
                out["legs"][i]["nights"] -= 1
            else:
                out["legs"][i]["nights"] += 1
    elif t == "stale_cache":
        f = r.uniform(0.80, 0.97) if r.random() < 0.5 else r.uniform(1.03, 1.2)
        out["rate"] = round(out["rate"] * f, 6)
    return out
