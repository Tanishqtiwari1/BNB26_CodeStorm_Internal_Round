"""Graph-based root-cause localization over agent trace graphs.

Nodes = steps (LLM decisions, tool calls, retrievals, final answer, task input).
Edges = data flow + control flow recovered from OpenTelemetry span links/parents.

Node features are LOCAL facts only (grounding, deviation from historical
baselines, retrieval checks, errors, node type, degree). No hand-made lineage
aggregates and no position: the network has to learn how errors propagate
along edges, which is what lets it follow the error source when it drifts
to new locations or new graph shapes.

  GNN        directional message passing (parents -> child, children -> parent),
             trained with a per-graph softmax over nodes (exactly one root cause).
             Trained with PyTorch; inference is plain NumPy (no torch at runtime).
  PageRank   training-free baseline: personalized PageRank on the reversed
             dependency graph, personalised by local anomaly (MicroRCA-style).
"""
import math

import numpy as np

from . import features as FT

KINDS = ["input", "llm", "retrieval", "tool", "final"]
NODE_FEATURES = (["value_z", "arg_grounding", "out_grounding", "has_null", "retrieval_relevance", "doc_len_z", "error", "exception",
                  "n_signals", "local_score", "has_value", "in_deg", "out_deg", "is_sink"] + [f"kind_{k}" for k in KINDS])


def graph_of(steps, norms):
    """-> (X [n, F], parents list-of-lists of indices, sig)"""
    sig = FT.step_signals(steps, norms)
    idx = {s["sid"]: i for i, s in enumerate(steps)}
    parents = [[idx[p] for p in s["parents"] if p in idx] for s in steps]
    children = [[] for _ in steps]
    for i, ps in enumerate(parents):
        for p in ps:
            children[p].append(i)
    X = np.zeros((len(steps), len(NODE_FEATURES)), dtype=np.float32)
    for i, s in enumerate(steps):
        d = sig[s["sid"]]
        X[i] = [min(d["value_z"], 20) / 5, d["arg_grounding"], d["out_grounding"], float(d["null_fields"] > 0), d["retrieval_relevance"],
                min(d["doc_len_z"], 20) / 5, d["error"], d["exception"], d["n_signals"], d["score"] / 4,
                float(d["value"] is not None), math.log1p(len(parents[i])), math.log1p(len(children[i])),
                float(not children[i] and s["kind"] != "final")] + [float(s["kind"] == k) for k in KINDS]
    return X, parents, children, sig


def _adj(parents, children, n):
    up = np.zeros((n, n), dtype=np.float32)
    dn = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for p in parents[i]:
            up[i, p] = 1.0 / len(parents[i])
        for c in children[i]:
            dn[i, c] = 1.0 / len(children[i])
    return up, dn


# ------------------------------------------------------------------ GNN (numpy inference)
def _relu(x):
    return np.maximum(x, 0)


def gnn_scores(W, X, parents, children):
    up, dn = _adj(parents, children, len(X))
    h = _relu(X @ W["in.w"].T + W["in.b"])
    for l in range(W["layers"]):
        h = _relu(h @ W[f"s{l}.w"].T + W[f"s{l}.b"] + (up @ h) @ W[f"u{l}.w"].T + (dn @ h) @ W[f"d{l}.w"].T)
    z = np.concatenate([h, X], axis=1)
    z = _relu(z @ W["o1.w"].T + W["o1.b"])
    logits = (z @ W["o2.w"].T + W["o2.b"]).ravel()
    e = np.exp(logits - logits.max())
    return logits, e / e.sum()


def train_gnn(graphs, epochs=60, hidden=64, layers=3, lr=3e-3, seed=0):
    """graphs: list of (X, parents, children, root_index)."""
    import torch
    import torch.nn as nn
    torch.manual_seed(seed)
    F = graphs[0][0].shape[1]

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.inp = nn.Linear(F, hidden)
            self.s = nn.ModuleList([nn.Linear(hidden, hidden) for _ in range(layers)])
            self.u = nn.ModuleList([nn.Linear(hidden, hidden, bias=False) for _ in range(layers)])
            self.d = nn.ModuleList([nn.Linear(hidden, hidden, bias=False) for _ in range(layers)])
            self.o1 = nn.Linear(hidden + F, hidden)
            self.o2 = nn.Linear(hidden, 1)

        def forward(self, X, UP, DN, mask):
            h = torch.relu(self.inp(X))
            for l in range(layers):
                h = torch.relu(self.s[l](h) + self.u[l](UP @ h) + self.d[l](DN @ h))
            z = torch.relu(self.o1(torch.cat([h, X], -1)))
            return self.o2(z).squeeze(-1).masked_fill(~mask, -1e9)

    def batches(gs, bs=64, shuffle=True):
        order = np.random.default_rng(seed).permutation(len(gs)) if shuffle else np.arange(len(gs))
        for k in range(0, len(gs), bs):
            chunk = [gs[j] for j in order[k:k + bs]]
            n = max(len(g[0]) for g in chunk)
            Xb = np.zeros((len(chunk), n, F), np.float32)
            U = np.zeros((len(chunk), n, n), np.float32)
            D = np.zeros((len(chunk), n, n), np.float32)
            M = np.zeros((len(chunk), n), bool)
            y = np.zeros(len(chunk), np.int64)
            for b, (X, ps, cs, r) in enumerate(chunk):
                m = len(X)
                Xb[b, :m] = X
                u, d = _adj(ps, cs, m)
                U[b, :m, :m], D[b, :m, :m] = u, d
                M[b, :m] = True
                y[b] = r
            yield (torch.tensor(Xb), torch.tensor(U), torch.tensor(D), torch.tensor(M), torch.tensor(y))

    net = Net()
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=1e-4)
    for ep in range(epochs):
        net.train()
        tot = 0.0
        for Xb, U, D, M, y in batches(graphs):
            loss = nn.functional.cross_entropy(net(Xb, U, D, M), y)
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss.detach()) * len(y)
        if ep % 20 == 19:
            print(f"  gnn epoch {ep + 1}: loss {tot / len(graphs):.3f}")
    sd = {k: v.detach().numpy() for k, v in net.state_dict().items()}
    W = {"layers": layers, "in.w": sd["inp.weight"], "in.b": sd["inp.bias"], "o1.w": sd["o1.weight"], "o1.b": sd["o1.bias"],
         "o2.w": sd["o2.weight"], "o2.b": sd["o2.bias"]}
    for l in range(layers):
        W[f"s{l}.w"], W[f"s{l}.b"] = sd[f"s.{l}.weight"], sd[f"s.{l}.bias"]
        W[f"u{l}.w"], W[f"d{l}.w"] = sd[f"u.{l}.weight"], sd[f"d.{l}.weight"]
    return W


# ------------------------------------------------------------------ PageRank baseline
def pagerank_scores(sig, steps, parents, alpha=0.85, iters=50):
    n = len(steps)
    a = np.array([sig[s["sid"]]["score"] + 1e-3 for s in steps], dtype=float)
    pers = a / a.sum()
    # walk from each node to its parents (upstream), weighted by parent anomaly
    P = np.zeros((n, n))
    for i in range(n):
        ps = parents[i]
        if ps:
            w = np.array([a[p] for p in ps])
            P[i, ps] = w / w.sum()
        else:
            P[i, i] = 1.0
    r = pers.copy()
    for _ in range(iters):
        r = (1 - alpha) * pers + alpha * (r @ P)
    return r * a  # rank anomalous nodes that sit upstream of other anomalies
