"""``scripts/hermes_telegram_setup.py``'s ``main`` keeps the ``.env`` round-trip contract.

The wizard's last step appends ``TELEGRAM_HOME_CHANNEL`` by reading ALL of
``~/.hermes/profiles/main/.env``, concatenating one line and writing the whole
file back, so every line it never touched is round-tripped through that write
and has to survive byte-for-byte.  Until 2026-09-20 (merge ``4305f20db3``) both
halves were a plain ``encoding="utf-8"`` with no ``errors=`` and no
``newline=``.  Found by scripts/check_env_writer_contract.py, which pins this
writer in ``KNOWN_WRITERS``.

The other three writers fixed in that merge each got a behavioural test; this
one did not, because the writer sits at the end of a long interactive
``main()``.  It turns out three seams reach it -- the bot token, the Telegram
API and the home directory -- so the round-trip below drives the REAL
``main()`` and the production code stays untouched.

The BOM axis bites differently here than in the sibling tests.  Those writers
match a key per line, so a BOM hides the FIRST key and they append a duplicate
of the line they meant to update; this one tests ``"TELEGRAM_HOME_CHANNEL" not
in content`` over the whole file, and a leading BOM cannot hide a substring.
What ``utf-8-sig`` buys here is that the BOM is not re-emitted into a file a
POSIX shell sources -- so that is what the BOM test pins, alongside the
no-duplicate property the siblings assert.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests._home_isolation import redirect_home

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "hermes_telegram_setup.py"
)

CHAT_ID = "-1001234567890"
# What main() concatenates: a blank separator line, the key, a trailing LF.
APPENDED = f"\nTELEGRAM_HOME_CHANNEL={CHAT_ID}\n".encode()


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_telegram_setup_env", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_telegram_api(token, method, **params):
    """Every call main() makes, returning the one field each caller reads back."""
    if method == "createForumTopic":
        return {"message_thread_id": 42}
    if method == "sendMessage":
        return {"message_id": 7}
    if method == "getChat":
        return {"title": "Hermes Event Bus", "type": "supergroup"}
    return {}


def _run_wizard(monkeypatch, tmp_path, env_bytes: bytes) -> bytes:
    """Drive the real ``main()`` over an ``.env`` of *env_bytes*; return the result."""
    mod = load_module()
    home = redirect_home(monkeypatch, tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home / ".hermes"))

    env_path = home / ".hermes" / "profiles" / "main" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes, never write_text: write_text emits CRLF on Windows and would
    # hide the very defect these tests exist to catch.
    env_path.write_bytes(env_bytes)

    # get_bot_token reads the SAME .env with a bare encoding="utf-8". It is an
    # unpaired pre-check -- out of the round-trip contract's scope, since
    # nothing it reads is written back -- but it would raise on the cp1252
    # fixture before main() ever reached the writer under test.
    monkeypatch.setattr(mod, "get_bot_token", lambda: "test-token")
    monkeypatch.setattr(mod, "telegram_api", _fake_telegram_api)
    monkeypatch.setattr(sys, "argv", ["hermes_telegram_setup.py", f"--chat-id={CHAT_ID}"])

    mod.main()
    return env_path.read_bytes()


def test_non_utf8_env_preserves_unrelated_bytes(tmp_path, monkeypatch):
    """errors="surrogateescape" on both halves: a cp1252 byte on an unrelated
    line must round-trip.  Bare utf-8 raises UnicodeDecodeError out of the
    middle of the wizard, and errors="replace" writes U+FFFD over it."""
    original = b"NAME=caf\xe9\nTELEGRAM_BOT_TOKEN=abc\n"

    body = _run_wizard(monkeypatch, tmp_path, original)

    assert body == original + APPENDED


def test_update_leaves_untouched_lines_byte_identical(tmp_path, monkeypatch):
    original = b"FIRST=1\nMIDDLE=2\nLAST=3\n"

    body = _run_wizard(monkeypatch, tmp_path, original)

    assert body == original + APPENDED


def test_lf_is_kept_on_every_platform(tmp_path, monkeypatch):
    """newline="\\n" on the write: text mode would turn every untouched LF into
    CRLF on Windows, leaving a \\r in every value for a POSIX shell that sources
    the same file."""
    body = _run_wizard(monkeypatch, tmp_path, b"FIRST=1\nLAST=2\n")

    assert b"\r\n" not in body


def test_bom_does_not_duplicate_the_first_key(tmp_path, monkeypatch):
    """encoding="utf-8-sig" on the read + "utf-8" on the write: a Notepad BOM is
    consumed, not carried into the rewritten file, and the appended key lands
    exactly once."""
    body = _run_wizard(monkeypatch, tmp_path, b"\xef\xbb\xbfFIRST=1\nLAST=2\n")

    assert body.count(b"TELEGRAM_HOME_CHANNEL=") == 1
    assert not body.startswith(b"\xef\xbb\xbf")
    assert body == b"FIRST=1\nLAST=2\n" + APPENDED
