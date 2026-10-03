# PROJECT_HANDOFF.md: BLACK BOX (AI Agent Flight Recorder)

> Hand-off for a new Claude Code session. Read this file first, then `README.md`.
> Last updated: 2026-10-03. Owner: Tanishq Tewari (B.Tech 3rd yr, Manipal University Jaipur), team with Nehal Shah.
> Context: GDG on Campus (Fr. Conceicao Rodrigues College of Engineering) hackathon, **internal round**, AI/ML track, problem statement **#2 "Black Box: A Flight Recorder for AI Agents"**. The team was assigned this, their first preference.

---

## 0. TL;DR for the next session

- **The backend, ML and replay engine work and are tested (20/20 tests pass). Do not rewrite them.** Build on `blackbox/service.py` and `blackbox/api.py`.
- **Next job: a from-scratch UI redesign** (section 5). The current `web/` frontend works and is wired to real data, but the user wants a new, interactive, human-designed UI that doesn't look AI-generated. Keep the API contract and replace `web/`.
- **Absolute rules:** no fake data or metrics, no fabricated explanations, no disconnected buttons, no leaking fault labels into the model.
- **Run it:** `./.venv/bin/uvicorn blackbox.api:app --port 8000` → http://localhost:8000
- **Rebuild data and model:** `./.venv/bin/python -m blackbox.cli all` (~1 min).
- **Not a git repo yet.** Suggest `git init` and a first commit before big changes, but ask the user first.

---

## 1. PROJECT OVERVIEW

### What Black Box is
A debugging system for AI agents. It **records** every step of an agent execution (LLM calls, retrievals, tool calls, final answer) along with data-flow dependencies, **learns** to localize the step most likely to have caused a failure, **explains** why with evidence from the trace, and lets the developer **replay from that step's checkpoint**. Replay re-executes only the step and the steps that depend on it, then **compares** original vs repaired runs to verify the fix.

### Official problem statement (verbatim requirements, GDG PDF "Problem Statements.pdf", AI/ML #2)
> Develop Black Box, an AI-powered debugging system that learns from agent execution traces to identify suspicious or failure-causing steps in an agent's execution. The system should capture observable execution history and train a model to recognize patterns associated with successful and failed runs. When a new execution fails, the system should identify the most likely problematic step and allow that point to be investigated through replay and alternative execution paths. The system must demonstrate that its learned diagnosis can be evaluated against known failures and that proposed fixes can be tested without unnecessarily repeating unaffected parts of the execution.

Key features listed by the organisers:
1. **Execution Data:** capture relevant information from successful and failed runs.
2. **Failure Diagnosis:** train a model to identify anomalous or failure-causing steps.
3. **Failure Explanation:** evidence from the execution history supporting the diagnosis.
4. **Checkpointed Replay:** investigate executions from intermediate states.
5. **Alternative Execution:** test changes to a suspected step and observe the effect on the outcome.
6. **Model Evaluation:** measure ability to localize known failures and generalize to unseen failures.
7. **Trace Comparison:** compare executions to understand how changes affected the outcome.

**Requirement → implementation map** (all implemented):

| # | Requirement | Implementation |
|---|---|---|
| 1 | Capture history | `recorder.py` (SQLite), `sdk.py` (any Python agent) |
| 2 | Learn from success and failure | `model.train`: step ranker (failed runs) + run-failure classifier (all runs); baselines come from successful runs |
| 3 | Identify the problematic step | `model.diagnose` / `model.analyze` |
| 4 | Explain with evidence | `model.explain`: occlusion over signal groups → evidence text with expected/observed values |
| 5 | Checkpointed replay | event-sourced state; `replay.fork` |
| 6 | Alternative execution | `replay.fork` modes `repair` / `patch_output` / `patch_args` |
| 7 | No unnecessary re-execution | only the step and its data-flow descendants re-run |
| 8 | Evaluate against known failures | fault injection gives labelled root causes; `model.evaluate` |
| 9 | Generalize to unseen failures | 3 held-out fault types, never trained on |
| 10 | Compare executions | `replay.diff` / `replay.compare` |

### Core objective
Win the hackathon with a technically honest, working system: a real learned diagnosis (not hard-coded), real replay, strong evaluation including unseen failures, and a clear demo.

### USP
**"From Failure to Fix — Without Starting Over."**
Loop: **DETECT → EXPLAIN → REPLAY → REPAIR → VERIFY.**
Positioning, exact wording: *"Observability tells you what happened. Black Box is designed to turn agent observability into an actionable debugging workflow."* **Never claim** it is the only tool that does this, that it debugs arbitrary agents automatically, or that it's production-ready.

### Main user journey
Agent run fails → open the run → Black Box shows the **likely root-cause step** + confidence + evidence (expected vs observed) + downstream impact → **Replay from this step** → choose repair (re-run fresh / patch output / patch args) → **Apply patch → Run replay** → only affected steps re-run → **Verify**: original FAILED vs repaired SUCCESS, with step diff, re-executed vs reused counts.

---

## 2. CURRENT ARCHITECTURE

```
 user task ─► agents/ adapter ─► agent.execute (plan DAG) ─► Recorder (SQLite) ─► features.py ─► model.py
              travel-llm | travel-sim                             ▲                (trace-only)   (rank, explain, analyze)
                    ▲  re-invokes real step functions             │                                     │
                    └──────────── replay.fork (descendants only) ◄┴── service.py ◄── api.py (FastAPI) ◄── web/ (SPA)
```

