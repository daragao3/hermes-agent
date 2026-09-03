"""Attribution tests for ``control_center.storage.resume_graph``.

The Control Center's approve/reject buttons are HTMX form posts on a loopback
FastAPI app. Auth is OPT-IN (``HERMES_CC_TOKEN``), and even when enabled the
token is a bearer secret that identifies nobody. So nothing in such a request
establishes WHO acted, and the durable ``pipeline.json`` audit entry this
function writes must name the SURFACE, never a person.

Before 2026-09-03 it hardcoded ``actor="diego"`` and a note reading
``Control Center: diego clicked ...``. That is wrong attribution rather than
missing attribution, and a confident wrong answer stops a postmortem looking.
It also fed ``jobflow_quality.golden_set._HUMAN_ACTORS = ("diego",)``, which
reads a ``diego`` actor in pipeline history as proof a real person decided.
"""
from __future__ import annotations

import importlib.machinery
import sys
import types
from unittest.mock import MagicMock

import pytest

import pipeline_state
from control_center import storage


@pytest.fixture
def fake_graphs(monkeypatch):
    """Stub ``graphs`` so the test never imports the real package (~10s cold).

    The stub carries a REAL ``ModuleSpec``: ``resume_graph`` calls
    ``importlib.util.find_spec("graphs")``, which raises ``ValueError`` for a
    module that is in ``sys.modules`` with ``__spec__`` set to None.
    """
    mod = types.ModuleType("graphs")
    mod.__spec__ = importlib.machinery.ModuleSpec("graphs", None)
    mod.resume_full = MagicMock(
        return_value={
            "job_id": "job-1",
            "job": {"title": "VP AI Products", "company": "Acme"},
            "tracker_stage": "ready_to_submit",
            "score": 91,
        }
    )
    monkeypatch.setitem(sys.modules, "graphs", mod)
    return mod


@pytest.fixture
def fake_manager(monkeypatch):
    """``resume_graph`` does ``from pipeline_state import PipelineManager``
    inside the function body, so patching the module attribute is enough."""
    mgr = MagicMock()
    monkeypatch.setattr(pipeline_state, "PipelineManager", MagicMock(return_value=mgr))
    return mgr


def test_resume_graph_audit_entry_never_claims_a_person(fake_graphs, fake_manager):
    storage.resume_graph("job-job-1", "approved", "comp band matches")

    kw = fake_manager.update_stage.call_args.kwargs
    assert kw["actor"] != "diego"
    assert kw["actor"] == storage.unattributed_actor("control_center")


def test_resume_graph_audit_note_never_names_a_person(fake_graphs, fake_manager):
    """The note is the human-readable half of the same durable record, so it
    has to agree with the actor field. Fixing one and not the other leaves the
    false claim exactly where a reader looks first."""
    storage.resume_graph("job-job-1", "approved", "comp band matches")

    notes = fake_manager.update_stage.call_args.kwargs["notes"]
    assert "diego" not in notes.lower()
    assert "comp band matches" in notes  # the operator's reason still survives


def test_resume_graph_threads_an_explicit_actor_when_one_is_known(
    fake_graphs, fake_manager
):
    """The parameter exists so an authenticated caller can supply the truth.
    Nothing derives it -- see the module docstring on why a guesser would
    re-create the defect."""
    storage.resume_graph("job-job-1", "approved", actor="diego")

    assert fake_manager.update_stage.call_args.kwargs["actor"] == "diego"


def test_resume_graph_blank_actor_counts_as_absent(fake_graphs, fake_manager):
    """A blank actor must fall back, not be written through. A falsy actor in
    the record reads as attributed-to-nothing rather than as missing -- the
    same property cron_lifecycle_emitter.resolve_caller makes load-bearing."""
    storage.resume_graph("job-job-1", "rejected", actor="   ")

    assert fake_manager.update_stage.call_args.kwargs["actor"] == (
        storage.unattributed_actor("control_center")
    )


def test_unattributed_actor_names_the_surface_and_marks_itself(fake_graphs):
    """The value must be self-describing: consumers see the actor string alone
    (events/subscribers/telegram_notifier.py renders ``p.get('actor')``)."""
    assert storage.unattributed_actor("control_center") == "unattributed:control_center"
    assert storage.unattributed_actor("") == "unattributed:unknown_surface"
    assert storage.unattributed_actor(None) == "unattributed:unknown_surface"


def test_resume_graph_still_writes_the_control_center_source(
    fake_graphs, fake_manager
):
    """REGRESSION GUARD, not a fix assertion -- this passes on both sides of the
    fix by design. It is here because ``source`` is now the only thing keeping
    the STAGE_TRANSITION event at HIGH priority: pipeline_state.manager bumps on
    ``source in human_surfaces OR actor == "diego"``, and this change removes the
    second disjunct for this path."""
    storage.resume_graph("job-job-1", "approved")

    assert fake_manager.update_stage.call_args.kwargs["source"] == "control_center"
