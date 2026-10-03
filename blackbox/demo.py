"""The scripted live-demo scenario (dynamic agent, OpenTelemetry trace).

One traveler, New York -> Paris, 3 nights at Hotel Lumiere.
  * With Ollama running, a real SLM (default qwen2.5:7b) drives the agent and the
    flight API returns the outbound fare in cents (an injected, labelled environment
    fault). The model uses it and the answer is wrong. (A wrong hotel page was tried
    first: the model noticed and re-searched, so it is not used for the demo.)
  * Without Ollama, the deterministic benchmark policy runs and its hotel-cost
    calculation uses 245 EUR instead of the 180 EUR on the page (injected, labelled).
Black Box must find the step on its own; the label is only for the audience reveal.
"""
import os
import random
import re

from . import agent as A
from .faults_v2 import make_fault
from .react_agent import OllamaPolicy, ScriptedPolicy, execute

WRONG_PRICE = 245.0


def killer_task():
    task = {"origin": "New York", "travelers": 1, "legs": [{"city": "Paris", "hotel": "Hotel Lumiere", "nights": 3}],
            "per_diem": False, "taxi": False, "reflect_after": [], "budget": None}
    task["budget"] = int(round(A.ground_truth(task)["total_usd"] + 100, -1))
    task["question"] = A.question_text(task)
    return task


def run_killer(rec, prefer_slm=None):
    task = killer_task()
    slm = OllamaPolicy()
    use_slm = (prefer_slm if prefer_slm is not None else os.environ.get("BLACKBOX_DEMO_POLICY", "slm") == "slm") and slm.available()
    if use_slm:
        policy, agent = slm, "react-slm"
        fault = make_fault("unit_mixup", 0, seed=0)
        fault["demo_note"] = "Injected for the demo: the flight-price API returned the outbound fare in cents instead of dollars."
    else:
        policy, agent = ScriptedPolicy("standard"), "react-sim"
        fault = make_fault("hallucinated_value", 0, seed=0)
        fault["params"]["value"] = WRONG_PRICE
        fault["demo_note"] = f"Injected for the demo: the hotel-cost calculation used {WRONG_PRICE:g} EUR; the page says 180 EUR."
    steps, final, _, fsid = execute(task, policy, fault=fault, seed=42)
    ok, gt = A.judge(task, final)
    fault["sid"] = fsid
    rid = rec.save_run(task, steps, final, ok, gt, fault, split="demo", agent=agent,
                       meta={"policy": getattr(policy, "variant", None), "model": policy.model,
                             "provider": "ollama" if use_slm else "scripted"})
    rec.commit()
    return rid


def suggested_repair(steps, root_sid):
    """A repair derived from the recorded trace, for the demo's 'patch' step.
    Retrieval root -> re-run the tool. Calculation root -> rebuild the expression
    with the price stated on the retrieved page."""
    s = next((x for x in steps if x["sid"] == root_sid), None)
    if s is None:
        raise KeyError(root_sid)
    if s["kind"] in ("tool", "retrieval"):
        return {"sid": root_sid, "mode": "repair", "patch": None,
                "source": f"re-run {s['name']}({', '.join(f'{k}={v}' for k, v in s['args'].items())}) without the fault"}
    if s["name"] == "call:calculator":
        doc = next((x for x in steps if x["kind"] == "retrieval" and "text" in x["output"]), None)
        m = re.search(r"Standard room: (\d+) ([A-Z]{3})", doc["output"]["text"]) if doc else None
        if not m:
            raise ValueError("no retrieved page states a standard-room price")
        parts = s["output"]["args"]["expression"].split("*")
        parts[0] = m.group(1)
        return {"sid": root_sid, "mode": "patch_output", "source": m.group(0),
                "patch": {"tool": "calculator", "args": {"expression": "*".join(parts)}}}
    return {"sid": root_sid, "mode": "repair", "patch": None, "source": "re-run the decision"}
