"""Critical verification of the final integration-hook corrections."""
import ast
import importlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import uuid

import pytest
import yaml


def test_tui_rebound_names_exist_in_actual_server(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    server = importlib.import_module("tui_gateway.server")
    folder = Path(server.__file__).parent
    missing = []
    for path in folder.glob("*.py"):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in module.body:
            if not isinstance(node, ast.If) or "TYPE_CHECKING" not in ast.unparse(node.test):
                continue
            for statement in node.body:
                if isinstance(statement, ast.ImportFrom) and statement.module == "tui_gateway.server":
                    missing.extend(f"{path.name}:{item.name}" for item in statement.names
                                   if item.name not in vars(server))
    assert not missing, missing
    assert server._methods


def test_hosted_console_executor_retains_bounded_worker_pool(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from hermes_cli import console_engine

    monkeypatch.setattr(console_engine, "_console_run_executor", None)
    pool = console_engine._get_console_run_executor()
    try:
        assert pool._max_workers == 2
        assert pool.submit(lambda: "completed").result(timeout=10) == "completed"
    finally:
        pool.shutdown(wait=True)


def _gitleaks_hook(root):
    """The gitleaks entry of the repo's own pre-commit config: (repo, rev, args)."""
    config = yaml.safe_load((root / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == "gitleaks":
                return repo["repo"], repo["rev"], list(hook.get("args", []))
    return None


def _pre_commit_home():
    """Where pre-commit keeps its clones -- its own precedence, not a guess."""
    if os.environ.get("PRE_COMMIT_HOME"):
        return Path(os.environ["PRE_COMMIT_HOME"])
    if os.environ.get("XDG_CACHE_HOME"):
        return Path(os.environ["XDG_CACHE_HOME"]) / "pre-commit"
    return Path.home() / ".cache" / "pre-commit"


def _resolve_gitleaks(repo, rev):
    """The binary the pre-commit hook itself would run, else whatever is on PATH.

    The repo<hash> cache key is derived from a tempdir name, so it is neither
    stable across hook bumps nor the same on any two hosts. pre-commit records
    (repo, ref) -> path in its db.db, so ask that first; fall back to scanning
    every golangenv under the cache, then to PATH.
    """
    home = _pre_commit_home()
    exe = "gitleaks.exe" if os.name == "nt" else "gitleaks"
    candidates = []
    db = home / "db.db"
    if db.is_file():
        try:
            with sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True) as conn:
                rows = conn.execute(
                    "SELECT path FROM repos WHERE repo = ? AND ref = ?", (repo, rev)
                ).fetchall()
        except sqlite3.Error:
            rows = []
        candidates.extend(Path(row[0]) / "golangenv-default" / "bin" / exe for row in rows)
    candidates.extend(sorted(home.glob(f"repo*/golangenv-default/bin/{exe}")))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    on_path = shutil.which("gitleaks")
    return Path(on_path) if on_path else None


def _resolve_gitleaks_config(args):
    """The --config the hook passes, else the XDG location that path lives at."""
    for arg in args:
        if arg.startswith("--config="):
            configured = Path(arg[len("--config="):]).expanduser()
            if configured.is_file():
                return configured
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    fallback = xdg / "gitleaks" / "gitleaks.toml"
    return fallback if fallback.is_file() else None


def test_exact_fixture_exceptions_keep_unallowlisted_secret_detection():
    """An exact-fixture .gitleaksignore must not allowlist a fresh synthetic api_key.

    Runs the same gitleaks binary and ruleset the repo's pre-commit hook does.
    When neither is present on this host the test skips rather than fabricating
    a scanner: the contract under test is the ignore file's precision, and only
    the real scanner can falsify it.
    """
    root = Path(__file__).resolve().parents[1]
    hook = _gitleaks_hook(root)
    if hook is None:
        pytest.skip("no gitleaks hook in .pre-commit-config.yaml")
    repo, rev, args = hook
    scanner = _resolve_gitleaks(repo, rev)
    if scanner is None:
        pytest.skip(f"no gitleaks binary: not in {_pre_commit_home()} for {repo}@{rev}, not on PATH")
    config = _resolve_gitleaks_config(args)
    if config is None:
        pytest.skip("no gitleaks.toml: neither the hook's --config nor ~/.config/gitleaks/gitleaks.toml exists")
    synthetic = "api_key = '" + uuid.uuid4().hex + uuid.uuid4().hex + "'\n"
    result = subprocess.run(
        [str(scanner), "stdin", "--redact", "--no-banner",
         f"--config={config}",
         f"--gitleaks-ignore-path={root / '.gitleaksignore'}"],
        input=synthetic, text=True, capture_output=True, cwd=root, timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "leaks found" in result.stdout + result.stderr