### Frontend: `web/` (to be redesigned)
- Plain HTML/CSS/JS SPA, no build step, hash router. Served by FastAPI at `/` and `/static/*`.
- Files: `web/index.html` (shell), `web/style.css` (Stitch "Obsidian Telemetry" tokens), `web/app.js` (all views, ~660 lines).
- Current routes: `#/` overview · `#/runs` · `#/investigate[/:id]` (alias `#/run/:id`) · `#/repair[/:id]?sid=&mode=` (alias `#/replay/:id`) · `#/comparisons` · `#/compare/:a/:b` · `#/eval` · `#/demo` · `#/about`.
- Fonts: Geist + JetBrains Mono (Google Fonts; falls back offline).
- Legacy: `app.py` is an older Streamlit dashboard. It still works (`streamlit run app.py`) but is not the main UI and can be deleted later. Ask the user first.

### Backend
- **FastAPI** `blackbox/api.py`: thin routes that call `blackbox/service.py`, with error mapping KeyError→404, ReplayUnsupported→409, ValueError→422, LLMError→502.
- **Service layer** `blackbox/service.py`: the *only* thing the API calls. Owns the Recorder and the model bundle (hot-reloads when `data/model.joblib` changes), caches analyses, stores per-model diagnoses, and runs a background thread on startup to diagnose any undiagnosed failed runs (`BLACKBOX_BACKGROUND=1`, the default).

### Database: SQLite `data/blackbox.db` (~32 MB)
- `runs(run_id, question, task_json, final_json, success, expected_json, fault_type, fault_sid, fault_json, split, parent_run_id, fork_sid, fork_mode, n_reexecuted, created, agent, meta_json)`
  - `split` ∈ `train | test | heldout | demo | live | fork | external`
  - `agent` ∈ `travel-sim | travel-llm | external` (NULL means travel-sim, from older rows)
  - fault columns are **labels for training/eval/UI reveal only**
  - forks have `parent_run_id`
- `steps(run_id, idx, sid, kind, name, role, parents_json, args_json, output_json, latency_ms, error, retries, reused)`; primary key `(run_id, idx)`. `kind` ∈ `llm | retrieval | tool | final`.
- `diagnoses(run_id, model_tag, top_sid, top_name, top_score, p_fail)`: cached model output, keyed by the model's `trained_at` tag.
- Migrations are automatic in `Recorder.__init__` (ALTER TABLE adds `agent`, `meta_json`).
- LLM response cache: `data/llm_cache.db` (only created in Anthropic mode).

### ML / model (`blackbox/features.py`, `blackbox/model.py`)
- **Step model:** `HistGradientBoostingClassifier` (balanced classes), scored per step and ranked per run. Trained on failed **train-split** runs only; the label is "this step is the injected fault step".
- **Run model:** `HistGradientBoostingClassifier` on run-level aggregates; predicts failure (AUC 0.904).
- **Features (`MODEL_FEATURES`)**, all fault-agnostic and computed only from the trace:
  - arg grounding: are args traceable to parent outputs? Literal constant args like `fx_rate.quote`, `db_lookup.table` are learned from successful history and excluded.
  - output grounding: are LLM output numbers present in the prompt/context?
  - `value_z`: deviation from the per-tool/per-arg-signature historical baseline (log-space z).
  - null fields, retrieval relevance, `doc_len_z`.
  - lineage: `lineage_root`, `anc_susp`, `max_anc_z`, `anc_max_score`, `earliest_suspicious`, `n_suspicious_before`.
  - blast radius: `desc_mean_z`, `frac_desc_anom`, `desc_max_score`, `n_desc`.
  - error/retries, combined `local_score`, `n_local_signals`.
- **Deliberately excluded:** step identity (`name_code`, `kind_*`), position (`pos_ratio`, `steps_to_end`, `run_len`) and `latency_z`. Real API latency differs from the simulated corpus, and no fault affects timing.
- **Explanations (`explain`):**
  - For local signals, neutralise the raw signal in the trace, recompute all derived features (`features.derive` + `rows_from_signals`) and re-score. Structural groups are overridden directly.
  - Also reports `joint_local` (all local signals removed together), because overlapping signals hide each other when removed one at a time.
  - Evidence items carry `signal`, `label` ("Value anomaly", "Argument mismatch", "Ungrounded output", "Missing field", "Retrieval inconsistency", "Downstream impact", "Upstream healthy", "Step error"), `text`, and optional `expected` / `observed`.
- **`analyze(bundle, steps)`** returns everything the UI needs: `p_fail`, `root_cause`, `suspects` (top-3 with evidence), `steps` (score, rank, flags, suspicious, children), `impacted`, `impacted_anomalous`, `upstream{steps, anomalous, healthy}`.
- **Baselines:** `random`, `last_step`, `max_anomaly`, and `first_suspicious` (flagged steps in order, the rest shuffled; this tie-break is deliberately fair, see §4).

### Agent execution (`blackbox/agent.py`, `blackbox/world.py`, `blackbox/agents/`)
- **Domain:** travel-expense estimation ("Estimate the total USD cost for N travelers flying from X: k nights at Hotel H in City C, …, and the flight back. Include per-diem meals / airport taxis. Is it within the $B budget?").
- `world.py`: deterministic data (hotels with nightly rate / city tax / breakfast, FX rates, flight prices via hash, per-diem, taxi, hotel documents).
- `agent.build_plan(task)`: builds a DAG of `Step(sid, kind, name, parents, derive, run, role)`. 10–45 steps.
  - Step ids: `parse`, `L{i}.doc`, `L{i}.rate`, `L{i}.fx`, `L{i}.hotel_local`, `L{i}.hotel_usd`, `L{i}.hotel_rooms`, `L{i}.flight`, `L{i}.flight_all`, `L{i}.pd`, `L{i}.pd_total`, `L{i}.taxi`, `L{i}.taxi_usd`, `L{i}.total`, `R.flight`, `R.flight_all`, `T.total`, `T.check`, `T.final`, `X{k}.reflect` (distractors).
