import random

from .. import agent as A


class ReplayUnsupported(Exception):
    pass


class Adapter:
    """Minimal contract an agent implements to be recorded *and* replayed."""

    name = "base"
    label = "Base agent"
    description = ""

    def build_plan(self, task):
        raise NotImplementedError

    def judge(self, task, final):
        """-> (success: bool, expected: dict)"""
        raise NotImplementedError

    def latency(self, kind, measured_ms, rng):
        return measured_ms

    def meta(self):
        return {}

    def execute(self, task, fault=None, rng=None, **replay_kw):
        return A.execute(task, fault=fault, rng=rng or random.Random(0), plan_fn=self.build_plan,
                         latency_fn=self.latency, **replay_kw)
