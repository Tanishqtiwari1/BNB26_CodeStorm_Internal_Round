"""v2 tests: dynamic tool-calling agent, OpenTelemetry traces, graph models, dynamic replay, demo, API."""
import importlib
import json
import os
import random

import pytest

os.environ["BLACKBOX_LLM"] = "mock"
os.environ["BLACKBOX_DEMO_POLICY"] = "scripted"  # tests never depend on a local model being installed

from blackbox import agent as A
from blackbox import demo
from blackbox import faults_v2 as F2
from blackbox import generate_v2 as G2
from blackbox import model as M
from blackbox import model_v2 as M2
from blackbox import otel
from blackbox import replay as RP
from blackbox.react_agent import ScriptedPolicy, execute
from blackbox.recorder import Recorder


@pytest.fixture(scope="module")
def v2(tmp_path_factory):
    d = tmp_path_factory.mktemp("v2")
    db, model, metrics = str(d / "v2.db"), str(d / "model_v2.joblib"), str(d / "metrics.json")
    G2.generate(1400, db, seed=5)
    M2.train(db, model, epochs=25)
    m = M2.evaluate(db, model, metrics, replay_eval=False)
    import joblib
    return {"db": db, "model": model, "metrics_path": metrics, "metrics": m, "rec": Recorder(db), "bundle": joblib.load(model)}


def _run(rec, ftype=None, split=None):
    q, p = "SELECT run_id, fault_sid FROM runs WHERE parent_run_id IS NULL AND success=0 AND fault_sid IS NOT NULL", []
    if ftype:
        q += " AND fault_type=?"; p.append(ftype)
    if split:
        q += " AND split=?"; p.append(split)
    return rec.db.execute(q + " LIMIT 1", p).fetchone()


# ---------------------------------------------------------------- agent + OpenTelemetry
def test_dynamic_agent_solves_tasks_and_varies_shape():
    shapes = set()
    for seed in range(6):
        t = A.make_task(random.Random(seed))
        steps, final, _, _ = execute(t, ScriptedPolicy(), seed=seed)
        assert A.judge(t, final)[0]
        shapes.add(tuple(s["name"] for s in steps))
        assert steps[0]["kind"] == "input" and steps[-1]["kind"] == "final"
        for s in steps[1:]:
            assert s["parents"], s["sid"]  # every step is connected (data-flow links or control parent)
    assert len(shapes) == 6  # no fixed plan


def test_steps_come_from_otel_spans():
    t = A.make_task(random.Random(2))
    tr = otel.tracer()
    steps, _, _, _ = execute(t, ScriptedPolicy(), seed=3)
    tools = [s for s in steps if s["kind"] in ("tool", "retrieval")]
    assert all(s["parents"][0].endswith("call:" + s["name"]) for s in tools)  # tool span is a child of the decision span
    assert any(len(s["parents"]) > 1 for s in steps if s["name"] == "call:calculator")  # span links = data flow


def test_otlp_ingestion_converts_foreign_traces():
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": "t1", "spanId": "a", "name": "agent", "startTimeUnixNano": "1", "endTimeUnixNano": "9"},
        {"traceId": "t1", "spanId": "b", "parentSpanId": "a", "name": "chat", "startTimeUnixNano": "2", "endTimeUnixNano": "3",
         "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}]},
        {"traceId": "t1", "spanId": "c", "parentSpanId": "b", "name": "lookup", "startTimeUnixNano": "4", "endTimeUnixNano": "6",
         "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
                        {"key": "gen_ai.tool.name", "value": {"stringValue": "lookup"}},
                        {"key": "gen_ai.tool.call.result", "value": {"stringValue": "{\"amount\": 19.99}"}}]}]}]}]}
    out = otel.otlp_json_to_steps(payload)["t1"]["steps"]
    assert [s["kind"] for s in out] == ["llm", "tool"]
    assert out[1]["parents"] == [out[0]["sid"]] and out[1]["output"] == {"amount": 19.99}