- `agent.execute(task, fault, rng, start_pv, rerun, overrides, plan_fn, latency_fn)`: runs the plan, injects the fault between `derive` and `run` (args) or after `run` (output), records a step dict per step. Also handles replay (reuse non-rerun steps).
- `agent.judge(task, final)`: the "task check". The total must be within 2% of ground truth and the budget verdict must match. Ground truth = clean simulated run.
- **Adapters (`blackbox/agents/`):**
  - `travel-sim`: deterministic simulated agent (benchmark corpus), simulated latency.
  - `travel-llm`: same DAG, but `parse_task`, `extract_rate` and `final_answer` are real LLM calls via `blackbox/llm.py`. Real wall-clock latency in Anthropic mode; simulated latency in mock mode.
  - `external`: runs recorded through the SDK. Diagnosable, **not replayable** (no adapter).
- **LLM client (`blackbox/llm.py`):**
  - `BLACKBOX_LLM=auto|anthropic|mock`; auto uses Anthropic if `ANTHROPIC_API_KEY` is set, otherwise mock.
  - Model: `BLACKBOX_LLM_MODEL`, default `claude-opus-5-5`.
  - Uses `client.beta.messages.create(..., output_config={"effort":"low"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")` and handles refusals and SDK errors → `LLMError`.
  - Responses cached in SQLite.
  - The mock parses the *question text* with regex; it does not read the task spec.

### Fault injection (`blackbox/faults.py`)
One fault per faulty run; labels go on the run row only.
- **Training faults:** `wrong_arg`, `unit_mixup`, `irrelevant_retrieval`, `hallucinated_value`, `dropped_field`, `wrong_operation`.
- **Held-out faults (never trained on):** `truncated_context`, `off_by_one`, `stale_cache`.
- `params.value` can pin a hallucinated value (used by the scripted demo).

### Trace recorder (`blackbox/recorder.py`)
- Append-only SQLite with automatic migrations. Checkpoint state at step *k* = the fold of recorded outputs 0..k (event sourcing), so there are no snapshots.
- Key methods: `save_run`, `run`, `steps`, `list_runs(status, split, agent, forks, parent, q, limit, offset, forks_only)` (parameterised SQL; returns `n_steps`, `duration_ms`, `parent_success`), `stats`, `replay_stats`, `save_diagnosis` / `get_diagnosis` / `undiagnosed_failed` / `diagnosis_stats`, `checkpoint`.
- Thread-safe via `RLock` (`check_same_thread=False`).
- `runs_df` takes a raw WHERE string. **Internal use only, never pass user input.**

### Replay engine (`blackbox/replay.py`)
- `fork(rec, run_id, sid, mode, patch, save=True)`:
  1. Load the run, get its adapter via `run.agent`, rebuild the plan, and check the recorded step order matches.
  2. `rerun = {sid} ∪ descendants(sid)`.
  3. `adapter.execute(..., start_pv=recorded, rerun=rerun, overrides=...)`.
  4. Judge the result, diff it, and save it as a fork run.
- Injected faults elsewhere in the run persist; the fault at `sid` itself is removed when replaying that step.
- RNG seeded with `zlib.crc32(run_id|sid|mode)` for reproducibility.
- Patches are applied by key presence (`"output" in ov`), so falsy patches like `{}` work.
- `diff(a, b)` returns rows `{idx, sid, name, kind, changed, reused, rerun, before, after, args_before, args_after}`, plus `first_divergence` and `n_changed`.
- `compare(rec, a, b)` returns the diff plus `a`, `b`, `expected`, `n_rerun`, `n_reused`, `fixed`.
- `service.replay` adds `reexecution_error` (the first re-executed step that raised), `changed` (list of sids) and `verified` (orig failed and new succeeded).

### APIs (`blackbox/api.py`, OpenAPI docs at `/docs`)
| Method | Path | Returns |
|---|---|---|
| GET | `/api/info` | llm provider/model, agents, train/heldout fault lists + descriptions, model_ready |
| GET | `/api/stats` | runs, passed, failed, failure_rate, failures_detected, failures_analyzed, root_causes_identified (top score ≥ 0.5), identified_threshold, avg_diagnosis_score, replay_attempts, repairs_verified, steps_avoided, steps_reexecuted, replay_steps_total, avg_steps, avg_duration_ms, recent_failed[8] (with root_sid/name/score), recent_replays[5] |
| GET | `/api/runs?status=&split=&agent=&q=&limit=&offset=` | `{total, runs[]}`; failed top-level rows include `root{sid,name,score,p_fail}` |
| GET | `/api/runs/{id}` | run meta + steps + `replayable` + `label` (ground truth, for humans only) |
| GET | `/api/runs/{id}/trace` | steps |
| GET | `/api/runs/{id}/diagnosis` | `model.analyze` output |
| GET | `/api/runs/{id}/steps/{sid}/explanation` | score, rank, evidence, contribs |
| POST | `/api/runs/{id}/replay` `{sid, mode: repair\|patch_output\|patch_args, patch}` | fork result (`run_id`, success, verified, n_total, n_reexecuted, n_reused, n_suffix, rerun[], changed[], diff, reexecution_error, final, expected) |
| GET | `/api/runs/{id}/forks` | replays of a run |
| GET | `/api/replays` | all replays (with `parent_success`) |
| GET | `/api/compare?a=&b=` | `replay.compare` output |
| GET | `/api/metrics` | `data/metrics.json` |
| POST | `/api/agent/run` `{agent, seed, fault_type}` | new live run |
| POST | `/api/demo/killer` | scripted demo run id |
| GET | `/api/demo/patch/{id}` | `{sid:"L0.rate", patch:{amount,currency}, source:"Standard room: 180 EUR"}`, parsed from the recorded L0.doc text |

