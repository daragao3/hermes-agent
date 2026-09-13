"""SR-493 (ADR-0024 §4): library exceptions must not be bucketed as
non-retryable local validation errors. In 0.21.1 the local-validation
classifier lives in agent/turn_api_error.py.
"""

import re
from pathlib import Path


def test_run_agent_excludes_library_exceptions_from_local_validation():
    src = Path(__file__).resolve().parents[2] / "agent" / "turn_api_error.py"
    text = src.read_text(encoding="utf-8", errors="replace")
    assert "is_library_exception" in text, "SR-493 not wired into turn_api_error"
    # Must be used to exclude library exceptions from the local-validation
    # bucket; 0.21.1 extracted the predicate into a helper return.
    assert re.search(r"return not is_library_exception\(api_error\)", text)
