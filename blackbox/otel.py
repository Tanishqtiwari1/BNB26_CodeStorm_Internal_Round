"""OpenTelemetry integration.

Agents emit standard OpenTelemetry spans (GenAI semantic conventions:
gen_ai.operation.name = "chat" | "execute_tool", gen_ai.tool.name,
gen_ai.request.model, gen_ai.system). Black Box turns spans into its step
graph:

  * span parent/child  -> control-flow edge (LLM call -> the tool it invoked)
  * span links         -> data-flow edges (step consumed a value produced by
                          an earlier span)

Two entry points:
  CollectingExporter   in-process SpanExporter used by our own agents
  otlp_json_to_steps   OTLP/HTTP JSON payloads from *any* instrumented agent
"""
import json
import threading
from collections import defaultdict

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

KIND_ATTR = "blackbox.kind"


class CollectingExporter(SpanExporter):
    """Buffers finished spans per trace id until the agent run collects them."""

    def __init__(self):
        self._spans = defaultdict(list)
        self._lock = threading.Lock()

    def export(self, spans):
        with self._lock:
            for s in spans:
                self._spans[s.context.trace_id].append(s)
        return SpanExportResult.SUCCESS

    def pop(self, trace_id):
        with self._lock:
            return self._spans.pop(trace_id, [])

    def shutdown(self):
        pass


_provider, _exporter = None, None


def tracer():
    global _provider, _exporter
    if _provider is None:
        _exporter = CollectingExporter()
        _provider = TracerProvider(resource=Resource.create({"service.name": "blackbox-agent"}))
        _provider.add_span_processor(SimpleSpanProcessor(_exporter))
    return _provider.get_tracer("blackbox.agent")


def collect(trace_id):
    return _exporter.pop(trace_id) if _exporter else []


def _attr(span_attrs, key, default=None):
    v = span_attrs.get(key, default)
    if isinstance(v, str) and key in ("blackbox.args", "blackbox.output"):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return {"text": v}
    return v


def _kind(attrs, name):
    k = attrs.get(KIND_ATTR)
    if k:
        return k
    op = attrs.get("gen_ai.operation.name", "")
    if op in ("chat", "text_completion", "generate_content"):
        return "llm"
    if op == "execute_tool":
        return "retrieval" if "search" in str(attrs.get("gen_ai.tool.name", name)) or "retriev" in name else "tool"
    return "tool"


def sdk_spans_to_steps(spans):
    """Convert finished SDK spans of one trace into Black Box step records."""
    spans = [s for s in spans if s.parent is not None or s.attributes.get(KIND_ATTR)]  # drop the run's root span
    spans.sort(key=lambda s: s.start_time)
    sid_of = {s.context.span_id: s.attributes.get("blackbox.sid", f"s{i:02d}.{s.name}") for i, s in enumerate(spans)}
    steps = []
    for i, s in enumerate(spans):
        a = dict(s.attributes)
        parents = [sid_of[l.context.span_id] for l in s.links if l.context.span_id in sid_of]
        if s.parent is not None and s.parent.span_id in sid_of and sid_of[s.parent.span_id] not in parents:
            parents.insert(0, sid_of[s.parent.span_id])
        steps.append({"idx": i, "sid": sid_of[s.context.span_id], "kind": _kind(a, s.name), "name": a.get("blackbox.name", s.name),
                      "role": a.get("blackbox.role", a.get("blackbox.name", s.name)), "parents": parents,
                      "args": _attr(a, "blackbox.args", {}), "output": _attr(a, "blackbox.output", {}),
                      "latency_ms": round((s.end_time - s.start_time) / 1e6, 1) if a.get("blackbox.latency_ms") is None
                      else float(a["blackbox.latency_ms"]),
                      "error": a.get("blackbox.error") or None, "retries": int(a.get("blackbox.retries", 0)),
                      "reused": bool(a.get("blackbox.reused", False))})
    return steps


def _otlp_val(v):
    for k in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if k in v:
            return int(v[k]) if k == "intValue" else v[k]
    if "arrayValue" in v:
        return [_otlp_val(x) for x in v["arrayValue"].get("values", [])]
    return None


def otlp_json_to_steps(payload):
    """OTLP/HTTP JSON (`resourceSpans`) -> {trace_id: [steps]} for any instrumented agent."""
    by_trace = defaultdict(list)
    for rs in payload.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []):
            for sp in ss.get("spans", []):
                by_trace[sp["traceId"]].append(sp)
    out = {}
    for tid, spans in by_trace.items():
        spans.sort(key=lambda s: int(s.get("startTimeUnixNano", 0)))
        attrs = {s["spanId"]: {a["key"]: _otlp_val(a["value"]) for a in s.get("attributes", [])} for s in spans}
        roots = [s for s in spans if not s.get("parentSpanId")]
        keep = [s for s in spans if s.get("parentSpanId") or attrs[s["spanId"]].get(KIND_ATTR)] or spans
        sid = {s["spanId"]: attrs[s["spanId"]].get("blackbox.sid", f"s{i:02d}.{s['name']}") for i, s in enumerate(keep)}
        steps = []
        for i, s in enumerate(keep):
            a = attrs[s["spanId"]]
            parents = [sid[l["spanId"]] for l in s.get("links", []) if l.get("spanId") in sid]
            if s.get("parentSpanId") in sid and sid[s["parentSpanId"]] not in parents:
                parents.insert(0, sid[s["parentSpanId"]])
            args = a.get("blackbox.args") or a.get("gen_ai.tool.call.arguments") or a.get("gen_ai.prompt") or {}
            out_v = a.get("blackbox.output") or a.get("gen_ai.tool.call.result") or a.get("gen_ai.completion") or {}
            parse = lambda v: (json.loads(v) if isinstance(v, str) and v[:1] in "[{" else ({"text": v} if isinstance(v, str) else v))
            err = None
            if s.get("status", {}).get("code") in (2, "STATUS_CODE_ERROR"):
                err = "exception"
            steps.append({"idx": i, "sid": sid[s["spanId"]], "kind": _kind(a, s["name"]),
                          "name": a.get("gen_ai.tool.name") or s["name"], "role": a.get("gen_ai.tool.name") or s["name"],
                          "parents": parents, "args": parse(args), "output": parse(out_v),
                          "latency_ms": round((int(s.get("endTimeUnixNano", 0)) - int(s.get("startTimeUnixNano", 0))) / 1e6, 1),
                          "error": err, "retries": 0, "reused": False})
        question = next((attrs[r["spanId"]].get("blackbox.question") or r.get("name") for r in roots), "")
        out[tid] = {"question": question, "steps": steps}
    return out
