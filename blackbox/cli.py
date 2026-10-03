"""One-shot pipelines.

    python -m blackbox.cli all        # v2: dynamic SLM-style agent, OTel traces, graph models (default product)
    python -m blackbox.cli all-v1     # v1: fixed-plan travel agent + per-step GBM (legacy)
"""
import argparse
import json

from . import generate as G
from . import model as M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["generate", "train", "eval", "diagnose", "all", "all-v1", "data"])
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--n", type=int, default=5000)
    ap.add_argument("--db", default="data/blackbox.db")
    a = ap.parse_args()
    if a.cmd == "all":
        return run_v2(a)
    if a.cmd == "data":
        return rebuild_data(a)
    if a.cmd == "all-v1":
        a.cmd = "all"
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


def run_v2(a):
    from . import generate_v2 as G2
    from . import model_v2 as M2
    from .service import Service
    st = G2.generate(a.n, a.db)
    print("generated:", sum(st.values()), "dynamic-agent runs (OpenTelemetry traces)")
    M2.train(a.db, "data/model_v2.joblib", epochs=a.epochs)
    m = M2.evaluate(a.db, "data/model_v2.joblib", "data/metrics.json")
    L = m["localization"]
    print(f"\n{'method':18s}" + "".join(f"{sp:>17s}" for sp in M2.SPLITS) + "   (top-1 / top-3)")
    for meth in M2.METHODS:
        print(f"{meth:18s}" + "".join(f"{L[sp][meth]['top1']:10.1%}/{L[sp][meth]['top3']:5.0%}" for sp in M2.SPLITS))
    print("n per split:", {sp: L[sp]["gnn"]["n"] for sp in M2.SPLITS})
    print("\nper fault type (GNN):")
    for k, v in sorted(m["by_fault_type"].items(), key=lambda kv: kv[1]["heldout"]):
        print(f"  {k:22s} {'UNSEEN' if v['heldout'] else 'seen  '} top1 {v['top1']:.1%} top3 {v['top3']:.1%} (n={v['n']})")
    print(f"\nrun failure AUC: {m['run_failure_auc']:.3f}")
    print("counterfactual:", json.dumps(m.get("counterfactual"), indent=1))
    n = Service(db=a.db, model_path="data/model_v2.joblib").diagnose_all()
    print(f"stored diagnoses for {n} failed runs")


def rebuild_data(a):
    """Regenerate the (deterministic) v2 corpus and store diagnoses with the committed model.
    Used on hosts without PyTorch (e.g. Render): no training needed."""
    from . import generate_v2 as G2
    from .service import Service
    st = G2.generate(a.n, a.db)
    print("generated:", sum(st.values()), "runs")
    print("stored diagnoses:", Service(db=a.db, model_path="data/model_v2.joblib").diagnose_all())


if __name__ == "__main__":
    main()
