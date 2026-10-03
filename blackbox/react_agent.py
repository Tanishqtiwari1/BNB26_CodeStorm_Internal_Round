"""Dynamic tool-calling agent (ReAct-style), instrumented with OpenTelemetry.

The agent decides its own next action each turn, so traces have no fixed
shape: order differs, legs interleave, shared FX lookups fan out, transient
tool errors cause retries, verification re-calls create extra branches.

Policies (who decides the next action):
  ScriptedPolicy  deterministic stochastic planner used to build the large
                  labelled benchmark quickly (variant="standard" | "verifier")
  OllamaPolicy    a real small language model run locally (default qwen2.5:7b via Ollama)
  GroqPolicy      a hosted open model via Groq (used where Ollama can't run, e.g. Render)

Every turn produces OTel spans:
  call:<tool>  (gen_ai.operation.name=chat)          the model's decision
  <tool>       (gen_ai.operation.name=execute_tool)   child of the decision
  final_answer (gen_ai.operation.name=chat)
Data-flow edges are recovered by value provenance (which earlier observation
produced each number/string the model used) and emitted as span links.
"""
import ast
import json
import operator
import os
import random
import re
import time
import urllib.error
import urllib.request

from opentelemetry import trace
from opentelemetry.trace import Link

from . import otel
from . import world as W

QREGEX = re.compile(r"for (\d+) travelers? flying from (.+?): (.+), and the flight back\.(.*?)Is it within the \$([\d,]+) budget")
LEGRE = re.compile(r"(\d+) nights? at (.+?) in (.+)")
NUMRE = re.compile(r"-?\d+(?:\.\d+)?")

TOOLS = {
    "search_hotel": {"kind": "retrieval", "desc": "Look up a hotel's information page", "args": {"hotel": "hotel name"}},
    "fx_rate": {"kind": "tool", "desc": "USD value of 1 unit of a currency", "args": {"currency": "ISO code, e.g. EUR"}},
    "flight_price": {"kind": "tool", "desc": "One-way economy fare in USD per person", "args": {"origin": "city", "destination": "city"}},
    "per_diem": {"kind": "tool", "desc": "Daily meal allowance in USD for a city", "args": {"city": "city"}},
    "taxi_fare": {"kind": "tool", "desc": "Airport taxi fare in local currency", "args": {"city": "city"}},
    "calculator": {"kind": "tool", "desc": "Evaluate an arithmetic expression", "args": {"expression": "e.g. 180*3*1.08"}},
}


# ---------------------------------------------------------------- tools (deterministic world)
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg}


def _calc(expr):
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("unsupported expression")
    return round(float(ev(ast.parse(str(expr), mode="eval"))), 2)


def run_tool(name, args):
    if name == "search_hotel":  # behaves like a search engine: best match for partial names
        h = str(args.get("hotel", ""))
        if h not in W.HOTELS:
            q = set(h.lower().replace(",", " ").split())
            best = max(W.HOTELS, key=lambda x: len(q & set(x.lower().split())))
            if not q & set(best.lower().split()):
                raise KeyError(f"no hotel matches '{h}'")
            h = best
        return {"text": W.hotel_doc(h)}
    if name == "fx_rate":
        return {"rate": W.FX_TO_USD[str(args["currency"]).upper()]}
    if name == "flight_price":
        return {"usd": W.flight_price_usd(args["origin"], args["destination"])}
    if name == "per_diem":
        return {"usd": float(W.PER_DIEM_USD[args["city"]])}
    if name == "taxi_fare":
        c = args["city"]
        return {"amount": float(W.TAXI_LOCAL[c]), "currency": W.CITIES[c]}
    if name == "calculator":
        return {"value": _calc(args["expression"])}
    raise KeyError(f"unknown tool {name}")


def parse_question(q):
    m = QREGEX.search(q)
    if not m:
        raise ValueError("could not parse question")
    legs = []
    for part in m.group(3).split(", then "):
        lm = LEGRE.match(part.strip())
        legs.append({"city": lm.group(3), "hotel": lm.group(2), "nights": int(lm.group(1))})
    return {"origin": m.group(2), "travelers": int(m.group(1)), "legs": legs,
            "per_diem": "per-diem" in m.group(4), "taxi": "taxi" in m.group(4), "budget": int(m.group(5).replace(",", ""))}


def _fmt(x):
    return f"{x:g}" if isinstance(x, float) else str(x)


