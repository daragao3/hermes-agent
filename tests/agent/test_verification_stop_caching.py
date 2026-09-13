"""Verification-loop synthetic scaffolding must never reach durable session state.

verify_on_stop / pre_verify inject a synthetic user nudge to keep the agent
going one more turn before it can claim completion. The assistant response is
real content that persists and is emitted to the UI as an interim message.
Only the nudge (the synthetic user message) is flagged, so only the nudge
gets stripped from the durable transcript. This test file verifies:

  - The verification-loop flags remain registered in
    ``_EPHEMERAL_SCAFFOLDING_FLAGS`` (so nudges are stripped).
  - The DB flush drops only the nudge, keeping the assistant candidate.
  - The JSON log drops only the nudge, keeping the assistant candidate.
"""

import sys
from unittest.mock import MagicMock

import pytest




@pytest.fixture(autouse=True)
def _restore_sys_modules():
    """``_fresh_run_agent`` wipes the agent stack out of ``sys.modules``. Put the original
    module objects back afterwards: sibling test files hold module-level references into
    ``hermes_cli.*`` / ``tools.*`` and their monkeypatches would otherwise land on modules
    the app no longer imports."""
    saved = dict(sys.modules)
    yield
    _restore_modules(saved)


def _restore_modules(saved):
    sys.modules.clear()
    sys.modules.update(saved)
    # Re-imports rebound ``pkg.<child>`` attributes to the fresh module objects; point them
    # back so ``from pkg import child`` and ``sys.modules["pkg.child"]`` agree again.
    for name, mod in saved.items():
        parent, _, child = name.rpartition(".")
        if parent and parent in saved:
            try:
                setattr(saved[parent], child, mod)
            except Exception:
                pass


def _fresh_run_agent(hermes_home):
    for mod in list(sys.modules):
        if mod == "run_agent" or mod.startswith("agent.") or mod.startswith("tools.") or mod.startswith("hermes_"):
            del sys.modules[mod]
    import run_agent  # noqa: F401
    return sys.modules["run_agent"]


def test_verification_flags_registered_as_ephemeral(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    _fresh_run_agent(tmp_path)
    from agent.session_persistence import _EPHEMERAL_SCAFFOLDING_FLAGS, _is_ephemeral_scaffolding

    assert "_verification_stop_synthetic" in _EPHEMERAL_SCAFFOLDING_FLAGS
    assert "_pre_verify_synthetic" in _EPHEMERAL_SCAFFOLDING_FLAGS

    # The nudge messages ARE scaffolding (they carry the synthetic flag).
    assert _is_ephemeral_scaffolding(
        {"role": "user", "content": "[System: run tests]", "_pre_verify_synthetic": True}
    )
    assert _is_ephemeral_scaffolding(
        {"role": "user", "content": "[System: run tests]", "_verification_stop_synthetic": True}
    )
    # Real messages (including the assistant candidate) are not.
    assert not _is_ephemeral_scaffolding({"role": "user", "content": "hi"})
    assert not _is_ephemeral_scaffolding({"role": "assistant", "content": "premature done"})


def _make_agent(ra, session_id, tmp_path):
    agent = ra.AIAgent(
        session_id=session_id,
        api_key="test-key",
        base_url="http://127.0.0.1:8000/v1",
        provider="openai-compat",
        model="test-model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    agent._session_db = MagicMock()
    agent._session_db_created = True

    agent.logs_dir = tmp_path / "logs"
    agent.logs_dir.mkdir(parents=True, exist_ok=True)
    return agent


def test_db_flush_drops_only_nudge_keeps_candidate(tmp_path, monkeypatch):
    """The assistant candidate is NOT flagged synthetic, so it persists.
    Only the nudge (flagged synthetic) is dropped from the DB flush."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    ra = _fresh_run_agent(tmp_path)
    agent = _make_agent(ra, "sess_db", tmp_path)

    messages = [
        {"role": "user", "content": "hi"},
        # Assistant candidate — NOT flagged synthetic, persists.
        {"role": "assistant", "content": "premature done"},
        # Nudge — flagged synthetic, gets dropped.
        {"role": "user", "content": "[System: run tests]", "_verification_stop_synthetic": True},
        {"role": "assistant", "content": "verified and clean"},
    ]

    agent._flush_messages_to_session_db(messages, conversation_history=[])

    persisted = [
        msg.get("content")
        for _args, kwargs in agent._session_db.append_messages_batch.call_args_list
        for msg in kwargs["messages"]
    ]
    assert "hi" in persisted
    assert "verified and clean" in persisted
    # The assistant candidate persists — it is real content.
    assert "premature done" in persisted
    # Only the nudge is dropped.
    assert "[System: run tests]" not in persisted


# Grafted from the fork side in the 0.21.1 merge: definitions the other side
# has and this file's base side does not.

@pytest.fixture(autouse=True)
def _restore_purged_modules():
    """Put ``sys.modules`` back the way ``_fresh_run_agent`` found it.

    ``_fresh_run_agent`` drops every ``run_agent`` / ``agent.*`` / ``tools.*``
    / ``hermes_*`` module and re-imports, which is the right way to pick up a
    changed ``HERMES_HOME``. What it never did is put them back, so every test
    collected after this file ran against freshly-imported duplicates while
    already-imported test modules still held references to the originals.

    Two live copies of a module means two distinct class objects with the same
    name, so ``except SomeError`` and ``isinstance`` stop matching across the
    boundary. That is why the damage landed almost entirely on error-path
    assertions: this file was responsible for all 7 failures in
    ``transports/test_codex_app_server_session.py`` (``*_failure_returns_error``,
    ``oauth_*_failure``, ``*_raises``), confirmed by running the two files
    together — 7 failed — and by the innocent-verdict control on
    ``test_vision_routing_31179.py``, which purges too but happened to hit
    nothing the victim depends on.

    Restoring ``sys.modules`` alone is NOT enough, and this is the part that is
    easy to get wrong: ``import a.b as x`` reads ``sys.modules``, while
    ``from a.b import y`` reads the attribute ``b`` on the parent package. Fix
    only the first and half the imports still resolve to the stale copy. The
    same two-step was needed in
    ``tests/agent/test_empty_tool_name_loop_dampening.py``.
    """
    snapshot = dict(sys.modules)
    yield
    purged = {
        name: module for name, module in snapshot.items()
        if sys.modules.get(name) is not module
    }
    for name, module in purged.items():
        sys.modules[name] = module
    for name, module in purged.items():
        parent_name, _, child = name.rpartition(".")
        if not parent_name:
            continue
        parent = sys.modules.get(parent_name)
        if parent is not None and getattr(parent, child, None) is not module:
            setattr(parent, child, module)