# ---------------------------------------------------------------- benchmark + models
def test_drift_splits_exist_and_labels_land(v2):
    rows = v2["rec"].db.execute("SELECT split, fault_type, fault_sid FROM runs WHERE parent_run_id IS NULL").fetchall()
    splits = {r[0] for r in rows}
    assert {"train", "test", "heldout", "drift_loc", "drift_topo"} <= splits
    for sp, ft, sid in rows:
        if sp == "heldout":
            assert ft in F2.HELDOUT_FAULTS
        if ft:
            assert sid  # every stored fault actually landed on a step


def test_gnn_beats_baselines(v2):
    L = v2["metrics"]["localization"]
    for sp in ("test", "drift_topo"):
        assert L[sp]["gnn"]["top1"] > L[sp]["random"]["top1"] + 0.4
        assert L[sp]["gnn"]["top1"] >= L[sp]["pagerank"]["top1"]


def test_diagnosis_ignores_labels(v2):
    rec, b = v2["rec"], v2["bundle"]
    rid, _ = _run(rec)
    before = M.analyze(b, rec.steps(rid))
    rec.db.execute("UPDATE runs SET fault_type=NULL, fault_sid=NULL, fault_json=NULL WHERE run_id=?", (rid,))
    assert M.analyze(b, rec.steps(rid)) == before


# ---------------------------------------------------------------- dynamic replay
def test_replay_repairs_tool_fault_and_reuses_steps(v2):
    rec = v2["rec"]
    rid, sid = _run(rec, "irrelevant_retrieval")
    f = RP.fork(rec, rid, sid, "repair", save=False)
    assert f["success"] and not f["orig_success"]
    assert f["n_reused"] >= [s["sid"] for s in rec.steps(rid)].index(sid)  # everything before the checkpoint is reused
    assert f["n_reexecuted"] < f["n_total"]


def test_replay_patch_decision_output(v2):
    rec = v2["rec"]
    rid, sid = _run(rec, "wrong_arg")
    steps = rec.steps(rid)
    doc = next(s for s in steps if s["kind"] == "retrieval")
    import re
    cur = re.search(r"Standard room: \d+ ([A-Z]{3})", doc["output"]["text"]).group(1)
    f = RP.fork(rec, rid, sid, "patch_output", {"tool": "fx_rate", "args": {"currency": cur}}, save=False)
    assert f["success"]


def test_replay_patch_args_on_decision_is_rejected(v2):
    rec = v2["rec"]
    rid, sid = _run(rec, "wrong_arg")
    with pytest.raises(ValueError):
        RP.fork(rec, rid, sid, "patch_args", {"x": 1}, save=False)


def test_compare_aligns_changed_paths(v2):
    rec = v2["rec"]
    rid, sid = _run(rec, "dropped_field")
    f = RP.fork(rec, rid, sid, "repair", save=True)
    c = RP.compare(rec, rid, f["run_id"])
    assert c["fixed"] and c["first_divergence"]
    assert all(r["status"] in ("same", "changed", "added", "removed") for r in c["rows"] if "status" in r)


# ---------------------------------------------------------------- demo + API
def test_demo_end_to_end(v2):
    rec, b = v2["rec"], v2["bundle"]
    rid = demo.run_killer(rec, prefer_slm=False)
    run = rec.run(rid)
    assert run["agent"] == "react-sim" and not run["success"]
    root = M.analyze(b, rec.steps(rid))["root_cause"]
    assert root["sid"] == run["fault"]["sid"]
    rep = demo.suggested_repair(rec.steps(rid), root["sid"])
    assert rep["patch"]["args"]["expression"].startswith("180*")
    f = RP.fork(rec, rid, rep["sid"], rep["mode"], rep["patch"], save=False)
    assert f["success"]


@pytest.fixture(scope="module")
def client(v2):
    from fastapi.testclient import TestClient
    os.environ.update(BLACKBOX_DB=v2["db"], BLACKBOX_MODEL=v2["model"], BLACKBOX_METRICS=v2["metrics_path"], BLACKBOX_BACKGROUND="0")
    import blackbox.api as api
    importlib.reload(api)
    return TestClient(api.app)


