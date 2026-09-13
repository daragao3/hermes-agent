"""Filesystem classification snapshot owned by one project-tree build."""

import os
from functools import cache


class ProjectPathPolicy:
    """Resolve symlinks once per input without retaining paths across requests."""

    def __init__(self, hermes_home: str):
        self._realpath = cache(os.path.realpath)
        home = self._realpath(os.path.expanduser("~"))
        candidates = (os.sep, home, os.path.dirname(home), "/home", "/Users")
        self._non_workspace_dirs = {
            os.path.normcase(self._realpath(path)) for path in candidates if path}
        self._hermes_home = self._realpath(hermes_home)
        self._hermes_home_key = os.path.normcase(self._hermes_home)
        self.exists = cache(os.path.isdir)

    def is_junk_root(self, root: str) -> bool:
        """Auto git projects exclude home containers and all of HERMES_HOME."""
        if not root:
            return True
        real = self._realpath(root)
        return (
            os.path.normcase(real) in self._non_workspace_dirs
            or real == self._hermes_home
            or real.startswith(self._hermes_home + os.sep))

    def is_junk_cwd(self, cwd: str) -> bool:
        """Non-git workspaces may be descendants of HERMES_HOME, but not it."""
        if not cwd:
            return True
        real = os.path.normcase(self._realpath(cwd))
        return real in self._non_workspace_dirs or real == self._hermes_home_key
