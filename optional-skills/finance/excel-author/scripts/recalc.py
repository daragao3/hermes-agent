#!/usr/bin/env python3
"""Recalculate an .xlsx file's formulas using LibreOffice headless.

Usage: python recalc.py <path.xlsx> [timeout_seconds]

openpyxl writes formula strings but does not compute them. Downstream scripts
that open the file with data_only=True get None for every formula cell until
something has actually calculated the workbook. Excel does this on open;
headless pipelines need LibreOffice (or similar) to do it explicitly.

Exits 0 on success (workbook recomputed and resaved in place), non-zero on
failure. Writes status JSON to stdout either way.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000
_CREATE_SUSPENDED = 0x00000004


def _windows_job_for(proc: subprocess.Popen):
    """Create a job object and put *proc* in it; the handle, or None.

    The Windows equivalent of the POSIX process group: every descendant
    inherits membership, and ``TerminateJobObject`` kills by membership --
    never by pid or image name. ``Popen._handle`` names exactly the process we
    spawned; a Popen without one (a test double) is left alone.
    """
    try:
        import ctypes

        handle = getattr(proc, "_handle", None)
        if handle is None:
            return None
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        if not kernel32.AssignProcessToJobObject(job, int(handle)):
            kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _windows_resume(proc: subprocess.Popen) -> bool:
    """Thaw a CREATE_SUSPENDED child (``NtResumeProcess`` on the Popen handle)."""
    try:
        import ctypes

        ntdll = ctypes.WinDLL("ntdll")
        ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
        return ntdll.NtResumeProcess(int(proc._handle)) == 0
    except Exception:
        return False


def _windows_job_terminate(job) -> bool:
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        return bool(kernel32.TerminateJobObject(job, 1))
    except Exception:
        return False


def _windows_close(handle) -> None:
    if handle is None:
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle(handle)
    except Exception:
        pass


def _tree_kill(proc: subprocess.Popen, job=None) -> None:
    """Kill *proc* and its descendants; never raises.

    Best effort. Correctness does not depend on it — with file-backed stdio
    there is nothing left to drain and we never wait on the child again — but
    an abandoned ``soffice.bin`` keeps a lock on the user profile and wedges
    every later LibreOffice run, so it is worth reaping.

    Windows: the job captured at spawn is terminated by membership. Never
    ``taskkill /T``: it walked ParentProcessId edges, and an orphan whose dead
    parent's pid had been recycled onto our launcher died with it
    (2026-09-17). Without a job only the launcher we hold is provably ours,
    so only it is killed.
    """
    try:
        if _IS_WINDOWS:
            if job is None or not _windows_job_terminate(job):
                proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except OSError:
            pass


def _run_captured(argv: list[str], timeout: int) -> subprocess.CompletedProcess:
    """``subprocess.run(argv, capture_output=True, timeout=…)`` that actually
    honours ``timeout`` on Windows, by capturing into temp files not pipes.

    ``soffice.exe`` is only a launcher: it spawns ``soffice.bin`` and that
    grandchild inherits the capture pipe handles, holding the write end open so
    the pipe never reaches EOF. ``subprocess.run`` kills only the direct child
    on timeout and then blocks re-draining, forever — the documented Windows
    capture-pipe grandchild hang. Files have no reader threads, nothing to
    drain, and closing a file handle cannot block.

    Open-coded rather than importing ``hermes_cli._subprocess_compat``: skill
    scripts under ``optional-skills/`` are standalone stdlib-only programs run
    as ``python recalc.py <path>``, and none of them import from the repo.
    Returns decoded text, so callers must not ``.decode()`` the result.
    """
    if _IS_WINDOWS:
        # Created frozen so the launcher joins its job before its first instruction:
        # nothing it spawns (``soffice.bin``) can predate the job.
        popen_kwargs = {"creationflags": _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW | _CREATE_SUSPENDED}
    else:
        # Own process group so killpg() on timeout reaches the grandchildren.
        popen_kwargs = {"start_new_session": True}

    def _read(handle) -> str:
        handle.seek(0)
        return handle.read().decode("utf-8", errors="replace").replace("\r\n", "\n")

    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        proc = subprocess.Popen(
            argv,
            stdout=out_f,
            stderr=err_f,
            stdin=subprocess.DEVNULL,
            **popen_kwargs,
        )
        job = None
        if _IS_WINDOWS:
            job = _windows_job_for(proc)
            if not _windows_resume(proc):
                proc.kill()  # never leave a frozen child sitting out the whole timeout
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _tree_kill(proc, job)
            raise subprocess.TimeoutExpired(
                proc.args, timeout, output=_read(out_f), stderr=_read(err_f),
            )
        finally:
            _windows_close(job)
        return subprocess.CompletedProcess(
            proc.args, proc.returncode, _read(out_f), _read(err_f),
        )


def find_libreoffice() -> str | None:
    for cmd in ("libreoffice", "soffice"):
        path = shutil.which(cmd)
        if path:
            return path
    return None


def recalc(xlsx_path: str, timeout: int = 60) -> dict:
    src = Path(xlsx_path).resolve()
    if not src.exists():
        return {"status": "error", "error": f"File not found: {src}"}

    lo = find_libreoffice()
    if lo is None:
        return {
            "status": "error",
            "error": "libreoffice not found on PATH — install it or recalc in a real Excel session",
        }

    with tempfile.TemporaryDirectory() as td:
        try:
            completed = _run_captured(
                [
                    lo,
                    "--headless",
                    "--calc",
                    "--convert-to",
                    "xlsx",
                    str(src),
                    "--outdir",
                    td,
                ],
                timeout=timeout,
            )
            # check=True open-coded: _run_captured cannot honour it (it never
            # raises CalledProcessError), and dropping the check would let a
            # failed convert fall through to the "did not produce output file"
            # branch below, burying LibreOffice's own stderr.
            completed.check_returncode()
        except subprocess.TimeoutExpired:
            return {"status": "error", "error": f"libreoffice timed out after {timeout}s"}
        except subprocess.CalledProcessError as e:
            # e.stderr is already decoded text — _run_captured decodes for us.
            return {
                "status": "error",
                "error": f"libreoffice exited {e.returncode}: {(e.stderr or '')[:500]}",
            }

        produced = Path(td) / src.name
        if not produced.exists():
            return {"status": "error", "error": "libreoffice did not produce output file"}

        shutil.copy(produced, src)

    return {"status": "success", "file": str(src)}


def main():
    if len(sys.argv) < 2:
        print("Usage: python recalc.py <path.xlsx> [timeout_seconds]", file=sys.stderr)
        sys.exit(2)
    timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    result = recalc(sys.argv[1], timeout=timeout)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
