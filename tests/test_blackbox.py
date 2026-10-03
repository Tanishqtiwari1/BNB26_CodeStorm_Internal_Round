"""End-to-end tests: corpus, leakage, model, replay, patching, comparison, demo, API.

    ./.venv/bin/python -m pytest -q
"""
import importlib
import os
import random

import pytest

os.environ["BLACKBOX_LLM"] = "mock"  # never call a real API from tests

from blackbox import agent as A
from blackbox import demo
from blackbox import faults as F
from blackbox import features as FT
from blackbox import generate as G
from blackbox import model as M
from blackbox import replay as RP
from blackbox.agents import ReplayUnsupported, get_adapter
from blackbox.agents.travel_llm import _mock_parse
from blackbox.recorder import Recorder


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    d = tmp_path_factory.mktemp("bb")
    db, model, metrics = str(d / "bb.db"), str(d / "model.joblib"), str(d / "metrics.json")
    G.generate(900, db, seed=3)
    M.train(db, model)
    m = M.evaluate(db, model, metrics, replay_eval=False)
    return {"db": db, "model": model, "metrics_path": metrics, "metrics": m, "rec": Recorder(db), "bundle": M.load(model)}


def _faulty_run(rec, ftype=None, success=0):
    where = "parent_run_id IS NULL AND fault_type IS NOT NULL AND success=?"
    params = [success]
    if ftype:
        where += " AND fault_type=?"
        params.append(ftype)
    row = rec.db.execute(f"SELECT run_id, fault_sid FROM runs WHERE {where} LIMIT 1", params).fetchone()
    assert row, f"no run for {ftype}"
    return row


# ---------------------------------------------------------------- agent & corpus
def test_execution_is_deterministic():
    t = A.make_task(random.Random(5))
    a = A.execute(t, rng=random.Random(9))
    b = A.execute(t, rng=random.Random(9))
    assert a == b
    assert A.judge(t, a[-1]["output"])[0]


def test_splits_separate_seen_and_unseen_faults(corpus):
    rows = corpus["rec"].db.execute("SELECT split, fault_type FROM runs WHERE parent_run_id IS NULL").fetchall()
    for split, ft in rows:
        if split == "heldout":
            assert ft in F.HELDOUT_FAULTS
        if split in ("train", "test") and ft:
            assert ft in F.TRAIN_FAULTS
    assert {r[0] for r in rows} >= {"train", "test", "heldout"}


def test_mock_llm_parses_from_question_text():
    rng = random.Random(1)
    for _ in range(25):
        t = A.make_task(rng)
        import json
        p = json.loads(_mock_parse(t["question"]))
        assert p["origin"] == t["origin"] and p["travelers"] == t["travelers"]
        assert [(l["city"], l["hotel"], l["nights"]) for l in p["legs"]] == \
               [(l["city"], l["hotel"], l["nights"]) for l in t["legs"]]
        assert p["budget"] == t["budget"] and p["per_diem"] == t["per_diem"] and p["taxi"] == t["taxi"]


# ---------------------------------------------------------------- leakage
def test_model_features_contain_no_labels_or_identity():
    for f in FT.MODEL_FEATURES:
        assert "fault" not in f and "label" not in f
        assert f not in ("name_code", "pos_ratio", "steps_to_end", "run_len") and not f.startswith("kind_")


def test_diagnosis_ignores_run_level_labels(corpus):
    rec, b = corpus["rec"], corpus["bundle"]
    rid, _ = _faulty_run(rec)
    before = M.analyze(b, rec.steps(rid))
    rec.db.execute("UPDATE runs SET fault_type=NULL, fault_sid=NULL, fault_json=NULL WHERE run_id=?", (rid,))
    after = M.analyze(b, rec.steps(rid))
    assert before == after


# ---------------------------------------------------------------- model quality
def test_model_beats_baselines(corpus):
    L = corpus["metrics"]["localization"]
    for split in ("test", "heldout"):
        assert L[split]["model"]["top1"] > L[split]["random"]["top1"] + 0.3
        assert L[split]["model"]["top1"] >= L[split]["max_anomaly"]["top1"]
    assert L["heldout"]["model"]["n"] > 0


def test_explanation_has_trace_evidence(corpus):
    rec, b = corpus["rec"], corpus["bundle"]
    rid, sid = _faulty_run(rec, "hallucinated_value")
    a = M.analyze(b, rec.steps(rid))
    assert a["root_cause"]["sid"] == sid
    signals = {e["signal"] for e in a["root_cause"]["evidence"]}
    assert "out_grounding" in signals


