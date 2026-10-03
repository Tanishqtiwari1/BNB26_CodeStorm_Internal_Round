"""Generate a labelled corpus of agent runs (clean + fault-injected).

Splits (assigned per run, before anything is trained):
  train    clean runs + runs with TRAINING fault types        (70%)
  test     clean runs + runs with TRAINING fault types        (30%, never trained on)
  heldout  runs with HELD-OUT fault types only                (never trained on)
Labels (fault type, faulty step) are stored on the run row for training and
evaluation only; the model's features are computed from the step trace alone.
"""
import argparse
import os
import random

from . import agent as A
from . import faults as F
from .recorder import Recorder


def generate(n=5000, path="data/blackbox.db", seed=7, p_clean=0.35, p_heldout=0.25):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    rec = Recorder(path)
    rng = random.Random(seed)
    stats = {}
    for i in range(n):
        task = A.make_task(rng)
        plan = A.build_plan(task)
        u = rng.random()
        fault = None
        if u >= p_clean:
            pool = F.HELDOUT_FAULTS if rng.random() < p_heldout else F.TRAIN_FAULTS
            fault = F.make_fault(rng.choice(pool), plan, task, rng)
        recs = A.execute(task, fault=fault, rng=random.Random(rng.randrange(10**9)))
        final = recs[-1]["output"]
        ok, gt = A.judge(task, final)
        if fault is None:
            split = "train" if rng.random() < 0.7 else "test"
        elif fault["type"] in F.HELDOUT_FAULTS:
            split = "heldout"
        else:
            split = "train" if rng.random() < 0.7 else "test"
        rec.save_run(task, recs, final, ok, gt, fault, split)
        key = (fault["type"] if fault else "clean", ok)
        stats[key] = stats.get(key, 0) + 1
    rec.commit()
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--db", default="data/blackbox.db")
    a = ap.parse_args()
    st = generate(a.n, a.db)
    for (k, ok), v in sorted(st.items()):
        print(f"{k:22s} {'PASS' if ok else 'FAIL'} {v}")
