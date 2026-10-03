"""Agent adapters.

Black Box's recorder, features, model and replay engine are agent-agnostic;
an adapter tells them how a particular agent builds its step DAG, how a run
is judged, and how latency is recorded. Replay needs an adapter because
re-executing a step means calling that agent's real step function again.

  travel-sim  deterministic simulated agent (benchmark corpus)
  travel-llm  the same workflow with real LLM calls (Anthropic, or mock offline)
  external    runs recorded through blackbox.sdk -- diagnosable, not replayable
"""
from .base import Adapter, ReplayUnsupported
from .travel_llm import TravelLLM
from .travel_sim import TravelSim

ADAPTERS = {a.name: a for a in (TravelLLM(), TravelSim())}


def get_adapter(name):
    a = ADAPTERS.get(name or "travel-sim")
    if a is None:
        raise ReplayUnsupported(f"no replay adapter registered for agent '{name}'")
    return a


__all__ = ["ADAPTERS", "Adapter", "ReplayUnsupported", "get_adapter"]