# ---------------------------------------------------------------- replay
def test_replay_reexecutes_only_descendants(corpus):
    rec = corpus["rec"]
    rid, sid = _faulty_run(rec, "hallucinated_value")
    run, steps = rec.run(rid), rec.steps(rid)
    plan = A.build_plan(run["task"])
    expect = {sid} | A.descendants(plan, sid)
    f = RP.fork(rec, rid, sid, "repair", save=False)
    assert set(f["rerun"]) == expect
    orig = {s["sid"]: s for s in steps}
    for s in f["steps"]:
        if s["sid"] not in expect:
            assert s["reused"] and s["output"] == orig[s["sid"]]["output"]
        else:
            assert not s["reused"]
    assert f["success"] and not f["orig_success"]
    assert f["diff"]["first_divergence"] == sid


def test_replay_elsewhere_keeps_fault(corpus):
    rec = corpus["rec"]
    rid, sid = _faulty_run(rec, "hallucinated_value")
    other = next(s["sid"] for s in rec.steps(rid) if s["sid"] not in ({sid} | A.descendants(A.build_plan(rec.run(rid)["task"]), sid)))
    f = RP.fork(rec, rid, other, "repair", save=False)
    assert not f["success"]


def test_patch_with_falsy_values_is_respected(corpus):
    rec = corpus["rec"]
    rid, _ = _faulty_run(rec, success=1) if False else (rec.db.execute(
        "SELECT run_id FROM runs WHERE parent_run_id IS NULL AND success=1 LIMIT 1").fetchone()[0], None)
    steps = rec.steps(rid)
    calc = next(s for s in steps if s["role"] == "calc_hotel_local")
    f = RP.fork(rec, rid, calc["sid"], "patch_args", {"op": "mul", "xs": [0, 0]}, save=False)
    assert next(s for s in f["steps"] if s["sid"] == calc["sid"])["output"] == {"value": 0.0}
    g = RP.fork(rec, rid, calc["sid"], "patch_output", {}, save=False)
    assert next(s for s in g["steps"] if s["sid"] == calc["sid"])["output"] == {}
    assert not g["success"]  # downstream steps can't read a value from {}


def test_replay_is_reproducible(corpus):
    rec = corpus["rec"]
    rid, sid = _faulty_run(rec)
    a = RP.fork(rec, rid, sid, "repair", save=False)
    b = RP.fork(rec, rid, sid, "repair", save=False)
    assert [s["latency_ms"] for s in a["steps"]] == [s["latency_ms"] for s in b["steps"]]


def test_compare_saved_fork(corpus):
    rec = corpus["rec"]
    rid, sid = _faulty_run(rec, "unit_mixup")
    f = RP.fork(rec, rid, sid, "repair", save=True)
    c = RP.compare(rec, rid, f["run_id"])
    assert c["first_divergence"] == sid and c["fixed"]
    assert c["n_rerun"] == f["n_reexecuted"] and c["n_reused"] == f["n_reused"]


def test_external_runs_are_diagnosable_not_replayable(tmp_path, corpus):
    from blackbox.sdk import Tracer
    t = Tracer(str(tmp_path / "ext.db"))
    with t.run("refund for order 42?") as r:
        a = r.llm("parse", {"question": "refund for order 42?"}, lambda a: {"order_id": 42})
        b = r.tool("lookup", {"order_id": 42}, lambda a: {"amount": 19.99}, parents=[a])
        r.final("answer", {"total": 19.99}, lambda a: {"total_usd": a["total"]}, parents=[b])
        r.finish(True)
    steps = t.rec.steps(t.last_run_id)
    assert len(M.analyze(corpus["bundle"], steps)["steps"]) == 3
    with pytest.raises(ReplayUnsupported):
        RP.fork(t.rec, t.last_run_id, "lookup#1", "repair")


# ---------------------------------------------------------------- real-agent demo
def test_killer_demo_end_to_end(corpus):
    rec, b = corpus["rec"], corpus["bundle"]
    rid = demo.run_killer(rec)
    run = rec.run(rid)
    assert run["agent"] == "travel-llm" and not run["success"]
    a = M.analyze(b, rec.steps(rid))
    assert a["root_cause"]["sid"] == "L0.rate"
    f = RP.fork(rec, rid, "L0.rate", "repair", save=False)
    assert f["success"] and f["n_reexecuted"] == 8 and f["n_reused"] == 4
    p = RP.fork(rec, rid, "L0.rate", "patch_output", {"amount": 180.0, "currency": "EUR"}, save=False)
    assert p["success"]


def test_llm_agent_matches_sim_agent_when_clean():
    t = A.make_task(random.Random(21))
    sim = get_adapter("travel-sim").execute(t)
    llm = get_adapter("travel-llm").execute(t)
    assert sim[-1]["output"]["total_usd"] == llm[-1]["output"]["total_usd"]


# ---------------------------------------------------------------- API
@pytest.fixture(scope="module")
def client(corpus):
    from fastapi.testclient import TestClient
    os.environ.update(BLACKBOX_DB=corpus["db"], BLACKBOX_MODEL=corpus["model"], BLACKBOX_METRICS=corpus["metrics_path"])
    import blackbox.api as api
    importlib.reload(api)
    return TestClient(api.app)


