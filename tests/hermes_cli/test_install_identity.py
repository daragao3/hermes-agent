from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
from pathlib import Path
import time

from gateway.hosted_rooms import local_authority_gateway_id
import hermes_cli.install_identity as install_identity
from hermes_cli.install_identity import read_or_create_install_id


def _race_first_install_id(
    root_value,
    minted,
    results,
    start_barrier=None,
    writer_entered=None,
    release_writer=None,
):
    root = Path(root_value)
    install_identity.uuid.uuid4 = lambda: type("FixedUuid", (), {"hex": minted})()
    if start_barrier is not None:
        start_barrier.wait(timeout=10)
    if writer_entered is not None:
        original_mkstemp = install_identity.tempfile.mkstemp

        def held_mkstemp(*args, **kwargs):
            writer_entered.set()
            assert release_writer.wait(timeout=10)
            return original_mkstemp(*args, **kwargs)

        install_identity.tempfile.mkstemp = held_mkstemp
    results.put(read_or_create_install_id(root))


def test_concurrent_first_use_returns_one_persisted_identity(tmp_path):
    with ThreadPoolExecutor(max_workers=16) as executor:
        values = list(executor.map(lambda _: read_or_create_install_id(tmp_path), range(64)))

    assert len(set(values)) == 1
    assert values[0]
    assert (tmp_path / "install_id").read_text(encoding="utf-8").strip() == values[0]


def test_independent_first_callers_return_the_single_committed_identity(tmp_path, monkeypatch):
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    writer_entered = context.Event()
    release_writer = context.Event()
    winner = context.Process(
        target=_race_first_install_id,
        args=(
            str(tmp_path),
            "a" * 32,
            results,
            None,
            writer_entered,
            release_writer,
        ),
    )
    loser = context.Process(
        target=_race_first_install_id,
        args=(str(tmp_path), "b" * 32, results),
    )

    winner.start()
    assert writer_entered.wait(timeout=10)
    loser.start()
    time.sleep(0.25)
    assert loser.is_alive()
    release_writer.set()
    processes = [winner, loser]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    returned = [results.get(timeout=2) for _ in processes]
    persisted = (tmp_path / "install_id").read_text(encoding="utf-8").strip()

    assert returned == [persisted, persisted]

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(
        install_identity,
        "_INSTALL_ID_CACHE",
        {"root": None, "value": None},
    )
    assert local_authority_gateway_id() == f"install:{persisted}"


def test_concurrent_corrupt_file_repair_returns_one_committed_identity(tmp_path):
    (tmp_path / "install_id").write_text("corrupt\n", encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_first_install_id,
            args=(str(tmp_path), value, results, barrier),
        )
        for value in ("a" * 32, "b" * 32)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    returned = [results.get(timeout=2) for _ in processes]
    persisted = (tmp_path / "install_id").read_text(encoding="utf-8").strip()

    assert returned == [persisted, persisted]


def test_transient_read_failure_recovers_the_committed_identity(tmp_path, monkeypatch):
    committed = "c" * 32
    path = tmp_path / "install_id"
    path.write_text(committed + "\n", encoding="utf-8")
    real_read_text, injected = Path.read_text, []

    def collide_once(self, *args, **kwargs):
        if self == path and not injected:
            injected.append(self)
            raise PermissionError(13, "open collided with a publisher's replace")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", collide_once)

    value = read_or_create_install_id(tmp_path)

    assert injected, "the transient read failure was never exercised"
    assert value == committed
    assert real_read_text(path, encoding="utf-8").strip() == committed


def test_persistent_read_failure_returns_none_without_minting(tmp_path, monkeypatch):
    committed = "c" * 32
    path = tmp_path / "install_id"
    path.write_text(committed + "\n", encoding="utf-8")
    real_read_text = Path.read_text

    def always_refuse(self, *args, **kwargs):
        if self == path:
            raise PermissionError(13, "unreadable for the life of the call")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", always_refuse)

    assert read_or_create_install_id(tmp_path) is None
    assert real_read_text(path, encoding="utf-8").strip() == committed
    assert list(tmp_path.glob(".install_id-*")) == []


def test_transient_replace_failure_still_publishes_the_identity(tmp_path, monkeypatch):
    real_replace, injected = os.replace, []

    def collide_once(src, dst, *args, **kwargs):
        if str(dst).endswith("install_id") and not injected:
            injected.append(dst)
            raise PermissionError(13, "a reader holds the destination open")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(install_identity.os, "replace", collide_once)

    value = read_or_create_install_id(tmp_path)

    assert injected, "the transient replace failure was never exercised"
    assert value and install_identity._INSTALL_ID_RE.fullmatch(value)
    assert (tmp_path / "install_id").read_text(encoding="utf-8").strip() == value
    assert list(tmp_path.glob(".install_id-*")) == []


def test_persistent_replace_failure_returns_none_and_leaves_no_temp_file(tmp_path, monkeypatch):
    real_replace = os.replace

    def always_refuse(src, dst, *args, **kwargs):
        if str(dst).endswith("install_id"):
            raise PermissionError(13, "the destination stays held")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(install_identity.os, "replace", always_refuse)

    assert read_or_create_install_id(tmp_path) is None
    assert not (tmp_path / "install_id").exists()
    assert list(tmp_path.glob(".install_id-*")) == []
