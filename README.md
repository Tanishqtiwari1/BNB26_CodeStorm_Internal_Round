# BLACK BOX: AI Agent Flight Recorder

**From Failure to Fix — Without Starting Over.**

`DETECT → EXPLAIN → REPLAY → REPAIR → VERIFY`

> Black Box learns to localize likely failure-causing steps from AI-agent execution traces, explains its diagnosis with evidence from the trace, and lets a developer replay from that step. It re-executes only what depends on the change, then compares the original and fixed runs.

```
AI AGENT FAILED → BLACK BOX FOUND WHERE → EXPLAINED WHY → REPLAYED FROM THAT POINT
→ FIX TESTED → ONLY NECESSARY STEPS RE-RUN → ORIGINAL vs FIXED COMPARED
```

## The product loop (every stage is real functionality)

| Stage | What happens | Where in the UI | Backed by |
|---|---|---|---|
| **DETECT** | The task check flags failed runs; the run model scores failure risk from the trace | Overview metrics, Runs | `judge`, `run_clf` |
| **EXPLAIN** | The likely root-cause step, its confidence (step-model score), and evidence with *expected vs observed* values from the trace | Trace Investigation | `model.analyze` / `explain` |
| **REPLAY** | Restore the checkpoint; re-execute the step and its data-flow descendants; reuse the rest | Replay & Repair → Checkpoint | `replay.fork` |
| **REPAIR** | Re-run the step fresh, patch its output, or patch its arguments (Apply Patch → Run Replay) | Replay & Repair → Repair | `replay.fork(mode=…)` |
| **VERIFY** | Re-judge the repaired run and diff it against the original | Replay & Repair → Verify, Comparisons | `judge`, `replay.compare` |

**Overview metrics are all real counts:**
- **Executions:** recorded runs.
- **Failures detected:** runs that failed the task check.
- **Root causes identified:** failed runs whose top-ranked step scores ≥ 0.5, from stored diagnoses. This is a confidence threshold, not a correctness claim.
- **Replay attempts:** saved replay runs.
- **Repairs verified:** replays where a failed run passes the task check afterwards.
- **Steps avoided:** steps reused instead of re-run, summed across replays.

The **Live Demo** page walks through all ten steps against the live backend: run, fail, detect, root cause, why, checkpoint, patch, re-execute, compare, verify. The demo's patch value is read from the recorded retrieved document ("Standard room: 180 EUR"), not hard-coded.

## Deploy (one click)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Tanishqtiwari1/BNB26_CodeStorm_Internal_Round)

`render.yaml` builds the benchmark and model during deploy (`python -m blackbox.cli all`) and serves the app with uvicorn. GitHub Pages can't host it, because the app needs a Python backend.

## Quick start

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m blackbox.cli all              # generate 5,000 runs → train → evaluate → store diagnoses (~1 min)
./.venv/bin/uvicorn blackbox.api:app --port 8000    # API + web UI → http://localhost:8000
./.venv/bin/python -m pytest -q                     # 20 end-to-end tests
```

Optional, to make the reference agent call a real model:
```bash
export ANTHROPIC_API_KEY=sk-ant-...        # without it the LLM steps use a deterministic offline mock
export BLACKBOX_LLM_MODEL=claude-opus-5-5  # default
export BLACKBOX_LLM=auto                   # auto | anthropic | mock
```

## Results (5,000 recorded runs; evaluated only on runs never used for training)

| Top-1 root-cause localization | Seen failure types | **Unseen** failure types |
|---|---|---|
| **Black Box model** | **94.0%** | **85.0%** |
| Rule: first suspicious step | 88.1% | 78.8% |
| Highest-anomaly step | 38.1% | 15.8% |
| Random step | 4.8% | 5.9% |

- Top-3: 96.8% seen / 87.7% unseen. Failure prediction from the trace alone: AUC 0.904.
- **Verified diagnosis:** repairing the #1 suspect makes 89.3% of failed runs pass; 92.1% pass within 3 replays.
- **Dependency-aware replay** re-executes 48% of steps on average, against 73% for a naive "re-run from the suspect step".

All numbers come from `python -m blackbox.cli all` → `data/metrics.json`, and the UI's Evaluation page reads that same file.

## Problem statement → implementation

| Requirement | Where |
|---|---|
| 1. Capture execution history | `recorder.py`: append-only SQLite log of every step (args, output, timing, errors, **data-flow parents**). `sdk.py` records any Python agent the same way. |
| 2. Learn from successful & failed runs | `model.train`: step-ranking model (failed runs) + run-failure model (all runs); historical baselines are built from successful runs. |
| 3. Identify the problematic step | `model.diagnose` / `model.analyze`: per-step root-cause score and ranking. |
| 4. Explain with evidence | `model.explain`: removes each signal, re-scores, and turns the facts that matter into evidence text. |
| 5. Checkpointed replay | State after step *k* = fold of recorded outputs (event sourcing); `replay.fork` restores it. |
| 6. Alternative paths / fixes | `replay.fork` modes: **repair** (re-run fresh), **patch_output**, **patch_args**. |
| 7. Don't re-run unaffected steps | Only step *k* and its data-flow descendants re-execute; the rest are reused verbatim. |
| 8. Evaluate against known failures | `faults.py` injects one labelled root cause per faulty run; `model.evaluate`. |
| 9. Generalize to unseen failures | 3 fault categories are held out from training entirely (`heldout` split). |
| 10. Compare executions | `replay.diff` / `replay.compare`: step-aligned diff, first divergence, outcome change. |

## Architecture

```
            ┌──────────── agents/ (adapters) ────────────┐
 user task →│ travel-llm: LLM parse → retrieval → LLM     │──► Recorder (SQLite) ──► features.py ──► model.py
            │   extract → tools → LLM answer               │        ▲    (trace-only signals)   (rank + explain)
            │ travel-sim: same DAG, simulated (benchmark)  │        │                               │
            └──────────────────────────────────────────────┘        │                               ▼
                         ▲ re-invokes real step functions      replay.py ◄── service.py ◄── api.py (FastAPI) ◄── web/ (UI)
                         └──────────────────────────────── (descendants only)
