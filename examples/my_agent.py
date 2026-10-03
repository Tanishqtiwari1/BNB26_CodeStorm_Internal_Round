"""Bring-your-own-agent test for Black Box.

A small grocery-budget agent that has nothing to do with Black Box's built-in
travel agent. It can follow three different strategies, so the shape of its
trace changes from run to run, and you can switch on one bug to see whether
Black Box finds it. Every step is sent as a standard OpenTelemetry span
(OTLP/HTTP JSON) to Black Box's /api/otlp/v1/traces endpoint.

Only the Python standard library is needed.

  python examples/my_agent.py --healthy 5                      # teach Black Box this agent's normal (once)
  python examples/my_agent.py                                   # clean run, live site
  python examples/my_agent.py --strategy running_total --bug cents
  python examples/my_agent.py --strategy verify --bug wrong_qty
  python examples/my_agent.py --url http://localhost:8000      # local server

Then open the printed link (or the Runs page, filter "External").
"""
import argparse
import json
import os
import random
import ssl
import time
import urllib.request

# ------------------------------------------------------------------ the "world"
STORE = {  # price per unit, USD
    "milk": 1.25, "bread": 2.50, "eggs": 3.20, "apples": 0.60, "rice": 4.75,
    "coffee": 8.90, "cheese": 5.40, "bananas": 0.30, "pasta": 1.80, "tomatoes": 0.45,
}
TAX = 0.08

STRATEGIES = {
    "plan_first": "look up every price, then compute the total once",
    "running_total": "keep a running total after every item",
    "verify": "plan first, then re-check the total with a second calculation",
}
BUGS = {
    "none": "no bug",
    "cents": "the price API returns one item's price in cents instead of dollars (tool fault)",
    "wrong_qty": "the agent copies the wrong quantity into the calculation (agent decision fault)",
    "skip_tax": "the agent forgets to add tax at the end (agent decision fault)",
}


# ------------------------------------------------------------------ span recording
class Trace:
    """Collects spans for one run and converts them to OTLP/HTTP JSON."""

    def __init__(self, question):
        self.trace_id = os.urandom(16).hex()
        self.root = os.urandom(8).hex()
        self.t0 = time.time_ns()
        self.question = question
        self.spans = []

    def span(self, name, op, args, output, parent=None, links=(), tool=None, error=False, ms=None):
        sid = os.urandom(8).hex()
        start = self.spans[-1]["endTimeUnixNano"] if self.spans else self.t0
        start = int(start) + 1000
        dur = int((ms if ms is not None else random.uniform(40, 400)) * 1e6)
        attrs = {"gen_ai.operation.name": op, "blackbox.args": json.dumps(args), "blackbox.output": json.dumps(output)}
        if tool:
            attrs["gen_ai.tool.name"] = tool
        if op == "chat":
            attrs["gen_ai.request.model"] = "my-own-agent"
        self.spans.append({
            "traceId": self.trace_id, "spanId": sid, "parentSpanId": parent or self.root, "name": name,
            "startTimeUnixNano": str(start), "endTimeUnixNano": str(start + dur),
            "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()],
            "links": [{"traceId": self.trace_id, "spanId": l} for l in links if l],
            "status": {"code": 2 if error else 1},
        })
        return sid

    def otlp(self):
        end = self.spans[-1]["endTimeUnixNano"]
        root = {"traceId": self.trace_id, "spanId": self.root, "name": self.question, "startTimeUnixNano": str(self.t0),
                "endTimeUnixNano": end, "attributes": [{"key": "blackbox.question", "value": {"stringValue": self.question}}]}
        return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "my-grocery-agent"}}]},
                                   "scopeSpans": [{"scope": {"name": "my-agent"}, "spans": [root] + self.spans}]}]}