# ---------------------------------------------------------------- scripted policy (benchmark)
class ScriptedPolicy:
    """Reads the question, gathers facts with tools and computes the answer.
    Decisions depend only on (task, observations so far, seed), so a run can be
    resumed from any checkpoint (needed for replay)."""

    def __init__(self, variant="standard"):
        self.variant = variant
        self.model = f"scripted-{variant}"

    def facts(self, plan, history):
        f = {"doc": {}, "fx": {}, "hotel_usd": {}, "flight": {}, "pd": {}, "pd_total": {}, "taxi": {}, "taxi_usd": {},
             "back": None, "total": None, "verified": set(), "errors": {}}
        for h in history:
            a, obs, err = h["action"], h["obs"], h.get("error")
            key = h.get("need")
            if err:
                f["errors"][key] = f["errors"].get(key, 0) + 1
                continue
            if key is None:
                continue
            kind, i = key
            if kind == "doc":
                if i in f["doc"]:
                    f["verified"].add(key)
                f["doc"][i] = obs.get("text", "")
            elif kind == "fx":
                f["fx"][i] = obs.get("rate")
            elif kind in ("hotel_usd", "pd_total", "taxi_usd", "total"):
                if kind == "total":
                    f["total"] = obs.get("value")
                else:
                    f[kind][i] = obs.get("value")
            elif kind == "flight":
                f["flight"][i] = obs.get("usd")
            elif kind == "back":
                f["back"] = obs.get("usd")
            elif kind == "pd":
                f["pd"][i] = obs.get("usd")
            elif kind == "taxi":
                f["taxi"][i] = obs
            elif kind == "verify":
                f["verified"].add(key)
        return f

    @staticmethod
    def read_price(doc):
        m = re.search(r"Standard room: (\d+) ([A-Z]{3})", doc) or re.search(r"(\d+) ([A-Z]{3})", doc)
        return (float(m.group(1)), m.group(2)) if m else (None, None)

    def candidates(self, plan, f):
        """Every action that could sensibly come next: (need, tool, args)."""
        c = []
        trav, legs = plan["travelers"], plan["legs"]
        for i, leg in enumerate(legs):
            if i not in f["doc"]:
                c.append((("doc", i), "search_hotel", {"hotel": leg["hotel"]}))
                continue
            price, cur = self.read_price(f["doc"][i])
            if cur and cur not in f["fx"]:
                c.append((("fx", cur), "fx_rate", {"currency": cur}))
            elif cur and i not in f["hotel_usd"] and price is not None:
                expr = f"{_fmt(price)}*{leg['nights']}*{_fmt(f['fx'][cur])}" + (f"*{trav}" if trav > 1 else "")
                c.append((("hotel_usd", i), "calculator", {"expression": expr}))
            if self.variant == "verifier" and ("doc", i) not in f["verified"] and i in f["hotel_usd"]:
                c.append((("doc", i), "search_hotel", {"hotel": leg["hotel"]}))
        for i, leg in enumerate(legs):
            if i not in f["flight"]:
                src = plan["origin"] if i == 0 else legs[i - 1]["city"]
                c.append((("flight", i), "flight_price", {"origin": src, "destination": leg["city"]}))
            if plan["per_diem"]:
                if i not in f["pd"]:
                    c.append((("pd", i), "per_diem", {"city": leg["city"]}))
                elif i not in f["pd_total"]:
                    c.append((("pd_total", i), "calculator", {"expression": f"{_fmt(f['pd'][i])}*{leg['nights']}*{trav}"}))
            if plan["taxi"]:
                if i not in f["taxi"]:
                    c.append((("taxi", i), "taxi_fare", {"city": leg["city"]}))
                else:
                    cur = f["taxi"][i].get("currency")
                    if cur not in f["fx"]:
                        c.append((("fx", cur), "fx_rate", {"currency": cur}))
                    elif i not in f["taxi_usd"]:
                        c.append((("taxi_usd", i), "calculator", {"expression": f"{_fmt(f['taxi'][i]['amount'])}*{_fmt(f['fx'][cur])}"}))
        if f["back"] is None:
            c.append((("back", 0), "flight_price", {"origin": legs[-1]["city"], "destination": plan["origin"]}))
        return c

    def components(self, plan, f):
        parts = []
        for i in range(len(plan["legs"])):
            parts.append(f["hotel_usd"].get(i))
            parts.append((f["flight"].get(i), plan["travelers"]))
            if plan["per_diem"]:
                parts.append(f["pd_total"].get(i))
            if plan["taxi"]:
                parts.append(f["taxi_usd"].get(i))
        parts.append((f["back"], plan["travelers"]))
        return parts

    def decide(self, question, history, rng, fault_hook):
        plan = parse_question(question)
        f = self.facts(plan, history)
        # retry the last call after a transient tool error
        if history and history[-1].get("error") and history[-1]["error"] != "exception":
            last = history[-1]
            return {"tool": last["action"]["tool"], "args": last["action"]["args"], "need": last["need"]}
        cands = self.candidates(plan, f)
        if cands:
            if self.variant == "verifier":  # topology drift: flights first, then hotels in order
                cands.sort(key=lambda x: (x[1] != "flight_price", x[0][0] == "doc"))
                pick = cands[0]
            else:
                pick = rng.choice(cands)
            act = {"tool": pick[1], "args": dict(pick[2]), "need": pick[0]}
            return fault_hook(act, plan, f)
        if f["total"] is None:
            parts = self.components(plan, f)
            terms = [(_fmt(p[0]) + (f"*{p[1]}" if p[1] > 1 else "")) if isinstance(p, tuple) else _fmt(p) for p in parts]
            act = {"tool": "calculator", "args": {"expression": "+".join(terms)}, "need": ("total", 0)}
            return fault_hook(act, plan, f)
        total = f["total"]
        return {"tool": "final_answer", "args": {"total_usd": total, "within_budget": total <= plan["budget"],
                                                  "summary": f"Estimated total ${total:,.2f}, "
                                                             f"{'within' if total <= plan['budget'] else 'over'} the ${plan['budget']:,} budget."},
                "need": ("final", 0)}


