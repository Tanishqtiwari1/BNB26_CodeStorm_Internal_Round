from .. import agent as A
from .base import Adapter


class TravelSim(Adapter):
    name = "travel-sim"
    label = "Travel-expense agent (simulated)"
    description = "Deterministic simulated agent used to build the labelled benchmark corpus."

    def build_plan(self, task):
        return A.build_plan(task)

    def judge(self, task, final):
        return A.judge(task, final)

    def latency(self, kind, measured_ms, rng):
        return A._latency(kind, rng)  # simulated, identical to corpus generation