---

## 3. IMPLEMENTATION STATUS

### Completed (working and tested)
- Simulated agent, world, fault injection (6 training + 3 held-out), corpus generation (5,000 runs, ~122.7k steps).
- Recorder + SDK + migrations + diagnosis cache.
- Features, step model, run model, baselines, evaluation (localization, by fault type, AUC, counterfactual repair, replay efficiency).
- Explanations with expected/observed evidence and upstream/downstream context.
- Adapter architecture; real-LLM reference agent (Anthropic or deterministic mock).
- Dependency-aware replay with three modes, diff, compare, verification, re-execution error reporting.
- Scripted "killer" demo + document-derived patch.
- FastAPI backend with all endpoints above; service layer; background diagnosis.
- Current web UI implementing every screen and the full loop (to be redesigned, see §5).
- 20 end-to-end pytest tests.

### Partially completed
- **Real-LLM mode is implemented but has never been run against the live Anthropic API** (no key on the build machine). Mock mode is fully tested. **First thing to do once a key exists:** `export ANTHROPIC_API_KEY=…`, start the server, run the Live Demo, and confirm parse, extract and answer all work and the JSON parsing holds up.
- **SDK (`blackbox/sdk.py`)** records any Python agent, and those runs can be diagnosed. But the model's baselines (`value_z` norms) are learned from the travel domain, so for new tools only the grounding, lineage and error signals are informative. External runs can't be replayed.
- **The Settings screen doesn't exist yet** (requested in §6).

### Missing / not done
- The UI redesign (§5–7).
- A Settings screen (LLM provider/model status, DB/model info, re-run benchmark, diagnosis threshold display, reset demo data). Only expose settings the backend actually supports. Add endpoints if needed.
- A real-world external benchmark. The Who&When (ICML 2025) and TRAIL (Patronus AI, 2025) agent-failure datasets were discussed as optional external validation; nothing has been downloaded or verified. Treat both as unverified until checked.
- Version control (`git init`), CI.
- Pagination / virtualization for very large traces in the UI (current traces are ≤ ~45 steps).
- A Docker/one-command launcher (optional).

---

## 4. IMPORTANT TECHNICAL DECISIONS (and what NOT to rewrite)

| Decision | Why |
|---|---|
| **Synthetic, fault-injected corpus** instead of a Kaggle dataset | The brief requires evaluation "against known failures". Injection gives exact step-level root-cause labels, controllable unseen fault types, and reproducibility (`cli all` regenerates everything). |
| **Held-out fault types** (`heldout` split) | Demonstrates generalization to unseen failures (requirement 9). Splits are assigned per run before training. |
| **Fault-agnostic, trace-only features; no step identity, position or timing** | Prevents memorising "extract_rate is usually the culprit". Raised unseen top-1 from ~43% to 85%. Timing is excluded for robustness to real API latency. |
| **Gradient boosting, pointwise and ranked per run** | Fast, robust on tabular signals, trains in seconds; ranking within a run is what localization needs. |
| **Literal constant args learned from history** | `quote=USD` and similar were falsely flagged as "ungrounded". |
| **`doc_len_z` instead of a fixed 0.8 ratio** | Truncated docs sat at 81% of normal length and slipped past the hard-coded threshold. Every value is now a z-score against its baseline. |
| **Fair `first_suspicious` baseline** (unflagged steps shuffled) | With index-order tie-break the rule "won" off-by-one by luck, because parse is always step 0. |
| **Explanations recompute derived features** + `joint_local` | One-at-a-time occlusion made overlapping signals look unimportant. |
| **Event-sourced checkpoints** | Every step writes one output; the fold reconstructs state with no snapshot storage. |
| **Adapter pattern for replay** | Replay must call the agent's real step functions (and the real LLM). SDK runs are honestly marked non-replayable. |
| **Service layer between API and ML** | No ML logic in routes; tests and the UI share one code path. |
| **Diagnoses stored per model version** | One diagnosis ≈ 12 ms × 2,775 failed runs ≈ 33 s, too slow per request. Stored results make `/api/stats` ~0.2 s and the counts exact (not sampled). |
| **LLM cache + deterministic mock** | Reproducible demos/replays; runs offline; the UI clearly labels "OFFLINE MOCK". |
| **Demo patch parsed from the recorded document** | Avoids a hard-coded fix value; the source quote is shown. |
| **Plain JS frontend, no build step** | Zero tooling risk at a hackathon. *The redesign may switch frameworks, but if it adds a build step, document it and keep FastAPI static serving working.* |

