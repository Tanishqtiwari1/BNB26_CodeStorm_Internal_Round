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
- **Model calls avoided / tool calls avoided / execution time not repeated:** reused model and tool steps across saved replays, with their recorded latency. No dollar figures are shown, because model costs aren't tracked.

The **Live Demo** page walks through all ten steps against the live backend: run, fail, detect, root cause, why, checkpoint, patch, re-execute, compare, verify. The suggested repair is derived from the trace (e.g. re-run the faulty tool call), not hard-coded.

## v2 (what is deployed): graph-based debugging of dynamic agents

The v1 agent followed a fixed plan, and its diagnosis model scored steps one at a time. v2 removes both assumptions.

- **A real agent that decides its own steps.** A tool-calling loop where the next call (search hotel, FX, flights, per-diem, taxi, calculator, final answer) is chosen each turn:
  - by a real language model: **Ollama** `qwen2.5:7b` when running locally (`BLACKBOX_SLM`), or **Groq** `openai/gpt-oss-20b` on the hosted site (`GROQ_API_KEY`);
  - or, for the large labelled benchmark, by a deterministic stochastic policy.

  Order, retries, shared lookups and verification calls differ run to run, so **every trace has its own graph shape**.
- **OpenTelemetry tracing.** Every decision and tool call is an OTel span using the GenAI semantic conventions (`gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.request.model`).
  - Control flow comes from span parents; data flow from span links, found by tracing which earlier observation produced each value the model used.
  - `POST /api/otlp/v1/traces` accepts OTLP/HTTP JSON from any instrumented agent.
- **Graph neural network for root cause.** Directional message passing over the trace graph, using only per-step facts (grounding, baseline deviation, retrieval checks, errors, node type, degree). It learns how errors propagate, so it keeps working when the error source moves or the graph shape changes. It's trained with PyTorch; inference is plain NumPy.
- **New drift evaluation:**
  - **Error source moved:** training fault types injected at locations never faulted in training.
  - **New agent behaviour:** a different policy, so graph shapes never seen in training.
- **Dynamic replay.** Restore the checkpoint, patch or re-run the step, and **let the agent re-plan**. Tool calls with unchanged inputs are reused from the recording; new ones are executed. Comparison aligns traces of different shapes.

### v2 results (5,000 dynamic-agent runs; top-1 root-cause localization on runs never used for training)

| Method | Seen faults | Unseen fault types | Error source moved | New agent behaviour |
|---|---|---|---|---|
| **Graph neural network** | **93.1%** | **88.4%** | 86.2% | **93.5%** |
| Gradient boosting + hand-made lineage features (v1 approach) | 89.6% | 86.5% | **88.4%** | 88.5% |
| First-suspicious rule | 65.7% | 84.8% | 78.0% | 67.3% |
| Personalized PageRank (no training) | 58.8% | 76.9% | 69.8% | 59.9% |
| Random | 2.9% | 4.3% | 3.0% | 3.0% |

- **Top-3:** the GNN finds the root cause within its top 3 for 96–100% of runs on every split.
- **Verified repairs:** repairing the #1 suspect fixes **90.9%** of failures, and **98.1%** within 3 replays.
- **Replay cost:** a replay re-executes **34%** of steps on average.
- **Run-failure detection:** AUC 0.745.

### v2 commands
```bash
./.venv/bin/pip install -r requirements.txt -r requirements-train.txt   # + PyTorch for training
./.venv/bin/python -m blackbox.cli all        # generate 5,000 dynamic runs → train GNN/GBM → evaluate → diagnose (~1 min)
./.venv/bin/python -m blackbox.cli data       # regenerate data + diagnoses with the committed model (no PyTorch; used on Render)
./.venv/bin/python -m blackbox.cli all-v1     # the original fixed-plan benchmark
brew install ollama && ollama serve & ollama pull qwen2.5:7b   # real SLM for the live agent (optional)
```

## Live app

- **Home page:** https://blackbox-flight-recorder.onrender.com. It explains the problem with a real recorded run; the hero card's *Replay from root cause* button runs an actual replay.
- **App:** https://blackbox-flight-recorder.onrender.com/app (Overview, Trace Investigation, Replay & Repair, Comparisons, Evaluation, Live Demo, **Connect Your Agent**).