def test_api_v2_flow(client):
    info = client.get("/api/info").json()
    assert info["model_version"] == "v2" and "react-sim" in [a["name"] for a in info["agents"]]
    s0 = client.get("/api/stats").json()
    rid = client.post("/api/demo/killer").json()["run_id"]
    dx = client.get(f"/api/runs/{rid}/diagnosis").json()
    ev = {e["label"]: e for e in dx["root_cause"]["evidence"]}
    assert ev["Ungrounded output"]["observed"] == "245" and "180" in ev["Ungrounded output"]["expected"]
    p = client.get(f"/api/demo/patch/{rid}").json()
    r = client.post(f"/api/runs/{rid}/replay", json={"sid": p["sid"], "mode": p["mode"], "patch": p["patch"]}).json()
    assert r["verified"] and r["n_reused"] > 0
    s1 = client.get("/api/stats").json()
    assert s1["repairs_verified"] == s0["repairs_verified"] + 1
    live = client.post("/api/agent/run", json={"agent": "react-sim", "seed": 7, "fault_type": "unit_mixup"}).json()
    assert client.get(f"/api/runs/{live['run_id']}").json()["agent"] == "react-sim"
    m = client.get("/api/metrics").json()
    assert m["version"] == "v2-graph" and "drift_topo" in m["localization"]


def test_api_otlp_ingest(client):
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": "z9", "spanId": "a", "name": "agent", "startTimeUnixNano": "1", "endTimeUnixNano": "9"},
        {"traceId": "z9", "spanId": "b", "parentSpanId": "a", "name": "search", "startTimeUnixNano": "2", "endTimeUnixNano": "3",
         "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}}, {"key": "gen_ai.tool.name", "value": {"stringValue": "search"}}]}]}]}]}
    ids = client.post("/api/otlp/v1/traces", json=payload).json()["runs"]
    run = client.get(f"/api/runs/{ids[0]}").json()
    assert run["agent"] == "external" and run["n_steps"] == 1
    assert client.get(f"/api/runs/{ids[0]}/diagnosis").status_code == 200
    assert client.post(f"/api/runs/{ids[0]}/replay", json={"sid": run["steps"][0]["sid"]}).status_code == 409


def test_expression_args_grounded_number_by_number():
    from blackbox.features import _match
    assert _match("2.5 * 2 + 1.25", [2.5, 2.0, 1.25], set())
    assert not _match("2.5 * 4 + 1.25", [2.5, 2.0, 1.25], set())  # 4 never observed upstream
    assert _match("0.0 + 2.5 * 1", [2.5], set())  # constants 0 and 1 need no source


def test_bring_your_own_agent_upload_and_sample(v2):
    from blackbox.service import Service
    svc = Service(db=v2["db"], model_path=v2["model"], metrics_path=v2["metrics_path"])
    # uploaded trace: the refund decision uses an amount no tool returned
    ex = json.load(open(os.path.join(os.path.dirname(__file__), "..", "web", "example_trace.json")))
    rid = svc.ingest_simple(ex)["runs"][0]
    a = svc.analysis(rid)
    assert a["root_cause"]["sid"] == "d3" and a["baseline"]["service"] == "support-refund-bot"
    with pytest.raises(ValueError):
        svc.ingest_simple({"steps": [{"name": "x", "parents": ["missing"]}]})
    # sample agent: warm-up gives every item its own price history, so the unit bug is found at the tool call
    r = svc.sample_agent("running_total", "cents", seed=101)
    assert not r["success"] and r["warmup_runs"] > 0
    a = svc.analysis(r["run_id"])
    step = next(s for s in svc.rec.steps(r["run_id"]) if s["sid"] == a["root_cause"]["sid"])
    assert step["name"] == "get_price" and step["args"]["item"] == r["bug_item"]
    assert a["baseline"]["active"]