def test_api_flow(client):
    assert client.get("/api/info").json()["llm"]["provider"] == "mock"
    s = client.get("/api/stats").json()
    assert s["runs"] > 0 and s["failed"] > 0
    runs = client.get("/api/runs", params={"status": "failed", "limit": 5}).json()
    assert runs["total"] > 0 and len(runs["runs"]) == 5
    rid = client.post("/api/demo/killer").json()["run_id"]
    run = client.get(f"/api/runs/{rid}").json()
    assert run["replayable"] and run["label"]["fault_sid"] == "L0.rate"
    assert len(client.get(f"/api/runs/{rid}/trace").json()["steps"]) == run["n_steps"]
    dx = client.get(f"/api/runs/{rid}/diagnosis").json()
    assert dx["root_cause"]["sid"] == "L0.rate" and dx["root_cause"]["evidence"]
    ex = client.get(f"/api/runs/{rid}/steps/L0.rate/explanation").json()
    assert ex["rank"] == 1
    r = client.post(f"/api/runs/{rid}/replay", json={"sid": "L0.rate", "mode": "patch_output",
                                                    "patch": {"amount": 180, "currency": "EUR"}}).json()
    assert r["success"] and r["n_reexecuted"] == 8
    r2 = client.post(f"/api/runs/{rid}/replay", json={"sid": "L0.rate", "mode": "patch_args",
                                                     "patch": {"hotel": "Hotel Lumiere", "context": "Standard room: 180 EUR per night.", "model": "x"}}).json()
    assert r2["success"]
    c = client.get("/api/compare", params={"a": rid, "b": r["run_id"]}).json()
    assert c["fixed"] and c["first_divergence"] == "L0.rate"
    assert len(client.get(f"/api/runs/{rid}/forks").json()["runs"]) == 2
    live = client.post("/api/agent/run", json={"agent": "travel-llm", "seed": 4, "fault_type": "stale_cache"}).json()
    assert client.get(f"/api/runs/{live['run_id']}").json()["agent"] == "travel-llm"
    assert "localization" in client.get("/api/metrics").json()


def test_api_errors(client):
    assert client.get("/api/runs/doesnotexist").status_code == 404
    rid = client.post("/api/demo/killer").json()["run_id"]
    assert client.post(f"/api/runs/{rid}/replay", json={"sid": "nope"}).status_code == 404
    assert client.post(f"/api/runs/{rid}/replay", json={"sid": "L0.rate", "mode": "patch_output"}).status_code == 422
    assert client.post("/api/agent/run", json={"fault_type": "bogus"}).status_code == 422


# ---------------------------------------------------------------- USP loop: detect → explain → replay → repair → verify
def test_usp_loop_metrics_are_real(client, corpus):
    s0 = client.get("/api/stats").json()
    rid = client.post("/api/demo/killer").json()["run_id"]
    p = client.get(f"/api/demo/patch/{rid}").json()
    assert p["patch"] == {"amount": 180.0, "currency": "EUR"} and "180 EUR" in p["source"]  # read from the recorded document
    r = client.post(f"/api/runs/{rid}/replay", json={"sid": p["sid"], "mode": "patch_output", "patch": p["patch"]}).json()
    assert r["verified"] and r["reexecution_error"] is None and "L0.rate" in r["changed"]
    s1 = client.get("/api/stats").json()
    assert s1["replay_attempts"] == s0["replay_attempts"] + 1
    assert s1["repairs_verified"] == s0["repairs_verified"] + 1
    assert s1["steps_avoided"] == s0["steps_avoided"] + r["n_reused"]
    assert s1["failures_detected"] == s0["failures_detected"] + 1
    assert 0 <= s1["root_causes_identified"] <= s1["failures_analyzed"] <= s1["failures_detected"]
    reps = client.get("/api/replays", params={"limit": 5}).json()["runs"]
    assert reps[0]["run_id"] == r["run_id"] and reps[0]["parent_success"] == 0 and reps[0]["success"] == 1


def test_reexecution_error_is_reported(client):
    rid = client.post("/api/demo/killer").json()["run_id"]
    r = client.post(f"/api/runs/{rid}/replay", json={"sid": "L0.rate", "mode": "patch_output", "patch": {}}).json()
    assert not r["verified"] and r["reexecution_error"]["sid"] == "L0.fx"
    assert "currency" in r["reexecution_error"]["error"]


def test_evidence_has_expected_and_observed(client):
    rid = client.post("/api/demo/killer").json()["run_id"]
    rc = client.get(f"/api/runs/{rid}/diagnosis").json()["root_cause"]
    obs = {e["label"]: e for e in rc["evidence"]}
    assert obs["Ungrounded output"]["observed"] == "245" and "180" in obs["Ungrounded output"]["expected"]
    if "Value anomaly" in obs:  # needs a historical baseline for this hotel in the (small) test corpus
        assert "historical baseline" in obs["Value anomaly"]["expected"]
