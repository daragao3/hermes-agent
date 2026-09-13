"""Read deployment acceptance evidence without advancing it or inferring runtime identity."""

import hashlib
import json
import re
from pathlib import Path


def changed_paths(status: str) -> set[str]:
    """Paths from Git porcelain -z, including both sides of a rename."""
    records = iter(status.split("\0"))
    paths = set()
    for record in records:
        if not record:
            continue
        paths.add(record[3:])
        if "R" in record[:2] or "C" in record[:2]:
            original = next(records, "")
            if original:
                paths.add(original)
    return paths


def deployment_evidence(repo: Path, head: str, dirty_paths: set[str], baseline_path: Path) -> dict:
    """Acceptance names an exact clean source tree; loaded process code is separate.

    A missing receipt is unknown, while a present but invalid receipt is
    unverified. Only the baseline's explicit dirty-path exclusions are
    honored; every other tracked or untracked change is unaccepted.
    """
    result = {"deployment_state": "unknown", "accepted_commit": "", "deployment_detail": ""}
    if not baseline_path.exists():
        return result
    result["deployment_state"] = "unverified"
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        if not isinstance(baseline, dict) or baseline.get("schema_version") != 1 or baseline.get("state") != "accepted":
            raise ValueError("baseline is not an accepted v1 receipt")
        if Path(baseline.get("repo_path", "")).resolve() != repo.resolve():
            raise ValueError("baseline belongs to a different checkout")
        commit = baseline.get("commit", "")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("baseline commit is not a full SHA")
        for key in ("validation_receipt", "reload_receipt"):
            receipt_path = Path(baseline.get(key, ""))
            if not receipt_path.is_absolute():
                raise ValueError(f"{key} must be absolute")
            expected = baseline.get(f"{key}_sha256")
            if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != expected:
                raise ValueError(f"{key} hash mismatch")
        excluded = baseline.get("excluded_dirty_paths", [])
        if not isinstance(excluded, list) or any(not isinstance(path, str) for path in excluded):
            raise ValueError("invalid excluded_dirty_paths")
        unexpected = dirty_paths - set(excluded)
        result.update(accepted_commit=commit,
                      deployment_state="accepted" if head == commit and not unexpected else "unaccepted")
        if unexpected:
            result["deployment_detail"] = "Unaccepted dirty paths: " + ", ".join(sorted(unexpected)[:5])
    except (OSError, ValueError, TypeError) as exc:
        result["deployment_detail"] = str(exc)
    return result
