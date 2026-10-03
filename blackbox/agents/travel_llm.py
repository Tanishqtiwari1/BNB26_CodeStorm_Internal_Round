"""Reference agent with real LLM calls, instrumented by Black Box.

Same tool workflow as the simulated agent (so the trained model's historical
baselines apply), but the three language steps are genuine model calls:

  parse_task    LLM turns the user's question into a structured plan
  extract_rate  LLM reads the retrieved hotel document and extracts the price
  final_answer  LLM writes the answer for the user from the computed result

With no ANTHROPIC_API_KEY the agent runs in mock mode: a deterministic
offline stand-in that reads the same text with regexes.
"""
import re

from .. import agent as A
from .. import llm
from .base import Adapter

PARSE_SYSTEM = (
    "You convert a travel-cost question into a JSON plan. Reply with ONLY a JSON object with keys: "
    "origin (string), travelers (integer), legs (array of {city, hotel, nights}), per_diem (boolean), "
    "taxi (boolean), budget (integer USD). Copy names exactly as written in the question."
)
EXTRACT_SYSTEM = (
    "You read a hotel information snippet and extract the nightly price of the standard room. "
    'Reply with ONLY JSON: {"amount": <number>, "currency": "<ISO code>"}. '
    'If the standard room price is not in the snippet, reply {"amount": null, "currency": null}.'
)
ANSWER_SYSTEM = "You answer a traveler in one short, plain sentence using only the numbers you are given."


# ---------------------------------------------------------------- mock LLM (offline)
_Q = re.compile(r"for (\d+) travelers? flying from (.+?): (.+), and the flight back\.(.*?)Is it within the \$([\d,]+) budget")
_LEG = re.compile(r"(\d+) nights? at (.+?) in (.+)")


def _mock_parse(question):
    m = _Q.search(question)
    if not m:
        return "{}"
    legs = []
    for part in m.group(3).split(", then "):
        lm = _LEG.match(part.strip())
        if lm:
            legs.append({"city": lm.group(3), "hotel": lm.group(2), "nights": int(lm.group(1))})
    import json
    return json.dumps({"origin": m.group(2), "travelers": int(m.group(1)), "legs": legs,
                       "per_diem": "per-diem" in m.group(4), "taxi": "taxi" in m.group(4),
                       "budget": int(m.group(5).replace(",", ""))})


def _mock_extract(prompt):
    import json
    return json.dumps(A.llm_extract({"context": prompt.split("Snippet:\n", 1)[-1]}))


# ---------------------------------------------------------------- LLM steps
def llm_parse(args, task=None):
    plan = llm.parse_json(llm.complete(PARSE_SYSTEM, args["question"], _mock_parse))
    legs = [{"city": str(l["city"]), "hotel": str(l["hotel"]),
             "nights": None if l.get("nights") is None else int(l["nights"])} for l in plan.get("legs", [])]
    if not legs:
        raise llm.LLMError("model returned a plan with no legs")
    return {"origin": str(plan["origin"]), "travelers": int(plan["travelers"]), "legs": legs,
            "per_diem": bool(plan.get("per_diem")), "taxi": bool(plan.get("taxi")),
            "budget": int(plan["budget"])}


def llm_extract(args, task=None):
    prompt = f"Hotel: {args['hotel']}\nSnippet:\n{args['context']}"
    d = llm.parse_json(llm.complete(EXTRACT_SYSTEM, prompt, _mock_extract, max_tokens=256))
    amt = d.get("amount")
    return {"amount": None if amt is None else float(amt), "currency": d.get("currency")}


def llm_answer(args, task=None):
    verdict = "within" if args["within_budget"] else "over"
    prompt = (f"Total trip cost: {args['total']:.2f} USD. Budget margin: {args['margin']:.2f} USD "
              f"({verdict} budget). Answer the traveler.")
    mock = lambda _: (f"The trip will cost about ${args['total']:,.0f}, which is {verdict} budget "
                      f"by ${abs(args['margin']):,.0f}.")
    summary = llm.complete(ANSWER_SYSTEM, prompt, mock, max_tokens=200)
    return {"total_usd": round(float(args["total"]), 2), "within_budget": args["within_budget"], "summary": summary}


class TravelLLM(Adapter):
    name = "travel-llm"
    label = "Travel-expense agent (real LLM)"
    description = "Live agent: LLM parses the request, reads retrieved documents and writes the answer; tools do the math."

    def build_plan(self, task):
        plan = A.build_plan(task)
        model = llm.describe()["model"]
        for s in plan:
            if s.name == "parse_task":
                s.derive = lambda t, pv, m=model: {"question": t["question"], "model": m}
                s.run = llm_parse
            elif s.name == "extract_rate":
                d0 = s.derive
                s.derive = lambda t, pv, d0=d0, m=model: {**d0(t, pv), "model": m}
                s.run = llm_extract
            elif s.name == "final_answer":
                s.derive = lambda t, pv, m=model: {"total": pv["T.total"]["value"],
                                                   "within_budget": pv["T.check"]["within_budget"],
                                                   "margin": pv["T.check"]["margin"], "model": m}
                s.run = llm_answer
        return plan

    def judge(self, task, final):
        return A.judge(task, final)

    def latency(self, kind, measured_ms, rng):
        # real wall-clock for real API calls; simulated in mock mode so that
        # timing features stay comparable with the benchmark corpus
        return round(measured_ms, 1) if llm.provider() == "anthropic" else A._latency(kind, rng)

    def meta(self):
        return llm.describe()