**Do NOT rewrite:** `agent.py` execution/replay semantics, `faults.py` taxonomy + splits, `features.py` signal definitions, `model.py` training/evaluation/explain/analyze, `replay.py`, `recorder.py` schema (extend only, with migrations), `service.py`/`api.py` contracts (extend, don't break). Tests in `tests/test_blackbox.py` encode these behaviours.

### Known limitations (be honest about these in the pitch)
- **One synthetic workflow.** Trained and evaluated on one reference workflow (travel expense); transfer to other agents is untested.
- **Off-by-one is the weakest fault type (71% top-1).** When the wrong count coincides with another number in the question, the trace shows no anomaly.
- **"Confidence" is the step model's score, not a calibrated probability.** The UI labels it "step-ranking model score".
- **"Root causes identified" = top score ≥ 0.5.** That's a confidence threshold, not correctness.
- **The scripted demo failure is injected.** The LLM's extraction is replaced with 245 EUR and labelled as such; it's not a spontaneous LLM error.
- **Real-LLM path is unverified live** (see §3).
- **New tools are cold-start.** Value baselines need history, so brand-new tools have weaker signals.

---

## 5. UI/UX DIRECTION (for the redesign)

**The UI must be redesigned from scratch.** The current `web/` is functional and matches the Stitch "Obsidian Telemetry" palette, but the user wants a new design that:
- is **interactive and human-designed**, and must **not look AI-generated** (no generic card grids, gradients, glows, emoji, or "AI magic" styling);
- is **not cluttered**;
- feels like a **professional developer debugging tool** (think Chrome DevTools / Sentry / Honeycomb / Linear quality: dense where needed, calm, precise);
- is built around the core workflow **DETECT → EXPLAIN → REPLAY → REPAIR → VERIFY**;
- carries the USP **"From Failure to Fix — Without Starting Over."** as the product experience, not a banner.

**Design references the user provided:**
- `stitch_black_box_ai_flight_recorder.zip` (repo root): Google Stitch export containing `obsidian_telemetry/DESIGN.md` (full token system) and mockups for the dashboard overview, trace investigation / root-cause analysis, replay workspace / execution comparison, and runs explorer, each as `screen.png` + `code.html`.
  - Palette: canvas `#0A0C10`, shell `#0F1218`, elevated `#161B22`, inspector `#1C2128`, borders `#30363D`; text `#F0F6FC` / `#C9D1D9` / `#8B949E`.
  - Semantics: cobalt `#3B82F6` = replay/active, emerald `#10B981` = success/repaired, crimson `#EF4444` = failure, amber `#F59E0B` = probable root cause, slate `#64748B` = reused.
  - Fonts: Geist + JetBrains Mono; 4–6px radii; 1px borders; no blurry shadows.
  - **Caution:** the mockups contain fake elements (token log-prob charts, telemetry pools, traces per second, user profile, "v2.4.1", cluster names). **Do not build them unless backed by real data.**
- `ui:ux.zip` (repo root): **appeared later and has NOT been reviewed yet.** Inspect it first; it likely contains newer UI/UX direction from the user.

---

## 6. REQUIRED SCREENS

Every screen must use real API data. "Endpoint" means what already exists.

1. **Overview:** USP hero ("From Failure to Fix — Without Starting Over." + supporting line), CTAs **Investigate a Failure** (→ latest failed run) and **Run Demo**, the 5-stage loop with each stage linking to its real screen, the six real metrics (`/api/stats`), recent failures and recent verified repairs, and the benchmark snapshot (`/api/metrics`). Use the precise observability-vs-Black Box wording from §1.
2. **Run Explorer:** filterable, paginated runs (`/api/runs`: status, split/source, agent, search). Columns: run id, status, task, agent, source, steps, duration, likely root cause + score, recorded time.
3. **Trace Investigation:** the primary screen. Step list + dependency graph (layered DAG from `parents`) + root-cause panel. Status per step: root cause (amber), impacted descendants (red), anomaly (amber dim), ok (green); for fork runs, reused (slate) / re-executed (blue).
4. **Step Inspector:** contextual panel for the selected step: kind, operation/role, score + rank, latency, error/retries, depends-on / used-by (clickable), anomaly flags (`diagnosis.steps[].flags`), input JSON, output JSON. Actions: replay from here / patch output / patch args.
5. **Root Cause Analysis:** "Black Box found a likely root cause". Step, confidence (`root_cause.score`, labelled as a model score), evidence cards with **expected vs observed**, upstream state (`upstream.healthy`), downstream effect (`impacted`), other suspects, `joint_local` note, and a "reveal ground-truth label" control for benchmark/demo runs (`run.label`; never used by the model).
6. **Replay Workspace:** choose a checkpoint step; show **full execution (N steps) vs Black Box replay (k re-executed, N−k reused)**; per-step plan tags REUSED / RE-EXECUTED · CHECKPOINT / RE-EXECUTED / PRESERVED. Descendants can be computed client-side from `parents` or taken from the replay result's `rerun`.
7. **Repair / Patch:** modes **Re-run step fresh** (`repair`), **Patch output**, **Patch arguments**. Show the current value (recorded output or args), a proposed-fix JSON editor, **Apply Patch** (validate + field diff) → **Run Replay** → **Cancel**. For `split=demo` + `L0.rate`, offer "use value from retrieved document" (`/api/demo/patch/{id}`, show the `source` quote). Then a verify result:
   - **REPAIR VERIFIED** / NOT VERIFIED;
   - original vs repaired outcome and counts (`n_total`, `n_reexecuted`, `n_reused`, `n_suffix`, `changed`);
   - error state when `reexecution_error` is set: "Checkpoint restored, but step NN failed during re-execution", with step, error, args and Retry;
   - API errors shown with HTTP status and message, never "something went wrong".
8. **Execution Comparison:** list of all replays (`/api/replays`) and a detail view (`/api/compare`): ORIGINAL vs REPAIRED header, first divergence, changed/re-executed/reused counts, expected answer, a step-aligned table with REUSED / CHANGED · RE-EXECUTED / RE-EXECUTED · SAME tags, and expandable before/after JSON.
9. **Evaluation:** grouped by loop stage, from `/api/metrics`:
   - detect: AUC;
   - explain: top-1/top-3 seen/unseen vs baselines, per fault type with seen vs never-seen marked;
   - replay: full re-run vs suffix re-run vs Black Box replay average steps;
   - repair/verify: confirm_top1, fixed_within_3, avg_replays;
   - methodology: training vs held-out fault lists from `/api/info`.
10. **Live Demo:** a 10-step presenter-paced sequence (Next / Run all / Restart), each step a real API call: run agent → agent fails → detect → root cause → why → replay plan → patch applied → only affected re-executed → original vs repaired → repair verified. Target 1–3 minutes, understandable without code knowledge.
11. **Settings (new):** show LLM provider/model (`/api/info`), whether the API key is set (provider = anthropic), DB path / run counts, model `trained_at`, diagnosis threshold (0.5), and links to the API docs. Optional actions only if backed by new endpoints (e.g. "re-run diagnoses"). Never fake toggles.

**Empty states:**
- "NO FAILED RUNS · Your agent executions are healthy. [Run Demo]"
- "NO REPLAY YET · Select a suspicious step to replay from its checkpoint. [Investigate Trace]"

**Preferred copy:** "Likely root cause", "Root cause identified", "Trace captured", "Replay from checkpoint", "3 steps affected", "5 steps reused", "Patch applied", "Execution diverged", "Repair verified", "Original vs repaired".
**Banned copy:** "Revolutionary AI", "Next-generation intelligence", "Supercharge", "AI magic", "Automagically".

---

## 7. CORE UX PRINCIPLES
1. **The trace is the primary object.** Every screen hangs off a run.
2. **The root cause is the primary insight,** visible within seconds of opening a failed run.
3. **Replay is the primary action.** One obvious button from the root cause.
4. **Comparison proves the repair.** Verification is evidence (diff + task check), not a toast.
5. **Progressive disclosure.** Summary first; JSON, all suspects and signals on demand.
6. **Contextual inspector.** Selecting a step anywhere (list, graph, chips) updates one inspector.
7. **Minimal clutter.** Few panels, one accent at a time, the semantic colours above.
8. **Real interactions.** Every button calls the backend; no fake animations pretending to compute.
9. **No fake data.** Only API values; label scores honestly; label mock mode and injected faults.
10. **No decorative AI effects.** No glow, gradient blobs, sparkles or typing animations.

---

## 8. CURRENT PROBLEMS / ISSUES IDENTIFIED (complete list)

**Fixed already (for history; don't reintroduce):**
- `agent.execute` ignored falsy patches (`ov.get(...) or ...`). Now key-presence based.
- `agent.execute` recorded the previous step's args when `derive` raised (`locals().get("args")`). Now resets `args = {}` per step.
- Replay RNG used Python `hash()` (randomised per process). Now uses `zlib.crc32`.
- SDK runs were saved as `agent="travel-sim"`, so replay crashed. Now `agent="external"` → 409 ReplayUnsupported.
- The dashboard stats endpoint took 39 s (full explanations on 250 runs). Now uses stored diagnoses (~0.2 s).
- Evidence was missing key facts because overlapping signals masked each other. Fixed with derived-feature recomputation, always listing present local signals, and `joint_local`.
- `fx_rate.quote = "USD"` was flagged as an ungrounded argument. Fixed with learned literal args.
- Truncated documents (81% length) were missed by a fixed 0.8 ratio. Fixed with `doc_len_z`.
- The model underperformed the rule on unseen faults (overfit to identity features). Fixed by removing identity/position features and adding lineage features.
- The `first_suspicious` baseline was unfairly strong (index tie-break). Made fair.
- UI: wide graphs overflowed the grid (fixed with `min-width:0`); the Streamlit sidebar was hidden (now legacy); the demo patch source note vanished on re-render (fixed).

**Open:**
- Real-LLM mode untested live; JSON parsing of model output relies on regex extraction (`llm.parse_json`), so it may need hardening (e.g. structured outputs) once tested.
- With a real LLM, `truncated_context` makes extraction return `null`, so `hotel_local` raises an exception. That produces a different trace shape from the simulated corpus; check how the diagnosis behaves.
- Benchmark is synthetic only; no external dataset validation.
- Off-by-one weakness (71%).
- `Recorder.runs_df(where)` takes raw SQL (internal only).
- The background diagnosis thread shares one SQLite connection under an RLock. Fine for a demo, not for heavy concurrency.
- `data/blackbox.db` accumulates demo/live/fork runs; `cli all` regenerates (and **deletes**) the DB.
- `app.py` (Streamlit) duplicates UI logic; it's legacy.
- No git repo; `.gitignore` exists (excludes `.venv`, `data/*.db`). Note that `data/model.joblib` and `metrics.json` are not ignored.
- UI needs the redesign (§5) and a Settings screen.
- Google Fonts need internet; offline the UI falls back to system fonts.

---

## 9. NEXT STEPS (prioritized)

1. **Inspect `ui:ux.zip`** (new, unreviewed) and re-read `stitch_black_box_ai_flight_recorder.zip`, then confirm the design direction with the user before writing code.
2. **Suggest `git init` + an initial commit** of the current working state (ask the user first).
3. **Redesign the frontend from scratch** per §5–7 against the existing API. Keep FastAPI serving `/` + `/static`. Suggested order:
   1. Trace Investigation + Step Inspector + Root Cause (most important).
   2. Replay Workspace + Repair/Patch + Verify.
   3. Execution Comparison.
   4. Overview.
   5. Run Explorer.
   6. Live Demo.
   7. Evaluation.
   8. Settings.
4. **Add the Settings screen** (+ a `/api/settings` or extend `/api/info` with `trained_at`, DB stats, thresholds). Real values only.
5. **Verify every interaction in a browser** (replay, patch, error state with patch `{}` on `L0.rate`, comparison, demo Run all, empty states). Keep `pytest` green and add API tests for any new endpoints.
6. **Real-LLM verification** when a key is available (see §3), and harden `llm.parse_json` if needed.
7. **Optional, if time allows:** external validation on Who&When/TRAIL (verify availability and licence first); improve off-by-one; one-command launcher.
8. **Pitch assets:** a 60-second demo script (below), a 2-minute technical explanation, and a backup demo video.

### 60-second demo (current behaviour)
1. Live Demo → **Run all**. The agent says **$2,569.80, over budget**; the expected answer is **$2,359.20, within budget**.
2. Root cause **Step 03 · L0.rate (extract_rate)**, ~99% model score. Evidence:
   - "245 deviates 6.2σ from this hotel's baseline (≈180)";
   - "245 not present in the input (document says 180)";
   - upstream healthy; 7 downstream steps affected.
3. Replay plan: 8 re-run / 4 reused. Patch `amount 245 → 180`, read from the document "Standard room: 180 EUR".
4. **REPAIR VERIFIED:** FAILED → SUCCESS; diverged at L0.rate; 7 steps changed.

### Safe claims for the pitch
- "Learns to localize failure-causing steps from execution traces: **94.0%** top-1 on held-out runs with seen failure types and **85.0%** on failure categories never seen in training, beating rule baselines (88.1% / 78.8%)."
- "Diagnoses are explained with trace evidence and verified by replay: **92.1%** of failures fixed and confirmed within 3 replays."
- "Replay re-executes only affected steps: **47.8%** of steps on average vs 73.1% for re-running from the suspect step."
- "Any Python agent can be recorded and diagnosed via the SDK; replay needs an adapter."

---

## 10. HOW TO RUN

```bash
cd ~/Desktop/BlackBox

# one-time setup (the .venv already exists on this machine, using Python 3.13)
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# (re)build benchmark: generate 5,000 runs → train → evaluate → store diagnoses   (~1 min, DELETES data/blackbox.db)
./.venv/bin/python -m blackbox.cli all
#   or individual stages: generate | train | eval | diagnose   (e.g. --n 3000)

# API + web UI
./.venv/bin/uvicorn blackbox.api:app --port 8000      # http://localhost:8000  ·  docs: /docs

# legacy Streamlit dashboard (optional)
./.venv/bin/streamlit run app.py
```

**Environment variables (all optional):**

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | enables the real LLM; without it, offline mock |
| `BLACKBOX_LLM` | `auto` | `auto`, `anthropic` or `mock` |
| `BLACKBOX_LLM_MODEL` | `claude-opus-5-5` | model for the real LLM steps |
| `BLACKBOX_LLM_CACHE` | `data/llm_cache.db` | LLM response cache |
| `BLACKBOX_DB` | `data/blackbox.db` | runs database |
| `BLACKBOX_MODEL` | `data/model.joblib` | trained model |
| `BLACKBOX_METRICS` | `data/metrics.json` | evaluation output |
| `BLACKBOX_BACKGROUND` | `1` | background diagnosis thread on startup |

**Dependencies (`requirements.txt`):** numpy, pandas, scikit-learn, joblib, fastapi, uvicorn[standard], anthropic>=1.0 (installed: 1.11.0), httpx, pytest, plus streamlit and plotly for the legacy app. `.claude/launch.json` defines `blackbox-web` (uvicorn :8000) and `blackbox-streamlit` (:8501) for preview tooling.

---

## 11. TESTING

```bash
./.venv/bin/python -m pytest -q        # 20 tests, ~15–25 s, all passing as of 2026-10-03
```
`tests/test_blackbox.py` builds its own temporary 900-run corpus and model (it never touches `data/`) and forces `BLACKBOX_LLM=mock`. It covers:
- **determinism & splits:** execution determinism; heldout split contains only held-out faults.
- **mock parsing:** the mock LLM parses from the question text.
- **no label leakage:** `MODEL_FEATURES` contain no labels or identity; diagnosis is identical when run labels are deleted.
- **model quality:** the model beats random/max-anomaly baselines; explanations carry trace evidence.
- **replay:** replay re-runs exactly `{sid} ∪ descendants` and reuses the rest; replaying elsewhere keeps the fault; falsy patches are respected; replay is reproducible; comparing a saved fork works.
- **SDK runs:** external SDK runs are diagnosable but raise ReplayUnsupported.
- **scripted demo:** end to end (L0.rate ranked #1; repair fixes it with 8 re-executed / 4 reused; patch_output fixes it); LLM agent equals the sim agent when clean.
- **API:** full flow (all endpoints); API errors (404/422).
- **USP loop:** metrics increment correctly after a verified replay; re-execution errors are reported (`L0.fx` KeyError 'currency' for patch `{}`); evidence has expected/observed.

**Benchmark (`python -m blackbox.cli all`), expected output with seed 7, n=5000:**

| Method | Seen top-1 | Seen top-3 | Unseen top-1 | Unseen top-3 |
|---|---|---|---|---|
| model | 94.0% | 96.8% | 85.0% | 87.7% |
| first_suspicious | 88.1% | 89.8% | 78.8% | 81.2% |
| max_anomaly | 38.1% | 43.8% | 15.8% | 17.9% |
| last_step | 0.0% | 6.0% | 0.0% | 0.0% |
| random | 4.8% | 13.3% | 5.9% | 15.3% |

- **Per fault type (top-1):** hallucinated_value 100%, dropped_field 100%, irrelevant_retrieval 100%, unit_mixup 95.9%, wrong_arg 93.6%, wrong_operation 75.5%; unseen: truncated_context 99.6%, stale_cache 84.4%, off_by_one 71.1%.
- **Run-failure AUC:** 0.904.
- **Counterfactual:** confirm_top1 89.3%, fixed_within_3 92.1%, avg_replays 1.20, re-exec 11.4/23.9 steps (47.8%), suffix 17.4 (73.1%).
- **Corpus:** 5,000 runs, 2,771 failed, 122,701 steps.
- **Diagnose stage:** stores 2,775 diagnoses in ~34 s.

**Known failures:** none at the time of writing. The only historical flake: the evidence test previously assumed a "Value anomaly" item, which depends on corpus history; it's now conditional.

**Manual checks done in the browser (current UI):** overview, runs, investigation (statuses correct: only descendants of L0.rate marked impacted), replay & repair (apply patch → run → verified), error path, comparisons list/detail, evaluation, demo Run all (10/10 steps → REPAIR VERIFIED).

---

## 12. FILE MAP

| Path | Purpose |
|---|---|
| `PROJECT_HANDOFF.md` | this file |
| `README.md` | public project README (results, architecture, claims, limitations, demo script) |
| `requirements.txt` | Python deps |
| `blackbox/world.py` | deterministic world data (hotels, FX, flights, per-diem, taxi, hotel documents) |
| `blackbox/agent.py` | task generation, `build_plan` DAG, `execute` (with fault hooks + replay support), `descendants`, `ground_truth`, `judge` |
| `blackbox/faults.py` | fault taxonomy (6 training + 3 held-out), `make_fault`, `mutate_args`, `mutate_output`, descriptions |
| `blackbox/generate.py` | corpus generation + split assignment (train/test/heldout) |
| `blackbox/recorder.py` | SQLite flight recorder: schema, migrations, run/step IO, listings, stats, diagnosis cache, replay stats |
| `blackbox/features.py` | trace-only signals, historical norms (incl. literal args), `derive`, `rows_from_signals`, `MODEL_FEATURES`, `signal_flags`, run-level features |
| `blackbox/model.py` | train, load, `diagnose`, `explain` (evidence with expected/observed), `analyze`, baselines, `evaluate` |
| `blackbox/replay.py` | `fork` (dependency-aware replay, three modes), `diff`, `compare` |
| `blackbox/agents/__init__.py` | adapter registry (`travel-llm`, `travel-sim`), `get_adapter`, `ReplayUnsupported` |
| `blackbox/agents/base.py` | `Adapter` contract (`build_plan`, `judge`, `latency`, `meta`, `execute`) |
| `blackbox/agents/travel_sim.py` | simulated adapter |
| `blackbox/agents/travel_llm.py` | real-LLM adapter: prompts, mock parser/extractor, LLM step functions |
| `blackbox/llm.py` | Anthropic client (`claude-opus-5-5`, fallbacks, refusal handling), mock mode, SQLite cache, `parse_json` |
| `blackbox/demo.py` | scripted demo task/fault (`hallucinated_value` 245 at L0.rate), `run_killer`, `patch_from_document` |
| `blackbox/service.py` | application service used by the API: analysis cache, stored diagnoses, stats, replays, live/demo runs |
| `blackbox/api.py` | FastAPI routes + static frontend serving |
| `blackbox/sdk.py` | `Tracer` for recording any Python agent (`agent="external"`) |
| `blackbox/cli.py` | `generate` / `train` / `eval` / `diagnose` / `all` |
| `web/index.html`, `web/style.css`, `web/app.js` | current SPA (to be redesigned) |
| `app.py` | legacy Streamlit dashboard |
| `tests/test_blackbox.py` | 20 end-to-end tests |
| `data/blackbox.db` | runs/steps/diagnoses (regenerated by `cli all`) |
| `data/model.joblib` | trained bundle (`clf`, `run_clf`, `norms`, `features`, `trained_at`) |
| `data/metrics.json` | evaluation output read by `/api/metrics` |
| `.claude/launch.json` | preview server configs |
| `.streamlit/config.toml` | legacy Streamlit theme |
| `stitch_black_box_ai_flight_recorder.zip` | Stitch design export (design system + mockups) |
| `ui:ux.zip` | **new, unreviewed** design input from the user |

### Outside this repo (context only)
- `~/.claude/skills/gstack`: gstack (Garry Tan's Claude Code skill pack) installed with `--no-team --no-plan-tune-hooks --no-timeline-stop-hook --no-prefix`; Bun 1.4.2 installed via Homebrew. Its README also asks to add a gstack section to the global CLAUDE.md (use `/browse`, never Claude-in-Chrome); **the user hasn't approved that yet**, so it wasn't done.
- Earlier, unrelated work in the same session: Tata Elxsi Teliport S4 Case Study 5 (VahanSaarthi) slides at `~/Desktop/VahanSaarthi_Teliport_S4_Case_Study_5_FINAL.pptx`. Not part of this project.

---

## 13. WORKING WITH THIS USER (preferences observed)
- **Goal is to win the hackathon.** Prioritise a working, demonstrable loop over breadth.
- **Strict honesty:** no fabricated metrics, no fake explanations, no fake UI, no unsupported claims. Label mock mode, injected faults and model scores explicitly. The user repeatedly asked for this.
- **Wants speed:** "do it fast". Act, don't over-ask; but confirm before persistent or global config changes (e.g. editing the global CLAUDE.md, git commits, deleting files).
- **Preserve working code:** extend; don't rewrite the core (§4).
- **Verify in a real browser** after UI changes, and report what was and wasn't verified.

## 14. FIRST COMMANDS FOR A NEW SESSION
```bash
cd ~/Desktop/BlackBox
./.venv/bin/python -m pytest -q                         # expect 20 passed
unzip -l 'ui:ux.zip'                                     # NOTE: filename contains a colon; always quote it
unzip -oq 'ui:ux.zip' -d /tmp/uiux && ls -R /tmp/uiux | head -50
unzip -oq stitch_black_box_ai_flight_recorder.zip -d /tmp/stitch   # design system: /tmp/stitch/*/obsidian_telemetry/DESIGN.md
./.venv/bin/uvicorn blackbox.api:app --port 8000        # then open http://localhost:8000 and http://localhost:8000/docs
curl -s localhost:8000/api/stats | head -c 300          # sanity: runs≈5000+, failures_analyzed == failures_detected (after background diagnosis)
```
If `data/` is missing or corrupted: `./.venv/bin/python -m blackbox.cli all` rebuilds everything (~1 min).
