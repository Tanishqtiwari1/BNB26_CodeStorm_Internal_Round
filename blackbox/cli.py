"""One-shot pipeline: generate -> train -> evaluate.

    python -m blackbox.cli all --n 5000
"""
import argparse
import json

from . import generate as G
from . import model as M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["generate", "train", "eval", "diagnose", "all"])
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--db", default="data/blackbox.db")
    a = ap.parse_args()
    if a.cmd in ("generate", "all"):
        st = G.generate(a.n, a.db)
        print("generated:", sum(st.values()), "runs")
    if a.cmd in ("train", "all"):
        _, n, pos = M.train(a.db)
        print(f"trained step model on {n} steps ({pos} root causes)")
    if a.cmd in ("eval", "all"):
        m = M.evaluate(a.db)
        L = m["localization"]
        print(f"\n{'method':18s} {'seen top1':>9s} {'top3':>6s} | {'unseen top1':>11s} {'top3':>6s}")
        for meth in M.METHODS:
            t, h = L["test"][meth], L["heldout"][meth]
            print(f"{meth:18s} {t['top1']:9.1%} {t['top3']:6.1%} | {h['top1']:11.1%} {h['top3']:6.1%}")
        print("\nper fault type (model):")
        for k, v in sorted(m["by_fault_type"].items(), key=lambda kv: kv[1]["heldout"]):
            print(f"  {k:22s} {'UNSEEN' if v['heldout'] else 'seen  '} top1 {v['top1']:.1%} top3 {v['top3']:.1%} (n={v['n']})")
        print(f"\nrun failure AUC: {m['run_failure_auc']:.3f}")
        print("counterfactual:", json.dumps(m.get("counterfactual"), indent=1))
    if a.cmd in ("diagnose", "all"):
        from .service import Service
        n = Service(db=a.db).diagnose_all()
        print(f"stored diagnoses for {n} failed runs")


if __name__ == "__main__":
    main()
