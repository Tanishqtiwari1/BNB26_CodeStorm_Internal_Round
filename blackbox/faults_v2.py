"""Fault injection for the dynamic (ReAct) agent.

Two families, so root causes land on different node types:
  decision faults  the model makes a bad tool call   -> root = the call:<tool> step
  tool faults      the environment returns bad data   -> root = the tool step

Each fault targets one occurrence (`occ`) of an event. Training/test faults
use occurrence 0; the location-drift split uses later occurrences, i.e. the
error source sits somewhere the model never saw it during training.
"""
import random

from . import world as W

TRAIN_FAULTS = ["wrong_arg", "hallucinated_value", "wrong_operation", "dropped_field", "irrelevant_retrieval", "unit_mixup"]
HELDOUT_FAULTS = ["off_by_one", "truncated_context", "stale_cache"]
ALL_FAULTS = TRAIN_FAULTS + HELDOUT_FAULTS
DECISION_FAULTS = {"wrong_arg": "fx", "hallucinated_value": "hotel_usd", "wrong_operation": "hotel_usd",
                   "dropped_field": "total", "off_by_one": "hotel_usd"}
TOOL_FAULTS = {"irrelevant_retrieval": "search_hotel", "truncated_context": "search_hotel",
               "unit_mixup": "flight_price", "stale_cache": "fx_rate"}
DESCRIPTIONS = {
    "wrong_arg": "Model called the FX tool with a currency that doesn't match the hotel document",
    "hallucinated_value": "Model wrote a hotel price into the calculation that isn't in the document",
    "wrong_operation": "Model used + instead of × in a cost calculation",
    "dropped_field": "Model left one cost component out of the final sum",
    "irrelevant_retrieval": "Search returned the page of a different hotel",
    "unit_mixup": "Flight API returned cents instead of dollars",
    "off_by_one": "Model used the wrong number of nights",
    "truncated_context": "Search returned a truncated page missing the room price",
    "stale_cache": "FX tool served a stale cached rate",
}


def make_fault(ftype, occ=0, seed=0):
    return {"type": ftype, "occ": int(occ), "params": {"seed": seed}}


def _count(history, pred):
    return sum(1 for h in history if not h.get("error") and pred(h))


def apply_action_fault(fault, act, plan, facts, history):
    t = fault["type"]
    need_kind = DECISION_FAULTS.get(t)
    if not need_kind or not act.get("need") or act["need"][0] != need_kind:
        return act
    occ = _count(history, lambda h: h.get("need") and h["need"][0] == need_kind)
    if occ != fault["occ"]:
        return act
    r = random.Random(fault["params"]["seed"])
    a = dict(act)
    args = dict(a["args"])
    if t == "wrong_arg":
        args["currency"] = r.choice([c for c in W.FX_TO_USD if c not in (args["currency"], "USD")])
    elif t in ("hallucinated_value", "off_by_one", "wrong_operation"):
        parts = args["expression"].split("*")
        if t == "hallucinated_value":
            p = float(parts[0])
            v = float(fault["params"].get("value") or round(p * r.choice([r.uniform(0.55, 0.85), r.uniform(1.2, 1.7)])))
            parts[0] = f"{v:g}"
        elif t == "off_by_one":
            n = int(parts[1])
            parts[1] = str(n - 1 if n > 1 and r.random() < 0.5 else n + 1)
        expr = "*".join(parts)
        if t == "wrong_operation":
            expr = expr.replace("*", "+", 1)
        args["expression"] = expr
    elif t == "dropped_field":
        terms = args["expression"].split("+")
        if len(terms) < 2:
            return act
        k = min(fault["occ"], len(terms) - 1) if fault.get("drop_index") is None else fault["drop_index"]
        terms.pop(k)
        args["expression"] = "+".join(terms)
    a["args"] = args
    a["fault_applied"] = True
    return a


def apply_tool_fault(fault, tool, args, obs, history):
    """Returns (obs, applied)."""
    t = fault["type"]
    if TOOL_FAULTS.get(t) != tool:
        return obs, False
    occ = _count(history, lambda h: h["action"]["tool"] == tool)
    if occ != fault["occ"]:
        return obs, False
    r = random.Random(fault["params"]["seed"])
    obs = dict(obs)
    if t == "irrelevant_retrieval":
        city = W.HOTELS[args["hotel"]][0]
        same = [h for h in W.hotels_in(city) if h != args["hotel"]]
        pool = same if (same and r.random() < 0.5) else [h for h in W.HOTELS if h != args["hotel"]]
        obs["text"] = W.hotel_doc(fault["params"].get("doc_hotel") or r.choice(pool))
    elif t == "truncated_context":
        full = obs["text"]
        obs["text"] = full.split(". ")[0] + ". " + full[full.index("City tax"):]
    elif t == "unit_mixup":
        obs["usd"] = round(obs["usd"] * 100, 2)
    elif t == "stale_cache":
        f = r.uniform(0.8, 0.95) if r.random() < 0.5 else r.uniform(1.05, 1.2)
        obs["rate"] = round(obs["rate"] * f, 6)
    return obs, True


def n_occurrences(ftype, task):
    """How many times the targeted event happens in a correct run (for location drift)."""
    legs = task["legs"]
    if ftype in ("hallucinated_value", "wrong_operation", "off_by_one", "irrelevant_retrieval", "truncated_context"):
        return len(legs)
    if ftype in ("wrong_arg", "stale_cache"):
        curs = {W.CITIES[l["city"]] for l in legs} | ({W.CITIES[l["city"]] for l in legs} if task["taxi"] else set())
        return len(curs)
    if ftype == "unit_mixup":
        return len(legs) + 1
    if ftype == "dropped_field":
        return 2 * len(legs) + 1  # number of sum terms is at least this
    return 1