# ---------------------------------------------------------------- real SLM policy (Ollama)
SYSTEM = """You are a travel-expense agent. Compute the exact total trip cost in USD by calling tools, one tool per turn.
Procedure:
1. For each hotel: search_hotel with the exact hotel name, read ONLY the "Standard room" nightly price and its currency
   (ignore city tax and breakfast), call fx_rate for that currency, then calculator: price * nights * fx_rate * travelers.
2. Flights: one flight_price call per leg: origin to the first city, each city to the next city, and the flight back from the
   last city to the origin. Each fare is per person, multiply by travelers.
3. Only if per-diem is requested: per_diem for each city, then allowance * nights * travelers.
4. Only if airport taxis are requested: one taxi_fare per city (not per traveler), converted with fx_rate.
   The trip ALWAYS ends with a flight back: flight_price(origin=<last city>, destination=<origin>). Never skip it.
5. calculator: add all components (hotels + every flight leg including the flight back + extras).
   Then final_answer with that total; within_budget is true exactly when total_usd <= budget (e.g. 2300 <= 2460 is true).
Only use numbers that appear in the question or in tool results. Never repeat a call you already made."""

TOOL_SPECS = [
    {"type": "function", "function": {"name": "search_hotel", "description": "Get a hotel's information page",
     "parameters": {"type": "object", "properties": {"hotel": {"type": "string"}}, "required": ["hotel"]}}},
    {"type": "function", "function": {"name": "fx_rate", "description": "USD value of 1 unit of a currency",
     "parameters": {"type": "object", "properties": {"currency": {"type": "string", "description": "ISO code"}}, "required": ["currency"]}}},
    {"type": "function", "function": {"name": "flight_price", "description": "One-way economy fare in USD per person",
     "parameters": {"type": "object", "properties": {"origin": {"type": "string"}, "destination": {"type": "string"}}, "required": ["origin", "destination"]}}},
    {"type": "function", "function": {"name": "per_diem", "description": "Daily meal allowance in USD per person",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "taxi_fare", "description": "Airport taxi fare in local currency",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "calculator", "description": "Evaluate an arithmetic expression with + - * / and parentheses",
     "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}}},
    {"type": "function", "function": {"name": "final_answer", "description": "Report the final total",
     "parameters": {"type": "object", "properties": {"total_usd": {"type": "number"}, "within_budget": {"type": "boolean"},
                                                     "summary": {"type": "string"}}, "required": ["total_usd", "within_budget", "summary"]}}},
]


class OllamaPolicy:
    """A real small language model choosing the next tool call (Ollama native tool calling)."""

    def __init__(self, model=None, host=None):
        self.model = model or os.environ.get("BLACKBOX_SLM", "qwen2.5:7b")
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def available(self):
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=2) as r:
                return any(m["name"] == self.model or m["name"] == self.model + ":latest" for m in json.load(r).get("models", []))
        except Exception:
            return False

    def _chat(self, messages):
        import hashlib

        from . import llm
        llm._cache = llm._cache or llm._Cache()
        h = hashlib.sha256(json.dumps(["ollama-tools", self.model, messages]).encode()).hexdigest()
        hit = llm._cache.get(h)
        if hit is not None:
            return json.loads(hit)
        body = json.dumps({"model": self.model, "messages": messages, "tools": TOOL_SPECS, "stream": False,
                           "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 256}}).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as r:
            msg = json.load(r)["message"]
        llm._cache.put(h, json.dumps(msg))
        return msg

    def decide(self, question, history, rng, fault_hook):
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
        for h in history:
            msgs.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": h["action"]["tool"], "arguments": h["action"]["args"]}}]})
            msgs.append({"role": "tool", "content": json.dumps(h["obs"])})
        msg = self._chat(msgs)
        calls = msg.get("tool_calls") or []
        if calls:
            fn = calls[0]["function"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            act = {"tool": fn["name"], "args": dict(args), "need": None}
        else:  # model answered in text instead of calling a tool
            act = {"tool": "invalid_output", "args": {}, "need": None, "raw": msg.get("content", "")}
        # loop guard: the same call three times in a row ends the run (recorded as a failure)
        last = [json.dumps(h["action"], sort_keys=True) for h in history[-2:]]
        if len(last) == 2 and all(x == json.dumps({"tool": act["tool"], "args": act["args"]}, sort_keys=True) for x in last):
            return {"tool": "final_answer", "args": {"total_usd": None, "within_budget": None, "summary": "stopped: repeated tool call"}, "need": None}
        return act


class GroqPolicy(OllamaPolicy):
    """Hosted open model via Groq's OpenAI-compatible API (key from GROQ_API_KEY, never logged)."""

    PREFERRED = ["llama-3.1-8b-instant", "qwen/qwen3-32b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]
    BASE = "https://api.groq.com/openai/v1"
    _models = None

    def __init__(self, model=None):
        self.key = os.environ.get("GROQ_API_KEY", "")
        self.model = model or os.environ.get("GROQ_MODEL") or self._pick()

    def _req(self, path, body=None):
        req = urllib.request.Request(self.BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                                              "User-Agent": "blackbox-flight-recorder"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            from .llm import LLMError
            detail = e.read().decode(errors="replace")[:200]
            raise LLMError(f"Groq HTTP {e.code}: {detail}") from None

    def _pick(self):
        if not self.key:
            return self.PREFERRED[0]
        if GroqPolicy._models is None:
            try:
                GroqPolicy._models = {m["id"] for m in self._req("/models").get("data", [])}
            except Exception:
                GroqPolicy._models = set()
        return next((m for m in self.PREFERRED if m in GroqPolicy._models), self.PREFERRED[0])

    def available(self):
        return bool(self.key)

    def _chat(self, messages):
        import hashlib

        from . import llm
        oai, n = [], 0
        for m in messages:  # Ollama-style history -> OpenAI tool-calling format
            if m["role"] == "assistant" and m.get("tool_calls"):
                n += 1
                fn = m["tool_calls"][0]["function"]
                oai.append({"role": "assistant", "content": None, "tool_calls": [
                    {"id": f"call_{n}", "type": "function", "function": {"name": fn["name"], "arguments": json.dumps(fn["arguments"])}}]})
            elif m["role"] == "tool":
                oai.append({"role": "tool", "tool_call_id": f"call_{n}", "content": m["content"]})
            else:
                oai.append({"role": m["role"], "content": m["content"]})
        llm._cache = llm._cache or llm._Cache()
        h = hashlib.sha256(json.dumps(["groq", self.model, oai]).encode()).hexdigest()
        hit = llm._cache.get(h)
        if hit is not None:
            return json.loads(hit)
        r = self._req("/chat/completions", {"model": self.model, "messages": oai, "tools": TOOL_SPECS, "tool_choice": "auto",
                                            "temperature": 0, "max_tokens": 512})
        msg = r["choices"][0]["message"]
        out = {"content": msg.get("content") or "", "tool_calls": [{"function": {"name": c["function"]["name"],
               "arguments": c["function"].get("arguments") or "{}"}} for c in (msg.get("tool_calls") or [])]}
        llm._cache.put(h, json.dumps(out))
        return out


def live_policy():
    """The real model to use for live runs: local Ollama if running, else hosted Groq if a key is set."""
    o = OllamaPolicy()
    if o.available():
        return o
    g = GroqPolicy()
    return g if g.available() else None


def provider_of(policy):
    return "groq" if isinstance(policy, GroqPolicy) else "ollama" if isinstance(policy, OllamaPolicy) else "scripted"


# ---------------------------------------------------------------- provenance (data-flow edges)
def _values(obj):
    """Numbers and short strings an output/arg contains (numbers inside text too)."""
    nums, strs = set(), set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, bool) or x is None:
            return
        elif isinstance(x, (int, float)):
            nums.add(round(float(x), 6))
        elif isinstance(x, str):
            for n in NUMRE.findall(x.replace(",", "")):
                nums.add(round(float(n), 6))
            if len(x) <= 40:
                strs.add(x)
            for tok in re.findall(r"[A-Z]{3}", x):
                strs.add(tok)
    walk(obj)
    return nums, strs


def provenance(used, producers, trivial=(0.0, 1.0, 2.0)):
    """Which earlier steps produced the values in `used`: observations (tool outputs, the task)
    are preferred over values the model itself wrote earlier; most recent producer wins."""
    nums, strs = _values(used)
    obs = [p for p in producers if "call:" not in p[0] and "final_answer" not in p[0]]
    dec = [p for p in producers if p not in obs]
    src = []

    def find(pred):
        for group in (obs, dec):
            for sid, (pn, ps) in reversed(group):
                if pred(pn, ps):
                    return sid
        return None
    for v in nums:
        if v not in trivial and (sid := find(lambda pn, ps: v in pn)):
            src.append(sid)
    for v in strs:
        if sid := find(lambda pn, ps: v in ps or any(v in s for s in ps if len(s) > len(v))):
            src.append(sid)
    return list(dict.fromkeys(src))


# ---------------------------------------------------------------- run loop
def execute(task, policy, fault=None, seed=0, max_turns=40, resume=None, sim_latency=True):
    """Run (or resume) the agent. Returns (OTel-derived steps, final output, history, fault_sid).

    resume (replay) = {"steps": restored step records, "history": matching history,
                       "memo": {(tool, args_json): obs}, "action": forced next decision (optional),
                       "tool_action": re-run only the tool of this already-restored decision (optional),
                       "tool_output": forced output for that tool (optional)}
    """
    from .faults_v2 import apply_action_fault, apply_tool_fault
    rng = random.Random(seed)
    tr = otel.tracer()
    question = task["question"]
    resume = resume or {}
    history = list(resume.get("history", []))
    prior = list(resume.get("steps", []))
    memo = dict(resume.get("memo", {}))
    is_real = isinstance(policy, OllamaPolicy)
    state = {"idx": 0, "fault_sid": None}
    span_ctx, producers = {}, []

    def lat(kind):
        return {"llm": rng.uniform(300, 900), "retrieval": rng.uniform(80, 220), "tool": rng.uniform(15, 120),
                "final": rng.uniform(1, 5), "input": 0.0}[kind]

    def fhook(act, plan, f):
        return apply_action_fault(fault, act, plan, f, history) if fault else act

    def emit(st, links=(), parent_sid=None, reused=False):
        kw = {"links": [Link(span_ctx[p]) for p in links if p in span_ctx]}
        if parent_sid:
            kw["context"] = trace.set_span_in_context(trace.NonRecordingSpan(span_ctx[parent_sid]))
        with tr.start_as_current_span(st["name"], **kw) as sp:
            _set(sp, st, reused=reused)
        span_ctx[st["sid"]] = sp.get_span_context()
        state["idx"] += 1

    def do_tool(act, dec_sid, forced_obs=None):
        tool = act["tool"]
        tsid = f"s{state['idx']:02d}.{tool}"
        key = (tool, json.dumps(act["args"], sort_keys=True))
        err, reused, applied = None, False, False
        t1 = time.perf_counter()
        if forced_obs is not None:
            obs = forced_obs
        elif key in memo:
            obs, reused = memo[key], True
        else:
            try:
                obs = run_tool(tool, act["args"])
                if fault:
                    obs, applied = apply_tool_fault(fault, tool, act["args"], obs, history)
                if sim_latency and not is_real and tool != "calculator" and rng.random() < 0.04:
                    err, obs = "timeout", {"error": "upstream timeout"}
            except Exception as e:
                obs, err = {"error": f"{type(e).__name__}: {e}"}, "exception"
        ms = (time.perf_counter() - t1) * 1000
        st = {"sid": tsid, "kind": TOOLS[tool]["kind"], "name": tool, "role": tool, "parents": [dec_sid], "args": act["args"],
              "output": obs, "latency_ms": round(ms if is_real else lat(TOOLS[tool]["kind"]) + (900 if err == "timeout" else 0), 1),
              "error": err, "retries": 0}
        emit(st, parent_sid=dec_sid, reused=reused)
        if applied:
            state["fault_sid"] = tsid
        if not err:
            producers.append((tsid, _values(obs)))
        history.append({"action": {"tool": tool, "args": act["args"]}, "obs": obs, "error": err, "need": act.get("need"),
                        "dec_sid": dec_sid, "tool_sid": tsid})

    with tr.start_as_current_span("agent.run", attributes={"blackbox.question": question, "gen_ai.system": "blackbox"}) as root:
        for s in prior:  # restored checkpoint: re-emitted as reused spans so the replay trace is complete
            emit({**s}, links=s["parents"], reused=True)
            producers.append((s["sid"], _values(s["output"].get("args", {}) if s["kind"] == "llm" else s["output"])))
        if not prior:
            emit({"sid": "s00.task", "kind": "input", "name": "task", "role": "task", "parents": [], "args": {},
                  "output": {"question": question}, "latency_ms": 0.0, "error": None, "retries": 0})
            producers.append(("s00.task", _values(question)))
        if resume.get("tool_action"):
            do_tool(resume["tool_action"], prior[-1]["sid"], resume.get("tool_output"))
        forced = resume.get("action")
        for turn in range(max_turns):
            t0 = time.perf_counter()
            act = forced if forced is not None else policy.decide(question, history, rng, fhook)
            forced = None
            ms = (time.perf_counter() - t0) * 1000
            tool = act["tool"]
            final = tool == "final_answer"
            dsid = f"s{state['idx']:02d}.{'final_answer' if final else 'call:' + tool}"
            parents = provenance(act["args"], producers) or [producers[-1][0]]
            bad = not final and tool not in TOOLS
            dec = {"sid": dsid, "kind": "final" if final else "llm", "name": "final_answer" if final else f"call:{tool}",
                   "role": "final_answer" if final else "decide", "parents": parents,
                   "args": {"model": getattr(policy, "model", "?"), "turn": len(history),
                            "need": list(act["need"]) if act.get("need") else None},
                   "output": dict(act["args"]) if final else {"tool": tool, "args": act["args"]},
                   "latency_ms": round(ms if is_real else lat("final" if final else "llm"), 1),
                   "error": "exception" if bad else None, "retries": 0}
            if bad:
                dec["output"]["raw"] = str(act.get("raw", ""))[:300]
            emit(dec, links=parents)
            if act.get("fault_applied"):
                state["fault_sid"] = dsid
            producers.append((dsid, _values(act["args"])))
            if final:
                break
            if bad:
                history.append({"action": {"tool": tool, "args": act["args"]}, "obs": {"error": f"unknown tool {tool}"},
                                "error": "exception", "need": None, "dec_sid": dsid, "tool_sid": None})
                continue
            do_tool(act, dsid)
        trace_id = root.get_span_context().trace_id
    steps = otel.sdk_spans_to_steps(otel.collect(trace_id))
    final_out = next((s["output"] for s in reversed(steps) if s["kind"] == "final"), {})
    return steps, final_out, history, state["fault_sid"]


def _set(span, st, reused=False):
    a = {"blackbox.sid": st["sid"], "blackbox.kind": st["kind"], "blackbox.name": st["name"], "blackbox.role": st.get("role", st["name"]),
         "blackbox.args": json.dumps(st["args"]), "blackbox.output": json.dumps(st["output"]),
         "blackbox.latency_ms": float(st["latency_ms"]), "blackbox.retries": int(st.get("retries", 0)), "blackbox.reused": reused}
    if st.get("error"):
        a["blackbox.error"] = st["error"]
    if st["kind"] in ("llm", "final"):
        a["gen_ai.operation.name"] = "chat"
        a["gen_ai.request.model"] = str(st["args"].get("model", ""))
    elif st["kind"] in ("tool", "retrieval"):
        a["gen_ai.operation.name"] = "execute_tool"
        a["gen_ai.tool.name"] = st["name"]
    span.set_attributes(a)
