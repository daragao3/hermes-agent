"""Native pipe and foreground ownership contracts across the environment split."""
import os
import threading
from types import SimpleNamespace

import pytest

from tools.environments import base, base_output


@pytest.mark.skipif(os.name != 'nt', reason='native Windows anonymous pipe contract')
@pytest.mark.parametrize('stop_requested', [False, True])
def test_windows_drain_finishes_without_inherited_writer_eof(stop_requested):
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, 'rb', buffering=0)
    proc = SimpleNamespace(stdout=stream, poll=lambda: None if stop_requested else 0)
    output = base_output._BoundedOutputCollector(1000)
    stop = threading.Event()
    if stop_requested:
        stop.set()
    else:
        os.write(write_fd, 'retained café'.encode())
    thread = threading.Thread(target=base_output._drain_stdout, args=(proc, output, stop), daemon=True)
    thread.start()
    try:
        thread.join(timeout=2)
        assert not thread.is_alive(), 'drain waited for a still-open inherited writer'
        if not stop_requested:
            assert 'retained café' in output.render()
    finally:
        os.close(write_fd)
        thread.join(timeout=2)
        stream.close()


def test_sandbox_lookup_can_remain_non_materializing(tmp_path, monkeypatch):
    target = tmp_path / 'uncreated'
    monkeypatch.setenv('TERMINAL_SANDBOX_DIR', str(target))
    assert base.get_sandbox_dir(create=False) == target
    assert not target.exists()
    assert base.get_sandbox_dir() == target
    assert target.is_dir()


@pytest.mark.parametrize('wait_fails', [False, True])
def test_deadline_worker_registers_under_originating_thread_and_always_releases(wait_fails):
    owner = threading.get_ident()

    class Environment(base.BaseEnvironment):
        def cleanup(self):
            pass

        def _prepare_command(self, command):
            return command, None

        def _wrap_command(self, command, cwd):
            return command

        def _run_bash(self, *args, **kwargs):
            assert threading.get_ident() != owner
            return SimpleNamespace(poll=lambda: None)

        def _wait_for_process(self, proc, **kwargs):
            assert kwargs['watch_interrupt_tid'] == owner
            assert owner in base.inflight_process_threads()
            assert threading.get_ident() not in base.inflight_process_threads()
            if wait_fails:
                raise RuntimeError('injected wait failure')
            return {'output': 'done', 'returncode': 0}

    env = Environment(cwd='C:/scratch', timeout=1)
    try:
        if wait_fails:
            with pytest.raises(RuntimeError, match='injected wait failure'):
                env.execute('unused', rewrite_compound_background=False)
        else:
            assert env.execute('unused', rewrite_compound_background=False)['output'] == 'done'
        assert owner not in base.inflight_process_threads()
    finally:
        env.cleanup()
