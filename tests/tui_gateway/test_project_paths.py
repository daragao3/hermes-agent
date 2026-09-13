"""Real filesystem policy and per-request work bounds for project classification."""

import os
import subprocess
from collections import Counter

from tui_gateway.project_paths import ProjectPathPolicy


def test_classification_preserves_symlinks_and_refreshes_profile_between_builds(tmp_path):
    first = tmp_path / "profile-a"
    second = tmp_path / "profile-b"
    child = first / "workspace"
    sibling = tmp_path / "profile-a-sibling"
    for directory in (child, second, sibling):
        directory.mkdir(parents=True)
    alias = tmp_path / "alias"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(child)],
            check=True, capture_output=True, timeout=10)
    else:
        alias.symlink_to(child, target_is_directory=True)

    policy = ProjectPathPolicy(str(first))
    home = os.path.realpath(os.path.expanduser("~"))
    for path in ("", os.sep, home, os.path.dirname(home), "/home", "/Users", str(first)):
        assert policy.is_junk_root(path)
        assert policy.is_junk_cwd(path)
    for path in (str(child), str(alias)):
        assert policy.is_junk_root(path)
        assert not policy.is_junk_cwd(path)
    assert not policy.is_junk_root(str(sibling))
    assert not policy.is_junk_cwd(str(sibling))

    next_build = ProjectPathPolicy(str(second))
    assert next_build.is_junk_root(str(second))
    assert next_build.is_junk_cwd(str(second))
    assert not next_build.is_junk_root(str(first))
    assert not next_build.is_junk_cwd(str(first))
    assert policy.is_junk_root(str(first))  # An in-flight build retains its profile.


def test_repeated_rows_resolve_each_path_once_with_independent_build_caches(tmp_path, monkeypatch):
    realpath, isdir = os.path.realpath, os.path.isdir
    resolutions, stats = Counter(), Counter()

    def resolve(path):
        resolutions[path] += 1
        return realpath(path)

    def exists(path):
        stats[path] += 1
        return isdir(path)

    monkeypatch.setattr(os.path, "realpath", resolve)
    monkeypatch.setattr(os.path, "isdir", exists)
    home = str(tmp_path / "profile")
    workspace = str(tmp_path / "workspace")
    os.mkdir(workspace)
    first = ProjectPathPolicy(home)
    for _ in range(100):
        assert not first.is_junk_root(workspace)
        assert not first.is_junk_cwd(workspace)
        assert first.exists(workspace)
    assert resolutions[workspace] == 1
    assert max(resolutions.values()) == 1
    assert stats[workspace] == 1

    second = ProjectPathPolicy(home)
    assert not second.is_junk_root(workspace)
    assert second.exists(workspace)
    # Another request must neither reuse nor clear the in-flight request's memo.
    assert not first.is_junk_root(workspace)
    assert first.exists(workspace)
    assert resolutions[workspace] == 2
    assert stats[workspace] == 2
