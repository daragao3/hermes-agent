"""Hermes JobFlow as LangGraph (Phase B of ADR-0020).

Stage-1 (shipped): Matcher scoring as a typed graph node. Default via `invoke()`.
Stage-3 (shipped): Full pipeline Matcher->Tailor->HITL->Apply->Tracker with
checkpointing. Access via `invoke_full()`.

Public API:
    from graphs import (
        build_jobflow_graph,   # Stage-1 graph (Matcher-only)
        build_full_graph,      # Stage-3 graph (full pipeline + checkpointer)
        JobFlowState,
        invoke,                # Stage-1 runner
        invoke_full,           # Stage-3 runner with checkpointing
    )
"""

# Exports resolve lazily (PEP 562). ``langgraph`` is a local-carry dependency
# (requirements-local-graph.txt) that is not part of the locked project
# environment, and the eager ``from .jobflow import ...`` made every submodule
# -- including the langgraph-free ``graphs._profile`` -- unimportable without
# it. ``from graphs import invoke`` still works exactly as before.
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # static view of the lazy exports below
    from .critic import CriticState, build_critic_graph, invoke_critic
    from .jobflow import (
        JobFlowState,
        build_full_graph,
        build_jobflow_graph,
        invoke,
        invoke_full,
        resume_full,
    )

_EXPORTS = {
    "JobFlowState": "jobflow",
    "build_full_graph": "jobflow",
    "build_jobflow_graph": "jobflow",
    "invoke": "jobflow",
    "invoke_full": "jobflow",
    "resume_full": "jobflow",
    "CriticState": "critic",
    "build_critic_graph": "critic",
    "invoke_critic": "critic",
}


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(f".{module_name}", __name__), name)
    globals()[name] = value
    return value


__all__ = [
    # JobFlow
    "JobFlowState",
    "build_full_graph",
    "build_jobflow_graph",
    "invoke",
    "invoke_full",
    "resume_full",
    # Critic
    "CriticState",
    "build_critic_graph",
    "invoke_critic",
]
