"""Callback retry contract with real SQLite; full SessionDB remains separate."""
import contextlib
import sqlite3

import pytest

import hermes_state_readpool as readpool


def test_transient_lock_releases_read_context_before_retry(tmp_path, monkeypatch):
    path = tmp_path / 'read.db'
    with contextlib.closing(sqlite3.connect(path)) as setup:
        setup.execute('CREATE TABLE payload(value TEXT)')
        setup.execute("INSERT INTO payload VALUES ('preserved')")
        setup.commit()
    with contextlib.closing(sqlite3.connect(path, timeout=0)) as writer:
        writer.execute('BEGIN EXCLUSIVE')
        active = []
        released = []
        sleeps = []

        @contextlib.contextmanager
        def read_context():
            conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0)
            active.append(conn)
            try:
                yield conn
            finally:
                active.remove(conn)
                conn.close()
                released.append(conn)

        def sleep(delay):
            assert not active
            assert len(released) == 1
            sleeps.append(delay)
            writer.rollback()

        monkeypatch.setattr(readpool.time, 'sleep', sleep)
        result = readpool.execute_read_with_retry(
            read_context, lambda conn: conn.execute('SELECT value FROM payload').fetchone())
        assert result == ('preserved',)
        assert len(released) == 2
        assert len(sleeps) == 1
        assert 0.020 <= sleeps[0] <= 0.150


@pytest.mark.parametrize('message', ['database is locked', 'database is busy'])
def test_contention_budget_is_bounded_and_preserves_last_error(monkeypatch, message):
    attempts = []
    sleeps = []
    error = sqlite3.OperationalError(message)

    @contextlib.contextmanager
    def read_context():
        attempts.append(1)
        raise error
        yield  # pragma: no cover

    monkeypatch.setattr(readpool.time, 'sleep', sleeps.append)
    with pytest.raises(sqlite3.OperationalError) as caught:
        readpool.execute_read_with_retry(read_context, lambda conn: None)
    assert caught.value is error
    assert len(attempts) == 15
    assert len(sleeps) == 14


@pytest.mark.parametrize('error', [
    sqlite3.OperationalError('no such table: payload'),
    sqlite3.OperationalError('disk I/O error'),
    sqlite3.DatabaseError('database disk image is malformed'),
    ValueError('invalid continuation identity'),
])
def test_non_contention_callback_errors_propagate_once(monkeypatch, error):
    attempts = []
    released = []

    @contextlib.contextmanager
    def read_context():
        try:
            yield object()
        finally:
            released.append(1)

    def callback(conn):
        attempts.append(conn)
        raise error

    def unexpected_sleep(delay):
        pytest.fail('non-contention errors must not sleep or retry')

    monkeypatch.setattr(readpool.time, 'sleep', unexpected_sleep)
    with pytest.raises(type(error)) as caught:
        readpool.execute_read_with_retry(read_context, callback)
    assert caught.value is error
    assert len(attempts) == len(released) == 1