Free tier: the first load can take 30–60 s while the server wakes up.

## Deploy (one click)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Tanishqtiwari1/BNB26_CodeStorm_Internal_Round)

`render.yaml` regenerates the benchmark runs and diagnoses with the committed model (`python -m blackbox.cli data`, no PyTorch needed) and serves the app with uvicorn. Set `GROQ_API_KEY` in the Render dashboard so the live agent uses a real model. GitHub Pages can't host the app because it needs a Python backend; the Pages URL redirects to Render.

## Quick start

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m blackbox.cli data             # 5,000 benchmark runs + diagnoses with the committed model
./.venv/bin/uvicorn blackbox.api:app --port 8000    # API + web UI → http://localhost:8000
./.venv/bin/python -m pytest -q                     # tests (v1 + v2)
```

Real model for the live agent (optional; without one, runs use the labelled benchmark policy):
```bash
ollama serve & ollama pull qwen2.5:7b    # local, used first when running
export GROQ_API_KEY=...                  # hosted fallback (never commit keys)
```

## v1 results (fixed-plan agent, kept for comparison)

The original fixed-plan benchmark (`python -m blackbox.cli all-v1`, `data/metrics_v1.json`): gradient boosting reached 94.0% top-1 on seen and 85.0% on unseen failure types. The v2 numbers above are the ones the deployed app shows.

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

> This section describes the v1 step features. v2 reuses them as node features and adds the GNN over the trace graph (see the v2 section above).

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

> The v1 corpus is described here. v2 uses the same idea with 5,000 dynamic-agent runs and two extra drift splits (`drift_loc`, `drift_topo`); see `blackbox/generate_v2.py`.

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

## The real-agent demo (Live Demo page)

A real model (Groq `openai/gpt-oss-20b` hosted, Ollama `qwen2.5:7b` locally) plans every tool call for: *New York → Paris, 3 nights at Hotel Lumiere, budget $2,460.*

- **Injected, labelled fault:** the flight-price API returns the fare in cents (88,800 instead of 888). This is a simulated tool bug, shown as such in the UI.
- The model trusts the tool and answers **$90,271, over budget**; the task check expects **$2,359, within budget**.
- If no model is reachable, the run falls back to the benchmark policy with a hallucinated hotel price, and the run is labelled with what drove it.

## 60-second judge demo
1. **Live Demo → Start demo** (or *Run all*). The real model runs the trip estimate and fails: $90,271 over budget vs the expected $2,359.
2. **Root cause:** Step 07, `flight_price`, ~99% confidence. **Why:** "Output 88,800 deviates 50σ from the historical baseline (typical ≈ 888)", and every upstream step looks normal. The 3 downstream steps that consumed the bad value are marked as impacted.
3. **Replay from the checkpoint:** 6 steps are reused from the recording; only the tool call and what depends on it re-run, and the model re-plans from there.
4. **Verified repair:** $2,359.20, within budget. The comparison page shows the step-aligned diff and a latency waterfall in which the reused steps cost nothing.
5. *(Optional)* Open **Trace Investigation** on any benchmark run, press ↑/↓ to walk the steps, or reveal the ground-truth label: "Black Box ranked it #1".
6. *(Optional)* Run `python examples/my_agent.py` to send a completely different agent's trace and investigate it live (see below).

## Bring your own agent (OpenTelemetry)

`examples/my_agent.py` is a small grocery-budget agent unrelated to the travel agent, with three strategies (`plan_first`, `running_total`, `verify`) that give different trace graphs, and optional bugs (`cents`, `wrong_qty`, `skip_tax`). It sends standard OTLP/HTTP JSON spans to `/api/otlp/v1/traces`, standard library only:

```bash
python examples/my_agent.py --healthy 5                              # teach Black Box this agent's normal
python examples/my_agent.py --strategy running_total --bug cents     # then break it
```

No terminal needed: the app's **Connect Your Agent** page (`/app#/connect`) offers three ways to try this:
- run the grocery agent from the browser;
- upload a trace file (Black Box's simple JSON format or OTLP JSON), with a refund-bot example (`web/example_trace.json`);
- copy-paste snippets for Python, curl and OpenTelemetry.

The simple format is one JSON object per run: `{"question", "service", "success", "steps": [{"id", "name", "kind", "parents", "args", "output"}]}`. Post it to `POST /api/traces`.

External agents are judged only against **their own** earlier passing runs (the OTLP `service.name`); value baselines switch on after 3 healthy runs, and the investigation page shows which baseline was used.

**Measured locally on this agent** (18 failed runs, 3 strategies × 3 bugs × 2 seeds, after 6 healthy runs): the true root cause is ranked #1 in **9/18**. Results by bug: unit bug 4/6, wrong quantity 3/6, missing tax step 2/6. The model was trained only on the travel workflow, so this is the honest transfer number: it shows the pipeline works on any OTel agent, and that accuracy on a new agent is lower until that agent has its own training data.

## Claims we can make
- Black Box **learns** to localize failure-causing steps from execution traces of a dynamic tool-calling agent: **93.1%** top-1 on held-out runs, **88.4%** on failure types never seen in training, and 86–94% when the error source moves or the agent's behaviour (graph shape) changes. It beats rule-based and PageRank baselines.
- Diagnoses are **explained** with facts from the trace and **verified** by replay: repairing the #1 suspect fixes 90.9% of failures, 98.1% within 3 replays.
- Replay restores the checkpoint and re-executes about **34%** of steps on average, and the agent may re-plan after the patch.
- A real language model drives the live demo, and every step is an **OpenTelemetry** span.
- Any OpenTelemetry-instrumented agent can be **recorded and diagnosed** via OTLP; replay needs an adapter.

**Do not claim:** high accuracy on arbitrary new agents (measured 9/18 on one unfamiliar agent), benchmarking on real-world production failures, or production readiness.

## Known limitations
- **Synthetic benchmark.** Training and evaluation use one reference workflow (travel expense) with injected faults. On an unfamiliar agent, top-1 was 9/18 (see above).
- **Baselines need history.** Value anomalies need earlier healthy runs of the same tool and arguments; a brand-new tool has weaker signals.
- **Missing steps are hard.** When an agent skips a step (e.g. forgets tax), nothing anomalous is recorded at the cause, so the diagnosis lands downstream.
- **Some runs can't be replayed.** Replay needs an adapter that can re-invoke the agent; OTLP/SDK-recorded runs are diagnosis-only.
- **Hosted data resets.** On Render's free tier the database is rebuilt on each deploy, so live counters (replays, verified repairs) start from zero.

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
blackbox/otel.py        OpenTelemetry spans → step graph (SDK + OTLP/HTTP JSON)
blackbox/react_agent.py tool-calling agent: scripted, Ollama and Groq policies
blackbox/faults_v2.py   v2 decision + tool faults
blackbox/graph_model.py GNN + PageRank baselines
blackbox/model_v2.py    v2 training, evaluation, diagnosis
blackbox/replay_v2.py   dynamic replay (agent re-plans after the patch)
examples/my_agent.py    bring-your-own-agent OTLP example
web/                    landing page (landing.*) + app (index.html, app.js, style.css); plain HTML/CSS/JS, no build step
tests/                  end-to-end tests
app.py                  legacy Streamlit dashboard (still works)
```

## API
`GET /api/info` · `GET /api/stats` · `GET /api/replays` · `GET /api/demo/patch/{id}` · `GET /api/runs` · `GET /api/runs/{id}` · `GET /api/runs/{id}/trace` · `GET /api/runs/{id}/diagnosis` · `GET /api/runs/{id}/steps/{sid}/explanation` · `POST /api/runs/{id}/replay` `{sid, mode: repair|patch_output|patch_args, patch}` · `GET /api/runs/{id}/forks` · `GET /api/compare?a=&b=` · `GET /api/metrics` · `POST /api/agent/run` · `POST /api/demo/killer` · `POST /api/otlp/v1/traces` · `POST /api/traces` (simple JSON or OTLP JSON) · `GET /api/connect/options` · `POST /api/connect/sample` `{strategy, bug}`. Interactive docs are at `/docs`.
