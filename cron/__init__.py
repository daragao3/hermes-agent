"""Cron public API, loaded on demand.

Importing a pure guard must not initialize the job store or scheduler. Public
exports retain their original owners; resolving an export imports that owner.
"""

import importlib

_EXPORTS = ['create_job', 'get_job', 'list_jobs', 'remove_job', 'update_job', 'pause_job', 'resume_job', 'set_resume_barrier', 'clear_resume_barrier', 'ResumeBarrierError', 'trigger_job', 'request_run', 'JobPaused', 'rearm_oneshot', 'tick', 'JOBS_FILE']
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    owner = "cron.scheduler" if name == "tick" else "cron.jobs"
    return getattr(importlib.import_module(owner), name)


def __dir__():
    return sorted(set(globals()) | set(__all__))
