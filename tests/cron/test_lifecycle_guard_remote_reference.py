"""A remote backend is POSIX no matter what host the gateway runs on.

The referenced-script walk used to carry references as ``pathlib.Path`` only, so a
remote path was re-spelled with LOCAL semantics before ``read_remote_script`` saw it.
On Windows a rooted-but-driveless path such as ``/remote/a.sh`` is NOT absolute, so it
was anchored to the local drive and the remote backend was asked for a C:-prefixed
path. That read returns nothing, and the walk then hits ``if not script_text:
continue`` -- it FAILED OPEN, silently skipping a script it never managed to read.

``PureWindowsPath`` cannot round-trip a POSIX path, so no local rewrite fixes this; the
walk has to carry the original token alongside the Path. These tests pin the reference
the remote is asked for AND the security consequence of getting it wrong.
"""

import sys

from cron import lifecycle_guard

guard = lifecycle_guard.contains_gateway_lifecycle_command_or_referenced_script

WINDOWS = sys.platform.startswith("win")


def _recorder(text="echo ok\n"):
    """A fake remote backend that records what it was asked for."""
    seen: list[str] = []

    def read(path: str) -> str:
        seen.append(path)
        return text

    return seen, read


# --- the reference handed to the remote -------------------------------------


def test_absolute_posix_reference_reaches_the_remote_verbatim():
    seen, read = _recorder()
    guard("bash /remote/a.sh", read_remote_script=read)
    assert seen == ["/remote/a.sh"]


def test_relative_reference_is_anchored_on_the_remote_cwd_posix_style():
    """Anchoring must use POSIX join semantics: os.path.join on Windows would
    produce a backslashed path the remote cannot open."""
    seen, read = _recorder()
    guard("bash helper.sh", cwd="/srv/app", read_remote_script=read)
    assert seen == ["/srv/app/helper.sh"]


def test_home_relative_reference_is_left_for_the_remote_to_expand():
    """Only the remote knows its own HOME; expanding locally names a directory
    that need not exist there (and on Windows is a drive-letter path)."""
    seen, read = _recorder()
    # cwd MUST be set: without it the anchoring branch is never reached and the
    # assertion holds whether or not `~` is special-cased (a vacuous test -- caught
    # by a surviving mutant that removed the tilde branch).
    guard("bash ~/deploy.sh", cwd="/srv/app", read_remote_script=read)
    assert seen == ["~/deploy.sh"]


def test_sourced_script_reference_reaches_the_remote_verbatim():
    """The dot/source branch resolves through the same helper."""
    seen, read = _recorder()
    guard(". /remote/env.sh", read_remote_script=read)
    assert seen == ["/remote/env.sh"]


# --- the security consequence -----------------------------------------------


def test_lifecycle_command_inside_a_remote_script_is_blocked():
    """THE POINT. Mis-spelling the reference made this read return nothing and the
    walk continue past it -- a fail-open on the exact case the guard exists for."""
    seen, read = _recorder("hermes gateway restart\n")
    assert guard("bash /remote/deploy.sh", read_remote_script=read) is True
    assert seen == ["/remote/deploy.sh"]


def test_lifecycle_command_inside_a_relative_remote_script_is_blocked():
    seen, read = _recorder("hermes gateway stop\n")
    assert guard("bash deploy.sh", cwd="/srv/app", read_remote_script=read) is True
    assert seen == ["/srv/app/deploy.sh"]


def test_benign_remote_script_still_passes():
    """Control: the fix must not turn the remote path into a blanket block."""
    seen, read = _recorder("ls -la /tmp\n")
    assert guard("bash /remote/benign.sh", read_remote_script=read) is False
    assert seen == ["/remote/benign.sh"]


# --- local behaviour is untouched -------------------------------------------


def test_local_script_is_read_locally_and_never_asked_of_the_remote(tmp_path):
    script = tmp_path / "local.sh"
    script.write_text("hermes gateway restart\n", encoding="utf-8")
    seen, read = _recorder()
    assert guard("bash " + script.as_posix(), read_remote_script=read) is True
    assert seen == [], "a file that exists locally must not be fetched over the wire"


def test_local_relative_reference_still_resolves_against_a_local_cwd(tmp_path):
    """The Path half still uses LOCAL semantics -- that is what the local read needs."""
    script = tmp_path / "helper.sh"
    script.write_text("hermes gateway stop\n", encoding="utf-8")
    assert guard("bash helper.sh", cwd=str(tmp_path)) is True


def test_host_absolute_reference_is_not_re_anchored_on_the_remote_cwd():
    """A reference already absolute FOR THIS HOST is handed over unchanged instead of
    being glued onto the remote cwd.

    Deliberately platform-split, because the correct answer differs: a drive-letter
    reference is absolute on Windows, but on POSIX ``C:/x`` is a perfectly ordinary
    RELATIVE name and must still be anchored. A cwd is passed on purpose -- without one
    the anchoring branch is never reached and the assertion holds either way (that
    vacuity let a mutant dropping the check survive).
    """
    seen, read = _recorder()
    guard("bash C:/nonexistent-lcg/helper.sh", cwd="/srv/app", read_remote_script=read)
    if WINDOWS:
        assert seen == ["C:/nonexistent-lcg/helper.sh"]
    else:
        assert seen == ["/srv/app/C:/nonexistent-lcg/helper.sh"]


def test_nested_relative_reference_inside_a_remote_script_is_followed():
    """The recursion cwd must come from the REMOTE spelling too.

    Deriving it from the local Path reintroduces the same fail-open one level down:
    the nested reference is anchored on a local directory, the remote is asked for a
    path it does not have, and the walk continues past the script that actually
    carries the lifecycle command. Not normalized on purpose -- POSIX resolves
    ``/remote/./sub.sh`` itself, and collapsing ``..`` lexically is wrong through
    symlinks.
    """
    seen: list[str] = []

    def read(path: str) -> str:
        seen.append(path)
        if path.endswith("deploy.sh"):
            return "bash ./sub.sh\n"
        return "hermes gateway restart\n"

    assert guard("bash /remote/deploy.sh", read_remote_script=read) is True
    assert seen == ["/remote/deploy.sh", "/remote/./sub.sh"]


def test_relative_reference_without_a_cwd_is_left_relative():
    """Deliberate: with no cwd the remote gets the bare name, NOT one anchored on this
    process's cwd.

    The old walk fell back to ``Path.cwd()``, which names a directory on the GATEWAY
    HOST -- meaningless to the remote and, on Windows, a drive-letter path. Handing the
    reference over unanchored lets the remote resolve it against its own cwd, which is
    what the shell there would do anyway.
    """
    seen, read = _recorder()
    guard("bash helper.sh", read_remote_script=read)
    assert seen == ["helper.sh"]
