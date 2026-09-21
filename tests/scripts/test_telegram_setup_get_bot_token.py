"""``scripts/hermes_telegram_setup.py``'s ``get_bot_token`` reads a live ``.env``.

It is an UNPAIRED read -- the token is never written back -- so
scripts/check_env_writer_contract.py deliberately leaves it out of the
byte-preservation contract, and the sibling round-trip test stubs it out.
That scoping is right for the contract and wrong for the wizard: until
2026-09-20 the read was a bare ``encoding="utf-8"``, so one cp1252 byte
anywhere in ``~/.hermes/profiles/main/.env`` raised ``UnicodeDecodeError``
before the wizard did anything, and a Notepad BOM on line 1 hid
``TELEGRAM_BOT_TOKEN=`` behind three invisible bytes and fell through to the
environment-variable path.  Plain reachability, not corruption -- which is why
the writer guard could never flag it.  Found while writing the sibling test
(loops telegram-setup-env-writer-behavioural-test-20260920, FINDING 2).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests._home_isolation import redirect_home

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "hermes_telegram_setup.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_telegram_setup_token", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _get_bot_token_over(monkeypatch, tmp_path, env_bytes: bytes) -> str:
    mod = load_module()
    home = redirect_home(monkeypatch, tmp_path)
    env_path = home / ".hermes" / "profiles" / "main" / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    # write_bytes, never write_text: the fixture's bytes ARE the test.
    env_path.write_bytes(env_bytes)
    # If the .env read fell through, the env-var path must not rescue it.
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return mod.get_bot_token()


def test_bom_and_cp1252_byte_elsewhere_still_yield_the_token(tmp_path, monkeypatch):
    """utf-8-sig consumes a leading BOM so the key on line 1 is still matched,
    and surrogateescape lets a cp1252 byte on an UNRELATED line pass through
    instead of raising out of the wizard's first step."""
    token = _get_bot_token_over(
        monkeypatch,
        tmp_path,
        b"\xef\xbb\xbfTELEGRAM_BOT_TOKEN=123456:abc-DEF\nNAME=caf\xe9\n",
    )

    assert token == "123456:abc-DEF"