# ------------------------------------------------------------------ the agent
def run_agent(cart, strategy, bug, seed):
    rnd = random.Random(seed)
    question = "Total cost with 8% tax for: " + ", ".join(f"{q} x {item}" for item, q in cart.items())
    tr = Trace(question)
    task = tr.span("task", "chat", {}, {"question": question, "cart": cart, "tax_rate": TAX}, ms=1)
    bad_item = rnd.choice(list(cart)) if bug in ("cents", "wrong_qty") else None

    prices, price_span = {}, {}
    running, run_span = 0.0, task
    for item, qty in cart.items():
        d = tr.span(f"call:get_price", "chat", {"need": item}, {"tool": "get_price", "args": {"item": item}}, links=[task])
        price = STORE[item] * (100 if (bug == "cents" and item == bad_item) else 1)
        p = tr.span("get_price", "execute_tool", {"item": item}, {"item": item, "usd": price}, parent=d, tool="get_price")
        prices[item], price_span[item] = price, p
        if strategy == "running_total":
            q = qty + (2 if (bug == "wrong_qty" and item == bad_item) else 0)
            expr = f"{running} + {price} * {q}"
            d = tr.span("call:calculator", "chat", {"expression": expr}, {"tool": "calculator", "args": {"expression": expr}}, links=[p, run_span, task])
            running = round(running + price * q, 2)
            run_span = tr.span("calculator", "execute_tool", {"expression": expr}, {"value": running}, parent=d, tool="calculator")

    if strategy == "running_total":
        subtotal, sub_span = running, run_span
    else:
        terms = [f"{prices[i]} * {q + (2 if (bug == 'wrong_qty' and i == bad_item) else 0)}" for i, q in cart.items()]
        expr = " + ".join(terms)
        d = tr.span("call:calculator", "chat", {"expression": expr}, {"tool": "calculator", "args": {"expression": expr}}, links=list(price_span.values()) + [task])
        subtotal = round(eval(expr), 2)  # the expression is built above from numbers only
        sub_span = tr.span("calculator", "execute_tool", {"expression": expr}, {"value": subtotal}, parent=d, tool="calculator")
        if strategy == "verify":
            expr2 = " + ".join(f"{q + (2 if (bug == 'wrong_qty' and i == bad_item) else 0)} * {prices[i]}" for i, q in cart.items())
            d = tr.span("call:calculator", "chat", {"expression": expr2}, {"tool": "calculator", "args": {"expression": expr2}}, links=list(price_span.values()) + [task])
            check = round(eval(expr2), 2)
            tr.span("calculator", "execute_tool", {"expression": expr2}, {"value": check, "matches": check == subtotal}, parent=d, tool="calculator")

    if bug == "skip_tax":
        total, tax_span = subtotal, sub_span
    else:
        expr = f"{subtotal} + {subtotal} * {TAX}"
        d = tr.span("call:calculator", "chat", {"expression": expr}, {"tool": "calculator", "args": {"expression": expr}}, links=[sub_span, task])
        total = round(subtotal * (1 + TAX), 2)
        tax_span = tr.span("calculator", "execute_tool", {"expression": expr}, {"value": total}, parent=d, tool="calculator")
    tr.span("final_answer", "chat", {}, {"total_usd": total, "text": f"The total is ${total:,.2f}"}, links=[tax_span])

    expected = round(sum(STORE[i] * q for i, q in cart.items()) * (1 + TAX), 2)
    return tr, total, expected, bad_item


def send(url, payload, success):
    try:
        import certifi  # macOS Python often lacks root certificates
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    req = urllib.request.Request(f"{url}/api/otlp/v1/traces?success={'true' if success else 'false'}",
                                 data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="https://blackbox-flight-recorder.onrender.com")
    ap.add_argument("--strategy", choices=STRATEGIES, default="plan_first")
    ap.add_argument("--bug", choices=BUGS, default="none")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--healthy", type=int, default=0, metavar="N",
                    help="first send N clean runs (random carts and strategies) so Black Box learns this agent's normal")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    for k in range(a.healthy):
        r = random.Random(10_000 + k + random.randrange(10**6))
        c = {i: r.randint(1, 4) for i in r.sample(list(STORE), r.randint(3, 5))}
        st = r.choice(list(STRATEGIES))
        tr, total, expected, _ = run_agent(c, st, "none", k)
        send(url, tr.otlp(), abs(total - expected) < 0.01)
        print(f"healthy run {k + 1}/{a.healthy} sent ({st})")
    seed = a.seed if a.seed is not None else random.randrange(10**6)
    rnd = random.Random(seed)
    cart = {i: rnd.randint(1, 4) for i in rnd.sample(list(STORE), rnd.randint(3, 5))}

    tr, total, expected, bad = run_agent(cart, a.strategy, a.bug, seed)
    ok = abs(total - expected) < 0.01
    print(f"strategy : {a.strategy} ({STRATEGIES[a.strategy]})")
    print(f"bug      : {a.bug} ({BUGS[a.bug]}){f' -> on item {bad!r}' if bad else ''}")
    print(f"answer   : ${total:,.2f}   expected ${expected:,.2f}   -> {'PASS' if ok else 'FAIL'}")
    print(f"spans    : {len(tr.spans)}")
    res = send(url, tr.otlp(), ok)
    for rid in res["runs"]:
        print(f"\nOpen in Black Box: {url}/#/investigate/{rid}")


if __name__ == "__main__":
    main()
