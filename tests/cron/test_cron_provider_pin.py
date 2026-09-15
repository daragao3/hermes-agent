"""Unpinned cron jobs run on their creation snapshot (#44585 follow-up).

Background: an UNPINNED cron job used to follow the live global default provider/model. A
temporary switch to a paid provider made every unpinned job silently inherit it on its next
tick (the $7.73 incident). The first fix failed closed on any drift, which instead killed every
unpinned job whenever the operator changed models — silently, for days.

Current contract:
  - create_job() snapshots the provider/model resolution WOULD pick at creation into
    job["provider_snapshot"] / job["model_snapshot"] (unpinned, agent-backed jobs only).
  - run_job() treats the snapshot as the effective pin: an unpinned axis runs on its snapshot
    even after the global default moved. Explicit per-job pins and the cron.model /
    cron.model_provider fleet defaults still win; a job with no snapshot follows the global
    default as before.

These tests exercise the full run_job path (real imports, mocked AIAgent +
resolve_runtime_provider against a temp HERMES_HOME) and the create_job snapshot capture.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is importable.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cron.scheduler import run_job


def _base_job(**overrides):
    job = {
        "id": "pin-test",
        "name": "pin test",
        "prompt": "hello",
        "model": None,
        "provider": None,
        "provider_snapshot": None,
        "base_url": None,
    }
    job.update(overrides)
    return job


def _run(job, tmp_path, *, current_provider="openrouter", current_model=None, cron_model=None,
         cron_model_provider=None):
    """Drive run_job against a temp config.yaml whose ``model.default`` / ``model.provider`` are
    the CURRENT global defaults. Returns ``(success, error, agent_kwargs, resolve_kwargs)`` where
    the last two are the kwargs AIAgent / resolve_runtime_provider were called with (None when
    never called)."""
    config_yaml = ""
    if current_model or current_provider:
        config_yaml += "model:\n"
        if current_model:
            config_yaml += f"  default: {current_model}\n"
        if current_provider:
            config_yaml += f"  provider: {current_provider}\n"
    cron_lines = []
    if cron_model is not None:
        cron_lines.append(f"  model: {cron_model}")
    if cron_model_provider is not None:
        cron_lines.append(f"  model_provider: {cron_model_provider}")
    if cron_lines:
        config_yaml += "cron:\n" + "\n".join(cron_lines) + "\n"
    (tmp_path / "config.yaml").write_text(config_yaml, encoding="utf-8")

    resolve_kwargs = {}

    def _resolve(**kwargs):
        resolve_kwargs.update(kwargs)
        return {
            "api_key": "test-key",
            "base_url": "https://example.invalid/v1",
            "provider": kwargs.get("requested") or current_provider,
            "api_mode": "chat_completions",
        }

    fake_db = MagicMock()
    with patch("cron.scheduler._hermes_home", tmp_path), \
         patch("cron.scheduler._get_hermes_home", return_value=tmp_path), \
         patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
         patch("hermes_cli.env_loader.load_hermes_dotenv"), \
         patch("hermes_cli.env_loader.reset_secret_source_cache"), \
         patch("hermes_state_registry.acquire", return_value=fake_db), \
         patch("hermes_cli.runtime_provider.resolve_runtime_provider", side_effect=_resolve), \
         patch("run_agent.AIAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = {"final_response": "ok"}
        mock_agent_cls.return_value = mock_agent
        success, _output, _final, error = run_job(job)
        agent_kwargs = mock_agent_cls.call_args.kwargs if mock_agent_cls.called else None
    return success, error, agent_kwargs, (resolve_kwargs or None)


class TestSnapshotIsTheEffectivePin:
    def test_unpinned_job_runs_on_snapshot_after_global_default_moved(self, tmp_path):
        """Global default moved old-provider/old-model -> new-provider/new-model; the unpinned job
        still runs, on what it was created under. Neither a skip nor a silent inherit."""
        job = _base_job(provider_snapshot="old-provider", model_snapshot="old-model")
        success, error, agent_kwargs, resolve_kwargs = _run(
            job, tmp_path, current_provider="new-provider", current_model="new-model")

        assert success is True, error
        assert agent_kwargs["model"] == "old-model"
        assert resolve_kwargs["requested"] == "old-provider"
        assert resolve_kwargs["target_model"] == "old-model"

    def test_explicit_job_pin_beats_snapshot(self, tmp_path):
        job = _base_job(
            provider="pinned-provider", model="pinned-model",
            provider_snapshot="old-provider", model_snapshot="old-model")
        success, error, agent_kwargs, resolve_kwargs = _run(
            job, tmp_path, current_provider="new-provider", current_model="new-model",
            cron_model="fleet-model")

        assert success is True, error
        assert agent_kwargs["model"] == "pinned-model"
        assert resolve_kwargs["requested"] == "pinned-provider"

    def test_cron_fleet_default_beats_snapshot(self, tmp_path):
        """cron.model / cron.model_provider deliberately route the whole unpinned fleet."""
        job = _base_job(provider_snapshot="old-provider", model_snapshot="old-model")
        success, error, agent_kwargs, resolve_kwargs = _run(
            job, tmp_path, current_provider="new-provider", current_model="new-model",
            cron_model="fleet-model", cron_model_provider="fleet-provider")

        assert success is True, error
        assert agent_kwargs["model"] == "fleet-model"
        assert resolve_kwargs["requested"] == "fleet-provider"

    def test_job_without_snapshot_follows_global_default(self, tmp_path):
        """Legacy record (keys absent) keeps tracking the live global default."""
        job = _base_job()
        job.pop("provider_snapshot", None)
        success, error, agent_kwargs, resolve_kwargs = _run(
            job, tmp_path, current_provider="new-provider", current_model="new-model")

        assert success is True, error
        assert agent_kwargs["model"] == "new-model"
        assert resolve_kwargs["requested"] is None

    def test_missing_model_guides_to_user_owned_cli(self, tmp_path, monkeypatch):
        """A missing-model failure cannot advertise agent-owned pinning."""
        monkeypatch.delenv("HERMES_MODEL", raising=False)
        success, error, agent_kwargs, _ = _run(
            _base_job(), tmp_path, current_provider="openrouter", current_model=None)

        assert success is False
        assert agent_kwargs is None
        assert "hermes cron edit pin-test --model <name>" in error
        assert "cronjob action=update" not in error


class TestCreateJobSnapshot:
    """create_job captures provider_snapshot for unpinned agent jobs only."""

    @staticmethod
    def _isolate_storage(monkeypatch):
        """Patch cron.jobs storage so create_job never touches the real store."""
        import contextlib
        import cron.jobs as jobs

        @contextlib.contextmanager
        def _noop_lock():
            yield

        monkeypatch.setattr(jobs, "_jobs_lock", _noop_lock, raising=True)
        monkeypatch.setattr(jobs, "load_jobs", lambda: [], raising=True)
        monkeypatch.setattr(jobs, "save_jobs", lambda j: None, raising=True)
        return jobs

    def test_unpinned_job_captures_snapshot(self, monkeypatch):
        jobs = self._isolate_storage(monkeypatch)

        with patch(
            "hermes_cli.runtime_provider.resolve_runtime_provider",
            return_value={"provider": "openrouter"},
        ):
            job = jobs.create_job(prompt="do a thing", schedule="every 1 hour")

        assert job["provider"] is None
        assert job["provider_snapshot"] == "openrouter"

    def test_pinned_job_skips_snapshot(self, monkeypatch):
        jobs = self._isolate_storage(monkeypatch)

        resolver = MagicMock(return_value={"provider": "openrouter"})
        with patch("hermes_cli.runtime_provider.resolve_runtime_provider", resolver):
            job = jobs.create_job(
                prompt="do a thing", schedule="every 1 hour", provider="nous"
            )

        # Explicit provider → pinned → no snapshot needed, and resolution skipped.
        assert job["provider"] == "nous"
        assert job["provider_snapshot"] is None
        resolver.assert_not_called()

    def test_snapshot_resolution_error_fails_open_to_none(self, monkeypatch):
        """If resolution raises at creation, snapshot is None — creation never breaks."""
        jobs = self._isolate_storage(monkeypatch)

        with patch(
            "hermes_cli.runtime_provider.resolve_runtime_provider",
            side_effect=RuntimeError("no creds"),
        ):
            job = jobs.create_job(prompt="do a thing", schedule="every 1 hour")

        assert job["provider_snapshot"] is None

    def test_unpinned_model_captures_model_snapshot(self, monkeypatch, tmp_path):
        """An unpinned model captures config.yaml model.default into model_snapshot."""
        jobs = self._isolate_storage(monkeypatch)
        (tmp_path / "config.yaml").write_text("model:\n  default: llama-3.3-70b:free\n", encoding="utf-8")
        monkeypatch.setattr(
            "cron.jobs.get_hermes_home", lambda: tmp_path, raising=True
        )
        with patch(
            "hermes_cli.runtime_provider.resolve_runtime_provider",
            return_value={"provider": "openrouter"},
        ):
            job = jobs.create_job(prompt="do a thing", schedule="every 1 hour")
        assert job["model"] is None
        assert job["model_snapshot"] == "llama-3.3-70b:free"

    def test_pinned_model_skips_model_snapshot(self, monkeypatch, tmp_path):
        """An explicit model → pinned → no model_snapshot captured."""
        jobs = self._isolate_storage(monkeypatch)
        (tmp_path / "config.yaml").write_text("model:\n  default: llama-3.3-70b:free\n", encoding="utf-8")
        monkeypatch.setattr(
            "cron.jobs.get_hermes_home", lambda: tmp_path, raising=True
        )
        with patch(
            "hermes_cli.runtime_provider.resolve_runtime_provider",
            return_value={"provider": "openrouter"},
        ):
            job = jobs.create_job(
                prompt="do a thing", schedule="every 1 hour", model="my-model"
            )
        assert job["model"] == "my-model"
        assert job["model_snapshot"] is None


class TestRuntimeResolutionTargetModel:
    """run_job must resolve the primary provider against the model the job will actually run
    (per-job pin > cron.model > snapshot > config default), so providers with model-specific
    api_mode routing pick the mode for that model instead of the stale persisted default."""

    def test_primary_resolution_passes_effective_model(self, tmp_path):
        job = _base_job(model="my-pinned-model", provider="openrouter")
        success, error, _agent_kwargs, resolve_kwargs = _run(
            job, tmp_path, current_provider="openrouter", current_model="other-model")

        assert success is True, error
        assert resolve_kwargs["target_model"] == "my-pinned-model"
        assert resolve_kwargs["requested"] == "openrouter"


# Grafted from the fork side in the 0.21.1 merge: definitions the other side
# has and this file's base side does not.

def _run_with_current_provider(job, current_provider, tmp_path):
    """Drive run_job with resolve_runtime_provider pinned to ``current_provider``.

    Returns (success, output, final_response, error, agent_constructed).
    """
    fake_db = MagicMock()
    with patch("cron.scheduler._hermes_home", tmp_path), \
         patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
         patch("hermes_cli.env_loader.load_hermes_dotenv"), \
         patch("hermes_cli.env_loader.reset_secret_source_cache"), \
         patch("hermes_state.SessionDB", return_value=fake_db), \
         patch(
             "hermes_cli.runtime_provider.resolve_runtime_provider",
             return_value={
                 "api_key": "test-key",
                 "base_url": "https://example.invalid/v1",
                 "provider": current_provider,
                 "api_mode": "chat_completions",
             },
         ), \
         patch("run_agent.AIAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = {"final_response": "ok"}
        mock_agent_cls.return_value = mock_agent

        success, output, final_response, error = run_job(job)
        agent_constructed = mock_agent_cls.called

    return success, output, final_response, error, agent_constructed

def _run_with_current_provider_and_model(job, current_provider, current_model, tmp_path):
    """Drive run_job with resolved provider pinned and config.yaml model.default
    set to ``current_model`` (the unpinned-model fire-time source)."""
    (tmp_path / "config.yaml").write_text(
        f"model:\n  default: {current_model}\n"
    )
    fake_db = MagicMock()
    with patch("cron.scheduler._hermes_home", tmp_path), \
         patch("cron.scheduler._get_hermes_home", return_value=tmp_path), \
         patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
         patch("hermes_cli.env_loader.load_hermes_dotenv"), \
         patch("hermes_cli.env_loader.reset_secret_source_cache"), \
         patch("hermes_state.SessionDB", return_value=fake_db), \
         patch(
             "hermes_cli.runtime_provider.resolve_runtime_provider",
             return_value={
                 "api_key": "test-key",
                 "base_url": "https://example.invalid/v1",
                 "provider": current_provider,
                 "api_mode": "chat_completions",
             },
         ), \
         patch("run_agent.AIAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = {"final_response": "ok"}
        mock_agent_cls.return_value = mock_agent
        success, output, final_response, error = run_job(job)
        agent_constructed = mock_agent_cls.called
    return success, output, final_response, error, agent_constructed

class TestModelDriftGuard:
    """#44585 C1: model drift on the SAME provider must also fail closed —
    the incident named a model (claude-fable-5), and an unpinned job reads
    config.yaml model.default fresh every tick independently of provider."""

    def test_model_drift_same_provider_runs_on_the_snapshot_not_the_new_model(self, tmp_path):
        """Provider unchanged, global default MODEL swapped to a premium one since creation.

        The fork used to REFUSE this run (#44585). 0.21.1 answers it with the creation snapshot
        instead: the job runs, on the free model it was created with, so the premium swap still
        cannot be billed to it silently. Asserted on the model the agent is actually constructed
        with -- the spend, not the message.
        """
        job = _base_job(
            provider_snapshot="openrouter",
            model_snapshot="llama-3.3-70b-instruct:free",
        )
        success, error, agent_kwargs, resolve_kwargs = _run(
            job, tmp_path,
            current_provider="openrouter", current_model="claude-fable-5")

        assert success is True, error
        assert agent_kwargs["model"] == "llama-3.3-70b-instruct:free"
        assert resolve_kwargs["target_model"] == "llama-3.3-70b-instruct:free"

    def test_model_snapshot_matches_runs(self, tmp_path):
        # Default model unchanged → runs normally.
        job = _base_job(
            provider_snapshot="openrouter",
            model_snapshot="llama-3.3-70b-instruct:free",
        )
        success, output, final_response, error, agent_constructed = \
            _run_with_current_provider_and_model(
                job, "openrouter", "llama-3.3-70b-instruct:free", tmp_path
            )
        assert agent_constructed is True
        assert success is True

    def test_pinned_model_bypasses_guard(self, tmp_path):
        # Explicit job["model"] → not unpinned → no model-drift skip even if the
        # global default differs from any snapshot.
        job = _base_job(
            provider_snapshot="openrouter",
            model_snapshot="old-model",
            model="my-pinned-model",
        )
        success, output, final_response, error, agent_constructed = \
            _run_with_current_provider_and_model(
                job, "openrouter", "claude-fable-5", tmp_path
            )
        assert agent_constructed is True
        assert success is True

    def test_no_model_snapshot_backcompat(self, tmp_path):
        # Pre-existing job without model_snapshot → no model-drift skip.
        job = _base_job(provider_snapshot="openrouter")  # no model_snapshot key set to a value
        success, output, final_response, error, agent_constructed = \
            _run_with_current_provider_and_model(
                job, "openrouter", "claude-fable-5", tmp_path
            )
        assert agent_constructed is True
        assert success is True

class TestProviderDriftGuard:
    def test_a_unpinned_snapshot_matches_runs_normally(self, tmp_path):
        """(a) Unpinned job whose snapshot == current provider → runs normally."""
        job = _base_job(provider_snapshot="openrouter")
        success, output, final_response, error, agent_constructed = \
            _run_with_current_provider(job, "openrouter", tmp_path)

        assert success is True
        assert error is None
        assert final_response == "ok"
        assert agent_constructed is True

    def test_b_unpinned_snapshot_differs_runs_on_the_snapshot_provider(self, tmp_path):
        """(b) Unpinned job whose snapshot != current provider -> runs on the SNAPSHOT.

        The fork refused this run (#44585, "fail closed"); 0.21.1 keeps the job on the provider it
        was created under instead. Same protection -- the newly-defaulted provider is never
        reached, so its bill is never incurred -- without stopping the job. Asserted on the
        provider actually resolved, which is where the spend would happen.
        """
        job = _base_job(provider_snapshot="openrouter")
        success, error, agent_kwargs, resolve_kwargs = _run(
            job, tmp_path, current_provider="nous")

        assert success is True, error
        assert resolve_kwargs["requested"] == "openrouter"
        assert agent_kwargs is not None

    def test_c_no_snapshot_runs_backcompat(self, tmp_path):
        """(c) Pre-existing job with NO provider_snapshot → runs (back-compat).

        Even though the current provider differs from anything, a job without a
        snapshot must behave exactly as before this fix: the guard never engages.
        """
        # A job dict that predates the field entirely (key absent, not None).
        job = _base_job()
        job.pop("provider_snapshot", None)
        success, output, final_response, error, agent_constructed = \
            _run_with_current_provider(job, "nous", tmp_path)

        assert success is True
        assert error is None
        assert agent_constructed is True

    def test_c2_snapshot_none_runs_backcompat(self, tmp_path):
        """(c') Job with provider_snapshot explicitly None → runs (back-compat)."""
        job = _base_job(provider_snapshot=None)
        success, output, final_response, error, agent_constructed = \
            _run_with_current_provider(job, "nous", tmp_path)

        assert success is True
        assert error is None
        assert agent_constructed is True

    def test_d_explicitly_pinned_runs_regardless_of_drift(self, tmp_path):
        """(d) Explicitly-pinned job (job["provider"] set) → runs regardless.

        A pinned job does not follow global state, so even a snapshot/current
        mismatch must not skip it. (Snapshot would normally be None for pinned
        jobs, but we set a mismatching one to prove the pin wins.)
        """
        job = _base_job(provider="openrouter", provider_snapshot="anthropic")
        # Current resolution differs from the (stale) snapshot, but the job is
        # pinned, so the guard must not engage.
        success, output, final_response, error, agent_constructed = \
            _run_with_current_provider(job, "nous", tmp_path)

        assert success is True
        assert error is None
        assert agent_constructed is True

