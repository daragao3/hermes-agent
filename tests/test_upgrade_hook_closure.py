"""Critical verification of the final integration-hook corrections."""
import ast
import importlib
from pathlib import Path
import subprocess
import uuid


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


def test_exact_fixture_exceptions_keep_unallowlisted_secret_detection():
    root = Path(__file__).resolve().parents[1]
    scanner = Path("C:/Users/diego/.cache/pre-commit/repo4xql6j0c/golangenv-default/bin/gitleaks.exe")
    synthetic = "api_key = '" + uuid.uuid4().hex + uuid.uuid4().hex + "'\n"
    result = subprocess.run(
        [str(scanner), "stdin", "--redact", "--no-banner",
         "--config=C:/Users/diego/.config/gitleaks/gitleaks.toml",
         f"--gitleaks-ignore-path={root / '.gitleaksignore'}"],
        input=synthetic, text=True, capture_output=True, cwd=root, timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "leaks found" in result.stdout + result.stderr