```

- `blackbox/agents/` holds adapters: each one supplies an agent's step DAG, task checker and latency policy. Replay re-runs steps through the adapter, so it calls the agent's real functions (and the real LLM, for `travel-llm`). SDK-recorded runs are tagged `external`: they can be diagnosed but not replayed, because no adapter exists to re-invoke them.
- `service.py` is the only layer the API calls. Routes contain no ML logic.

## ML approach

- **Labels for free:** `faults.py` breaks exactly one step per faulty run, so the true root cause is known.
- **Fault-agnostic features only** (`features.py`), computed from the observable trace:
  - Argument grounding: are args traceable to parent outputs? Constant arguments are learned from history.
  - Output grounding: are LLM outputs present in the prompt or context?
  - Deviation from per-tool historical baselines (z-scores).
  - Null fields, and document relevance and length.
  - Lineage: is this the earliest anomaly among the step's ancestors?
  - Blast radius: anomalies downstream.
  - Errors and retries.
- **The model never sees** fault labels, the step's identity (which tool it is), its position, or timing. Timing is excluded because real-API latencies differ from the simulated corpus.
- **Model:** `HistGradientBoostingClassifier`, scored per step and ranked within each run. A second classifier predicts run failure.
- **Baselines** compete on the same traces: first-suspicious rule, highest anomaly, last step, random.

## Dataset & evaluation methodology

`blackbox/generate.py` runs the simulated agent 5,000 times (35% clean, 65% with exactly one injected fault):

| Split | Contents | Used for |
|---|---|---|
| `train` (70%) | clean runs + runs with **training** fault types | training |
| `test` (30%) | clean runs + runs with **training** fault types | "seen" evaluation |
| `heldout` | runs with **held-out** fault types only | "unseen" evaluation |

**Training faults:** wrong_arg, unit_mixup, irrelevant_retrieval, hallucinated_value, dropped_field, wrong_operation.
**Held-out faults (never trained on):** truncated_context, off_by_one, stale_cache.

Splits are assigned per run before training. The test suite verifies that diagnosis output is identical when a run's fault labels are deleted.

## How replay works

1. Load the recorded run and rebuild the agent's plan through its adapter.
2. Compute the chosen step's data-flow descendants.
3. For every step in plan order: if it's not affected, reuse its recorded output; otherwise re-execute it via the agent's real step function (applying the patch at the chosen step).
4. Judge the new final answer, save it as a fork run (`parent_run_id`, `fork_sid`, `fork_mode`), and diff it against the original.

Injected faults elsewhere in the run persist, because only the chosen step changes. Replay randomness is seeded with a stable hash, so results are reproducible.

## The real-agent demo

`travel-llm` is an instrumented agent whose language steps are genuine model calls:
1. **LLM:** parse the request into a plan.
2. **Retrieval:** fetch each hotel's document.
3. **LLM:** extract the room price from the document.
4. **Tools:** FX rate, flights, calculator.
5. **LLM:** write the answer.

Responses are cached in `data/llm_cache.db`, so replays are reproducible. With no API key, a deterministic offline mock reads the same text with regular expressions, and the UI labels these runs **"LLM agent · offline mock"**.

**Scripted demo** (`demo.py`): New York → Paris, 3 nights at Hotel Lumiere, budget $2,460. The extraction step's answer is replaced with 245 EUR; the retrieved document says 180 EUR. This is a simulated hallucination, injected and labelled as such. The agent wrongly answers "over budget".

## 60-second judge demo
1. **Dashboard → ▶ Run the guided demo.** The run fails: the agent says $2,570, over budget; the expected answer is $2,359, within budget.
2. **Root cause:** Step 3, `L0.rate` (LLM extraction), score 99%. **Why:** "245 deviates 6.2σ from this hotel's historical price (≈180)", "245 is not present in the step's input context", "all upstream steps look normal". 7 downstream steps are impacted. In the inspector, the input shows "Standard room: 180 EUR".
3. **Replay from here → Run replay.** FAILED → PASSED: 8 of 12 steps re-executed, 4 reused (a naive re-run would have run 10).
4. **Compare original vs replay.** The first divergence is `L0.rate`; each step is labelled reused, re-run or changed.
5. *(Optional)* **Reveal ground-truth label:** "Black Box ranked it #1".
6. *(Optional)* **Run agent →** inject `truncated_context (never seen in training)` and watch it get localized.

## Claims we can make
- Black Box **learns** to localize failure-causing steps from execution traces: 94% top-1 on held-out runs with seen failure types and **85% on failure categories never seen in training**, beating rule-based baselines.
- Diagnoses are **explained** with facts from the trace and **verified** by replay: 92% of failures are fixed and confirmed within 3 replays.
- Replay re-executes **only the affected steps** (48% on average) through the agent's real step functions.
- Any Python agent can be **recorded and diagnosed** through the SDK; replay needs an adapter.

**Do not claim:** that it debugs arbitrary agents automatically, that it has been benchmarked on real-world agent failures, or production readiness.

## Known limitations
- **Synthetic benchmark.** The model is trained and evaluated on one reference workflow (travel expense). Transfer to other agents is untested.
- **Off-by-one is the weakest category (71%).** When a wrong count coincides with another number in the question, the trace shows no anomaly.
- **The real-LLM path wasn't exercised here** (no API key on the build machine). Mock mode is tested end to end; Anthropic mode is implemented per the SDK documentation.
- **Baselines need history.** Value baselines are per tool and per argument, so brand-new tools have weaker signals.
- **Some runs can't be replayed.** Replay requires a deterministic adapter; SDK-recorded runs are diagnosis-only.

## Project layout
```
blackbox/agent.py       plan DAG + executor (simulated travel agent)
blackbox/agents/        adapters: travel-llm (real LLM), travel-sim (benchmark)
blackbox/llm.py         Anthropic client + offline mock + response cache
blackbox/faults.py      6 training + 3 held-out fault types
blackbox/generate.py    labelled corpus generation and splits
blackbox/recorder.py    flight recorder (SQLite)
blackbox/features.py    trace-only features and historical baselines
blackbox/model.py       models, baselines, evaluation, explanations, analyze()
blackbox/replay.py      checkpointed dependency-aware replay, diff, compare
blackbox/demo.py        scripted demo scenario
blackbox/service.py     application service (used by the API)
blackbox/api.py         FastAPI endpoints + static UI
blackbox/sdk.py         tracer for any Python agent
web/                    frontend (HTML/CSS/JS, no build step; Stitch "Obsidian Telemetry" design system)
tests/                  end-to-end tests
app.py                  legacy Streamlit dashboard (still works)
```

## API
`GET /api/info` · `GET /api/stats` · `GET /api/replays` · `GET /api/demo/patch/{id}` · `GET /api/runs` · `GET /api/runs/{id}` · `GET /api/runs/{id}/trace` · `GET /api/runs/{id}/diagnosis` · `GET /api/runs/{id}/steps/{sid}/explanation` · `POST /api/runs/{id}/replay` `{sid, mode: repair|patch_output|patch_args, patch}` · `GET /api/runs/{id}/forks` · `GET /api/compare?a=&b=` · `GET /api/metrics` · `POST /api/agent/run` · `POST /api/demo/killer`. Interactive docs are at `/docs`.
