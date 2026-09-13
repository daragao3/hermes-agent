"""Real Git history must invalidate only changed Python caches, safely."""

import subprocess

import pytest

from hermes_cli import main, main_web_build


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        check=True, capture_output=True, text=True, timeout=20,
    ).stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("__pycache__/\n.bytecode-fingerprint*\n", encoding="utf-8")
    for folder in ("app", "legacy", "other", "tests"):
        (repo / folder).mkdir()
        (repo / folder / "module.py").write_text("value = 1\n", encoding="utf-8")
    _commit(repo)
    return repo


def _commit(repo):
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    return main._read_git_revision_fingerprint(repo)


def _cache(repo, folder):
    path = repo / folder / "__pycache__"
    path.mkdir(exist_ok=True)
    (path / "module.cpython-312.pyc").write_bytes(b"stale")
    return path


def test_git_delta_preserves_unaffected_caches_and_covers_renames_and_deletes(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(main, "PROJECT_ROOT", repo)
    main_web_build._record_bytecode_fingerprint()
    app, legacy, other, tests = [_cache(repo, name) for name in ("app", "legacy", "other", "tests")]
    (repo / "tests/module.py").write_text("value = 2\n", encoding="utf-8")
    (repo / "README.md").write_text("documentation change\n", encoding="utf-8")
    _commit(repo)

    main_web_build._sweep_stale_bytecode_if_checkout_changed()
    assert not tests.exists()
    assert app.exists() and legacy.exists() and other.exists()

    (repo / "renamed").mkdir()
    (repo / "app/module.py").rename(repo / "renamed/module.py")
    (repo / "legacy/module.py").unlink()
    renamed = _cache(repo, "renamed")
    _commit(repo)
    main_web_build._sweep_stale_bytecode_if_checkout_changed()
    assert not app.exists() and not legacy.exists() and not renamed.exists()
    assert other.exists()


@pytest.mark.parametrize("ambiguity", ["dirty", "untracked", "invalid_ref"])
def test_ambiguous_python_falls_back_without_stamping_a_concurrent_future_head(tmp_path, monkeypatch, ambiguity):
    repo = _repo(tmp_path)
    monkeypatch.setattr(main, "PROJECT_ROOT", repo)
    main_web_build._record_bytecode_fingerprint()
    (repo / "README.md").write_text("new commit\n", encoding="utf-8")
    captured = _commit(repo)
    if ambiguity == "dirty":
        (repo / "app/module.py").write_text("uncommitted = True\n", encoding="utf-8")
    elif ambiguity == "untracked":
        (repo / "untracked.py").write_text("uncommitted = True\n", encoding="utf-8")
    else:
        (repo / main_web_build._BYTECODE_FINGERPRINT_FILE).write_text("git:refs/heads/main:" + "f" * 40, encoding="utf-8")
    cache = _cache(repo, "other")
    real_clear = main._clear_bytecode_cache

    def clear_and_advance(root):
        removed = real_clear(root)
        (repo / "README.md").write_text("concurrent commit\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-qm", "concurrent")
        return removed

    monkeypatch.setattr(main, "_clear_bytecode_cache", clear_and_advance)
    main_web_build._sweep_stale_bytecode_if_checkout_changed()

    assert not cache.exists(), "ambiguous dirty Python must use the full sweep"
    assert (repo / main_web_build._BYTECODE_FINGERPRINT_FILE).read_text(encoding="utf-8") == captured
    assert main._read_git_revision_fingerprint(repo) != captured
    if ambiguity != "invalid_ref":
        source = repo / ("app/module.py" if ambiguity == "dirty" else "untracked.py")
        assert "uncommitted" in source.read_text(encoding="utf-8")
