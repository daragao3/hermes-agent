"""SR-493 (ADR-0024 §4): library exceptions must not be bucketed as
non-retryable local validation errors.

The loop body's error handling was extracted from run_agent.py to
agent/conversation_loop.py in the v0.15.x refactor, and the local-validation
bucket then moved again, to ``agent.turn_api_error._is_local_validation_error``.
This test used to grep conversation_loop.py for the wiring, which broke on that
second move while the behaviour stayed intact -- so it now pins the BEHAVIOUR
at the seam that decides, wherever that seam lives.
"""


def _exc_from_file(exc_type, fake_filename):
    # Raise from code whose co_filename we control, so the deepest traceback
    # frame reports ``fake_filename`` (same technique as test_error_classifier).
    code = compile(f"raise {exc_type.__name__}('boom')", fake_filename, "exec")
    try:
        exec(code, {})
    except exc_type as exc:
        return exc
    raise AssertionError("unreachable")


def test_run_agent_excludes_library_exceptions_from_local_validation():
    from agent.turn_api_error import _is_local_validation_error

    for exc_type in (TypeError, ValueError):
        lib = _exc_from_file(
            exc_type, "/usr/lib/python3.11/site-packages/openai/lib/_parsing/_responses.py"
        )
        assert _is_local_validation_error(lib) is False, (
            f"SR-493: a library-internal {exc_type.__name__} was bucketed as a "
            "non-retryable local validation error"
        )

        ours = _exc_from_file(exc_type, "/home/u/.hermes/agent-src/agent/some_module.py")
        assert _is_local_validation_error(ours) is True, (
            f"control: a {exc_type.__name__} from our own code must still be local"
        )
