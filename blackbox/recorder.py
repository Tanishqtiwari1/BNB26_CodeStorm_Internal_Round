"""Flight recorder: append-only SQLite log of agent runs and steps.

Each step stores its args, output, parent links (data dependencies), timing
and errors. Because steps are append-only and each writes one output, the
checkpoint *state* after step k is simply the fold of outputs 0..k
(event sourcing) -- no full snapshots needed, yet any step can be restored.

The `Recorder` API is agent-agnostic: any agent can call save_run (directly
or through blackbox.sdk). Fault-injection labels live on the run row only and
are never read by the diagnosis model.
"""
import json
import sqlite3
import threading
import time
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, question TEXT, task_json TEXT, final_json TEXT,
  success INTEGER, expected_json TEXT, fault_type TEXT, fault_sid TEXT,
  fault_json TEXT, split TEXT, parent_run_id TEXT, fork_sid TEXT,
  fork_mode TEXT, n_reexecuted INTEGER, created REAL
);
CREATE TABLE IF NOT EXISTS steps (
  run_id TEXT, idx INTEGER, sid TEXT, kind TEXT, name TEXT, role TEXT,
  parents_json TEXT, args_json TEXT, output_json TEXT, latency_ms REAL,
  error TEXT, retries INTEGER, reused INTEGER,
  PRIMARY KEY (run_id, idx)
);
CREATE INDEX IF NOT EXISTS ix_runs_split ON runs(split);
CREATE INDEX IF NOT EXISTS ix_runs_parent ON runs(parent_run_id);
CREATE TABLE IF NOT EXISTS diagnoses (
  run_id TEXT PRIMARY KEY, model_tag TEXT, top_sid TEXT, top_name TEXT, top_score REAL, p_fail REAL
);
"""
MIGRATIONS = {"agent": "TEXT", "meta_json": "TEXT"}
RUN_COLS = ["run_id", "question", "task_json", "final_json", "success", "expected_json", "fault_type",
            "fault_sid", "fault_json", "split", "parent_run_id", "fork_sid", "fork_mode", "n_reexecuted",
            "created", "agent", "meta_json"]


class Recorder:
    def __init__(self, path="data/blackbox.db"):
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        have = {r[1] for r in self.db.execute("PRAGMA table_info(runs)")}
        for col, typ in MIGRATIONS.items():
            if col not in have:
                self.db.execute(f"ALTER TABLE runs ADD COLUMN {col} {typ}")
        self.db.commit()

    # ---- write
    def save_run(self, task, recs, final, success, expected, fault=None, split="",
                 parent_run_id=None, fork_sid=None, fork_mode=None, n_reexecuted=None, run_id=None,
                 agent="travel-sim", meta=None):
        run_id = run_id or uuid.uuid4().hex[:12]
        row = (run_id, task.get("question", ""), json.dumps(task), json.dumps(final), int(success),
               json.dumps(expected), fault["type"] if fault else None, fault["sid"] if fault else None,
               json.dumps(fault) if fault else None, split, parent_run_id, fork_sid, fork_mode,
               n_reexecuted, time.time(), agent, json.dumps(meta or {}))
        with self.lock:
            self.db.execute(f"INSERT INTO runs ({','.join(RUN_COLS)}) VALUES ({','.join('?' * len(RUN_COLS))})", row)
            self.db.executemany(
                "INSERT INTO steps VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(run_id, r["idx"], r["sid"], r["kind"], r["name"], r.get("role", ""), json.dumps(r["parents"]),
                  json.dumps(r["args"]), json.dumps(r["output"]), r["latency_ms"], r["error"],
                  r["retries"], int(r.get("reused", False))) for r in recs])
        return run_id

    def commit(self):
        with self.lock:
            self.db.commit()

    # ---- read
    def _q(self, sql, params=()):
        with self.lock:
            cur = self.db.execute(sql, params)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def run(self, run_id):
        rows = self._q("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if not rows:
            return None
        d = rows[0]
        for k in ("task_json", "final_json", "expected_json", "fault_json", "meta_json"):
            d[k[:-5]] = json.loads(d[k]) if d.get(k) else None
        d["agent"] = d.get("agent") or "travel-sim"
        return d

    def steps(self, run_id):
        out = []
        for d in self._q("SELECT * FROM steps WHERE run_id=? ORDER BY idx", (run_id,)):
            d["parents"] = json.loads(d.pop("parents_json"))
            d["args"] = json.loads(d.pop("args_json"))
            d["output"] = json.loads(d.pop("output_json"))
            d["reused"] = bool(d["reused"])
            out.append(d)
        return out

    # ---- cached diagnoses (model output only; keyed by model version)
    def save_diagnosis(self, run_id, model_tag, top_sid, top_name, top_score, p_fail):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO diagnoses VALUES (?,?,?,?,?,?)",
                            (run_id, model_tag, top_sid, top_name, top_score, p_fail))
            self.db.commit()

    def get_diagnosis(self, run_id, model_tag):
        r = self._q("SELECT * FROM diagnoses WHERE run_id=? AND model_tag=?", (run_id, model_tag))
        return r[0] if r else None

    def undiagnosed_failed(self, model_tag, limit=100000):
        return [r["run_id"] for r in self._q(
            "SELECT r.run_id FROM runs r LEFT JOIN diagnoses d ON d.run_id=r.run_id AND d.model_tag=? "
            "WHERE r.success=0 AND r.parent_run_id IS NULL AND d.run_id IS NULL ORDER BY r.created DESC LIMIT ?",
            (model_tag, limit))]

    def diagnosis_stats(self, model_tag, threshold):
        return self._q(
            "SELECT COUNT(*) analyzed, SUM(d.top_score >= ?) identified, AVG(d.top_score) avg_score "
            "FROM diagnoses d JOIN runs r USING(run_id) WHERE d.model_tag=? AND r.success=0 AND r.parent_run_id IS NULL",
            (threshold, model_tag))[0]

    def replay_stats(self):
        """Real replay/repair counters, computed from saved fork runs."""
        return self._q(
            "SELECT COUNT(*) replays, "
            "SUM(CASE WHEN p.success=0 AND f.success=1 THEN 1 ELSE 0 END) verified, "
            "SUM(t.n - f.n_reexecuted) steps_avoided, SUM(f.n_reexecuted) steps_reexecuted, SUM(t.n) steps_total "
            "FROM runs f JOIN runs p ON p.run_id=f.parent_run_id "
            "JOIN (SELECT run_id, COUNT(*) n FROM steps GROUP BY run_id) t ON t.run_id=f.run_id")[0]

    def list_runs(self, status=None, split=None, agent=None, forks=False, parent=None, q=None,
                  limit=50, offset=0, forks_only=False):
        """Parameterised run listing with per-run step count and total duration."""
        where, params = [], []
        if parent:
            where.append("r.parent_run_id = ?")
            params.append(parent)
        elif forks_only:
            where.append("r.parent_run_id IS NOT NULL")
        elif not forks:
            where.append("r.parent_run_id IS NULL")
        if status in ("passed", "failed"):
            where.append("r.success = ?")
            params.append(1 if status == "passed" else 0)
        if split:
            where.append("r.split = ?")
            params.append(split)
        if agent:
            where.append("COALESCE(r.agent,'travel-sim') = ?")
            params.append(agent)
        if q:
            where.append("(r.run_id LIKE ? OR r.question LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        w = ("WHERE " + " AND ".join(where)) if where else ""
        total = self._q(f"SELECT COUNT(*) n FROM runs r {w}", params)[0]["n"]
        rows = self._q(
            f"SELECT r.run_id, r.question, r.success, r.split, COALESCE(r.agent,'travel-sim') agent, r.created, "
            f"r.fault_type, r.fault_sid, r.parent_run_id, r.fork_sid, r.fork_mode, r.n_reexecuted, "
            f"COUNT(s.idx) n_steps, ROUND(SUM(s.latency_ms),1) duration_ms, "
            f"(SELECT p.success FROM runs p WHERE p.run_id = r.parent_run_id) parent_success "
            f"FROM runs r JOIN steps s USING(run_id) {w} GROUP BY r.run_id ORDER BY r.created DESC "
            f"LIMIT ? OFFSET ?", params + [int(limit), int(offset)])
        return total, rows

    def stats(self):
        r = self._q("SELECT COUNT(*) n, SUM(success) ok FROM runs WHERE parent_run_id IS NULL")[0]
        s = self._q("SELECT AVG(c) avg_steps, AVG(d) avg_ms FROM (SELECT COUNT(*) c, SUM(latency_ms) d "
                    "FROM steps s JOIN runs r USING(run_id) WHERE r.parent_run_id IS NULL GROUP BY run_id)")[0]
        f = self._q("SELECT COUNT(*) n FROM runs WHERE parent_run_id IS NOT NULL")[0]
        return {"runs": r["n"] or 0, "passed": int(r["ok"] or 0), "failed": (r["n"] or 0) - int(r["ok"] or 0),
                "avg_steps": s["avg_steps"] or 0, "avg_duration_ms": s["avg_ms"] or 0, "replays": f["n"]}

    # ---- legacy helpers (benchmark / Streamlit)
    def runs_df(self, where="parent_run_id IS NULL"):
        import pandas as pd
        with self.lock:
            return pd.read_sql_query(f"SELECT run_id, question, success, fault_type, fault_sid, split, "
                                     f"parent_run_id, fork_sid, fork_mode, n_reexecuted FROM runs WHERE {where}",
                                     self.db)

    def checkpoint(self, run_id, idx):
        """Restore agent state (all step outputs) as it was right after step `idx`."""
        return {s["sid"]: s["output"] for s in self.steps(run_id) if s["idx"] <= idx}
