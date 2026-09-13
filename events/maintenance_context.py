"""Read-only correlation with an explicitly declared gateway maintenance window."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from events.paths import hermes_repo_root


def gateway_maintenance_context(*, path: Path | None = None, now=None) -> dict | None:
    path = path or hermes_repo_root() / "state" / "maintenance-window.json"
    now = now or datetime.now(timezone.utc)
    try:
        with path.open("rb") as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            return None
        marker = json.loads(raw.decode("utf-8-sig"))
        owner = marker.get("owner")
        reason = marker.get("reason")
        rows = marker.get("suppressed_rows")
        if (not isinstance(owner, str) or not owner.strip() or len(owner) > 120
                or any(ord(c) < 32 for c in owner)
                or not isinstance(reason, str) or not reason.strip() or len(reason) > 240
                or any(ord(c) < 32 for c in reason)
                or not isinstance(rows, list)
                or any(not isinstance(row, str) or not row.strip() for row in rows)
                or not any(isinstance(row, str) and row.casefold() in
                           {"hermes gateway", "hermes gateway*"} for row in rows)
                or any(row == "*" for row in rows)):
            return None
        opened = datetime.fromisoformat(marker["opened_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(marker["expires_at"].replace("Z", "+00:00"))
        if opened.tzinfo is None or expires.tzinfo is None:
            return None
        deadline = min(expires, opened + timedelta(hours=8))
        if not opened <= now < deadline:
            return None
        return {
            "basis": "declared_gateway_window", "owner": owner.strip(),
            "window_id": hashlib.sha256(raw).hexdigest(),
            "observed_at": now.isoformat(), "deadline": deadline.isoformat(),
            "readiness": "unconfirmed",
        }
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def gateway_stop_body(payload: dict) -> str:
    text = f"Gateway stopped ({payload.get('exit_reason', 'unknown')})."
    context = payload.get("maintenance_context")
    if isinstance(context, dict) and context.get("basis") == "declared_gateway_window":
        text += (f" Declared gateway maintenance at stop: {context.get('owner', '?')}; "
                 f"window deadline {context.get('deadline', '?')}. Readiness remains unconfirmed.")
    return text
