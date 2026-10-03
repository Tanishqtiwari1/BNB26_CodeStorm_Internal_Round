"""The scripted 60-second demo scenario.

One traveler, New York -> Paris, 3 nights at Hotel Lumiere. The LLM's
extraction step reports the room at 245 EUR instead of the 180 EUR in the
retrieved document (a simulated hallucination, injected and labelled as such).
The wrong price pushes the trip over budget, so the agent gives the wrong
verdict. Black Box has to find the step on its own; the label is only used to
show the audience afterwards whether it was right.
"""
import random

from . import agent as A
from .agents import get_adapter

WRONG_PRICE = 245.0


def killer_task():
    task = {"origin": "New York", "travelers": 1,
            "legs": [{"city": "Paris", "hotel": "Hotel Lumiere", "nights": 3}],
            "per_diem": False, "taxi": False, "reflect_after": [], "budget": None}
    gt = A.ground_truth(task)["total_usd"]
    # budget sits between the correct total and the total the bad price produces
    task["budget"] = int(round(gt + 100, -1))
    task["question"] = A.question_text(task)
    return task


def killer_fault():
    return {"type": "hallucinated_value", "sid": "L0.rate", "params": {"seed": 0, "value": WRONG_PRICE},
            "demo_note": f"Injected for the demo: the extraction LLM's answer is replaced with {WRONG_PRICE:g} EUR "
                         f"(the document says 180 EUR)."}


def run_killer(rec, agent="travel-llm"):
    ad = get_adapter(agent)
    task, fault = killer_task(), killer_fault()
    recs = ad.execute(task, fault=fault, rng=random.Random(42))
    ok, gt = ad.judge(task, recs[-1]["output"])
    rid = rec.save_run(task, recs, recs[-1]["output"], ok, gt, fault, split="demo", agent=agent, meta=ad.meta())
    rec.commit()
    return rid


def patch_from_document(steps):
    """The demo's repair: read the price the retrieved document actually states.
    Derived from the recorded trace (the L0.doc output), not hard-coded."""
    import re
    doc = next((s for s in steps if s["sid"] == "L0.doc"), None)
    if doc is None:
        raise KeyError("L0.doc")
    m = re.search(r"Standard room: (\d+) ([A-Z]{3})", doc["output"].get("text", ""))
    if not m:
        raise ValueError("the retrieved document does not state a standard-room price")
    return {"sid": "L0.rate", "patch": {"amount": float(m.group(1)), "currency": m.group(2)},
            "source": m.group(0)}
