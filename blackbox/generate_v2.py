"""Labelled benchmark for the dynamic agent (traces captured via OpenTelemetry).

Splits (assigned per run before training):
  train / test   clean runs + TRAINING fault types at their first occurrence (standard policy)
  heldout        HELD-OUT fault types (never trained on)
  drift_loc      TRAINING fault types injected at a *later* occurrence: the error source
                 sits at a location never faulted during training
  drift_topo     TRAINING fault types under a different agent behaviour ("verifier" policy:
                 different ordering + extra verification calls), i.e. unseen graph shapes
Labels (fault type, faulty step) live on the run row only; features never read them.
"""
import argparse
import os
import random

from . import agent as A
from . import faults_v2 as F
from .react_agent import ScriptedPolicy, execute
from .recorder import Recorder

AGENT = "react-sim"


def generate(n=5000, path="data/blackbox.db", seed=11, p_clean=0.3, p_heldout=0.22, p_drift_loc=0.13, p_drift_topo=0.13):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    rec = Recorder(path)
    rng = random.Random(seed)
    pols = {"standard": ScriptedPolicy("standard"), "verifier": ScriptedPolicy("verifier")}
    stats = {}
    for i in range(n):
        task = A.make_task(rng)
        variant, fault, split = "standard", None, None
        u = rng.random()
        if u < p_clean:
            split = "train" if rng.random() < 0.7 else "test"
            if rng.random() < 0.15:
                variant, split = "verifier", "drift_topo"
        else:
            v = rng.random()
            if v < p_heldout:
                fault, split = F.make_fault(rng.choice(F.HELDOUT_FAULTS), 0, rng.randrange(10**9)), "heldout"
            else:
                ft = rng.choice(F.TRAIN_FAULTS)
                w = rng.random()
                n_occ = F.n_occurrences(ft, task)
                if w < p_drift_loc / (1 - p_heldout) and n_occ >= 2:
                    fault, split = F.make_fault(ft, rng.randrange(1, n_occ), rng.randrange(10**9)), "drift_loc"
                elif w < (p_drift_loc + p_drift_topo) / (1 - p_heldout):
                    fault, split, variant = F.make_fault(ft, 0, rng.randrange(10**9)), "drift_topo", "verifier"
                else:
                    fault = F.make_fault(ft, 0, rng.randrange(10**9))
                    split = "train" if rng.random() < 0.7 else "test"
        steps, final, hist, fsid = execute(task, pols[variant], fault=fault, seed=rng.randrange(10**9))
        ok, gt = A.judge(task, final)
        if fault:
            fault["sid"] = fsid  # where the fault actually landed (None if its target never occurred)
            if fsid is None:
                fault = None
        rec.save_run(task, steps, final, ok, gt, fault, split, agent=AGENT, meta={"policy": variant})
        key = (split, fault["type"] if fault else "clean", ok)
        stats[key] = stats.get(key, 0) + 1
        if i % 500 == 499:
            rec.commit()
    rec.commit()
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--db", default="data/blackbox.db")
    a = ap.parse_args()
    for (sp, k, ok), v in sorted(generate(a.n, a.db).items()):
        print(f"{sp:10s} {k:22s} {'PASS' if ok else 'FAIL'} {v}")
