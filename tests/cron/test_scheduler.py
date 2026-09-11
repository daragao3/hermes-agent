"""Tests for cron/scheduler.py — origin resolution, delivery routing, and error logging."""

import concurrent.futures
import contextlib
import itertools
import json
import logging
import os
import re
import threading
import time
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from cron.scheduler import (
    SILENT_MARKER,
    _build_job_prompt,
    _deliver_result,
    _merge_mcp_into_per_job_toolsets,
    _resolve_cron_enabled_toolsets,
    _resolve_delivery_target,
    _summarize_cron_failure_for_delivery,
    run_job, run_one_job, _strip_iteration_markers,
)
from cron.scheduler_delivery import _resolve_origin, _send_media_via_adapter
from tools.env_passthrough import clear_env_passthrough
from tools.credential_files import clear_credential_files as clear_credential_files


@pytest.fixture
def _tick_lock_isolated(tmp_path):
    """Redirect scheduler tick lock to a per-test temp dir.

    tick() acquires an exclusive file lock at the path returned by
    _get_lock_paths() (derived at call time from _get_hermes_home()); under
    pytest-xdist parallel workers this races and lock-losers short-circuit
    with `return 0` before _process_job runs, breaking any test that asserts
    positive behavior (delivery called, output saved, log emitted).

    Test classes that call tick() must opt in via
    @pytest.mark.usefixtures("_tick_lock_isolated").
    """
    # v0.15.1 catch-up: upstream replaced the module-level _LOCK_DIR/_LOCK_FILE
    # constants with _get_lock_paths(), which derives the lock dir from the
    # _hermes_home override hook. Patch that hook so the lock lands under tmp.
    with patch("cron.scheduler._hermes_home", tmp_path):
        yield


class TestSummarizeCronFailureForDelivery:
    def test_embedded_429_in_source_identifier_is_not_a_rate_limit(self):
        summary = _summarize_cron_failure_for_delivery(
            {"name": "LLM Wiki Incremental Index", "no_agent": True},
            "Script failed: path/hash429abc.md source snapshot failure",
        )

        assert "provider rate limit" not in summary
        assert "hash429abc.md" in summary

    def test_http_429_is_still_classified_as_a_rate_limit(self):
        summary = _summarize_cron_failure_for_delivery(
            {"name": "provider-backed job"},
            "HTTP 429: Too Many Requests",
        )

        assert "provider rate limit" in summary
        # Chain wording is now honest (#85508): either the exhausted phrase
        # (chain configured) or the "No fallback chain configured" guidance.
        assert "fallback chain" in summary.lower()

    def test_no_agent_rate_limit_does_not_claim_a_fallback_chain(self):
        summary = _summarize_cron_failure_for_delivery(
            {"name": "script job", "no_agent": True},
            "HTTP 429: Too Many Requests",
        )

        # Composed with #77648: a no_agent job never gets provider-shaped
        # classification at all — the generic cleaner reports the script's
        # own error instead.
        assert "provider" not in summary.lower()
        assert "fallback chain" not in summary.lower()

    def test_no_agent_timeout_is_identified_as_a_script_timeout(self):
        summary = _summarize_cron_failure_for_delivery(
            {"name": "script job", "no_agent": True},
            "Script timed out after 3600s",
        )

        assert "script timed out" in summary
        assert "No model was invoked" in summary
        assert "provider timeout" not in summary
        assert "fallback chain" not in summary.lower()


class TestPerJobToolsetMcpMerge:
    """A per-job enabled_toolsets allowlist must not silently drop MCP servers."""

    CFG = {
        "mcp_servers": {
            "finnhub": {"enabled": True},
            "playwright": {"enabled": True},
            "disabled_one": {"enabled": False},
            "string_enabled": {"enabled": "true"},
            "not_a_dict": "ignored",
        }
    }

    def _enabled_names(self):
        return {"finnhub", "playwright", "string_enabled"}

    def test_native_only_list_gets_all_enabled_mcp_servers(self):
        result = _merge_mcp_into_per_job_toolsets(["web", "terminal"], self.CFG)
        assert result[:2] == ["web", "terminal"]
        assert set(result) == {"web", "terminal"} | self._enabled_names()


    def test_explicit_mcp_name_is_treated_as_allowlist(self):
        # User named one server -> add nothing further.
        result = _merge_mcp_into_per_job_toolsets(["web", "finnhub"], self.CFG)
        assert result == ["web", "finnhub"]
        assert "playwright" not in result

    def test_no_mcp_sentinel_opts_out_and_is_stripped(self):
        result = _merge_mcp_into_per_job_toolsets(["web", "no_mcp"], self.CFG)
        assert result == ["web"]
        assert not (set(result) & self._enabled_names())


    def test_resolver_empty_per_job_falls_through_to_platform(self):
        # No per-job list -> must delegate to _get_platform_tools (the platform
        # fallback), NOT the per-job merge. Stub the platform resolver and assert
        # it is the path taken and its result is returned.
        job = {"enabled_toolsets": None}
        sentinel = ["web", "finnhub"]
        with patch("hermes_cli.tools_config._get_platform_tools",
                   return_value=set(sentinel)) as m_platform:
            result = _resolve_cron_enabled_toolsets(job, self.CFG)
        m_platform.assert_called_once()
        # _get_platform_tools args: (cfg, "cron")
        assert m_platform.call_args[0][1] == "cron"
        assert set(result) == set(sentinel)

    def test_resolver_keeps_memory_in_per_job_list(self):
        result = _resolve_cron_enabled_toolsets(
            {"enabled_toolsets": ["memory", "file"]},
            {"mcp_servers": {}},
        )
        assert "memory" in result
        assert "file" in result

    def test_resolver_keeps_memory_from_platform_fallback(self):
        job = {"enabled_toolsets": None}
        with patch(
            "hermes_cli.tools_config._get_platform_tools",
            return_value={"web", "memory", "file"},
        ):
            result = _resolve_cron_enabled_toolsets(job, {})
        assert result == ["file", "memory", "web"]


class TestResolveOrigin:
    def test_full_origin(self):
        job = {
            "origin": {
                "platform": "telegram",
                "chat_id": "123456",
                "chat_name": "Test Chat",
                "thread_id": "42",
            }
        }
        result = _resolve_origin(job)
        assert isinstance(result, dict)
        assert result == job["origin"]
        assert result["platform"] == "telegram"
        assert result["chat_id"] == "123456"
        assert result["chat_name"] == "Test Chat"
        assert result["thread_id"] == "42"


    def test_string_origin_returns_none(self):
        # Regression: jobs.json entries created by the 2026-04-26 matcher-shadow
        # recovery plan stored a provenance tag in the `origin` field as a bare
        # string. The scheduler treated the field as a dict and crashed every
        # tick with `'str' object has no attribute 'get'`. Non-dict origins
        # must be coerced to None like any other malformed routing metadata.
        job = {"origin": "matcher-shadow-coverage-recovery-2026-04-26"}
        assert _resolve_origin(job) is None

    @pytest.mark.parametrize(
        "non_dict_origin",
        [
            "combined-digest-replaces-x-and-y-20260503",
            123,
            ["telegram", "12345"],
            ("platform", "chat_id"),
            42.0,
        ],
    )
    def test_non_dict_origin_returns_none_instead_of_crashing(self, non_dict_origin):
        """Non-dict origins (provenance strings from hand-edited or migrated
        jobs.json) must be treated as missing instead of crashing the
        scheduler tick on ``origin.get('platform')`` with
        ``'str' object has no attribute 'get'`` (#18722).

        Before this guard a job in this state crashed every fire attempt
        forever; ``mark_job_run`` recorded the error but the next tick
        re-loaded the poisoned origin and crashed identically.
        """
        job = {"origin": non_dict_origin}
        assert _resolve_origin(job) is None


# ── Platform-plugin import budget ──────────────────────────────────────────
#
# ``_resolve_delivery_targets`` reaches ``_iter_home_target_platforms``, which
# calls ``discover_plugins()`` + ``platform_registry.plugin_entries()``. That
# runs ``PlatformRegistry._resolve_all()``, which executes EVERY deferred
# platform loader — importing the real SDK behind each bundled adapter
# (discord.py, slack_sdk, matrix, ...). It is a once-per-interpreter import
# tax paid by whichever test in the process gets there first, and it is
# heavily I/O-bound, so its cost tracks host load rather than the test body.
#
# Measured on the same commit, same machine, two runs of ``pytest tests/cron``:
#   test_all_expands_to_every_connected_home_channel   11.43s -> 42.94s
#   test_human_friendly_label_without_suffix_resolved   8.32s -> 32.65s
#
# The 30s ``addopts`` cap is documented in pyproject.toml as the fallback
# inside each per-file subprocess spawned by scripts/run_tests_parallel.py.
# Under that runner the import lands in a fresh, unloaded interpreter; in a
# single monolithic ``pytest tests/events tests/cron`` process it does not.
# When the cap is hit, ``--timeout-method=thread`` dumps thread stacks and
# hard-exits, so the whole run loses its summary line over a slow import.
#
# These marks declare an honest budget for that import. They are NOT xfails
# and they hide no failure: the tests still assert exactly what they did, and
# still fail if the expansion logic breaks. The first test in the process to
# touch the registry pays the tax, so both classes carry the mark.
@pytest.mark.timeout(180)
class TestResolveDeliveryTarget:
    def test_origin_delivery_preserves_thread_id(self):
        job = {
            "deliver": "origin",
            "origin": {
                "platform": "telegram",
                "chat_id": "-1001",
                "thread_id": "17585",
            },
        }

        assert _resolve_delivery_target(job) == {
            "platform": "telegram",
            "chat_id": "-1001",
            "thread_id": "17585",
            "_resolved_from": "origin",
        }


    def test_bare_platform_delivery_uses_home_root_instead_of_origin_thread(self, monkeypatch):
        monkeypatch.setenv("DISCORD_HOME_CHANNEL", "home-parent")
        monkeypatch.delenv("DISCORD_HOME_CHANNEL_THREAD_ID", raising=False)

        job = {
            "deliver": "discord",
            "origin": {
                "platform": "discord",
                "chat_id": "origin-parent",
                "thread_id": "origin-thread",
            },
        }

        assert _resolve_delivery_target(job) == {
            "platform": "discord",
            "chat_id": "home-parent",
            "thread_id": None,
        }

    def test_telegram_cron_thread_id_overrides_home_thread_id(self, monkeypatch):
        """TELEGRAM_CRON_THREAD_ID wins over TELEGRAM_HOME_CHANNEL_THREAD_ID for cron (#24409)."""
        monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "-1001234567890")
        monkeypatch.setenv("TELEGRAM_HOME_CHANNEL_THREAD_ID", "5")
        monkeypatch.setenv("TELEGRAM_CRON_THREAD_ID", "42")

        assert _resolve_delivery_target({"deliver": "telegram"}) == {
            "platform": "telegram",
            "chat_id": "-1001234567890",
            "thread_id": "42",
        }


    def test_explicit_telegram_topic_target_overrides_cron_thread_id(self, monkeypatch):
        """Explicit ``telegram:chat:thread`` targets bypass TELEGRAM_CRON_THREAD_ID."""
        monkeypatch.setenv("TELEGRAM_CRON_THREAD_ID", "999")

        job = {"deliver": "telegram:-1003724596514:17"}
        assert _resolve_delivery_target(job) == {
            "platform": "telegram",
            "chat_id": "-1003724596514",
            "thread_id": "17",
            "_resolved_from": "explicit",
        }


    def test_human_friendly_label_resolved_via_channel_directory(self):
        """deliver: 'whatsapp:Alice (dm)' resolves to the real JID."""
        job = {"deliver": "whatsapp:Alice (dm)"}
        with patch(
            "gateway.channel_directory.resolve_channel_name",
            return_value="12345678901234@lid",
        ) as resolve_mock:
            result = _resolve_delivery_target(job)
        resolve_mock.assert_called_once_with("whatsapp", "Alice (dm)")
        assert result == {
            "platform": "whatsapp",
            "chat_id": "12345678901234@lid",
            "thread_id": None,
            "_resolved_from": "explicit",
        }


    def test_raw_id_not_mangled_when_directory_returns_none(self):
        """deliver: 'whatsapp:12345@lid' passes through when directory has no match."""
        job = {"deliver": "whatsapp:12345@lid"}
        with patch(
            "gateway.channel_directory.resolve_channel_name",
            return_value=None,
        ):
            result = _resolve_delivery_target(job)
        assert result == {
            "platform": "whatsapp",
            "chat_id": "12345@lid",
            "thread_id": None,
            "_resolved_from": "explicit",
        }

    def test_unresolved_target_still_delivered_as_written(self):
        """A stored job's platform-native target keeps delivering when neither
        parser nor directory recognizes it. Routing cron through
        resolve_send_target turned these into a warning plus a silently
        dropped delivery; pass_unresolved_references hands the raw id to the adapter
        again."""
        job = {"deliver": "telegram:ops-room"}
        with patch(
            "gateway.channel_directory.resolve_channel_name",
            return_value=None,
        ):
            result = _resolve_delivery_target(job)
        assert result == {
            "platform": "telegram",
            "chat_id": "ops-room",
            "thread_id": None,
            "_resolved_from": "explicit",
        }


    def test_list_form_deliver_is_normalized(self, monkeypatch):
        """deliver=['telegram'] (Python list) should resolve like 'telegram' string.

        Regression test for #17139: MCP clients / scripts that pass the deliver
        field as an array-shaped value used to fail with "no delivery target
        resolved for deliver=['telegram']" because ``str(['telegram'])`` was
        passed through to ``split(',')`` verbatim.
        """
        monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "-4004")
        job = {
            "deliver": ["telegram"],
            "origin": None,
        }

        assert _resolve_delivery_target(job) == {
            "platform": "telegram",
            "chat_id": "-4004",
            "thread_id": None,
        }

    def test_bare_matrix_delivery_uses_matrix_home_room(self, monkeypatch):
        monkeypatch.delenv("MATRIX_HOME_CHANNEL", raising=False)
        monkeypatch.setenv("MATRIX_HOME_ROOM", "!room123:example.org")

        assert _resolve_delivery_target({"deliver": "matrix"}) == {
            "platform": "matrix",
            "chat_id": "!room123:example.org",
            "thread_id": None,
        }


    def test_bare_whatsapp_delivery_uses_whatsapp_home_channel(self, monkeypatch):
        """Regression: _HOME_TARGET_ENV_VARS was missing a 'whatsapp' entry,
        so bare deliver=whatsapp jobs (cron jobs + whatsapp_escalator's
        synthetic event-bus job + digest_composer) all failed with
        'no delivery target resolved for deliver=whatsapp' even when
        WHATSAPP_HOME_CHANNEL was set."""
        monkeypatch.setenv("WHATSAPP_HOME_CHANNEL", "53910513393901@lid")

        assert _resolve_delivery_target({"deliver": "whatsapp"}) == {
            "platform": "whatsapp",
            "chat_id": "53910513393901@lid",
            "thread_id": None,
        }


    def test_bare_platform_delivery_preserves_home_thread_id(self, monkeypatch):
        monkeypatch.setenv("DISCORD_HOME_CHANNEL", "parent-42")
        monkeypatch.setenv("DISCORD_HOME_CHANNEL_THREAD_ID", "topic-7")

        assert _resolve_delivery_target({"deliver": "discord"}) == {
            "platform": "discord",
            "chat_id": "parent-42",
            "thread_id": "topic-7",
        }



# Same platform-plugin import budget as TestResolveDeliveryTarget above —
# see the block comment there for the measurements and rationale.
@pytest.mark.timeout(180)
class TestRoutingIntents:
    """``all`` routing intent expands at fire time."""

    def test_all_expands_to_every_connected_home_channel(self, monkeypatch):
        """deliver='all' fans out to every platform with a configured home channel."""
        from cron.scheduler import _resolve_delivery_targets

        monkeypatch.setenv("TELEGRAM_HOME_CHANNEL", "-111")
        monkeypatch.setenv("DISCORD_HOME_CHANNEL", "-222")
        monkeypatch.setenv("SLACK_HOME_CHANNEL", "C333")
        # Sanity: platforms without the env var must NOT appear in the expansion.
        monkeypatch.delenv("SIGNAL_HOME_CHANNEL", raising=False)
        monkeypatch.delenv("MATRIX_HOME_ROOM", raising=False)

        targets = _resolve_delivery_targets({"deliver": "all", "origin": None})
        platforms = sorted(t["platform"] for t in targets)

        assert "telegram" in platforms
        assert "discord" in platforms
        assert "slack" in platforms
        assert "signal" not in platforms
        assert "matrix" not in platforms


class TestDeliverResultWrapping:
    """Verify that cron deliveries are wrapped with header/footer and no longer mirrored."""

    def _safe_media_path(self, tmp_path, monkeypatch, name, data=b"media"):
        root = tmp_path / "media-cache"
        media_file = root / name
        media_file.parent.mkdir(parents=True, exist_ok=True)
        media_file.write_bytes(data)
        monkeypatch.setattr(
            "gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS",
            (root,),
        )
        return media_file.resolve()

    def test_delivery_wraps_content_with_header_and_footer(self):
        """Delivered content should include task name header and agent-invisible note."""
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("tools.send_message_tool._send_to_platform", new=AsyncMock(return_value={"success": True})) as send_mock:
            job = {
                "id": "test-job",
                "name": "daily-report",
                "deliver": "origin",
                "origin": {"platform": "telegram", "chat_id": "123"},
            }
            _deliver_result(job, "Here is today's summary.")

        send_mock.assert_called_once()
        sent_content = send_mock.call_args.kwargs.get("content") or send_mock.call_args[0][-1]
        assert "Cronjob Response: daily-report" in sent_content
        assert "(job_id: test-job)" in sent_content
        assert "-------------" in sent_content
        assert "Here is today's summary." in sent_content
        assert "To stop or manage this job" in sent_content


    def test_relay_fronted_home_uses_relay_config_and_live_adapter(self, monkeypatch, tmp_path):
        """Persisted Slack home survives restart without native Slack config."""
        from concurrent.futures import Future

        from gateway.config import GatewayConfig, HomeChannel, Platform, PlatformConfig

        relay = MagicMock()
        relay.fronts_platform.side_effect = lambda platform: platform == Platform.SLACK
        relay.send_for_platform = AsyncMock(return_value=MagicMock(success=True))
        relay.send_voice = AsyncMock(return_value=MagicMock(success=True))
        relay.supports_inchannel_continuable = False
        # Not a real RelayAdapter: keep the auto-created accessor from
        # shadowing the scalar False (MagicMock fabricates truthy callables).
        relay.supports_inchannel_continuable_for_platform = None

        config = GatewayConfig(
            platforms={
                Platform.RELAY: PlatformConfig(enabled=True),
                Platform.SLACK: PlatformConfig(
                    enabled=False,
                    home_channel=HomeChannel(
                        platform=Platform.SLACK,
                        chat_id="D123",
                        name="Owner DM",
                        user_id="U123",
                    ),
                ),
            },
        )
        loop = MagicMock()
        loop.is_running.return_value = True

        def fake_run_coro(coro, _loop):
            import asyncio as _asyncio

            future = Future()
            try:
                future.set_result(_asyncio.run(coro))
            except BaseException as exc:  # noqa: BLE001
                future.set_exception(exc)
            return future

        standalone_send = AsyncMock(return_value={"success": True})
        media_path = self._safe_media_path(tmp_path, monkeypatch, "relay-voice.mp3")
        monkeypatch.setenv("SLACK_HOME_CHANNEL", "D123")
        job = {
            "id": "relay-cron",
            "deliver": "slack",
        }

        with (
            patch("gateway.config.load_gateway_config", return_value=config),
            patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}),
            patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coro),
            patch("tools.send_message_tool._send_to_platform", new=standalone_send),
        ):
            result = _deliver_result(
                job,
                f"scheduled result\nMEDIA:{media_path}",
                adapters={Platform.RELAY: relay},
                loop=loop,
            )

        assert result is None
        relay.send_for_platform.assert_awaited_once()
        args = relay.send_for_platform.await_args.args
        assert args[:3] == (Platform.SLACK, "D123", "scheduled result")
        assert relay.send_for_platform.await_args.kwargs["metadata"]["user_id"] == "U123"
        relay.send_voice.assert_awaited_once()
        media_metadata = relay.send_voice.await_args.kwargs["metadata"]
        assert media_metadata["_relay_logical_platform"] == "slack"
        assert media_metadata["user_id"] == "U123"
        standalone_send.assert_not_awaited()


    def test_live_adapter_sends_media_as_attachments(self, tmp_path, monkeypatch):
        """When a live adapter is available, MEDIA files should be sent as native
        platform attachments (e.g., Discord voice, Telegram audio) rather than
        as literal 'MEDIA:/path' text."""
        from gateway.config import Platform
        from concurrent.futures import Future
        media_path = self._safe_media_path(tmp_path, monkeypatch, "cron-voice.mp3")

        adapter = AsyncMock()
        adapter.send.return_value = MagicMock(success=True)
        adapter.send_voice.return_value = MagicMock(success=True)

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.DISCORD: pconfig}

        loop = MagicMock()
        loop.is_running.return_value = True

        # run_coroutine_threadsafe returns concurrent.futures.Future (has timeout kwarg)
        def fake_run_coro(coro, _loop):
            # Actually run the routed coroutine (router._deliver_to_platform)
            # so the underlying adapter.send is invoked, then wrap the real
            # result in a completed Future (matching run_coroutine_threadsafe).
            import asyncio as _asyncio
            future = Future()
            try:
                future.set_result(_asyncio.run(coro))
            except BaseException as _e:  # noqa: BLE001
                future.set_exception(_e)
            return future

        job = {
            "id": "tts-job",
            "deliver": "origin",
            "origin": {"platform": "discord", "chat_id": "9876"},
        }

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}), \
             patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coro):
            _deliver_result(
                job,
                f"Here is TTS\nMEDIA:{media_path}",
                adapters={Platform.DISCORD: adapter},
                loop=loop,
            )

        # Text should be sent without the MEDIA tag
        adapter.send.assert_called_once()
        text_sent = adapter.send.call_args[0][1]
        assert "MEDIA:" not in text_sent
        assert "Here is TTS" in text_sent

        # Audio file should be sent as a voice attachment
        adapter.send_voice.assert_called_once()
        voice_call = adapter.send_voice.call_args
        assert voice_call[1]["audio_path"] == str(media_path)

    def test_delivery_strips_agent_iteration_marker(self):
        """The internal <AGENT_ITERATION_JSON> contract block must never reach
        the delivered body. It is machine-only (consumed by the cron event-bus
        extractors); leaking it makes Telegram's HTML parser reject the
        unsupported <agent_iteration_json> tag and fall back to plain text on
        every send (issue: 'Parse mode HTML failed in _send_telegram')."""
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        final_response = (
            "Scanned 4 sources, 23 new jobs (11 deduped).\n\n"
            "<AGENT_ITERATION_JSON>\n"
            '{"agent": "scout", "summary": "Scanned 4 sources, 23 new jobs"}\n'
            "</AGENT_ITERATION_JSON>"
        )

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("tools.send_message_tool._send_to_platform", new=AsyncMock(return_value={"success": True})) as send_mock, \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}):
            job = {
                "id": "scout-job",
                "name": "scout-scan",
                "deliver": "origin",
                "origin": {"platform": "telegram", "chat_id": "123"},
            }
            _deliver_result(job, final_response)

        send_mock.assert_called_once()
        sent_content = send_mock.call_args.kwargs.get("content") or send_mock.call_args[0][-1]
        # Marker tag and its JSON payload are gone; user-facing preamble stays.
        assert "AGENT_ITERATION_JSON" not in sent_content
        assert '"agent": "scout"' not in sent_content
        assert sent_content == "Scanned 4 sources, 23 new jobs (11 deduped)."


    def test_delivery_strips_legacy_tailor_iteration_marker(self):
        """The legacy Tailor-specific <TAILOR_ITERATION_JSON> block leaks the
        same way and must also be stripped before delivery."""
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        final_response = (
            "Tailored 3 of 5 eligible packets.\n\n"
            "<TAILOR_ITERATION_JSON>\n"
            '{"eligible_count": 5, "tailored_count": 3, "skipped_terminal_count": 2, '
            '"skipped_other_count": 0, "reason": "tailored_some"}\n'
            "</TAILOR_ITERATION_JSON>"
        )

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("tools.send_message_tool._send_to_platform", new=AsyncMock(return_value={"success": True})) as send_mock, \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}):
            job = {
                "id": "tailor-job",
                "name": "jobflow-tailor",
                "deliver": "origin",
                "origin": {"platform": "telegram", "chat_id": "123"},
            }
            _deliver_result(job, final_response)

        send_mock.assert_called_once()
        sent_content = send_mock.call_args.kwargs.get("content") or send_mock.call_args[0][-1]
        assert "TAILOR_ITERATION_JSON" not in sent_content
        assert "eligible_count" not in sent_content
        assert sent_content == "Tailored 3 of 5 eligible packets."


    def test_delivery_extracts_media_tags_before_send(self, tmp_path, monkeypatch):
        """Cron delivery should pass MEDIA attachments separately to the send helper."""
        from gateway.config import Platform
        media_path = self._safe_media_path(tmp_path, monkeypatch, "test-voice.ogg")

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("tools.send_message_tool._send_to_platform", new=AsyncMock(return_value={"success": True})) as send_mock, \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}):
            job = {
                "id": "voice-job",
                "deliver": "origin",
                "origin": {"platform": "telegram", "chat_id": "123"},
            }
            _deliver_result(job, f"Title\nMEDIA:{media_path}")

        send_mock.assert_called_once()
        args, kwargs = send_mock.call_args
        # Text content should have MEDIA: tag stripped
        assert "MEDIA:" not in args[3]
        assert "Title" in args[3]
        # Media files should be forwarded separately
        assert kwargs["media_files"] == [(str(media_path), False)]



class TestDeliverResultErrorReturns:
    """Verify _deliver_result returns error strings on failure, None on success."""

    def test_returns_error_when_platform_disabled(self):
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = False
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg):
            job = {
                "id": "disabled",
                "deliver": "origin",
                "origin": {"platform": "telegram", "chat_id": "123"},
            }
            result = _deliver_result(job, "Output.")
        assert result is not None
        assert "not configured" in result


@pytest.mark.usefixtures("_tick_lock_isolated")
class TestRunJobSessionPersistence:
    def test_run_job_passes_session_db_and_cron_platform(self, tmp_path):
        job = {
            "id": "test-job",
            "name": "test",
            "prompt": "hello",
        }
        fake_db = MagicMock()
        fake_db.get_compression_tip.side_effect = lambda session_id: session_id

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "test-key",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent

            success, output, final_response, error = run_job(job)

        assert success is True
        assert error is None
        assert final_response == "ok"
        assert "ok" in output

        kwargs = mock_agent_cls.call_args.kwargs
        assert kwargs["session_db"] is fake_db
        assert kwargs["platform"] == "cron"
        assert kwargs["session_id"].startswith("cron_test-job_")
        original_session_id = kwargs["session_id"]
        fake_db.get_compression_tip.assert_called_once_with(original_session_id)
        fake_db.end_session.assert_called_once()
        call_args = fake_db.end_session.call_args
        assert call_args[0][0] == original_session_id
        assert call_args[0][1] == "cron_complete"
        fake_db.close.assert_called_once()
        mock_agent.close.assert_called_once()


    def test_run_job_disarms_agent_close_after_scheduler_finalizes_session(self, tmp_path):
        """Cron owns the terminal session reason; agent.close must not end it twice.

        Regression for the #94736 teardown warning seen after every healthy cron
        run: the scheduler closed its shared SessionDB, then AIAgent.close() tried
        another end_session("agent_close"), forcing SessionDB to reopen solely
        for a redundant write.
        """
        job = {"id": "single-finalize", "name": "test", "prompt": "hello"}
        fake_db = MagicMock()
        fake_db.get_compression_tip.side_effect = lambda session_id: session_id
        closed = False
        calls_after_close = []

        def close_db():
            nonlocal closed
            closed = True

        def end_session(*args):
            if closed:
                calls_after_close.append(args)

        fake_db.close.side_effect = close_db
        fake_db.end_session.side_effect = end_session

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "test-key",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}

            def close_agent():
                if mock_agent._end_session_on_close:
                    fake_db.end_session(mock_agent.session_id, "agent_close")

            mock_agent.close.side_effect = close_agent
            mock_agent_cls.return_value = mock_agent
            success, *_ = run_job(job)

        assert success is True
        assert fake_db.end_session.call_count == 1
        assert calls_after_close == []


    @contextlib.contextmanager
    def _run_job_patches(self, tmp_path, extra=()):
        """Apply every patch run_job tests need, as one bundle.

        Yields ``(fake_db, mock_agent_cls)``. Using an ExitStack that enters
        the whole list means a caller can never silently drop a patch by
        index — the previous positional-list form let a seam split shift
        ``resolve_runtime_provider`` off the end of the applied slice, so the
        real resolver ran and (only on a dev machine with ambient creds) hid
        an auth failure that CI then caught. Every test enters all patches.

        ``extra`` is an iterable of additional context managers (e.g. a
        per-test ``_get_platform_tools`` patch) entered alongside the base set.
        """
        fake_db = MagicMock()
        mock_agent = MagicMock()
        mock_agent.run_conversation.return_value = {"final_response": "ok"}
        base = [
            patch("cron.scheduler._hermes_home", tmp_path),
            patch("cron.scheduler_delivery._resolve_origin", return_value=None),
            patch("hermes_cli.env_loader.load_hermes_dotenv"),
            patch("hermes_cli.env_loader.reset_secret_source_cache"),
            patch("hermes_state_registry.acquire", return_value=fake_db),
            patch(
                "hermes_cli.runtime_provider.resolve_runtime_provider",
                return_value={
                    "api_key": "test-key",
                    "base_url": "https://example.invalid/v1",
                    "provider": "openrouter",
                    "api_mode": "chat_completions",
                },
            ),
            patch("run_agent.AIAgent", return_value=mock_agent),
        ]
        with contextlib.ExitStack() as stack:
            entered = [stack.enter_context(cm) for cm in base]
            for cm in extra:
                stack.enter_context(cm)
            mock_agent_cls = entered[-1]  # the AIAgent patch
            yield fake_db, mock_agent_cls


    def test_run_job_memory_enabled_in_cron(self, tmp_path):
        """Cron agents get memory like any other agent run.

        skip_memory=False and the memory toolset is not policy-denied, so
        MEMORY.md/USER.md load and the memory tool follows normal toolset
        resolution.
        """
        job = {
            "id": "memory-enabled-job",
            "name": "test",
            "prompt": "hello",
        }
        with self._run_job_patches(tmp_path) as (fake_db, mock_agent_cls):
            run_job(job)

        kwargs = mock_agent_cls.call_args.kwargs
        assert kwargs["skip_memory"] is False
        assert "memory" not in (kwargs["disabled_toolsets"] or []), (
            "memory toolset must not be policy-denied in cron"
        )

    def test_run_job_keeps_per_job_memory_toolset(self, tmp_path):
        """A per-job enabled_toolsets naming memory keeps it."""
        job = {
            "id": "memory-toolset-job",
            "name": "test",
            "prompt": "remember what you learn",
            "enabled_toolsets": ["memory", "file"],
        }
        with self._run_job_patches(tmp_path) as (fake_db, mock_agent_cls):
            run_job(job)

        kwargs = mock_agent_cls.call_args.kwargs
        assert kwargs["skip_memory"] is False
        assert "memory" in (kwargs["enabled_toolsets"] or [])
        assert "file" in (kwargs["enabled_toolsets"] or [])
        assert "memory" not in kwargs["disabled_toolsets"]

    def test_tick_skips_due_jobs_while_dispatch_is_paused(self, tmp_path):
        """The drain gate runs before advancing a due job's schedule."""
        from cron.scheduler import tick

        job = {
            "id": "paused-due-job",
            "name": "paused due job",
            "schedule": {"kind": "interval", "seconds": 60},
            "next_run_at": "2020-01-01T00:00:00+00:00",
            "enabled": True,
        }
        with patch("cron.scheduler.get_due_jobs", return_value=[job]), patch(
            "cron.scheduler.claim_job_for_fire", return_value=True
        ) as claim, patch("cron.scheduler.run_one_job") as run_one:
            assert tick(verbose=False, sync=True, can_dispatch=lambda: False) == 0

        claim.assert_not_called()
        run_one.assert_not_called()

    def test_tick_marks_empty_response_as_error(self, tmp_path):
        """When run_job returns success=True but final_response is empty,
        tick() should mark the job as error so last_status != 'ok'.
        (issue #8585)
        """
        from cron.scheduler import tick

        job = {
            "id": "empty-job",
            "name": "empty-test",
            "prompt": "do something",
            "schedule": "every 1h",
            "enabled": True,
            "next_run_at": "2020-01-01T00:00:00",
            "deliver": "local",
            "last_status": None,
        }

        MagicMock()

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.mark_job_run") as mock_mark, \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("cron.scheduler.run_job", return_value=(True, "output", "", None)):
            tick(verbose=False)

        # Should be called with success=False because final_response is empty
        mock_mark.assert_called_once()
        call_args = mock_mark.call_args
        assert call_args[0][0] == "empty-job"
        assert call_args[0][1] is False  # success should be False
        assert "empty" in call_args[0][2].lower()  # error should mention empty

    def test_run_job_sets_auto_delivery_env_from_dotenv_home_channel(self, tmp_path, monkeypatch):
        job = {
            "id": "test-job",
            "name": "test",
            "prompt": "hello",
            "deliver": "telegram",
        }
        fake_db = MagicMock()
        seen = {}

        (tmp_path / ".env").write_text("TELEGRAM_HOME_CHANNEL=-2002\n")
        monkeypatch.delenv("TELEGRAM_HOME_CHANNEL", raising=False)
        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_PLATFORM", raising=False)
        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_CHAT_ID", raising=False)
        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_THREAD_ID", raising=False)

        class FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def run_conversation(self, *args, **kwargs):
                from gateway.session_context import get_session_env
                seen["platform"] = get_session_env("HERMES_CRON_AUTO_DELIVER_PLATFORM") or None
                seen["chat_id"] = get_session_env("HERMES_CRON_AUTO_DELIVER_CHAT_ID") or None
                seen["thread_id"] = get_session_env("HERMES_CRON_AUTO_DELIVER_THREAD_ID") or None
                return {"final_response": "ok"}

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler._preflight_job_config", return_value=None), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "***",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent", FakeAgent):
            success, output, final_response, error = run_job(job)

        assert success is True
        assert error is None
        assert final_response == "ok"
        assert "ok" in output
        assert seen == {
            "platform": "telegram",
            "chat_id": "-2002",
            "thread_id": None,
        }
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_PLATFORM") is None
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_CHAT_ID") is None
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_THREAD_ID") is None
        fake_db.close.assert_called_once()

    def test_run_job_preserves_slack_origin_thread_for_same_explicit_channel(self, tmp_path, monkeypatch):
        job = {
            "id": "slack-thread-job",
            "name": "slack-thread",
            "prompt": "hello",
            "deliver": "slack:C0B3KEP3SD6",
            "origin": {
                "platform": "slack",
                "chat_id": "C0B3KEP3SD6",
                "thread_id": "1778485067.844139",
            },
        }
        fake_db = MagicMock()
        seen = {}

        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_PLATFORM", raising=False)
        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_CHAT_ID", raising=False)
        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_THREAD_ID", raising=False)

        class FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def run_conversation(self, *args, **kwargs):
                from gateway.session_context import get_session_env

                seen["platform"] = get_session_env("HERMES_CRON_AUTO_DELIVER_PLATFORM") or None
                seen["chat_id"] = get_session_env("HERMES_CRON_AUTO_DELIVER_CHAT_ID") or None
                seen["thread_id"] = get_session_env("HERMES_CRON_AUTO_DELIVER_THREAD_ID") or None
                return {"final_response": "ok"}

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler._preflight_job_config", return_value=None), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "***",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent", FakeAgent):
            success, output, final_response, error = run_job(job)

        assert success is True
        assert error is None
        assert final_response == "ok"
        assert "ok" in output
        assert seen == {
            "platform": "slack",
            "chat_id": "C0B3KEP3SD6",
            "thread_id": "1778485067.844139",
        }
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_PLATFORM") is None
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_CHAT_ID") is None
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_THREAD_ID") is None
        fake_db.close.assert_called_once()

    @pytest.mark.parametrize("timeout_value", ["600", "0"])
    def test_run_job_heartbeats_oneshot_claim_in_both_wait_modes(
        self, tmp_path, monkeypatch, timeout_value
    ):
        """Timed and unlimited one-shot monitors both refresh their owned claim."""
        job = {
            "id": "heartbeat-job",
            "name": "heartbeat",
            "prompt": "hello",
            "schedule": {"kind": "once", "run_at": "2026-07-10T12:00:00Z"},
            "run_claim": {"at": "2026-07-10T12:00:00Z", "by": "owner-token"},
        }
        fake_db = MagicMock()

        class FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def run_conversation(self, *args, **kwargs):
                return {"final_response": "ok"}

        class FakeFuture:
            def result(self):
                return {"final_response": "ok"}

            def done(self):
                return True  # run_job's finally asks the real Future; this one has already returned

        fake_future = FakeFuture()
        fake_pool = MagicMock()
        fake_pool.submit.return_value = fake_future
        wait_results = [(set(), set()), ({fake_future}, set())]
        monotonic_ticks = itertools.count(step=61.0)
        monkeypatch.setenv("HERMES_CRON_TIMEOUT", timeout_value)

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler._preflight_job_config", return_value=None), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "***",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent", FakeAgent), \
             patch("cron.scheduler.concurrent.futures.ThreadPoolExecutor", return_value=fake_pool), \
             patch("cron.scheduler.concurrent.futures.wait", side_effect=wait_results), \
             patch("cron.scheduler.time.monotonic", side_effect=monotonic_ticks.__next__), \
             patch("cron.scheduler.heartbeat_run_claim", return_value=True) as heartbeat:
            success, _output, final_response, error = run_job(job)

        assert success is True
        assert error is None
        assert final_response == "ok"
        heartbeat.assert_called_once_with(
            "heartbeat-job", expected_owner="owner-token"
        )

    def test_run_job_resets_secret_source_cache_before_reload(self, tmp_path, monkeypatch):
        """Each run must clear the secret-source cache before re-reading the
        env, so a long-running gateway re-resolves Bitwarden/BSM-backed secrets
        instead of leaving the startup .env placeholder in place (#33465).

        A bare ``load_dotenv`` re-load can't do this: startup already recorded
        this HERMES_HOME in ``_APPLIED_HOMES``, so the external-secret pull
        no-ops and only the placeholder is re-applied. The scheduler must call
        ``reset_secret_source_cache()`` (forcing the re-pull) and route through
        ``load_hermes_dotenv`` (which then re-applies external secret sources).
        """
        job = {"id": "bsm-job", "name": "bsm", "prompt": "hello"}
        fake_db = MagicMock()
        call_order = []

        def _record_reset():
            call_order.append("reset")

        def _record_load(*args, **kwargs):
            call_order.append("load")
            return []

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.reset_secret_source_cache", _record_reset), \
             patch("hermes_cli.env_loader.load_hermes_dotenv", _record_load), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "***",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent
            success, _output, _final, error = run_job(job)

        assert success is True
        assert error is None
        # reset MUST precede the reload, else _APPLIED_HOMES no-ops the re-pull.
        assert call_order[:2] == ["reset", "load"], call_order

    def test_run_job_clears_stale_auto_delivery_thread_id_between_jobs(self, tmp_path, monkeypatch):
        jobs = [
            {
                "id": "threaded-job",
                "name": "threaded",
                "prompt": "hello",
                "deliver": "telegram:-1001:42",
            },
            {
                "id": "threadless-job",
                "name": "threadless",
                "prompt": "hello again",
                "deliver": "telegram:-2002",
            },
        ]
        fake_db = MagicMock()
        seen = []

        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_PLATFORM", raising=False)
        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_CHAT_ID", raising=False)
        monkeypatch.delenv("HERMES_CRON_AUTO_DELIVER_THREAD_ID", raising=False)

        class FakeAgent:
            def __init__(self, *args, **kwargs):
                pass

            def run_conversation(self, *args, **kwargs):
                from gateway.session_context import get_session_env

                seen.append(
                    {
                        "platform": get_session_env("HERMES_CRON_AUTO_DELIVER_PLATFORM") or None,
                        "chat_id": get_session_env("HERMES_CRON_AUTO_DELIVER_CHAT_ID") or None,
                        "thread_id": get_session_env("HERMES_CRON_AUTO_DELIVER_THREAD_ID") or None,
                    }
                )
                return {"final_response": "ok"}

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler._preflight_job_config", return_value=None), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "***",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent", FakeAgent):
            for job in jobs:
                success, output, final_response, error = run_job(job)
                assert success is True
                assert error is None
                assert final_response == "ok"
                assert "ok" in output

        assert seen == [
            {
                "platform": "telegram",
                "chat_id": "-1001",
                "thread_id": "42",
            },
            {
                "platform": "telegram",
                "chat_id": "-2002",
                "thread_id": None,
            },
        ]
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_PLATFORM") is None
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_CHAT_ID") is None
        assert os.getenv("HERMES_CRON_AUTO_DELIVER_THREAD_ID") is None
        assert fake_db.close.call_count == 2


class TestRunJobConfigLogging:
    """Verify that config.yaml parse failures are logged, not silently swallowed."""

    def test_bad_config_yaml_is_logged(self, caplog, tmp_path):
        """When config.yaml is malformed, a warning should be logged."""
        bad_yaml = tmp_path / "config.yaml"
        bad_yaml.write_text("invalid: yaml: [[[bad")

        job = {
            "id": "test-job",
            "name": "test",
            "prompt": "hello",
        }

        # Mock heavy post-yaml work so the test only exercises the warning
        # path. Without these mocks, run_job continues into provider
        # resolution and MCP discovery, both of which can spawn subprocesses
        # / hit the network and have caused this test to time out on CI
        # (>30s wall clock) under load. See PR #33661 follow-up.
        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   return_value={"provider": "openrouter", "api_key": "x",
                                 "base_url": "https://example.invalid",
                                 "api_mode": "chat_completions"}), \
             patch("tools.mcp_tool_discovery.discover_mcp_tools", return_value=[]), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent

            with caplog.at_level(logging.WARNING, logger="cron.scheduler"):
                run_job(job)

        assert any("failed to load config.yaml" in r.message for r in caplog.records), \
            f"Expected 'failed to load config.yaml' warning in logs, got: {[r.message for r in caplog.records]}"


class TestRunJobConfigEnvVarExpansion:
    """Verify that ${VAR} references in config.yaml are expanded when running cron jobs."""

    _RUNTIME = {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "provider": "openrouter",
        "api_mode": "chat_completions",
    }

    def test_model_env_ref_in_config_yaml_is_expanded(self, tmp_path, monkeypatch):
        """${VAR} in config.yaml model: is expanded using env after .env is loaded."""
        (tmp_path / "config.yaml").write_text("model: ${_HERMES_TEST_CRON_MODEL}\n")
        monkeypatch.setenv("_HERMES_TEST_CRON_MODEL", "gpt-4o-mini-cron-test")

        job = {"id": "env-job", "name": "env test", "prompt": "hi"}
        fake_db = MagicMock()

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   return_value=self._RUNTIME), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent
            success, _, _, error = run_job(job)

        assert success is True
        assert error is None
        kwargs = mock_agent_cls.call_args.kwargs
        assert kwargs["model"] == "gpt-4o-mini-cron-test", (
            f"Expected model='gpt-4o-mini-cron-test', got {kwargs['model']!r}. "
            "config.yaml ${VAR} was not expanded in the cron execution path."
        )


    def test_transient_dns_fallback_switches_provider_and_model_together(self, tmp_path):
        """DNS blip during primary OAuth resolve must still walk fallback_providers.

        Regression for Daily Focus Kickoff 2026-08-11: xai-oauth token refresh
        raised httpx.ConnectError ([Errno 8] nodename nor servname provided)
        and the scheduler only tried fallbacks on AuthError, so the job died
        before XAI_API_KEY / Anthropic could rescue it.
        """
        import httpx

        (tmp_path / "config.yaml").write_text(
            "model:\n"
            "  default: grok-4.5\n"
            "  provider: xai-oauth\n"
            "fallback_providers:\n"
            "  - provider: xai\n"
            "    model: grok-4.5\n"
            "  - provider: anthropic\n"
            "    model: claude-opus-5\n",
            encoding="utf-8",
        )
        job = {
            "id": "dns-fallback",
            "name": "dns fallback",
            "prompt": "hi",
            "provider": "xai-oauth",
            "model": "grok-4.5",
        }
        fake_db = MagicMock()
        requested = []

        def resolve_runtime(**kwargs):
            requested.append(kwargs.get("requested"))
            if kwargs.get("requested") in (None, "xai-oauth"):
                raise httpx.ConnectError(
                    "[Errno 8] nodename nor servname provided, or not known"
                )
            # First fallback rung (xai API key) succeeds.
            assert kwargs["requested"] == "xai"
            assert kwargs["target_model"] == "grok-4.5"
            return {**self._RUNTIME, "provider": "xai", "api_mode": "chat_completions"}

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   side_effect=resolve_runtime), \
             patch("tools.mcp_tool_discovery.discover_mcp_tools", return_value=[]), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent
            success, _, _, error = run_job(job)

        assert success is True, error
        assert error is None
        assert requested == ["xai-oauth", "xai"]
        kwargs = mock_agent_cls.call_args.kwargs
        assert kwargs["provider"] == "xai"
        assert kwargs["model"] == "grok-4.5"


    def test_auth_fallback_switches_provider_and_model_together(self, tmp_path):
        """Codex auth failure must produce OpenRouter+GLM, never OpenRouter+GPT."""
        from hermes_cli.auth import AuthError

        (tmp_path / "config.yaml").write_text(
            "model:\n"
            "  default: gpt-5.6-sol\n"
            "  provider: openai-codex\n"
            "fallback_providers:\n"
            "  - provider: anthropic\n"
            "  - provider: openrouter\n"
            "    model: z-ai/glm-5.2\n",
            encoding="utf-8",
        )
        job = {
            "id": "auth-fallback",
            "name": "auth fallback",
            "prompt": "hi",
            "provider_snapshot": "openai-codex",
            "model_snapshot": "gpt-5.6-sol",
        }
        fake_db = MagicMock()
        requested = []

        def resolve_runtime(**kwargs):
            requested.append(kwargs.get("requested"))
            if kwargs.get("requested") in (None, "openai-codex"):
                # Cron must retain the configured primary provider for drift
                # comparison even when older/custom AuthError sites omit it.
                raise AuthError("No Codex credentials stored")
            assert kwargs["requested"] == "openrouter"
            assert kwargs["target_model"] == "z-ai/glm-5.2"
            return {**self._RUNTIME, "provider": "openrouter"}

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   side_effect=resolve_runtime), \
             patch("tools.mcp_tool_discovery.discover_mcp_tools", return_value=[]), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent
            success, _, _, error = run_job(job)

        assert success is True
        assert error is None
        assert requested == [None, "openrouter"]
        kwargs = mock_agent_cls.call_args.kwargs
        assert kwargs["provider"] == "openrouter"
        assert kwargs["model"] == "z-ai/glm-5.2"


    def test_unexpanded_ref_passthrough_when_var_unset(self, tmp_path, monkeypatch):
        """When the env var is not set, the literal ${VAR} is kept verbatim (not crashed)."""
        (tmp_path / "config.yaml").write_text("model: ${_HERMES_TEST_CRON_UNSET_VAR}\n")
        monkeypatch.delenv("_HERMES_TEST_CRON_UNSET_VAR", raising=False)

        job = {"id": "unset-job", "name": "unset var test", "prompt": "hi"}
        fake_db = MagicMock()

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   return_value=self._RUNTIME), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent
            success, _, _, error = run_job(job)

        assert success is True
        kwargs = mock_agent_cls.call_args.kwargs
        # Unresolved refs are kept verbatim — _expand_env_vars contract
        assert kwargs["model"] == "${_HERMES_TEST_CRON_UNSET_VAR}"


class TestRunJobModelResolution:
    """Verify defensive model resolution for jobs stored with ``model: null``.

    Issue #23979: a cron job created without an explicit model is stored as
    ``model: null``. At fire time the scheduler must:
      1. fall back to ``HERMES_MODEL`` env if set,
      2. else fall back to config.yaml ``model.default`` if set,
      3. else fail fast with an actionable error — never let an empty string
         reach the provider where it surfaces as an opaque 400.
    """

    _RUNTIME = {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "provider": "openrouter",
        "api_mode": "chat_completions",
    }

    def test_null_job_model_falls_back_to_env(self, tmp_path, monkeypatch):
        """``model: null`` on the job uses HERMES_MODEL when set."""
        (tmp_path / "config.yaml").write_text("")
        monkeypatch.setenv("HERMES_MODEL", "env-model")

        job = {"id": "null-model-job", "name": "null model", "prompt": "hi", "model": None}
        fake_db = MagicMock()

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   return_value=self._RUNTIME), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent
            success, _, _, error = run_job(job)

        assert success is True
        assert error is None
        assert mock_agent_cls.call_args.kwargs["model"] == "env-model"


    def test_no_model_anywhere_fails_with_actionable_error(self, tmp_path, monkeypatch):
        """All three sources empty → fail fast with a clear message, not an opaque 400."""
        (tmp_path / "config.yaml").write_text("")
        monkeypatch.delenv("HERMES_MODEL", raising=False)

        job = {"id": "no-model-job", "name": "no model anywhere", "prompt": "hi", "model": None}
        fake_db = MagicMock()

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   return_value=self._RUNTIME), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            success, _, _, error = run_job(job)

        assert success is False
        assert error is not None
        assert "no model configured" in error
        # AIAgent must never be constructed with an empty model — that's
        # precisely the bug we're guarding against.
        mock_agent_cls.assert_not_called()


    def test_config_model_alias_key_resolves(self, tmp_path, monkeypatch):
        """A ``model: {model: ...}`` alias key resolves like the CLI sibling.

        ``hermes_cli/oneshot.py``, ``fallback_cmd.py`` and ``prompt_size.py``
        all accept ``model.model`` as an alias for ``model.default``. The cron
        resolver mirrors that so a config that works in the CLI also works in
        cron.
        """
        (tmp_path / "config.yaml").write_text("model:\n  model: alias-key-model\n")
        monkeypatch.delenv("HERMES_MODEL", raising=False)

        job = {"id": "alias-job", "name": "alias", "prompt": "hi", "model": None}
        fake_db = MagicMock()

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   return_value=self._RUNTIME), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent
            success, _, _, error = run_job(job)

        assert success is True
        assert error is None
        assert mock_agent_cls.call_args.kwargs["model"] == "alias-key-model"

    def test_corrupt_config_yaml_does_not_crash_with_job_model(self, tmp_path, monkeypatch):
        """A malformed config.yaml degrades gracefully when the job has a model."""
        (tmp_path / "config.yaml").write_text("{{{invalid yaml!!!")
        monkeypatch.delenv("HERMES_MODEL", raising=False)

        job = {"id": "corrupt-job", "name": "corrupt", "prompt": "hi", "model": "explicit-model"}
        fake_db = MagicMock()

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch("hermes_cli.runtime_provider.resolve_runtime_provider",
                   return_value=self._RUNTIME), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.return_value = {"final_response": "ok"}
            mock_agent_cls.return_value = mock_agent
            success, _, _, error = run_job(job)

        # Explicit job model survives the corrupt-config fall-through.
        assert success is True
        assert error is None
        assert mock_agent_cls.call_args.kwargs["model"] == "explicit-model"


class TestRunJobSkillBacked:
    def test_run_job_preserves_skill_env_passthrough_into_worker_thread(self, tmp_path):
        job = {
            "id": "skill-env-job",
            "name": "skill env test",
            "prompt": "Use the skill.",
            "skill": "notion",
        }

        fake_db = MagicMock()

        def _skill_view(name):
            assert name == "notion"
            from tools.env_passthrough import register_env_passthrough

            register_env_passthrough(["NOTION_API_KEY"])
            return json.dumps({"success": True, "content": "# notion\nUse Notion."})

        def _run_conversation(prompt, *, task_id=None):
            from tools.env_passthrough import get_all_passthrough

            assert isinstance(task_id, str)
            assert task_id.startswith("cron:skill-env-job:")
            assert "NOTION_API_KEY" in get_all_passthrough()
            return {"final_response": "ok"}

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler_delivery._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state_registry.acquire", return_value=fake_db), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "***",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("tools.skills_tool.skill_view", side_effect=_skill_view), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent = MagicMock()
            mock_agent.run_conversation.side_effect = _run_conversation
            mock_agent_cls.return_value = mock_agent

            try:
                success, output, final_response, error = run_job(job)
            finally:
                clear_env_passthrough()

        assert success is True
        assert error is None
        assert final_response == "ok"


@pytest.mark.usefixtures("_tick_lock_isolated")
class TestSilentDelivery:
    """Verify that [SILENT] responses suppress delivery while still saving output."""

    def _make_job(self):
        return {
            "id": "monitor-job",
            "name": "monitor",
            "deliver": "origin",
            "origin": {"platform": "telegram", "chat_id": "123"},
        }

    def test_silent_response_suppresses_delivery(self, caplog):
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", return_value=(True, "# output", "[SILENT]", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            with caplog.at_level(logging.INFO, logger="cron.scheduler"):
                tick(verbose=False)
        deliver_mock.assert_not_called()
        assert any(SILENT_MARKER in r.message for r in caplog.records)

    def test_silent_with_note_suppresses_delivery(self):
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", return_value=(True, "# output", "[SILENT] No changes detected", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            tick(verbose=False)
        deliver_mock.assert_not_called()

    def test_silent_trailing_suppresses_delivery(self):
        """Agent appended [SILENT] after explanation text — must still suppress."""
        response = "2 deals filtered out (like<10, reply<15).\n\n[SILENT]"
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", return_value=(True, "# output", response, None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            tick(verbose=False)
        deliver_mock.assert_not_called()

    def test_silent_is_case_insensitive(self):
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", return_value=(True, "# output", "[silent] nothing new", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            tick(verbose=False)
        deliver_mock.assert_not_called()

    def test_bracketless_silent_variants_suppress(self):
        """Bracketless near-markers the model emits when it drops brackets
        must still suppress delivery (#51438, #46917)."""
        from cron.scheduler import tick
        for marker in ("SILENT", "NO_REPLY", "NO REPLY", "no_reply"):
            with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
                 patch("cron.scheduler.run_job", return_value=(True, "# output", marker, None)), \
                 patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
                 patch("cron.scheduler._deliver_result") as deliver_mock, \
                 patch("cron.scheduler.mark_job_run"):
                tick(verbose=False)
            deliver_mock.assert_not_called()

    def test_report_quoting_marker_mid_sentence_still_delivers(self):
        """A genuine report that merely mentions the token mid-sentence must
        be delivered — the old substring check wrongly swallowed it."""
        response = "I considered staying [SILENT] but here is the summary: 3 items merged."
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", return_value=(True, "# output", response, None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            tick(verbose=False)
        deliver_mock.assert_called_once()


    def test_failed_job_always_delivers(self):
        """Failed jobs deliver regardless of [SILENT] in output."""
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", return_value=(False, "# output", "", "some error")), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            tick(verbose=False)
        deliver_mock.assert_called_once()

    def test_output_saved_even_when_delivery_suppressed(self):
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", return_value=(True, "# full output", "[SILENT]", None)), \
             patch("cron.scheduler.save_job_output") as save_mock, \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run"):
            save_mock.return_value = "/tmp/out.md"
            from cron.scheduler import tick
            tick(verbose=False)
        save_mock.assert_called_once_with("monitor-job", "# full output")
        deliver_mock.assert_not_called()

    def test_whitespace_only_response_is_marked_failed_not_delivered(self):
        """Whitespace-only final responses should behave like empty responses."""
        # v0.15.1 catch-up: tick() consumes get_due_and_skipped_jobs() (upstream),
        # so patch that — the auto-merge had carried the fork's stale get_due_jobs
        # patch, which left tick reading the real (empty) due list (mirrors the
        # sibling test_output_saved above).
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", return_value=(True, "# output", "   \n\t  ", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run") as mark_mock:
            from cron.scheduler import tick
            tick(verbose=False)

        deliver_mock.assert_not_called()
        mark_mock.assert_called_once_with(
            "monitor-job",
            False,
            "Agent completed but produced empty response (model error, timeout, or misconfiguration)",
            delivery_error=None,
        )


@pytest.mark.usefixtures("_tick_lock_isolated")
class TestEventEmitterSummary:
    def _make_job(self):
        return {
            "id": "learning-loop",
            "name": "learning-loop",
            "deliver": "origin",
            "origin": {"platform": "telegram", "chat_id": "123"},
        }

    def test_tick_preserves_moderately_long_summary_for_event_bus(self):
        """Cron event summaries should not be hard-cut at 500 chars."""
        response = (
            "Learning-loop review complete.\n\n"
            "- No `reasoning_effort` changes were justified. Effective live map still holds: "
            "main/sentinel/devflow `high`, matcher/tailor `xhigh`, tracker/applier/cv-handler "
            "`medium`, scout `low`, notifier `minimal`.\n"
            "- No `nudge.interval` changes were needed. Consolidated cadence is still correct: "
            "main/tracker/sentinel `14400`, scout/tailor/cv-handler/devflow `21600`, applier "
            "`10800`, matcher `7200`, notifier `43200`. "
            "`nudge.consolidate_memory: true` is still enabled everywhere."
        )
        assert len(response) > 500

        emitter = MagicMock()
        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._make_job()], [])), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job", return_value=(True, "# output", response, None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result"), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[{"id": "learning-loop", "consecutive_errors": 0}]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert emitter.on_job_completed.call_args.kwargs["output_summary"] == response


class TestOneShotDispatchClaim:
    """run_one_job must claim a finite one-shot's dispatch BEFORE run_job so a
    tick that dies mid-execution can't re-fire it forever (issue #38758).

    NOTE (merge v0.18.0): the fork's built-in ticker fires via
    ``tick`` -> ``_process_job`` -> ``run_job`` (Guard #3/#4 + soft-deadline),
    while the shared ``run_one_job`` body (used by the external Chronos
    ``fire_due`` path) is where the dispatch claim lives. This test therefore
    exercises ``run_one_job`` directly — the resolved source's home for the
    #38758 claim — instead of driving ``tick``.
    """

    def _oneshot(self):
        return {
            "id": "monitor-job",
            "name": "monitor",
            "deliver": "origin",
            "origin": {"platform": "telegram", "chat_id": "123"},
            "schedule": {"kind": "once", "run_at": "2026-01-01T00:00:00+00:00"},
            "repeat": {"times": 1, "completed": 0},
        }

    def test_claim_runs_before_run_job(self):
        order = []
        with patch("cron.scheduler.get_due_jobs", return_value=[self._oneshot()]), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.claim_dispatch", side_effect=lambda _id: order.append("claim") or True), \
             patch("cron.scheduler.run_job", side_effect=lambda _j, **_kw: order.append("run") or (True, "# out", "ok", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result"), \
             patch("cron.scheduler.mark_job_run"):
            run_one_job(self._oneshot())
        assert order == ["claim", "run"]  # claim strictly before side effect

    def test_refused_claim_skips_run_job(self):
        with patch("cron.scheduler.claim_dispatch", return_value=False), \
             patch("cron.scheduler.run_job") as run_mock, \
             patch("cron.scheduler.save_job_output"), \
             patch("cron.scheduler._deliver_result") as deliver_mock, \
             patch("cron.scheduler.mark_job_run") as mark_mock:
            run_one_job(self._oneshot())
        run_mock.assert_not_called()
        deliver_mock.assert_not_called()
        mark_mock.assert_not_called()


class TestBuildJobPromptSilentHint:
    """Verify _build_job_prompt always injects [SILENT] guidance."""

    def test_hint_always_present(self):
        job = {"prompt": "Check for updates"}
        result = _build_job_prompt(job)
        assert "[SILENT]" in result
        assert "Check for updates" in result


class TestParseWakeGate:
    """Unit tests for _parse_wake_gate — pure function, no side effects."""

    def test_empty_output_wakes(self):
        from cron.scheduler import _parse_wake_gate
        assert _parse_wake_gate("") is True
        assert _parse_wake_gate(None) is True


    def test_wake_gate_false_skips(self):
        from cron.scheduler import _parse_wake_gate
        assert _parse_wake_gate('{"wakeAgent": false}') is False


class TestRunJobWakeGate:
    """Integration tests for run_job wake-gate short-circuit."""

    @pytest.fixture(autouse=True)
    def _stub_runtime_provider(self):
        """Stub ``resolve_runtime_provider`` for wake-gate tests.

        ``run_job`` resolves the runtime provider BEFORE constructing
        ``AIAgent``, so these tests must mock ``resolve_runtime_provider``
        in addition to ``AIAgent`` — otherwise in a hermetic CI env (no
        API keys), the resolver raises and the test fails before the
        patched AIAgent is ever reached.
        """
        fake_runtime = {
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "test-key",
            "source": "stub",
            "requested_provider": None,
        }
        with patch(
            "hermes_cli.runtime_provider.resolve_runtime_provider",
            return_value=fake_runtime,
        ):
            yield

    def _make_job(self, name="wake-gate-test", script="check.py"):
        """Minimal valid cron job dict for run_job."""
        return {
            "id": f"job_{name}",
            "name": name,
            "prompt": "Do a thing",
            "schedule": "*/5 * * * *",
            "script": script,
        }

    def test_wake_false_skips_agent_and_returns_silent(self, caplog):
        """When _run_job_script output ends with {wakeAgent: false}, the agent
        is not invoked and run_job returns the SILENT marker so delivery is
        suppressed."""
        from cron.scheduler import SILENT_MARKER
        import cron.scheduler as scheduler
        from cron import scheduler_script as sched_script

        with patch.object(sched_script, "_run_job_script",
                          return_value=(True, '{"wakeAgent": false}')), \
             patch("run_agent.AIAgent") as agent_cls:
            success, doc, final, err = scheduler.run_job(self._make_job())

        assert success is True
        assert err is None
        assert final == SILENT_MARKER
        assert "Script gate returned `wakeAgent=false`" in doc
        agent_cls.assert_not_called()

    def test_wake_true_runs_agent_with_injected_output(self):
        """When the script returns {wakeAgent: true, data: ...}, the agent is
        invoked and the data line still shows up in the prompt."""
        import cron.scheduler as scheduler
        from cron import scheduler_script as sched_script

        script_output = '{"wakeAgent": true, "data": {"new": 3}}'
        agent = MagicMock()
        agent.run_conversation = MagicMock(return_value={
            "final_response": "ok", "messages": []
        })
        with patch.object(sched_script, "_run_job_script",
                          return_value=(True, script_output)), \
             patch("run_agent.AIAgent", return_value=agent) as agent_cls:
            success, doc, final, err = scheduler.run_job(self._make_job())

        agent_cls.assert_called_once()
        # The script output should be visible in the prompt passed to
        # run_conversation.
        call_kwargs = agent.run_conversation.call_args
        prompt_arg = call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("user_message", "")
        assert script_output in prompt_arg
        assert success is True
        assert err is None

    def test_script_runs_only_once_on_wake(self):
        """Wake-true path must not re-run the script inside _build_job_prompt
        (script would execute twice otherwise, wasting work and risking
        double-side-effects)."""
        import cron.scheduler as scheduler

        call_count = 0
        def _script_stub(path, timeout_s=None):
            nonlocal call_count
            call_count += 1
            return (True, "regular output")

        agent = MagicMock()
        agent.run_conversation = MagicMock(return_value={
            "final_response": "ok", "messages": []
        })
        with patch.object(scheduler, "_run_job_script", side_effect=_script_stub), \
             patch("run_agent.AIAgent", return_value=agent):
            scheduler.run_job(self._make_job())

        assert call_count == 1, f"script ran {call_count}x, expected exactly 1"

    def test_script_failure_does_not_trigger_gate(self):
        """If _run_job_script returns success=False, the gate is NOT evaluated
        and the agent still runs (the failure is reported as context)."""
        import cron.scheduler as scheduler

        # Malicious or broken script whose stderr happens to contain the
        # gate JSON — we must NOT honor it because ran_ok is False.
        agent = MagicMock()
        agent.run_conversation = MagicMock(return_value={
            "final_response": "ok", "messages": []
        })
        with patch.object(scheduler, "_run_job_script",
                          return_value=(False, '{"wakeAgent": false}')), \
             patch("run_agent.AIAgent", return_value=agent) as agent_cls:
            success, doc, final, err = scheduler.run_job(self._make_job())

        agent_cls.assert_called_once()  # Agent DID wake despite the gate-like text

    def test_no_script_path_runs_agent_normally(self):
        """Regression: jobs without a script still work."""
        import cron.scheduler as scheduler

        agent = MagicMock()
        agent.run_conversation = MagicMock(return_value={
            "final_response": "ok", "messages": []
        })
        job = self._make_job(script=None)
        job.pop("script", None)
        with patch.object(scheduler, "_run_job_script") as script_fn, \
             patch("run_agent.AIAgent", return_value=agent) as agent_cls:
            scheduler.run_job(job)

        script_fn.assert_not_called()
        agent_cls.assert_called_once()


class TestBuildJobPromptMissingSkill:
    """Verify that a missing skill logs a warning and does not crash the job."""

    def _missing_skill_view(self, name: str) -> str:
        return json.dumps({"success": False, "error": f"Skill '{name}' not found."})


    def test_missing_skill_injects_user_notice_into_prompt(self):
        """A system notice about the missing skill is injected into the prompt."""
        with patch("tools.skills_tool.skill_view", side_effect=self._missing_skill_view):
            result = _build_job_prompt({"skills": ["ghost-skill"], "prompt": "do something"})
        assert "ghost-skill" in result
        assert "not found" in result.lower() or "skipped" in result.lower()


class TestBuildJobPromptAbsoluteSkillPath:
    """Cron jobs may store absolute skill paths; normalize before skill_view."""

    def test_absolute_skill_path_normalized_before_skill_view(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "alpha-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Alpha\nDo alpha.")
        absolute_path = str(skill_dir)
        seen_names: list[str] = []

        def _skill_view(name: str) -> str:
            seen_names.append(name)
            if name == "alpha-skill":
                return json.dumps({"success": True, "content": "# Alpha\nDo alpha."})
            return json.dumps({"success": False, "error": f"Skill '{name}' not found."})

        with patch("tools.skills_tool.SKILLS_DIR", skills_dir), \
             patch("tools.skills_tool.skill_view", side_effect=_skill_view):
            result = _build_job_prompt({"skills": [absolute_path], "prompt": "go"})

        assert seen_names == ["alpha-skill"]
        assert "Do alpha." in result


class TestBuildJobPromptBumpUse:
    """Verify that cron jobs bump skill usage counters so the curator sees them as active."""

    def test_bump_use_called_for_loaded_skill(self):
        """bump_use is called for each successfully loaded skill."""

        def _skill_view(name: str) -> str:
            return json.dumps({"success": True, "content": f"Content for {name}."})

        with patch("tools.skills_tool.skill_view", side_effect=_skill_view), \
             patch("tools.skill_usage.bump_use") as mock_bump:
            _build_job_prompt({
                "id": "cron-task",
                "skills": ["alpha", "beta"],
                "prompt": "go",
            })

        assert mock_bump.call_count == 2
        calls = [c[0][0] for c in mock_bump.call_args_list]
        assert "alpha" in calls
        assert "beta" in calls
        assert all(
            call.kwargs == {"task_id": "cron-task"}
            for call in mock_bump.call_args_list
        )


class TestSendMediaViaAdapter:
    """Unit tests for _send_media_via_adapter — routes files to typed adapter methods."""

    def _safe_media_path(self, tmp_path, monkeypatch, name, data=b"media"):
        root = tmp_path / "media-cache"
        media_file = root / name
        media_file.parent.mkdir(parents=True, exist_ok=True)
        media_file.write_bytes(data)
        monkeypatch.setattr(
            "gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS",
            (root,),
        )
        return media_file.resolve()

    @staticmethod
    def _run_with_loop(adapter, chat_id, media_files, metadata, job):
        """Helper: run _send_media_via_adapter with immediate scheduling."""
        from concurrent.futures import Future

        def fake_run_coro(coro, _loop):
            coro.close()
            completed = Future()
            completed.set_result(MagicMock(success=True))
            return completed

        with patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coro):
            _send_media_via_adapter(adapter, chat_id, media_files, metadata, MagicMock(), job)


    def test_multiple_media_files_all_delivered(self, tmp_path, monkeypatch):
        adapter = MagicMock()
        adapter.send_voice = AsyncMock()
        adapter.send_image_file = AsyncMock()
        voice_path = self._safe_media_path(tmp_path, monkeypatch, "voice.mp3")
        photo_path = self._safe_media_path(tmp_path, monkeypatch, "photo.jpg")
        media_files = [(str(voice_path), False), (str(photo_path), False)]
        self._run_with_loop(adapter, "123", media_files, None, {"id": "j3"})
        adapter.send_voice.assert_called_once()
        adapter.send_image_file.assert_called_once()


class TestParallelTick:
    """Verify that tick() runs due jobs concurrently and isolates ContextVars."""

    @pytest.fixture(autouse=True)
    def _isolate_tick_lock(self, tmp_path):
        """Point the tick file lock at a per-test temp dir to avoid xdist contention."""
        lock_dir = tmp_path / "cron"
        lock_dir.mkdir()
        lock_file = lock_dir / ".tick.lock"
        with patch("cron.scheduler._get_lock_paths", return_value=(lock_dir, lock_file)):
            yield

    def test_parallel_jobs_run_concurrently(self):
        """Two jobs launched in the same tick should overlap in time."""
        import threading

        barrier = threading.Barrier(2, timeout=5)
        call_order = []

        def mock_run_job(job, *, defer_agent_teardown=None, **kw):
            """Each job hits a barrier — both must be active simultaneously."""
            call_order.append(("start", job["id"]))
            barrier.wait()  # blocks until both threads reach here
            call_order.append(("end", job["id"]))
            return (True, "output", "response", None)

        jobs = [
            {"id": "job-a", "name": "a", "deliver": "local"},
            {"id": "job-b", "name": "b", "deliver": "local"},
        ]

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=(jobs, [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", side_effect=mock_run_job), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            result = tick(verbose=False)

        assert result == 2
        # Both starts happened before both ends — proof of concurrency
        starts = [i for i, (action, _) in enumerate(call_order) if action == "start"]
        ends = [i for i, (action, _) in enumerate(call_order) if action == "end"]
        assert len(starts) == 2
        assert len(ends) == 2
        assert max(starts) < min(ends), f"Jobs not concurrent: {call_order}"

    def test_parallel_jobs_isolated_contextvars(self):
        """Each job's ContextVars must be isolated — no cross-contamination."""
        from gateway.session_context import get_session_env
        seen = {}

        def mock_run_job(job, *, defer_agent_teardown=None, **kw):
            origin = job.get("origin", {})
            # run_job sets ContextVars — verify each job sees its own
            from gateway.session_context import set_session_vars, clear_session_vars
            tokens = set_session_vars(
                platform=origin.get("platform", ""),
                chat_id=str(origin.get("chat_id", "")),
            )
            import time
            time.sleep(0.05)  # give other thread time to set its vars
            platform = get_session_env("HERMES_SESSION_PLATFORM")
            chat_id = get_session_env("HERMES_SESSION_CHAT_ID")
            seen[job["id"]] = {"platform": platform, "chat_id": chat_id}
            clear_session_vars(tokens)
            return (True, "output", "response", None)

        jobs = [
            {"id": "tg-job", "name": "tg", "deliver": "local",
             "origin": {"platform": "telegram", "chat_id": "111"}},
            {"id": "dc-job", "name": "dc", "deliver": "local",
             "origin": {"platform": "discord", "chat_id": "222"}},
        ]

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=(jobs, [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", side_effect=mock_run_job), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            tick(verbose=False)

        assert seen["tg-job"] == {"platform": "telegram", "chat_id": "111"}
        assert seen["dc-job"] == {"platform": "discord", "chat_id": "222"}

    def test_max_parallel_env_var(self, monkeypatch):
        """HERMES_CRON_MAX_PARALLEL=1 should restore serial behaviour."""
        monkeypatch.setenv("HERMES_CRON_MAX_PARALLEL", "1")
        call_times = []

        def mock_run_job(job, *, defer_agent_teardown=None, **_kw):
            import time
            call_times.append(("start", job["id"], time.monotonic()))
            time.sleep(0.05)
            call_times.append(("end", job["id"], time.monotonic()))
            return (True, "output", "response", None)

        jobs = [
            {"id": "s1", "name": "s1", "deliver": "local"},
            {"id": "s2", "name": "s2", "deliver": "local"},
        ]

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=(jobs, [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler.claim_job_for_fire", return_value=True), \
             patch("cron.scheduler.run_job", side_effect=mock_run_job), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            result = tick(verbose=False)

        assert result == 2
        # With max_workers=1, second job starts after first ends
        end_s1 = [t for action, jid, t in call_times if action == "end" and jid == "s1"][0]
        start_s2 = [t for action, jid, t in call_times if action == "start" and jid == "s2"][0]
        assert start_s2 >= end_s1, "Jobs ran concurrently despite max_parallel=1"


class TestDeliverResultTimeoutCancelsFuture:
    """When future.result(timeout=60) raises TimeoutError in the live adapter
    delivery path, the outcome depends on whether the coroutine was already
    running.  future.cancel() returning False means it is in flight on the wire
    (cannot be un-sent) → treat as DELIVERED and skip the standalone fallback to
    avoid a duplicate (#38922).  future.cancel() returning True means it never
    started (wedged loop) → nothing was sent, so fall through to standalone or
    the message is silently dropped.  Regression for #38922.
    """

    def test_live_adapter_timeout_assumes_delivered_no_duplicate(self):
        """End-to-end: live adapter confirmation times out past the 60s budget.
        The fix (#38922) treats the send as already-dispatched/delivered and
        does NOT run the standalone fallback — otherwise the message is sent
        twice."""
        from gateway.config import Platform
        from concurrent.futures import Future

        # Live adapter whose send() coroutine never resolves within the budget
        adapter = AsyncMock()
        adapter.send.return_value = MagicMock(success=True)

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        loop = MagicMock()
        loop.is_running.return_value = True

        # A real concurrent.futures.Future, but we override .result() to raise
        # TimeoutError exactly like the 60s wait firing in production.  We make
        # .cancel() return False to simulate the coroutine being ALREADY RUNNING
        # on the gateway loop (in flight on the wire) — the case where the send
        # cannot be un-sent and a standalone resend would be a duplicate.
        captured_future = Future()
        cancel_calls = []

        def in_flight_cancel():
            cancel_calls.append(True)
            return False  # already running — cannot be cancelled

        captured_future.cancel = in_flight_cancel
        captured_future.result = MagicMock(side_effect=TimeoutError("timed out"))

        def fake_run_coro(coro, _loop):
            coro.close()
            return captured_future

        job = {
            "id": "timeout-job",
            "deliver": "origin",
            "origin": {"platform": "telegram", "chat_id": "123"},
        }

        standalone_send = AsyncMock(return_value={"success": True})

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}), \
             patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coro), \
             patch("tools.send_message_tool._send_to_platform", new=standalone_send):
            result = _deliver_result(
                job,
                "Hello world",
                adapters={Platform.TELEGRAM: adapter},
                loop=loop,
            )

        # 1. cancel() was attempted (returned False = in flight).
        assert cancel_calls == [True], "future.cancel() should be attempted on TimeoutError"
        # 2. Delivery is reported successful (no error string returned).
        assert result is None, f"expected successful delivery, got error: {result!r}"
        # 3. The standalone fallback must NOT run — that is the #38922 fix:
        #    an in-flight confirmation timeout is assume-delivered, not a resend.
        standalone_send.assert_not_awaited()


class TestDeliverResultLiveAdapterUnconfirmed:
    """Regression for #47056.

    When a live adapter's send() returns ``None`` (swallowed exception / busy
    platform) or a result object that lacks an explicit ``success`` attribute
    (bare dict / partial object), the scheduler must NOT log "delivered via
    live adapter" and silently drop the message.  Every unconfirmed shape must
    fall through to the standalone delivery path so the message actually
    arrives.  The pre-fix check ``send_result is None or not getattr(...,
    "success", True)`` let a ``.success``-less object default to True = silent
    success.
    """

    def _run(self, send_value):
        from gateway.config import Platform
        from concurrent.futures import Future

        adapter = AsyncMock()
        adapter.send.return_value = send_value

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        loop = MagicMock()
        loop.is_running.return_value = True

        completed_future = Future()
        completed_future.set_result(send_value)

        def fake_run_coro(coro, _loop):
            coro.close()
            return completed_future

        job = {
            "id": "unconfirmed-job",
            "deliver": "origin",
            "origin": {"platform": "telegram", "chat_id": "123"},
        }

        standalone_send = AsyncMock(return_value={"success": True})

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}), \
             patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coro), \
             patch("tools.send_message_tool._send_to_platform", new=standalone_send):
            result = _deliver_result(
                job,
                "Hello world",
                adapters={Platform.TELEGRAM: adapter},
                loop=loop,
            )
        return result, standalone_send

    def test_none_result_falls_through_to_standalone(self):
        """send() returning None must trigger the standalone fallback, not a
        silent "delivered" log."""
        result, standalone_send = self._run(None)
        assert result is None, f"standalone should have delivered, got: {result!r}"
        standalone_send.assert_awaited_once()


class TestDeliverOriginUnresolvableIsLocal:
    """Regression for #43014.

    A cron job created in a CLI session has no {platform, chat_id} origin.
    With ``deliver=origin`` (or auto-detect / deliver=None) and no configured
    platform home channel, delivery is unresolvable — but that is the EXPECTED
    state for CLI jobs, not an error.  _deliver_result must return None (treat
    as local; output stays in last_output), not the "no delivery target
    resolved" error string that previously fired on every run.
    """

    def _deliver(self, job, monkeypatch):
        from cron import scheduler_delivery as sched_delivery
        # No home channel for any platform → origin is unresolvable.
        monkeypatch.setattr(sched_delivery, "_get_home_target_chat_id", lambda *_: "")
        return _deliver_result(job, "CLI bulletin")

    def test_origin_with_no_home_channels_returns_none(self, monkeypatch):
        job = {"id": "cli-job", "deliver": "origin", "origin": "cli-session-provenance"}
        assert self._deliver(job, monkeypatch) is None


class TestSendMediaTimeoutCancelsFuture:
    """Same orphan-coroutine guarantee for _send_media_via_adapter's
    future.result(timeout=30) call. If this times out mid-batch, the
    in-flight coroutine must be cancelled before the next file is tried.
    """

    def test_media_send_timeout_cancels_future_and_continues(self, tmp_path, monkeypatch):
        """End-to-end: _send_media_via_adapter with a future whose .result()
        raises TimeoutError. Assert cancel() fires and the loop proceeds
        to the next file rather than hanging or crashing."""
        from concurrent.futures import Future

        adapter = MagicMock()
        adapter.send_image_file = AsyncMock()
        adapter.send_video = AsyncMock()

        # First file: future that times out. Second file: future that resolves OK.
        timeout_future = Future()
        timeout_cancel_calls = []
        original_cancel = timeout_future.cancel

        def tracking_cancel():
            timeout_cancel_calls.append(True)
            return original_cancel()

        timeout_future.cancel = tracking_cancel
        timeout_future.result = MagicMock(side_effect=TimeoutError("timed out"))

        ok_future = Future()
        ok_future.set_result(MagicMock(success=True))

        futures_iter = iter([timeout_future, ok_future])

        def fake_run_coro(coro, _loop):
            coro.close()
            return next(futures_iter)

        root = tmp_path / "media-cache"
        slow = root / "slow.png"
        fast = root / "fast.mp4"
        slow.parent.mkdir(parents=True)
        slow.write_bytes(b"slow")
        fast.write_bytes(b"fast")
        monkeypatch.setattr(
            "gateway.platforms.base.MEDIA_DELIVERY_SAFE_ROOTS",
            (root,),
        )
        media_files = [
            (str(slow), False),   # times out
            (str(fast), False),   # succeeds
        ]

        loop = MagicMock()
        job = {"id": "media-timeout"}

        with patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coro):
            # Should not raise — the except Exception clause swallows the timeout
            _send_media_via_adapter(adapter, "chat-1", media_files, None, loop, job)

        # 1. The timed-out future was cancelled (the bug fix)
        assert timeout_cancel_calls == [True], "future.cancel() must fire on TimeoutError"
        # 2. Second file still got dispatched — one timeout doesn't abort the batch
        adapter.send_video.assert_called_once()
        assert adapter.send_video.call_args[1]["video_path"] == str(fast.resolve())


# ============================================================================
# Tailor structured iteration event (2026-04-29)
# Plan: docs/superpowers/plans/2026-04-29-tailor-structured-iteration-event.md
# ============================================================================


class TestStripIterationMarkers:
    """Unit tests for _strip_iteration_markers — pure function, no side effects.

    Guards the cron-delivery sanitizer that keeps internal iteration-tracking
    blocks out of user-facing message bodies (Telegram HTML-parse-fallback
    log spam, raw-JSON noise)."""

    def test_no_marker_returned_unchanged(self):
        # Critical no-op guarantee: a normal delivery (incl. trailing
        # whitespace and legit angle brackets like "5 < 10") is untouched.
        text = "All clear — 5 < 10 jobs left.\n\nNothing to do.\n"
        assert _strip_iteration_markers(text) == text

    def test_strips_agent_marker(self):
        text = (
            "Scanned 4 sources.\n\n"
            '<AGENT_ITERATION_JSON>{"agent": "scout", "summary": "ok"}</AGENT_ITERATION_JSON>'
        )
        assert _strip_iteration_markers(text) == "Scanned 4 sources."

    def test_strips_legacy_tailor_marker(self):
        text = (
            "Tailored some.\n\n"
            '<TAILOR_ITERATION_JSON>{"eligible_count": 1}</TAILOR_ITERATION_JSON>'
        )
        assert _strip_iteration_markers(text) == "Tailored some."

    def test_strips_multiline_json_block(self):
        text = (
            "Done.\n\n"
            "<AGENT_ITERATION_JSON>\n"
            "{\n"
            '  "agent": "matcher",\n'
            '  "summary": "scored 12"\n'
            "}\n"
            "</AGENT_ITERATION_JSON>"
        )
        assert _strip_iteration_markers(text) == "Done."

    def test_strips_both_markers_if_present(self):
        text = (
            "Report.\n\n"
            '<AGENT_ITERATION_JSON>{"agent": "a", "summary": "s"}</AGENT_ITERATION_JSON>\n'
            '<TAILOR_ITERATION_JSON>{"eligible_count": 0}</TAILOR_ITERATION_JSON>'
        )
        result = _strip_iteration_markers(text)
        assert "ITERATION_JSON" not in result
        assert result == "Report."

    def test_marker_in_middle_collapses_blank_gap(self):
        text = (
            "Header line.\n\n"
            '<AGENT_ITERATION_JSON>{"agent": "a", "summary": "s"}</AGENT_ITERATION_JSON>\n\n'
            "Footer line."
        )
        # No triple-newline gap should remain where the block was removed.
        result = _strip_iteration_markers(text)
        assert "ITERATION_JSON" not in result
        assert "\n\n\n" not in result
        assert result == "Header line.\n\nFooter line."

    def test_empty_and_none_inputs(self):
        assert _strip_iteration_markers("") == ""
        assert _strip_iteration_markers(None) is None


class TestExtractTailorIteration:
    """Unit tests for _extract_tailor_iteration — pure function, no side effects."""

    def _valid_payload_json(self) -> str:
        return (
            '{"eligible_count": 47, "tailored_count": 0, '
            '"skipped_terminal_count": 47, "skipped_other_count": 0, '
            '"reason": "all_already_terminal"}'
        )

    def test_happy_path_returns_parsed_payload(self):
        from cron.scheduler import _extract_tailor_iteration
        text = (
            "Some preamble.\n\n"
            f"<TAILOR_ITERATION_JSON>\n{self._valid_payload_json()}\n</TAILOR_ITERATION_JSON>\n\n"
            "[SILENT]"
        )
        parsed, err, raw = _extract_tailor_iteration(text)
        assert err is None
        assert parsed is not None
        assert parsed["eligible_count"] == 47
        assert parsed["tailored_count"] == 0
        assert parsed["reason"] == "all_already_terminal"
        assert raw is not None and "all_already_terminal" in raw

    def test_happy_path_block_anywhere_in_response(self):
        """Block can appear before or after free-text — order-insensitive."""
        from cron.scheduler import _extract_tailor_iteration
        text = (
            "Tailored 0 of 47 packets.\n\n"
            "All 47 were already terminal (already-applied).\n\n"
            f"<TAILOR_ITERATION_JSON>{self._valid_payload_json()}</TAILOR_ITERATION_JSON>"
        )
        parsed, err, _ = _extract_tailor_iteration(text)
        assert err is None
        assert parsed["eligible_count"] == 47

    def test_missing_marker_returns_missing_reason(self):
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_MISSING,
        )
        parsed, err, raw = _extract_tailor_iteration("Tailored zero packets. [SILENT]")
        assert parsed is None
        assert err == TAILOR_ITERATION_REASON_MISSING
        assert raw is None

    def test_empty_input_returns_missing(self):
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_MISSING,
        )
        parsed, err, _ = _extract_tailor_iteration("")
        assert err == TAILOR_ITERATION_REASON_MISSING
        parsed, err, _ = _extract_tailor_iteration(None)
        assert err == TAILOR_ITERATION_REASON_MISSING

    def test_malformed_json_returns_parse_failed(self):
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_PARSE_FAILED,
        )
        text = "<TAILOR_ITERATION_JSON>this is not json {[ </TAILOR_ITERATION_JSON>"
        parsed, err, raw = _extract_tailor_iteration(text)
        assert parsed is None
        assert err == TAILOR_ITERATION_REASON_PARSE_FAILED
        # raw_block must be present so the AGENT_ERROR payload can include it.
        assert raw and "this is not json" in raw

    def test_schema_mismatch_missing_field(self):
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        # Missing reason
        text = (
            '<TAILOR_ITERATION_JSON>{"eligible_count": 1, "tailored_count": 0, '
            '"skipped_terminal_count": 1, "skipped_other_count": 0}'
            "</TAILOR_ITERATION_JSON>"
        )
        parsed, err, raw = _extract_tailor_iteration(text)
        assert parsed is None
        assert err == TAILOR_ITERATION_REASON_SCHEMA_MISMATCH
        assert raw is not None  # raw block kept for AGENT_ERROR detail

    def test_schema_mismatch_negative_count(self):
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = (
            '<TAILOR_ITERATION_JSON>{"eligible_count": -1, "tailored_count": 0, '
            '"skipped_terminal_count": 0, "skipped_other_count": 0, '
            '"reason": "no_eligible_packets"}</TAILOR_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_tailor_iteration(text)
        assert err == TAILOR_ITERATION_REASON_SCHEMA_MISMATCH

    def test_schema_mismatch_count_is_string(self):
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = (
            '<TAILOR_ITERATION_JSON>{"eligible_count": "47", "tailored_count": 0, '
            '"skipped_terminal_count": 0, "skipped_other_count": 0, '
            '"reason": "tailored_some"}</TAILOR_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_tailor_iteration(text)
        assert err == TAILOR_ITERATION_REASON_SCHEMA_MISMATCH

    def test_schema_mismatch_count_is_bool(self):
        """bool subclasses int but masquerading as count is unhelpful."""
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = (
            '<TAILOR_ITERATION_JSON>{"eligible_count": true, "tailored_count": 0, '
            '"skipped_terminal_count": 0, "skipped_other_count": 0, '
            '"reason": "other"}</TAILOR_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_tailor_iteration(text)
        assert err == TAILOR_ITERATION_REASON_SCHEMA_MISMATCH

    def test_schema_mismatch_reason_empty(self):
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = (
            '<TAILOR_ITERATION_JSON>{"eligible_count": 0, "tailored_count": 0, '
            '"skipped_terminal_count": 0, "skipped_other_count": 0, '
            '"reason": ""}</TAILOR_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_tailor_iteration(text)
        assert err == TAILOR_ITERATION_REASON_SCHEMA_MISMATCH

    def test_schema_mismatch_non_dict_payload(self):
        """JSON parses but is a list — must be flagged as schema mismatch."""
        from cron.scheduler import (
            _extract_tailor_iteration,
            TAILOR_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = "<TAILOR_ITERATION_JSON>[1, 2, 3]</TAILOR_ITERATION_JSON>"
        parsed, err, _ = _extract_tailor_iteration(text)
        assert err == TAILOR_ITERATION_REASON_SCHEMA_MISMATCH

    def test_unknown_reason_is_passed_through(self):
        """Unknown enum values are not the parser's concern — Critic flags drift."""
        from cron.scheduler import _extract_tailor_iteration
        text = (
            '<TAILOR_ITERATION_JSON>{"eligible_count": 1, "tailored_count": 1, '
            '"skipped_terminal_count": 0, "skipped_other_count": 0, '
            '"reason": "bizarre_new_reason"}</TAILOR_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_tailor_iteration(text)
        assert err is None
        assert parsed["reason"] == "bizarre_new_reason"

    def test_marker_with_surrounding_whitespace(self):
        """Multiline JSON between markers, common LLM output shape."""
        from cron.scheduler import _extract_tailor_iteration
        text = """\
Tailoring run complete.

<TAILOR_ITERATION_JSON>
{
  "eligible_count": 4,
  "tailored_count": 2,
  "skipped_terminal_count": 1,
  "skipped_other_count": 1,
  "reason": "mixed"
}
</TAILOR_ITERATION_JSON>

Tailored 2 of 4 packets. Diego, see applications/.
"""
        parsed, err, _ = _extract_tailor_iteration(text)
        assert err is None
        assert parsed["tailored_count"] == 2


class TestEmitTailorIterationEvent:
    """Behavior tests for _emit_tailor_iteration_event — mocked EventBus.

    Verifies the gating, event-type selection, and payload shape on each
    of the 4 cases from the design doc.
    """

    def _make_emitter_with_bus(self):
        emitter = MagicMock()
        emitter.bus = MagicMock()
        return emitter

    def _tailor_job(self):
        return {"id": "jobflow-tailor-123", "name": "jobflow-tailor"}

    def test_gated_to_jobflow_tailor_only(self):
        """Other crons must not fire any tailor_iteration / AGENT_ERROR emit."""
        from cron.scheduler import _emit_tailor_iteration_event
        emitter = self._make_emitter_with_bus()
        not_tailor = {"id": "matcher-shadow", "name": "matcher-shadow"}
        _emit_tailor_iteration_event(emitter, not_tailor, "no marker, but not gated")
        assert emitter.bus.emit.call_count == 0

    def test_no_emitter_short_circuits(self):
        """None emitter must not raise (cron is in early-startup state)."""
        from cron.scheduler import _emit_tailor_iteration_event
        # Should not raise
        _emit_tailor_iteration_event(None, self._tailor_job(), "")

    def test_happy_path_emits_tailor_iteration_event(self):
        from cron.scheduler import _emit_tailor_iteration_event
        from events.schema import EventType
        emitter = self._make_emitter_with_bus()
        response = (
            'Tailored 2 of 4 packets.\n'
            '<TAILOR_ITERATION_JSON>'
            '{"eligible_count": 4, "tailored_count": 2, '
            '"skipped_terminal_count": 1, "skipped_other_count": 1, '
            '"reason": "mixed"}'
            '</TAILOR_ITERATION_JSON>'
        )
        _emit_tailor_iteration_event(emitter, self._tailor_job(), response)
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.TAILOR_ITERATION
        assert kwargs["source"] == "tailor"
        assert kwargs["correlation_id"] == "jobflow-tailor-123"
        assert kwargs["job_id"] == "jobflow-tailor-123"
        payload = kwargs["payload"]
        assert payload["eligible_count"] == 4
        assert payload["tailored_count"] == 2
        assert payload["reason"] == "mixed"
        # Plus the metadata we add in the wrapper
        assert payload["job_name"] == "jobflow-tailor"
        assert payload["job_id"] == "jobflow-tailor-123"

    def test_missing_marker_emits_agent_error_with_reason(self):
        from cron.scheduler import (
            _emit_tailor_iteration_event,
            TAILOR_ITERATION_REASON_MISSING,
        )
        from events.schema import EventType
        emitter = self._make_emitter_with_bus()
        _emit_tailor_iteration_event(emitter, self._tailor_job(), "Tailored 0 packets. [SILENT]")
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ERROR
        assert kwargs["source"] == "tailor"
        assert kwargs["payload"]["reason"] == TAILOR_ITERATION_REASON_MISSING
        # No raw block kept for the missing case (nothing to keep)
        assert "detail" not in kwargs["payload"]

    def test_malformed_json_emits_agent_error_parse_failed(self):
        from cron.scheduler import (
            _emit_tailor_iteration_event,
            TAILOR_ITERATION_REASON_PARSE_FAILED,
        )
        from events.schema import EventType
        emitter = self._make_emitter_with_bus()
        response = (
            "<TAILOR_ITERATION_JSON>this is not json {[ </TAILOR_ITERATION_JSON>"
        )
        _emit_tailor_iteration_event(emitter, self._tailor_job(), response)
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ERROR
        assert kwargs["payload"]["reason"] == TAILOR_ITERATION_REASON_PARSE_FAILED
        # Malformed block kept (bounded) so operators can see it
        assert "detail" in kwargs["payload"]
        assert "this is not json" in kwargs["payload"]["detail"]

    def test_schema_mismatch_emits_agent_error(self):
        from cron.scheduler import (
            _emit_tailor_iteration_event,
            TAILOR_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        from events.schema import EventType
        emitter = self._make_emitter_with_bus()
        # Missing required field
        response = (
            '<TAILOR_ITERATION_JSON>{"eligible_count": 1}</TAILOR_ITERATION_JSON>'
        )
        _emit_tailor_iteration_event(emitter, self._tailor_job(), response)
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ERROR
        assert kwargs["payload"]["reason"] == TAILOR_ITERATION_REASON_SCHEMA_MISMATCH

    def test_emit_failure_does_not_propagate(self):
        """A bus.emit() exception must degrade to debug log, not crash tick."""
        from cron.scheduler import _emit_tailor_iteration_event
        emitter = MagicMock()
        emitter.bus = MagicMock()
        emitter.bus.emit.side_effect = RuntimeError("simulated DB lock")
        # Must not raise
        _emit_tailor_iteration_event(emitter, self._tailor_job(), "anything")

    def test_detail_block_truncated_at_2000_chars(self):
        """Bounded detail prevents multi-MB payload blowing up audit log."""
        from cron.scheduler import _emit_tailor_iteration_event
        emitter = self._make_emitter_with_bus()
        big = "x" * 5000
        response = f"<TAILOR_ITERATION_JSON>{big}</TAILOR_ITERATION_JSON>"
        _emit_tailor_iteration_event(emitter, self._tailor_job(), response)
        kwargs = emitter.bus.emit.call_args.kwargs
        assert len(kwargs["payload"]["detail"]) == 2000

    def test_correlation_id_falls_back_to_none_when_no_job_id(self):
        """Defensive: a malformed job dict should not crash the emit."""
        from cron.scheduler import _emit_tailor_iteration_event
        emitter = self._make_emitter_with_bus()
        bad_job = {"name": "jobflow-tailor"}  # no id
        response = (
            '<TAILOR_ITERATION_JSON>'
            '{"eligible_count": 0, "tailored_count": 0, '
            '"skipped_terminal_count": 0, "skipped_other_count": 0, '
            '"reason": "no_eligible_packets"}'
            '</TAILOR_ITERATION_JSON>'
        )
        _emit_tailor_iteration_event(emitter, bad_job, response)
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["correlation_id"] is None
        assert kwargs["job_id"] is None


# ============================================================================
# Generic AGENT_ITERATION event (2026-04-30) — extends TAILOR_ITERATION
# pattern to every cron-driven agent.
# ============================================================================


class TestExtractAgentIteration:
    """Unit tests for _extract_agent_iteration — pure, no side effects."""

    def _valid_block(self, agent="scout", summary="Scanned 4 sources, 23 new") -> str:
        return (
            '<AGENT_ITERATION_JSON>'
            f'{{"agent": "{agent}", "summary": "{summary}", '
            '"counters": {"new": 23, "deduped": 11}}'
            '</AGENT_ITERATION_JSON>'
        )

    def test_happy_path_returns_parsed_payload(self):
        from cron.scheduler import _extract_agent_iteration
        text = "Some preamble.\n\n" + self._valid_block() + "\n\nDone."
        parsed, err, raw = _extract_agent_iteration(text)
        assert err is None
        assert parsed is not None
        assert parsed["agent"] == "scout"
        assert "23 new" in parsed["summary"]
        assert parsed["counters"] == {"new": 23, "deduped": 11}
        assert raw and "scout" in raw

    def test_missing_marker_returns_missing(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_MISSING,
        )
        parsed, err, raw = _extract_agent_iteration("Did some work. [SILENT]")
        assert parsed is None
        assert err == AGENT_ITERATION_REASON_MISSING
        assert raw is None

    def test_empty_input_returns_missing(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_MISSING,
        )
        for text in ("", None):
            parsed, err, _ = _extract_agent_iteration(text)
            assert err == AGENT_ITERATION_REASON_MISSING

    def test_malformed_json_returns_parse_failed(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_PARSE_FAILED,
        )
        text = "<AGENT_ITERATION_JSON>this is not json {[ </AGENT_ITERATION_JSON>"
        parsed, err, raw = _extract_agent_iteration(text)
        assert parsed is None
        assert err == AGENT_ITERATION_REASON_PARSE_FAILED
        assert raw and "not json" in raw

    def test_missing_agent_field_returns_schema_mismatch(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = '<AGENT_ITERATION_JSON>{"summary": "ok"}</AGENT_ITERATION_JSON>'
        parsed, err, _ = _extract_agent_iteration(text)
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_missing_summary_returns_schema_mismatch(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = '<AGENT_ITERATION_JSON>{"agent": "scout"}</AGENT_ITERATION_JSON>'
        parsed, err, _ = _extract_agent_iteration(text)
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_empty_string_field_returns_schema_mismatch(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = (
            '<AGENT_ITERATION_JSON>{"agent": "  ", "summary": "ok"}'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_counters_must_be_dict(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = (
            '<AGENT_ITERATION_JSON>{"agent": "scout", "summary": "ok", '
            '"counters": [1,2,3]}</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_counters_values_must_be_numeric_not_bool(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        # bool is subclass of int — must be rejected explicitly
        text = (
            '<AGENT_ITERATION_JSON>{"agent": "scout", "summary": "ok", '
            '"counters": {"flag": true}}</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_phase_seconds_accepts_exact_non_negative_finite_numeric_shape(self):
        from cron.scheduler import _extract_agent_iteration

        text = (
            '<AGENT_ITERATION_JSON>{"agent":"tracker","summary":"ok",'
            '"counters":{"messages":2,"phase_seconds":{'
            '"inbox":1.25,"pipeline_update":0,"analytics":2,'
            '"postgres_bridge":3.5,"api_reconcile":4}}}'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)

        assert err is None
        assert parsed["counters"]["phase_seconds"] == {
            "inbox": 1.25,
            "pipeline_update": 0,
            "analytics": 2,
            "postgres_bridge": 3.5,
            "api_reconcile": 4,
        }

    @pytest.mark.parametrize(
        "phase_seconds",
        [
            {"inbox": 1},
            {
                "inbox": True,
                "pipeline_update": 0,
                "analytics": 0,
                "postgres_bridge": 0,
                "api_reconcile": 0,
            },
            {
                "inbox": -1,
                "pipeline_update": 0,
                "analytics": 0,
                "postgres_bridge": 0,
                "api_reconcile": 0,
            },
            {
                "inbox": float("inf"),
                "pipeline_update": 0,
                "analytics": 0,
                "postgres_bridge": 0,
                "api_reconcile": 0,
            },
            {
                "inbox": 0,
                "pipeline_update": 0,
                "analytics": 0,
                "postgres_bridge": 0,
                "api_reconcile": 0,
                "extra": 1,
            },
        ],
    )
    def test_phase_seconds_rejects_invalid_shapes(self, phase_seconds):
        from cron.scheduler import (
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
            _extract_agent_iteration,
        )

        payload = {
            "agent": "tracker",
            "summary": "ok",
            "counters": {"phase_seconds": phase_seconds},
        }
        text = (
            "<AGENT_ITERATION_JSON>"
            + json.dumps(payload)
            + "</AGENT_ITERATION_JSON>"
        )
        parsed, err, _ = _extract_agent_iteration(text)

        assert parsed is None
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_unknown_nested_counter_remains_invalid(self):
        from cron.scheduler import (
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
            _extract_agent_iteration,
        )

        text = (
            '<AGENT_ITERATION_JSON>{"agent":"scout","summary":"ok",'
            '"counters":{"other_nested":{"value":1}}}</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)

        assert parsed is None
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_anomalies_must_be_list(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = (
            '<AGENT_ITERATION_JSON>{"agent": "scout", "summary": "ok", '
            '"anomalies": "single string"}</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_reason_must_be_string_when_present(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        text = (
            '<AGENT_ITERATION_JSON>{"agent": "scout", "summary": "ok", '
            '"reason": 123}</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_summary_truncated_at_max_chars(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_SUMMARY_MAX_CHARS,
        )
        long_summary = "x" * 500
        text = (
            f'<AGENT_ITERATION_JSON>{{"agent": "scout", "summary": "{long_summary}"}}'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)
        assert err is None
        assert len(parsed["summary"]) == AGENT_ITERATION_SUMMARY_MAX_CHARS
        assert parsed["summary"].endswith("…")

    def test_agent_name_lowercased_and_stripped(self):
        from cron.scheduler import _extract_agent_iteration
        text = (
            '<AGENT_ITERATION_JSON>{"agent": "  Sentinel ", "summary": "ok"}'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)
        assert err is None
        assert parsed["agent"] == "sentinel"

    def test_optional_fields_omitted(self):
        """Minimum-viable payload (agent + summary) must succeed."""
        from cron.scheduler import _extract_agent_iteration
        text = (
            '<AGENT_ITERATION_JSON>{"agent": "scout", "summary": "ok"}'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(text)
        assert err is None
        assert "counters" not in parsed
        assert "anomalies" not in parsed

    def test_brief_multiline_preserved_and_trimmed(self):
        from cron.scheduler import _extract_agent_iteration
        brief = "── Critic · daily skill review ──\nVERDICT: No changes recommended.\n\nACTION NEEDED: none"
        block = (
            '<AGENT_ITERATION_JSON>\n'
            '{"agent": "critic", "summary": "no changes",'
            ' "brief": ' + json.dumps("\n  " + brief + "  \n") + '}\n'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(block)
        assert err is None
        assert parsed["brief"] == brief  # surrounding whitespace trimmed, internal newlines kept
        assert "\n\n" in parsed["brief"]

    def test_brief_non_string_is_schema_mismatch(self):
        from cron.scheduler import _extract_agent_iteration
        block = (
            '<AGENT_ITERATION_JSON>\n'
            '{"agent": "critic", "summary": "x", "brief": 123}\n'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(block)
        assert parsed is None
        assert err == "agent_iteration_schema_mismatch"

    def test_brief_explicit_null_is_schema_mismatch(self):
        from cron.scheduler import (
            _extract_agent_iteration,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        block = (
            '<AGENT_ITERATION_JSON>\n'
            '{"agent": "critic", "summary": "x", "brief": null}\n'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(block)
        assert parsed is None
        assert err == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_brief_whitespace_only_treated_as_absent(self):
        from cron.scheduler import _extract_agent_iteration
        block = (
            '<AGENT_ITERATION_JSON>\n'
            '{"agent": "critic", "summary": "x", "brief": "   \\n  "}\n'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(block)
        assert err is None
        assert "brief" not in parsed

    def test_brief_oversized_truncated_with_ellipsis(self):
        from cron.scheduler import _extract_agent_iteration
        long_brief = "V" * 2000
        block = (
            '<AGENT_ITERATION_JSON>\n'
            '{"agent": "critic", "summary": "x", "brief": ' + json.dumps(long_brief) + '}\n'
            '</AGENT_ITERATION_JSON>'
        )
        parsed, err, _ = _extract_agent_iteration(block)
        assert err is None
        assert len(parsed["brief"]) == 1500
        assert parsed["brief"].endswith("…")


class TestEmitAgentIterationEvent:
    """Behavior tests for _emit_agent_iteration_event."""

    def _emitter_with_bus(self):
        emitter = MagicMock()
        emitter.bus = MagicMock()
        return emitter

    def _scout_job(self):
        return {"id": "scout-456", "name": "jobflow-scout"}

    def test_jobflow_tailor_short_circuits_to_avoid_double_emit(self):
        """jobflow-tailor has its own dedicated TAILOR_ITERATION event;
        the generic helper must not also fire on it."""
        from cron.scheduler import _emit_agent_iteration_event
        emitter = self._emitter_with_bus()
        tailor_job = {"id": "x", "name": "jobflow-tailor"}
        valid = (
            '<AGENT_ITERATION_JSON>{"agent": "tailor", "summary": "ok"}'
            '</AGENT_ITERATION_JSON>'
        )
        _emit_agent_iteration_event(emitter, tailor_job, valid)
        assert emitter.bus.emit.call_count == 0

    def test_no_emitter_short_circuits(self):
        from cron.scheduler import _emit_agent_iteration_event
        # Should not raise
        _emit_agent_iteration_event(None, self._scout_job(), "")

    def test_unknown_job_missing_marker_is_silent(self):
        """Non-canonical / ad-hoc jobs that omit the marker emit nothing —
        we only synthesize for known canonical agents (see fallback below).
        This preserves the original opt-in semantics for legacy/ad-hoc crons
        that never opted into AGENT_ITERATION."""
        from cron.scheduler import _emit_agent_iteration_event
        emitter = self._emitter_with_bus()
        adhoc_job = {"id": "adhoc-1", "name": "ad-hoc-cron-foo"}
        _emit_agent_iteration_event(emitter, adhoc_job, "Done.")
        assert emitter.bus.emit.call_count == 0

    def test_happy_path_emits_agent_iteration(self):
        from cron.scheduler import _emit_agent_iteration_event
        from events.schema import EventType
        emitter = self._emitter_with_bus()
        response = (
            '<AGENT_ITERATION_JSON>'
            '{"agent": "scout", "summary": "Scanned 4 sources, 23 new", '
            '"counters": {"new": 23, "deduped": 11}}'
            '</AGENT_ITERATION_JSON>'
        )
        _emit_agent_iteration_event(emitter, self._scout_job(), response)
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ITERATION
        assert kwargs["source"] == "scout"
        assert kwargs["correlation_id"] == "scout-456"
        payload = kwargs["payload"]
        assert payload["agent"] == "scout"
        assert "23 new" in payload["summary"]
        assert payload["counters"]["new"] == 23
        assert payload["job_name"] == "jobflow-scout"
        assert payload["job_id"] == "scout-456"

    def test_emitted_payload_carries_brief(self):
        import json
        from cron.scheduler import _emit_agent_iteration_event
        from events.schema import EventType
        emitter = self._emitter_with_bus()
        brief = (
            "── Critic · daily skill review ──\n"
            "VERDICT: No changes recommended.\n"
            "ACTION NEEDED: none"
        )
        response = (
            '<AGENT_ITERATION_JSON>'
            '{"agent": "scout", "summary": "no changes", "brief": '
            + json.dumps(brief) +
            ', "reason": "no_work"}'
            '</AGENT_ITERATION_JSON>'
        )
        _emit_agent_iteration_event(emitter, self._scout_job(), response)
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ITERATION
        payload = kwargs["payload"]
        assert payload["brief"] == brief
        assert "\n" in payload["brief"]

    def test_tracker_cycle_requires_phase_seconds(self):
        from cron.scheduler import (
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
            _emit_agent_iteration_event,
        )
        from events.schema import EventType

        emitter = self._emitter_with_bus()
        job = {"id": "tracker-1", "name": "jobflow-tracker-cycle"}
        response = (
            '<AGENT_ITERATION_JSON>{"agent":"tracker","summary":"ok",'
            '"counters":{"messages_processed":2}}</AGENT_ITERATION_JSON>'
        )

        _emit_agent_iteration_event(emitter, job, response)

        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ERROR
        assert kwargs["payload"]["reason"] == AGENT_ITERATION_REASON_SCHEMA_MISMATCH
        assert kwargs["payload"]["job_name"] == "jobflow-tracker-cycle"

    def test_tracker_cycle_emits_complete_phase_seconds(self):
        from cron.scheduler import _emit_agent_iteration_event
        from events.schema import EventType

        emitter = self._emitter_with_bus()
        job = {"id": "tracker-2", "name": "jobflow-tracker-cycle"}
        response = (
            '<AGENT_ITERATION_JSON>{"agent":"tracker","summary":"ok",'
            '"counters":{"phase_seconds":{"inbox":1.0,'
            '"pipeline_update":2.0,"analytics":0,"postgres_bridge":3.0,'
            '"api_reconcile":4.0}}}</AGENT_ITERATION_JSON>'
        )

        _emit_agent_iteration_event(emitter, job, response)

        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ITERATION
        assert kwargs["payload"]["counters"]["phase_seconds"]["analytics"] == 0

    def test_malformed_marker_emits_agent_error(self):
        from cron.scheduler import (
            _emit_agent_iteration_event,
            AGENT_ITERATION_REASON_PARSE_FAILED,
        )
        from events.schema import EventType
        emitter = self._emitter_with_bus()
        response = (
            "<AGENT_ITERATION_JSON>this is not json [{ </AGENT_ITERATION_JSON>"
        )
        _emit_agent_iteration_event(emitter, self._scout_job(), response)
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ERROR
        assert kwargs["payload"]["reason"] == AGENT_ITERATION_REASON_PARSE_FAILED
        assert kwargs["payload"]["job_name"] == "jobflow-scout"
        assert "not json" in kwargs["payload"]["detail"]

    def test_schema_mismatch_emits_agent_error(self):
        from cron.scheduler import (
            _emit_agent_iteration_event,
            AGENT_ITERATION_REASON_SCHEMA_MISMATCH,
        )
        from events.schema import EventType
        emitter = self._emitter_with_bus()
        # Missing both required fields
        response = '<AGENT_ITERATION_JSON>{"foo": "bar"}</AGENT_ITERATION_JSON>'
        _emit_agent_iteration_event(emitter, self._scout_job(), response)
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ERROR
        assert kwargs["payload"]["reason"] == AGENT_ITERATION_REASON_SCHEMA_MISMATCH

    def test_emit_failure_does_not_propagate(self):
        from cron.scheduler import _emit_agent_iteration_event
        emitter = MagicMock()
        emitter.bus = MagicMock()
        emitter.bus.emit.side_effect = RuntimeError("simulated DB lock")
        # Must not raise
        _emit_agent_iteration_event(emitter, self._scout_job(), "anything")

    # ------------------------------------------------------------------
    # Canonical agent-name override (2026-04-30) — payload.agent is keyed
    # off job_name via canonical_agent_source, not LLM choice.  See
    # docs/superpowers/specs/2026-04-30-agent-iteration-canonical-name.md
    # ------------------------------------------------------------------

    def test_devflow_bridge_overrides_llm_supplied_agent(self):
        """devflow-bridge job names emit ~5 different LLM-chosen agent
        names (devflow, hermes_to_devflow, bridge, watchdog, …).  The
        canonical mapping forces them all to 'devflow' so Telegram routing
        is deterministic."""
        from cron.scheduler import _emit_agent_iteration_event
        from events.schema import EventType
        emitter = self._emitter_with_bus()
        bridge_job = {"id": "bridge-1", "name": "devflow-bridge"}
        response = (
            '<AGENT_ITERATION_JSON>'
            '{"agent": "watchdog", "summary": "saw a successful run"}'
            '</AGENT_ITERATION_JSON>'
        )
        _emit_agent_iteration_event(emitter, bridge_job, response)
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ITERATION
        payload = kwargs["payload"]
        assert payload["agent"] == "devflow"
        assert payload["agent_llm_supplied"] == "watchdog"
        assert kwargs["source"] == "devflow"

    def test_jobflow_devflow_overrides_llm_supplied_agent(self):
        """jobflow-devflow's prompt says 'Act as the DevFlow agent for
        JobFlow on Hermes' — the LLM may pick devflow|jobflow|jaum.  The
        canonical mapping forces all three to 'devflow' so the Friday
        standup lands in devflow_firehose every time."""
        from cron.scheduler import _emit_agent_iteration_event
        emitter = self._emitter_with_bus()
        standup_job = {"id": "standup-1", "name": "jobflow-devflow"}
        response = (
            '<AGENT_ITERATION_JSON>'
            '{"agent": "jobflow", "summary": "Weekday standup digest"}'
            '</AGENT_ITERATION_JSON>'
        )
        _emit_agent_iteration_event(emitter, standup_job, response)
        kwargs = emitter.bus.emit.call_args.kwargs
        payload = kwargs["payload"]
        assert payload["agent"] == "devflow"
        assert payload["agent_llm_supplied"] == "jobflow"
        assert kwargs["source"] == "devflow"

    def test_unknown_job_keeps_llm_supplied_agent(self):
        """If job_name has no canonical mapping (ad-hoc cron, mistyped
        name), don't break routing by overriding to a non-canonical
        string.  Fall back to LLM-supplied so existing/legacy jobs keep
        working."""
        from cron.scheduler import _emit_agent_iteration_event
        emitter = self._emitter_with_bus()
        adhoc_job = {"id": "adhoc-1", "name": "ad-hoc-cron-foo"}
        response = (
            '<AGENT_ITERATION_JSON>'
            '{"agent": "watchdog", "summary": "did a thing"}'
            '</AGENT_ITERATION_JSON>'
        )
        _emit_agent_iteration_event(emitter, adhoc_job, response)
        kwargs = emitter.bus.emit.call_args.kwargs
        payload = kwargs["payload"]
        assert payload["agent"] == "watchdog"
        assert "agent_llm_supplied" not in payload
        assert kwargs["source"] == "watchdog"

    def test_canonical_override_is_idempotent_when_llm_already_correct(self):
        """When the LLM happens to pick the canonical name already, the
        override is a no-op semantically.  agent_llm_supplied still
        records what the LLM said (for audit consistency)."""
        from cron.scheduler import _emit_agent_iteration_event
        emitter = self._emitter_with_bus()
        bridge_job = {"id": "bridge-2", "name": "devflow-bridge"}
        response = (
            '<AGENT_ITERATION_JSON>'
            '{"agent": "devflow", "summary": "all good"}'
            '</AGENT_ITERATION_JSON>'
        )
        _emit_agent_iteration_event(emitter, bridge_job, response)
        kwargs = emitter.bus.emit.call_args.kwargs
        payload = kwargs["payload"]
        assert payload["agent"] == "devflow"
        assert payload["agent_llm_supplied"] == "devflow"

    # ------------------------------------------------------------------
    # Deterministic marker-missing fallback (2026-04-30) — when a known
    # canonical agent's job omits the AGENT_ITERATION_JSON marker, we
    # synthesize a placeholder event so 100% of canonical-agent runs
    # produce an AGENT_ITERATION trail.  Non-canonical jobs still
    # silently no-op so we don't spam ad-hoc crons.  See
    # docs/superpowers/specs/2026-04-30-agent-iteration-marker-fallback.md
    # ------------------------------------------------------------------

    def test_devflow_bridge_missing_marker_synthesizes_event(self):
        """devflow-bridge intermittently (~46% of runs) omits the
        AGENT_ITERATION_JSON marker entirely.  The fallback synthesizes
        a stand-in event so devflow_firehose still gets a heartbeat."""
        from cron.scheduler import _emit_agent_iteration_event
        from events.schema import EventType
        emitter = self._emitter_with_bus()
        bridge_job = {"id": "bridge-77", "name": "devflow-bridge"}
        _emit_agent_iteration_event(emitter, bridge_job, "Done with no marker.")
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ITERATION
        assert kwargs["source"] == "devflow"
        assert kwargs["correlation_id"] == "bridge-77"
        payload = kwargs["payload"]
        assert payload["agent"] == "devflow"
        assert payload["synthesized"] is True
        assert "synthesized" in payload["summary"]
        assert "AGENT_ITERATION_JSON" in payload["summary"]
        assert payload["summary"].startswith("devflow")
        assert payload["job_name"] == "devflow-bridge"
        assert payload["job_id"] == "bridge-77"
        # No LLM was consulted, so no agent_llm_supplied field.
        assert "agent_llm_supplied" not in payload

    def test_jobflow_applier_missing_marker_synthesizes_event(self):
        """jobflow-applier maps to canonical 'applier' — fallback fires
        for any canonical agent, not just devflow."""
        from cron.scheduler import _emit_agent_iteration_event
        from events.schema import EventType
        emitter = self._emitter_with_bus()
        applier_job = {"id": "applier-9", "name": "jobflow-applier"}
        _emit_agent_iteration_event(emitter, applier_job, "")
        assert emitter.bus.emit.call_count == 1
        kwargs = emitter.bus.emit.call_args.kwargs
        assert kwargs["event_type"] == EventType.AGENT_ITERATION
        assert kwargs["source"] == "applier"
        payload = kwargs["payload"]
        assert payload["agent"] == "applier"
        assert payload["synthesized"] is True
        assert payload["summary"].startswith("applier")
        assert payload["job_name"] == "jobflow-applier"
        assert payload["job_id"] == "applier-9"

    def test_jobflow_tailor_missing_marker_stays_silent(self):
        """jobflow-tailor short-circuits before extraction (its dedicated
        TAILOR_ITERATION emit hook handles its lifecycle).  The fallback
        must NOT synthesize a generic AGENT_ITERATION for tailor — that
        would double-emit alongside the tailor-specific event."""
        from cron.scheduler import _emit_agent_iteration_event
        emitter = self._emitter_with_bus()
        tailor_job = {"id": "tailor-1", "name": "jobflow-tailor"}
        _emit_agent_iteration_event(emitter, tailor_job, "Done with no marker.")
        assert emitter.bus.emit.call_count == 0


# Cron same-job concurrency guard -- added 2026-04-30. Closes the
# 2026-04-30 sentinel-vip-morning triple-fire (canonical case
# event_id 4edcb4b1-aa07-4dbb-b799-8af167d4f92e). The third fire
# at 14:49 hung in Anthropic and was killed only when the gateway
# restarted at 14:56. Two concurrent sentinel fires would also
# collide on the browser-harness per-process lock.
@pytest.mark.usefixtures("_tick_lock_isolated")
class TestDuplicateFireGuard:
    @pytest.fixture(autouse=True)
    def _reset_in_flight(self):
        """Clear _in_flight before AND after each test to keep tests independent."""
        from cron import scheduler as sch
        sch._in_flight.clear()
        yield
        sch._in_flight.clear()

    def _job(self, job_id="092f4ed7657c", name="sentinel-vip-morning"):
        return {"id": job_id, "name": name, "deliver": "local"}

    def test_concurrent_duplicate_fire_emits_skip_and_blocks_second_run_job(self):
        """Canonical 2026-04-30 sentinel triple-fire scenario (cross-tick race).

        The production duplicate is the trigger_job()-vs-tick race: a fire from
        an earlier tick is still in flight -- claimed in BOTH the submit-time
        running set (_running_job_ids, upstream's 0.16.0 non-blocking-dispatch
        dedup) AND Guard #3's _in_flight registry (with its cron_started
        event_id) -- when a second fire for the same job_id is dispatched on a
        later tick. That second fire must be blocked before it reaches run_job
        (which is what collided on the Chrome browser-harness lock) and must
        emit exactly one CRON_SKIPPED_DUPLICATE correlated to the live fire.

        Modelled deterministically (no threads/barriers): the winner "ran" on
        the prior tick, so we seed it as already-in-flight and dispatch only the
        duplicate. Regression guard: the running-set guard lands BEFORE
        _process_job, so before the fix it rejected the duplicate silently and
        Guard #3's emit seam was dead (the second fire's skip event was lost).
        """
        import time
        from cron import scheduler as sch
        from events.schema import EventType

        # Winner from an earlier tick, still running: claimed in the submit-time
        # running set AND Guard #3's registry, with its cron_started event_id.
        sch._running_job_ids.add("092f4ed7657c")
        sch._in_flight["092f4ed7657c"] = sch._InFlightRecord(
            start_monotonic=time.monotonic(),
            job_name="sentinel-vip-morning",
            cron_started_event_id="4edcb4b1-aa07-4dbb-b799-8af167d4f92e",
        )

        emitter = MagicMock()
        # If the duplicate wrongly started its own fire, on_job_started would be
        # called -- assert below that it is NOT.
        emitter.on_job_started.return_value = "should-not-be-emitted"

        skip_calls = []

        def capture_skip(**kwargs):
            skip_calls.append(kwargs)
            return "skip-evt-id"
        emitter.on_job_skipped_duplicate.side_effect = capture_skip

        run_job_calls = []

        def blocking_run_job(job):
            run_job_calls.append(job)
            return (True, "# output", "response", None)

        job = self._job()

        try:
            with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([dict(job)], [])), \
                 patch("cron.scheduler.advance_next_runs"), \
                 patch("cron.scheduler._get_event_emitter", return_value=emitter), \
                 patch("cron.scheduler.run_job", side_effect=blocking_run_job), \
                 patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
                 patch("cron.scheduler._deliver_result", return_value=None), \
                 patch("cron.scheduler.mark_job_run"), \
                 patch("cron.jobs.load_jobs", return_value=[
                     {"id": "092f4ed7657c", "consecutive_errors": 0}
                 ]):
                from cron.scheduler import tick
                tick(verbose=False)
        finally:
            # The autouse fixture clears _in_flight; the running set has no such
            # fixture, so release our seeded claim to keep tests independent.
            sch._running_job_ids.discard("092f4ed7657c")

        # The duplicate fire was blocked before run_job (the winner ran on the
        # prior tick we seeded) -- this is what protected the browser-harness.
        assert run_job_calls == [], (
            f"duplicate must not reach run_job; got {run_job_calls!r}"
        )
        # The duplicate must NOT emit its own cron_started.
        assert emitter.on_job_started.call_count == 0, (
            f"on_job_started called {emitter.on_job_started.call_count}x; "
            "duplicate fire emitted cron_started anyway"
        )
        # Exactly one CRON_SKIPPED_DUPLICATE.
        assert len(skip_calls) == 1, f"skip_calls={skip_calls!r}"

        skip = skip_calls[0]
        assert skip["job_id"] == "092f4ed7657c"
        assert skip["job_name"] == "sentinel-vip-morning"
        assert skip["reason"] == "concurrent_fire_blocked"
        # The skip event references the live in-flight cron_started.
        assert (
            skip["prior_cron_started_event_id"]
            == "4edcb4b1-aa07-4dbb-b799-8af167d4f92e"
        )
        assert skip["prior_elapsed_seconds"] >= 0
        # Sanity: the EventType identifier is also stable.
        assert EventType.CRON_SKIPPED_DUPLICATE.type_string == "cron_skipped_duplicate"

    def test_in_flight_cleared_after_successful_run(self):
        """After a job completes, the same job_id must be allowed to fire again."""
        from cron import scheduler as sch

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-1"

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._job()], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job",
                   return_value=(True, "# output", "response", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert "092f4ed7657c" not in sch._in_flight, (
            "_in_flight must be cleared after a successful run; "
            f"still holds {sch._in_flight!r}"
        )

    def test_in_flight_cleared_after_run_job_exception(self):
        """An exception inside run_job must still release the in-flight slot."""
        from cron import scheduler as sch

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-1"

        def boom(job):
            raise RuntimeError("simulated agent crash")

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._job()], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job", side_effect=boom), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert "092f4ed7657c" not in sch._in_flight, (
            "_in_flight must be cleared even when run_job raises"
        )

    def test_different_job_ids_do_not_collide(self):
        """The guard is keyed by job_id; unrelated jobs run in parallel."""
        import threading

        emitter = MagicMock()
        emitter.on_job_started.side_effect = ["evt-a", "evt-b"]

        skip_calls = []
        emitter.on_job_skipped_duplicate.side_effect = (
            lambda **kw: skip_calls.append(kw)
        )

        run_count = 0
        run_lock = threading.Lock()

        def mock_run(job):
            nonlocal run_count
            with run_lock:
                run_count += 1
            return (True, "# output", "response", None)

        jobs = [
            {"id": "job-a", "name": "a", "deliver": "local"},
            {"id": "job-b", "name": "b", "deliver": "local"},
        ]

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=(jobs, [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job", side_effect=mock_run), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "job-a", "consecutive_errors": 0},
                 {"id": "job-b", "consecutive_errors": 0},
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert run_count == 2
        assert emitter.on_job_started.call_count == 2
        assert skip_calls == [], (
            "Distinct job_ids must not be flagged as duplicates; "
            f"got skip_calls={skip_calls!r}"
        )

    def test_prior_fire_exceeded_timeout_reason(self, monkeypatch):
        """When the prior fire has been registered for longer than the
        configured hard-timeout, the reason switches to
        'prior_fire_exceeded_timeout' and the new fire is still rejected."""
        import time
        from cron import scheduler as sch

        # Force the guard's effective timeout down to 1 second so we can
        # seed an "old" in-flight record without sleeping past the
        # production default.
        monkeypatch.setenv("HERMES_CRON_HARD_TIMEOUT", "1")

        # Seed an in-flight record that pre-dates the timeout window.
        sch._in_flight["092f4ed7657c"] = sch._InFlightRecord(
            start_monotonic=time.monotonic() - 9999.0,
            job_name="sentinel-vip-morning",
            cron_started_event_id="prior-evt-id",
        )

        emitter = MagicMock()
        skip_calls = []
        emitter.on_job_skipped_duplicate.side_effect = (
            lambda **kw: skip_calls.append(kw)
        )

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([self._job()], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job") as mock_run, \
             patch("cron.scheduler.save_job_output"), \
             patch("cron.scheduler._deliver_result"), \
             patch("cron.scheduler.mark_job_run"):
            from cron.scheduler import tick
            tick(verbose=False)

        # run_job NEVER invoked (declined to start on top of wedged prior).
        mock_run.assert_not_called()
        # cron_started NOT emitted for this fire.
        assert emitter.on_job_started.call_count == 0

        assert len(skip_calls) == 1
        skip = skip_calls[0]
        assert skip["reason"] == "prior_fire_exceeded_timeout"
        assert skip["prior_cron_started_event_id"] == "prior-evt-id"
        assert skip["prior_elapsed_seconds"] >= 9999.0


class TestInFlightRegistryShape:
    """Document the _in_flight registry contract for Guard #1 (cron_aborted
    on shutdown), which builds on the same registry."""

    def test_registry_is_module_level_dict(self):
        """_in_flight is a module-level dict keyed by job_id."""
        from cron import scheduler as sch
        assert isinstance(sch._in_flight, dict)

    def test_record_has_documented_fields(self):
        from cron.scheduler import _InFlightRecord
        rec = _InFlightRecord(
            start_monotonic=42.0,
            job_name="any",
            cron_started_event_id=None,
        )
        assert rec.start_monotonic == 42.0
        assert rec.job_name == "any"
        assert rec.cron_started_event_id is None

    def test_lock_is_module_level(self):
        """_in_flight_lock serializes registry mutations across threads."""
        import threading
        from cron import scheduler as sch
        # threading.Lock is a factory; the underlying type is exposed via
        # type(threading.Lock()) — this checks we have a real lock object.
        assert isinstance(sch._in_flight_lock, type(threading.Lock()))


# Min-seconds-between-fires guard (Guard #4, 2026-04-30 follow-up) ---------
# Closes the SEQUENTIAL-burst gap left by Guard #3.  The 2026-04-30 sentinel
# triple-fire (14:02 / 14:34 / 14:49 UTC) had each prior fire fully
# completing before the next arrived -- so the in-flight registry was empty
# at each new fire's arrival and Guard #3 never engaged.  See
# sentinel-vip-burst-rc-2026-04-30.md §6 for the full design.
@pytest.mark.usefixtures("_tick_lock_isolated")
class TestMinIntervalGuard:
    @pytest.fixture(autouse=True)
    def _reset_in_flight_and_env(self, monkeypatch):
        """Clear _in_flight and the env-var override before/after each test."""
        from cron import scheduler as sch
        sch._in_flight.clear()
        monkeypatch.delenv("HERMES_CRON_MIN_SECONDS_BETWEEN_FIRES", raising=False)
        yield
        sch._in_flight.clear()

    def _job(
        self,
        job_id="092f4ed7657c",
        name="sentinel-vip-morning",
        min_seconds_between_fires=None,
        last_run_at=None,
    ):
        from hermes_time import now as _now
        # Default last_run_at = recent (5 min ago), default min=1800 (30 min)
        if last_run_at is None:
            last_run_at = (_now()).isoformat()
        job = {"id": job_id, "name": name, "deliver": "local"}
        if min_seconds_between_fires is not None:
            job["min_seconds_between_fires"] = min_seconds_between_fires
        if last_run_at is not None:
            job["last_run_at"] = last_run_at
        return job

    def test_fire_blocked_when_within_min_interval(self):
        """last_run_at = now - 5 min, min = 30 min => fire is blocked,
        run_job NOT called, cron_skipped_min_interval is emitted."""
        from datetime import timedelta
        from events.schema import EventType
        from hermes_time import now as _now

        five_min_ago = (_now() - timedelta(minutes=5)).isoformat()
        job = self._job(
            min_seconds_between_fires=1800,
            last_run_at=five_min_ago,
        )

        emitter = MagicMock()
        emitter.on_job_started.return_value = "should-not-be-emitted"
        skip_calls = []

        def capture_skip(**kwargs):
            skip_calls.append(kwargs)
            return "skip-evt-id"
        emitter.on_job_skipped_min_interval.side_effect = capture_skip

        run_job_called = False

        def fail_run_job(j):
            nonlocal run_job_called
            run_job_called = True
            return (True, "# output", "response", None)

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job", side_effect=fail_run_job), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        # Guard #4 must reject before run_job is invoked.
        assert run_job_called is False, "run_job should NOT be called"
        # cron_started must NOT have been emitted -- the guard fires earlier.
        assert emitter.on_job_started.call_count == 0, (
            "on_job_started should NOT have been emitted; Guard #4 rejects "
            "before the cron_started emit point"
        )
        # Exactly one cron_skipped_min_interval emitted.
        assert len(skip_calls) == 1, f"skip_calls={skip_calls!r}"
        skip = skip_calls[0]
        assert skip["job_id"] == "092f4ed7657c"
        assert skip["job_name"] == "sentinel-vip-morning"
        assert skip["last_run_at"] == five_min_ago
        assert skip["min_seconds_between_fires"] == 1800
        # ~300s (5 min) elapsed; allow some tolerance for test runtime.
        assert 290 <= skip["elapsed_since_last_seconds"] <= 320, (
            f"elapsed_since_last_seconds out of expected range: "
            f"{skip['elapsed_since_last_seconds']}"
        )
        # Sanity: the EventType identifier is stable.
        assert (
            EventType.CRON_SKIPPED_MIN_INTERVAL.type_string
            == "cron_skipped_min_interval"
        )

    def test_fire_proceeds_when_past_min_interval(self):
        """last_run_at = now - 31 min, min = 30 min => fire proceeds normally.

        Boundary: even one minute past the threshold lets the fire through.
        """
        from datetime import timedelta
        from hermes_time import now as _now

        thirty_one_min_ago = (_now() - timedelta(minutes=31)).isoformat()
        job = self._job(
            min_seconds_between_fires=1800,
            last_run_at=thirty_one_min_ago,
        )

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-1"

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job",
                   return_value=(True, "# output", "response", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        # cron_started SHOULD have been emitted -- guard didn't engage.
        assert emitter.on_job_started.call_count == 1
        # No skip event emitted.
        assert emitter.on_job_skipped_min_interval.call_count == 0

    def test_guard_off_by_default(self):
        """No min_seconds_between_fires field, no env var => fire proceeds
        even with last_run_at very recent.  Backward-compat default."""
        from datetime import timedelta
        from hermes_time import now as _now

        ten_seconds_ago = (_now() - timedelta(seconds=10)).isoformat()
        job = self._job(
            min_seconds_between_fires=None,  # explicitly off
            last_run_at=ten_seconds_ago,
        )
        # Field is omitted from the dict so it's truly absent
        job.pop("min_seconds_between_fires", None)

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-1"

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job",
                   return_value=(True, "# output", "response", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert emitter.on_job_started.call_count == 1
        assert emitter.on_job_skipped_min_interval.call_count == 0

    def test_env_var_default_applies_when_per_job_unset(self, monkeypatch):
        """When per-job field is unset but HERMES_CRON_MIN_SECONDS_BETWEEN_FIRES
        is set, the env-var value applies."""
        from datetime import timedelta
        from hermes_time import now as _now

        monkeypatch.setenv("HERMES_CRON_MIN_SECONDS_BETWEEN_FIRES", "1800")

        five_min_ago = (_now() - timedelta(minutes=5)).isoformat()
        job = self._job(
            min_seconds_between_fires=None,
            last_run_at=five_min_ago,
        )
        job.pop("min_seconds_between_fires", None)

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-should-not-fire"
        skip_calls = []
        emitter.on_job_skipped_min_interval.side_effect = (
            lambda **kw: (skip_calls.append(kw), "skip-evt")[1]
        )

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job",
                   return_value=(True, "# output", "response", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert len(skip_calls) == 1
        assert skip_calls[0]["min_seconds_between_fires"] == 1800

    def test_per_job_zero_overrides_env_var(self, monkeypatch):
        """Per-job ``min_seconds_between_fires=0`` opts OUT of the guard
        even when the env-var default is non-zero.  Per-job value wins."""
        from datetime import timedelta
        from hermes_time import now as _now

        monkeypatch.setenv("HERMES_CRON_MIN_SECONDS_BETWEEN_FIRES", "1800")

        thirty_seconds_ago = (_now() - timedelta(seconds=30)).isoformat()
        job = self._job(
            min_seconds_between_fires=0,
            last_run_at=thirty_seconds_ago,
        )

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-1"

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job",
                   return_value=(True, "# output", "response", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert emitter.on_job_started.call_count == 1
        assert emitter.on_job_skipped_min_interval.call_count == 0

    def test_in_flight_slot_released_on_reject(self):
        """After Guard #4 rejects, _in_flight must be empty so the next
        legitimate fire is not blocked by the rejected one's still-held slot."""
        from datetime import timedelta
        from cron import scheduler as sch
        from hermes_time import now as _now

        five_min_ago = (_now() - timedelta(minutes=5)).isoformat()
        job = self._job(
            min_seconds_between_fires=1800,
            last_run_at=five_min_ago,
        )

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-not-emitted"

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job",
                   return_value=(True, "# output", "response", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert "092f4ed7657c" not in sch._in_flight, (
            "_in_flight must be cleared after Guard #4 rejects; "
            f"still holds {sch._in_flight!r}"
        )

    def test_malformed_last_run_at_does_not_block(self):
        """A garbage last_run_at string must not wedge the scheduler.
        Defensive: production data should never land here, but a parse
        bug must let the job proceed."""
        job = self._job(
            min_seconds_between_fires=1800,
            last_run_at="not-an-iso-timestamp",
        )

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-1"

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job",
                   return_value=(True, "# output", "response", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        # Fire proceeds; no skip event.
        assert emitter.on_job_started.call_count == 1
        assert emitter.on_job_skipped_min_interval.call_count == 0

    def test_no_last_run_at_does_not_block(self):
        """A first-ever fire (last_run_at absent) must not be blocked by
        Guard #4.  This is the new-job bootstrap case."""
        job = self._job(
            min_seconds_between_fires=1800,
            last_run_at=None,
        )
        # Explicitly absent
        job.pop("last_run_at", None)

        emitter = MagicMock()
        emitter.on_job_started.return_value = "evt-1"

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler._get_event_emitter", return_value=emitter), \
             patch("cron.scheduler.run_job",
                   return_value=(True, "# output", "response", None)), \
             patch("cron.scheduler.save_job_output", return_value="/tmp/out.md"), \
             patch("cron.scheduler._deliver_result", return_value=None), \
             patch("cron.scheduler.mark_job_run"), \
             patch("cron.jobs.load_jobs", return_value=[
                 {"id": "092f4ed7657c", "consecutive_errors": 0}
             ]):
            from cron.scheduler import tick
            tick(verbose=False)

        assert emitter.on_job_started.call_count == 1
        assert emitter.on_job_skipped_min_interval.call_count == 0

    def test_helper_resolves_per_job_then_env_then_default(self, monkeypatch):
        """_job_min_seconds_between_fires resolution priority."""
        from cron.scheduler import _job_min_seconds_between_fires

        # 1. Per-job field wins
        monkeypatch.setenv("HERMES_CRON_MIN_SECONDS_BETWEEN_FIRES", "9999")
        assert _job_min_seconds_between_fires(
            {"min_seconds_between_fires": 30}
        ) == 30
        # Per-job 0 wins (opt-out)
        assert _job_min_seconds_between_fires(
            {"min_seconds_between_fires": 0}
        ) == 0

        # 2. Env var wins when per-job unset
        assert _job_min_seconds_between_fires({}) == 9999

        # 3. Default 0 when both unset
        monkeypatch.delenv("HERMES_CRON_MIN_SECONDS_BETWEEN_FIRES")
        assert _job_min_seconds_between_fires({}) == 0

        # 4. Garbage in env var falls back to default 0
        monkeypatch.setenv("HERMES_CRON_MIN_SECONDS_BETWEEN_FIRES", "not-an-int")
        assert _job_min_seconds_between_fires({}) == 0

        # 5. Garbage in per-job field falls back to env var
        monkeypatch.setenv("HERMES_CRON_MIN_SECONDS_BETWEEN_FIRES", "1800")
        assert _job_min_seconds_between_fires(
            {"min_seconds_between_fires": "not-an-int"}
        ) == 1800

        # 6. Negative per-job value clamped to 0
        assert _job_min_seconds_between_fires(
            {"min_seconds_between_fires": -100}
        ) == 0


class TestPerJobSoftDeadline:
    """Per-job soft deadline (2026-06-10 audit M1 T1.4).

    A hung LLM job used to block its worker forever — and in the
    sequential bucket, every later job in the tick. The deadline wrapper
    bounds the WAIT (threads can't be killed): parallel-safe jobs are
    marked failed + slot-released + abandoned; sequential jobs alert and
    keep waiting (abandoning them would race os.environ restore).
    """

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        from cron import scheduler as sched
        yield
        with sched._in_flight_lock:
            sched._in_flight.clear()

    def _stub_emitter(self, monkeypatch):
        from cron import scheduler as sched
        calls = []

        class _Emitter:
            def on_job_completed(self, **kw):
                calls.append(kw)

        monkeypatch.setattr(sched, "_get_event_emitter", lambda: _Emitter())
        return calls

    def test_fast_job_returns_result_unchanged(self, monkeypatch):
        import contextvars
        from cron import scheduler as sched
        calls = self._stub_emitter(monkeypatch)

        def fn(job, _abandoned=None):
            return True

        job = {"id": "fast-job", "name": "fast", "timeout_seconds": 5}
        assert sched._run_callable_with_deadline(
            job, fn, True, contextvars.copy_context()
        ) is True
        assert calls == []

    def test_zero_timeout_disables_deadline(self, monkeypatch):
        import contextvars
        from cron import scheduler as sched
        self._stub_emitter(monkeypatch)
        seen = []

        def fn(job, _abandoned="not-passed"):
            seen.append(_abandoned)
            return True

        job = {"id": "off-job", "name": "off", "timeout_seconds": 0}
        assert sched._run_callable_with_deadline(
            job, fn, True, contextvars.copy_context()
        ) is True
        # Disabled path runs process_fn directly, no abandon plumbing.
        assert seen == ["not-passed"]

    def test_parallel_timeout_marks_releases_and_abandons(self, monkeypatch):
        import contextvars
        import threading
        import time as _t
        from cron import scheduler as sched

        calls = self._stub_emitter(monkeypatch)
        marked = []
        monkeypatch.setattr(
            sched, "mark_job_run",
            lambda job_id, success, error, **kw: marked.append((job_id, success, error)),
        )
        runaway_done = threading.Event()
        saw_abandoned = []

        def fn(job, _abandoned=None):
            _t.sleep(1.2)  # well past the 0.2s deadline
            saw_abandoned.append(_abandoned.is_set())
            runaway_done.set()
            return True

        job = {"id": "hung-job", "name": "hung", "timeout_seconds": 0.2}
        # Simulate the worker's Guard #3 registration.
        assert sched._try_register_in_flight("hung-job", "hung") is None

        t0 = _t.monotonic()
        result = sched._run_callable_with_deadline(
            job, fn, True, contextvars.copy_context()
        )
        elapsed = _t.monotonic() - t0

        assert result is False
        assert elapsed < 1.0, "must return at the deadline, not at completion"
        assert marked == [("hung-job", False, marked[0][2])]
        assert "soft deadline exceeded" in marked[0][2]
        assert len(calls) == 1 and calls[0]["success"] is False
        # Slot released at the deadline so the next fire can register…
        assert sched._try_register_in_flight("hung-job", "hung") is None
        # …and the runaway finishing later must NOT pop the new record.
        assert runaway_done.wait(3), "runaway worker never finished"
        _t.sleep(0.1)
        with sched._in_flight_lock:
            assert "hung-job" in sched._in_flight
        assert saw_abandoned == [True]

    def test_parallel_timeout_hands_the_real_late_outcome_back(self, monkeypatch):
        """Exercise the actual watchdog/worker handoff, not just its helper.

        The worker finishes while the deadline owner is persisting the
        provisional failure. The explicit event orders the amendment and
        carries the exact timestamp/error identity needed by both CAS writes.
        """
        import contextvars
        import threading
        import time as _t
        from cron import scheduler as sched

        self._stub_emitter(monkeypatch)
        monkeypatch.setattr(sched, "mark_job_run", lambda *a, **k: "deadline-stamp")
        monkeypatch.setattr(sched, "finish_execution", lambda *a, **k: {})
        job_amends = []
        ledger_amends = []
        monkeypatch.setattr(
            sched,
            "amend_late_outcome_after_abandon",
            lambda *a, **k: (job_amends.append((a, k)), True)[1],
        )
        monkeypatch.setattr(
            sched,
            "amend_execution_after_abandon",
            lambda *a, **k: ledger_amends.append((a, k)),
        )
        amended = threading.Event()

        def fn(job, _abandoned=None, _deadline_box=None):
            _t.sleep(0.15)
            assert sched._deadline_has_elapsed(_abandoned, _deadline_box)
            assert sched._amend_late_deadline_outcome(
                job,
                success=True,
                error=None,
                deadline_box=_deadline_box,
            ) is True
            amended.set()
            return True

        job = {
            "id": "late-real-verdict",
            "name": "late",
            "timeout_seconds": 0.05,
            "execution_id": "exec-late",
        }
        assert sched._try_register_in_flight(job["id"], job["name"]) is None
        assert sched._run_callable_with_deadline(
            job, fn, True, contextvars.copy_context()
        ) is False
        assert amended.wait(2), "late worker never amended its verdict"

        assert len(job_amends) == 1
        assert job_amends[0][0] == (job["id"],)
        assert job_amends[0][1]["expected_last_run_at"] == "deadline-stamp"
        assert job_amends[0][1]["success"] is True
        assert len(ledger_amends) == 1
        assert ledger_amends[0][0] == ("exec-late",)
        assert ledger_amends[0][1]["success"] is True
        assert job_amends[0][1]["abandon_error"] == ledger_amends[0][1]["abandon_error"]

    def test_late_outcome_waits_without_abandoning_handoff(self, monkeypatch):
        """A slow provisional write cannot permanently discard the real verdict."""
        from cron import scheduler as sched

        waits = []

        class FinalizedWaitSpy:
            def wait(self, timeout=None):
                waits.append(timeout)
                return timeout is None

        job_amends = []
        monkeypatch.setattr(
            sched,
            "amend_late_outcome_after_abandon",
            lambda *a, **k: (job_amends.append((a, k)), True)[1],
        )
        assert sched._amend_late_deadline_outcome(
            {"id": "slow-finalizer"},
            success=True,
            error=None,
            deadline_box={
                "deadline_finalized": FinalizedWaitSpy(),
                "deadline_error": "deadline proxy",
                "deadline_last_run_at": "deadline-stamp",
            },
        ) is True
        assert waits == [None]
        assert len(job_amends) == 1

    def test_monotonic_boundary_waits_for_watchdog_decision(self, monkeypatch):
        """Worker routing cannot depend on which thread runs first after join."""
        import threading
        import time as _t
        from cron import scheduler as sched

        abandoned = threading.Event()
        decided = threading.Event()
        box = {
            "deadline_monotonic": _t.monotonic() - 0.001,
            "deadline_decided": decided,
        }
        result = []
        waiter = threading.Thread(
            target=lambda: result.append(
                sched._deadline_has_elapsed(abandoned, box)
            )
        )
        waiter.start()
        _t.sleep(0.02)
        assert waiter.is_alive(), "worker inferred a verdict before watchdog decision"
        abandoned.set()
        decided.set()
        waiter.join(1)
        assert result == [True]

    def test_completed_at_boundary_is_not_misclassified_as_abandoned(self):
        """An elapsed clock alone cannot turn a completed worker into timeout."""
        import threading
        import time as _t
        from cron import scheduler as sched

        decided = threading.Event()
        decided.set()
        assert sched._deadline_has_elapsed(
            threading.Event(),
            {
                "deadline_monotonic": _t.monotonic() - 0.001,
                "deadline_decided": decided,
            },
        ) is False

        # Sequential jobs carry no abandonment boundary: they alert and keep
        # waiting, so the same elapsed wall time must stay on the normal path.
        assert sched._deadline_has_elapsed(
            threading.Event(), {"deadline_monotonic": None}
        ) is False

    def test_abandon_signal_precedes_slow_failure_event(self, monkeypatch):
        """A slow event subscriber cannot leave the worker on the normal path.

        This pins the race where the worker finished while on_job_completed
        blocked, wrote success normally, and was then overwritten by the
        deadline's provisional failure.
        """
        import contextvars
        import threading
        from cron import scheduler as sched

        event_entered = threading.Event()
        release_event = threading.Event()
        worker_saw = []

        class SlowEmitter:
            def on_job_completed(self, **kwargs):
                event_entered.set()
                assert release_event.wait(2)

        monkeypatch.setattr(sched, "_get_event_emitter", lambda: SlowEmitter())
        monkeypatch.setattr(sched, "mark_job_run", lambda *a, **k: "stamp")

        def worker(job, _abandoned=None, _deadline_box=None):
            assert event_entered.wait(2)
            worker_saw.append(_abandoned.is_set())
            release_event.set()
            return True

        job = {"id": "event-race", "name": "race", "timeout_seconds": 0.05}
        assert sched._try_register_in_flight(job["id"], job["name"]) is None
        assert sched._run_callable_with_deadline(
            job, worker, True, contextvars.copy_context()
        ) is False
        assert worker_saw == [True]

    def test_process_job_branch_amends_instead_of_suppressing(
        self, monkeypatch, _tick_lock_isolated
    ):
        """Pin the original scheduler.py:6088 defect through the real branch.

        A helper-only test would stay green if ``_process_job`` went back to
        returning immediately after saving late output. Drive ``tick`` so the
        production branch itself must invoke the amendment.
        """
        import threading
        import time as _t
        from unittest.mock import patch
        from cron import scheduler as sched

        job = {
            "id": "late-process-branch",
            "name": "late-process",
            "timeout_seconds": 0.05,
            "deliver": "local",
            "schedule": {"kind": "cron", "expr": "0 * * * *"},
        }
        amended = threading.Event()
        seen = []

        def slow_success(_job):
            _t.sleep(0.15)
            return True, "saved output", "real response", None

        def amend(*args, **kwargs):
            seen.append((args, kwargs))
            amended.set()
            return True

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])),              patch("cron.scheduler.advance_next_runs"),              patch("cron.scheduler.create_execution", return_value={"id": "exec-real"}),              patch("cron.scheduler.mark_execution_running"),              patch("cron.scheduler.finish_execution"),              patch("cron.scheduler.run_job", side_effect=slow_success),              patch("cron.scheduler.save_job_output", return_value="/tmp/late.md"),              patch("cron.scheduler.mark_job_run", return_value="deadline-stamp"),              patch("cron.scheduler.amend_late_outcome_after_abandon", side_effect=amend),              patch("cron.scheduler.amend_execution_after_abandon"):
            assert sched.tick(verbose=False, sync=True) == 0
            assert amended.wait(2), "_process_job suppressed the late verdict"

        assert seen[0][0] == (job["id"],)
        assert seen[0][1]["success"] is True
        assert seen[0][1]["expected_last_run_at"] == "deadline-stamp"

    def test_output_save_crossing_deadline_uses_late_path(
        self, monkeypatch, _tick_lock_isolated
    ):
        """Output persistence cannot race abandonment into normal side effects."""
        import threading
        import time as _t
        from unittest.mock import patch
        from cron import scheduler as sched

        job = {
            "id": "save-crosses-deadline",
            "name": "save-crosses-deadline",
            "timeout_seconds": 0.08,
            "deliver": "local",
            "schedule": {"kind": "cron", "expr": "0 * * * *"},
        }
        amended = threading.Event()
        deliveries = []
        normal_success_marks = []

        def save_output(*args, **kwargs):
            _t.sleep(0.12)
            return "/tmp/save-crosses-deadline.md"

        def mark(job_id, success, error=None, **kwargs):
            if success:
                normal_success_marks.append(job_id)
            return "deadline-stamp"

        with patch("cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])), \
             patch("cron.scheduler.advance_next_runs"), \
             patch("cron.scheduler.create_execution", return_value={"id": "exec-save"}), \
             patch("cron.scheduler.mark_execution_running"), \
             patch("cron.scheduler.finish_execution"), \
             patch("cron.scheduler.run_job", return_value=(True, "output", "response", None)), \
             patch("cron.scheduler.save_job_output", side_effect=save_output), \
             patch("cron.scheduler.mark_job_run", side_effect=mark), \
             patch("cron.scheduler._deliver_result", side_effect=lambda *a, **k: deliveries.append(True)), \
             patch(
                 "cron.scheduler.amend_late_outcome_after_abandon",
                 side_effect=lambda *a, **k: (amended.set(), True)[1],
             ), \
             patch("cron.scheduler.amend_execution_after_abandon"):
            assert sched.tick(verbose=False, sync=True) == 0
            assert amended.wait(2), "save-boundary worker never used late CAS path"

        assert deliveries == []
        assert normal_success_marks == []

    def test_outer_deadline_proxy_is_replaced_by_late_inner_timeout(
        self, monkeypatch, _tick_lock_isolated
    ):
        """Equal nested limits still surface the inner timeout's richer cause.

        The outer join starts before ``run_job`` establishes its own hard-limit
        clock, so it normally records the soft-deadline proxy first. When the
        inner limit returns a few seconds later, the production late-outcome
        branch must replace that proxy in both durable stores.
        """
        import threading
        import time as _t
        from unittest.mock import patch
        from cron import scheduler as sched

        job = {
            "id": "nested-timeout",
            "name": "nested-timeout",
            "timeout_seconds": 0.05,
            "deliver": "local",
            "schedule": {"kind": "cron", "expr": "0 * * * *"},
        }
        hard_error = (
            "Cron job 'nested-timeout' exceeded wall-clock limit 3600s "
            "(elapsed 3602.97s) — last activity: executing tool: terminal"
        )
        job_amends = []
        ledger_amends = []
        amended = threading.Event()

        def late_inner_timeout(_job):
            _t.sleep(0.15)
            return False, "durable partial output", "", hard_error

        def amend_job(*args, **kwargs):
            job_amends.append((args, kwargs))
            amended.set()
            return True

        def amend_ledger(*args, **kwargs):
            ledger_amends.append((args, kwargs))
            return {"id": args[0], "status": "failed", "error": kwargs["error"]}

        with patch(
            "cron.scheduler.get_due_and_skipped_jobs", return_value=([job], [])
        ), patch("cron.scheduler.advance_next_runs"), patch(
            "cron.scheduler.create_execution", return_value={"id": "exec-nested"}
        ), patch("cron.scheduler.mark_execution_running"), patch(
            "cron.scheduler.finish_execution"
        ), patch(
            "cron.scheduler.run_job", side_effect=late_inner_timeout
        ), patch(
            "cron.scheduler.save_job_output", return_value="/tmp/late-timeout.md"
        ), patch(
            "cron.scheduler.mark_job_run", return_value="deadline-stamp"
        ), patch(
            "cron.scheduler.amend_late_outcome_after_abandon", side_effect=amend_job
        ), patch(
            "cron.scheduler.amend_execution_after_abandon", side_effect=amend_ledger
        ):
            assert sched.tick(verbose=False, sync=True) == 0
            assert amended.wait(2), "inner timeout never replaced outer proxy"

        assert len(job_amends) == 1
        assert job_amends[0][0] == (job["id"],)
        assert job_amends[0][1]["success"] is False
        assert job_amends[0][1]["error"] == hard_error
        assert job_amends[0][1]["expected_last_run_at"] == "deadline-stamp"
        assert "soft deadline exceeded" in job_amends[0][1]["abandon_error"]
        assert len(ledger_amends) == 1
        assert ledger_amends[0][0] == ("exec-nested",)
        assert ledger_amends[0][1]["success"] is False
        assert ledger_amends[0][1]["error"] == hard_error
        assert (
            ledger_amends[0][1]["abandon_error"]
            == job_amends[0][1]["abandon_error"]
        )

    def test_late_outcome_refuses_an_unidentified_deadline(self, monkeypatch):
        """Missing CAS identity fails closed rather than guessing at ownership."""
        import threading
        from cron import scheduler as sched

        touched = []
        monkeypatch.setattr(
            sched, "amend_late_outcome_after_abandon", lambda *a, **k: touched.append(1)
        )
        finalized = threading.Event()
        finalized.set()

        assert sched._amend_late_deadline_outcome(
            {"id": "unidentified"},
            success=True,
            error=None,
            deadline_box={"deadline_finalized": finalized},
        ) is False
        assert touched == []

    def test_missing_job_timestamp_still_amends_identified_execution(self, monkeypatch):
        """A failed job-store write must not strand the uniquely-owned ledger row."""
        import threading
        from cron import scheduler as sched

        job_touched = []
        ledger_touched = []
        monkeypatch.setattr(
            sched,
            "amend_late_outcome_after_abandon",
            lambda *a, **k: job_touched.append((a, k)),
        )
        monkeypatch.setattr(
            sched,
            "amend_execution_after_abandon",
            lambda *a, **k: (ledger_touched.append((a, k)), {"id": a[0]})[1],
        )
        finalized = threading.Event()
        finalized.set()

        assert sched._amend_late_deadline_outcome(
            {"id": "partial-deadline", "execution_id": "exec-partial"},
            success=True,
            error=None,
            deadline_box={
                "deadline_finalized": finalized,
                "deadline_error": "soft deadline",
                "deadline_last_run_at": None,
            },
        ) is True
        assert job_touched == []
        assert ledger_touched == [
            (
                ("exec-partial",),
                {
                    "abandon_error": "soft deadline",
                    "success": True,
                    "error": None,
                },
            )
        ]

    def test_sequential_timeout_alerts_but_waits_for_completion(self, monkeypatch):
        import contextvars
        import time as _t
        from cron import scheduler as sched

        calls = self._stub_emitter(monkeypatch)
        marked = []
        monkeypatch.setattr(
            sched, "mark_job_run",
            lambda *a, **kw: marked.append(a),
        )

        def fn(job, _abandoned=None):
            _t.sleep(0.7)
            return True

        job = {"id": "seq-job", "name": "seq", "timeout_seconds": 0.2}
        t0 = _t.monotonic()
        result = sched._run_callable_with_deadline(
            job, fn, False, contextvars.copy_context()
        )
        elapsed = _t.monotonic() - t0

        assert result is True, "sequential path must wait for the real result"
        assert elapsed >= 0.65
        # Alert fired at the deadline…
        assert len(calls) == 1 and calls[0]["success"] is False
        assert "sequential job" in calls[0]["error"]
        # …but the run was NOT marked failed (it's still owned by _process_job).
        assert marked == []

    def test_release_started_before_protects_successor_record(self):
        from cron import scheduler as sched

        # Deterministic: pin record start times explicitly instead of
        # relying on wall-clock ordering (fragile under a loaded suite).
        cutoff = 1000.0
        assert sched._try_register_in_flight("guard-job", "guard") is None
        with sched._in_flight_lock:
            sched._in_flight["guard-job"].start_monotonic = cutoff - 10
        # A record that started before the cutoff (the runaway) is popped.
        sched._release_in_flight_started_before("guard-job", cutoff)
        with sched._in_flight_lock:
            assert "guard-job" not in sched._in_flight

        # A record that started after the cutoff (a successor fire that
        # raced in) must survive the deadline handler's release.
        assert sched._try_register_in_flight("guard-job", "guard") is None
        with sched._in_flight_lock:
            sched._in_flight["guard-job"].start_monotonic = cutoff + 10
        sched._release_in_flight_started_before("guard-job", cutoff)
        with sched._in_flight_lock:
            assert "guard-job" in sched._in_flight, (
                "a record started after the cutoff must survive"
            )

    def test_per_job_script_timeout_overrides_global(self):
        import time as _t
        from cron import scheduler as sched

        sdir = sched._get_hermes_home() / "scripts"
        sdir.mkdir(parents=True, exist_ok=True)
        slow = sdir / "slow_gate_probe.py"
        # Sleep far longer than the 120s global so the two outcomes are
        # separated by minutes, not seconds. subprocess.run(timeout=...) kills
        # the child, so the honoured-timeout path never actually waits it out.
        slow.write_text(
            "import time\ntime.sleep(600)\nprint('done')\n", encoding="utf-8"
        )
        t0 = _t.monotonic()
        ok, out = sched._run_job_script("slow_gate_probe.py", timeout_s=1)
        elapsed = _t.monotonic() - t0
        assert ok is False
        assert "timed out after 1s" in out
        # 60s, not 6s: the honoured 1s timeout returns in ~1s plus interpreter
        # spawn, and spawn alone was measured at 6.6s on a box running the full
        # parallel gate — enough to fail a 6s bound while the override worked
        # perfectly. Falling back to the 120s global still fails this cleanly.
        assert elapsed < 60, "per-job timeout must override the 120s global"
        # Invalid / non-positive overrides fall back to the global default
        # (probe a fast script so the global never actually elapses).
        fast = sdir / "fast_gate_probe.py"
        fast.write_text("print('ok')\n", encoding="utf-8")
        ok2, out2 = sched._run_job_script("fast_gate_probe.py", timeout_s="bogus")
        assert ok2 is True and out2 == "ok"

    def test_timeout_resolution_priority(self, monkeypatch):
        from cron import scheduler as sched

        monkeypatch.setenv("HERMES_CRON_JOB_TIMEOUT_SECONDS", "111")
        assert sched._job_timeout_seconds({"timeout_seconds": 42}) == 42.0
        assert sched._job_timeout_seconds({}) == 111.0
        monkeypatch.delenv("HERMES_CRON_JOB_TIMEOUT_SECONDS")
        monkeypatch.setattr(
            sched, "load_config",
            lambda: {"cron": {"job_timeout_seconds": 77}},
        )
        assert sched._job_timeout_seconds({}) == 77.0
        monkeypatch.setattr(sched, "load_config", lambda: {})
        assert sched._job_timeout_seconds({}) == sched._DEFAULT_JOB_TIMEOUT_S
        # Per-job <= 0 disables.
        assert sched._job_timeout_seconds({"timeout_seconds": 0}) == 0.0


class TestCronDeliveryTargets:
    """``cron_delivery_targets`` powers the dashboard delivery dropdown.

    It must list every configured + cron-deliverable platform (no hardcoded
    set), flag whether each has its home channel set, and never include
    platforms whose gateway isn't configured.
    """

    def _patch_connected(self, monkeypatch, names):
        import gateway.config as gateway_config

        class _Platform:
            def __init__(self, value):
                self.value = value

        class _GatewayConfig:
            def get_connected_platforms(self_inner):
                return [_Platform(n) for n in names]

        monkeypatch.setattr(
            gateway_config, "load_gateway_config", lambda: _GatewayConfig()
        )

    def test_lists_configured_platforms_flagging_missing_home_channel(self, monkeypatch):
        from cron.scheduler_delivery import cron_delivery_targets

        self._patch_connected(monkeypatch, ["matrix", "telegram"])
        monkeypatch.delenv("MATRIX_HOME_ROOM", raising=False)
        monkeypatch.delenv("TELEGRAM_HOME_CHANNEL", raising=False)

        targets = {t["id"]: t for t in cron_delivery_targets()}

        # bot-chat:<profile> entries (machine-local Bot Chat injection) ride
        # the same listing but are not gateway platforms — scope the
        # platform assertions to the gateway entries.
        platform_targets = {k: v for k, v in targets.items() if not k.startswith("bot-chat")}

        assert set(platform_targets) == {"matrix", "telegram"}
        # Configured but no home channel → surfaced, flagged for the UI.
        assert platform_targets["matrix"]["home_target_set"] is False
        assert platform_targets["matrix"]["home_env_var"] == "MATRIX_HOME_ROOM"
        assert platform_targets["telegram"]["home_target_set"] is False
        # Bot Chat targets need no home channel: whatever profiles exist on
        # this machine must all be listed as ready.
        bot_chat = [v for k, v in targets.items() if k.startswith("bot-chat")]
        assert all(t["home_target_set"] for t in bot_chat)


class TestHomeTargetEnvVarRegistry:
    """Regression: ``_HOME_TARGET_ENV_VARS`` must include every gateway
    platform that supports cron-driven outbound delivery. Missing an
    entry means ``hermes cron create --deliver=<platform>`` silently
    fails to route through the platform's home channel."""


class TestCronDeliveryMirror:
    """cron.mirror_delivery / per-job attach_to_session: opt-in append of a
    cron delivery into the target chat's gateway session transcript.

    Default OFF preserves the historical isolation guarantee byte-for-byte.
    When enabled, delivery rides the existing gateway.mirror.mirror_to_session
    so cron uses exactly the same path interactive send_message mirroring uses.
    """


    def test_mirror_writes_user_role_with_label_not_assistant(self):
        """Regression for #2221 / #2313: the cron brief must mirror as a USER
        turn (with a [Cron delivery: ...] label), NOT assistant — an
        assistant-role mirror lands as assistant->assistant after the agent's
        last turn and breaks strict alternation on non-Anthropic providers."""
        from cron.scheduler_delivery import _maybe_mirror_cron_delivery

        with patch("gateway.mirror.mirror_to_session", return_value=True) as m:
            _maybe_mirror_cron_delivery(
                {"id": "j1", "name": "Morning Brief"}, "telegram", "123",
                "Market movers today", thread_id=None, enabled=True,
            )
        m.assert_called_once()
        args, kwargs = m.call_args
        assert kwargs.get("role") == "user", "cron mirror must be a user turn, not assistant"
        # The brief text is prefixed with a human-readable cron-delivery label
        # so replay (where the mirror metadata is dropped at the SQLite
        # boundary) still distinguishes it from a genuine user message.
        assert args[2].startswith("[Cron delivery: Morning Brief]")
        assert "Market movers today" in args[2]


    def test_delivery_mirrors_clean_content_not_wrapped(self):
        """When enabled, the mirror receives the CLEAN agent output, not the
        cron header/footer-wrapped delivery text."""
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.TELEGRAM: pconfig}

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("tools.send_message_tool._send_to_platform", new=AsyncMock(return_value={"success": True})), \
             patch("gateway.mirror.mirror_to_session", return_value=True) as mirror_mock:
            job = {
                "id": "test-job",
                "name": "daily-report",
                "deliver": "origin",
                "origin": {"platform": "telegram", "chat_id": "123"},
                "attach_to_session": True,
            }
            _deliver_result(job, "Here is today's summary.")

        mirror_mock.assert_called_once()
        mirrored_text = mirror_mock.call_args[0][2]
        # Clean content, no cron wrapper.
        assert "Here is today's summary." in mirrored_text
        assert "Cronjob Response:" not in mirrored_text
        assert "To stop or manage this job" not in mirrored_text


    # --- origin-scoping (mirror only into the conversation that created the job) ---


    # --- multi-participant parity with send_message (user_id passthrough) ---


    # --- continuable cron: thread-preferred (Teknium's interface) ---

    def test_open_thread_returns_id_on_thread_platform(self):
        """On a thread-capable adapter, _open_continuable_cron_thread returns
        the new thread id from create_handoff_thread."""
        from cron.scheduler_delivery import _open_continuable_cron_thread

        adapter = MagicMock()
        adapter.create_handoff_thread = AsyncMock(return_value="9001")

        # safe_schedule_threadsafe hands the coro to the gateway loop and
        # returns a future. Patch it to close the coro and return a ready
        # future carrying the adapter's thread id.
        def _run_now(coro, _loop):
            coro.close()
            fut = MagicMock()
            fut.result.return_value = "9001"
            return fut

        with patch("agent.async_utils.safe_schedule_threadsafe", side_effect=_run_now):
            tid = _open_continuable_cron_thread(
                {"id": "j1", "name": "Brief"}, adapter, "123", loop=MagicMock(),
            )
        assert tid == "9001"


    def test_seed_thread_session_creates_session_and_mirrors(self):
        """Seeding a freshly-opened thread creates the thread-keyed session via
        the adapter's live store and appends the brief via mirror_to_session."""
        from cron.scheduler_delivery import _seed_cron_thread_session

        store = MagicMock()
        adapter = MagicMock()
        adapter._session_store = store

        with patch("gateway.mirror.mirror_to_session", return_value=True) as mirror_mock:
            _seed_cron_thread_session(
                {"id": "j1"}, adapter, "telegram", "123", "9001",
                "Daily brief Task #2", chat_name="Ops",
            )

        # Session row created for the thread, then brief mirrored into it.
        store.get_or_create_session.assert_called_once()
        seeded_source = store.get_or_create_session.call_args[0][0]
        assert seeded_source.chat_type == "thread"
        assert seeded_source.thread_id == "9001"
        mirror_mock.assert_called_once()
        assert mirror_mock.call_args.kwargs.get("thread_id") == "9001"


class TestCronContinuableSurfaceInChannel:
    """cron_continuable_surface: in_channel — deliver a continuable cron FLAT
    into a channel (no dedicated thread), so a plain channel reply continues the
    job via the shared-channel session (platform, chat_id, None).

    Design: decisions.md D1/D2/D6 + F5. The scheduler reads the per-platform key
    generically from pconfig.extra; the in_channel branch is gated on the
    adapter capability flag ``supports_inchannel_continuable`` (Slack=True,
    others fail SAFE to thread). In in_channel mode the thread-open branch is
    SKIPPED (thread_id stays None), then ``_seed_cron_channel_session`` CREATES
    the flat shared-channel session and mirrors the brief into it (the shipped
    mirror only APPENDS to an existing session, and the flat channel row is
    otherwise absent for a chat_postMessage delivery).
    """

    def _slack_cfg(self, extra):
        """A mock GatewayConfig with a Slack pconfig carrying ``extra``."""
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        pconfig.extra = extra
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.SLACK: pconfig}
        return mock_cfg

    def _run_inchannel_delivery(self, extra, adapter, *, mirror_ok=True, origin=None,
                                attach_to_session=True):
        """Drive _deliver_result down the live-adapter path for a Slack
        channel-origin job with the given ``extra`` config. Returns the
        _open_continuable_cron_thread mock and the mirror_to_session mock."""
        from gateway.config import Platform
        from concurrent.futures import Future

        mock_cfg = self._slack_cfg(extra)

        loop = MagicMock()
        loop.is_running.return_value = True

        def fake_run_coro(coro, _loop):
            future = Future()
            try:
                import asyncio as _asyncio
                future.set_result(_asyncio.run(coro))
            except BaseException as _e:  # noqa: BLE001
                future.set_exception(_e)
            return future

        job = {
            "id": "brief-job",
            "name": "Daily Brief",
            "deliver": "origin",
            # Channel origin: no thread_id (flat channel message scheduled it).
            # Carries the scheduling user's id — the in_channel seed must key
            # the flat channel session to THIS user (see build_session_key).
            "origin": origin or {"platform": "slack", "chat_id": "C123", "user_id": "U_HUMAN"},
            # Opt into the continuable mirror (parameterized: the seed must
            # NOT depend on this — see the no-attach regression test).
            "attach_to_session": attach_to_session,
        }

        with patch("gateway.config.load_gateway_config", return_value=mock_cfg), \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}), \
             patch("cron.scheduler_delivery._open_continuable_cron_thread") as open_thread_mock, \
             patch("asyncio.run_coroutine_threadsafe", side_effect=fake_run_coro), \
             patch("gateway.mirror.mirror_to_session", return_value=mirror_ok) as mirror_mock:
            _deliver_result(
                job, "Here is today's brief.",
                adapters={Platform.SLACK: adapter}, loop=loop,
            )
        return open_thread_mock, mirror_mock

    def _slack_adapter(self, supports_inchannel=True, with_store=True):
        adapter = AsyncMock()
        adapter.send.return_value = MagicMock(
            success=True, message_id="msg_1", raw_response=None,
        )
        # Capability flag read via getattr in the scheduler.
        adapter.supports_inchannel_continuable = supports_inchannel
        # Pin the per-platform accessor OFF: an unspecced AsyncMock would
        # auto-create it as a truthy callable, silently routing every test
        # through the relay accessor branch instead of the native scalar
        # fallback these tests describe (and making supports_inchannel=False
        # unenforceable). None -> not callable -> scalar path, like a real
        # native adapter that never defines the method.
        adapter.supports_inchannel_continuable_for_platform = None
        # A live session store so the in_channel seed can CREATE the flat row
        # (the real bug: without a create step the mirror no-ops on a missing
        # session and the brief is lost). Use a plain MagicMock store.
        if with_store:
            adapter._session_store = MagicMock()
        return adapter

    def test_in_channel_skips_thread_open(self):
        """G2: in_channel mode must NOT open a handoff thread."""
        adapter = self._slack_adapter(supports_inchannel=True)
        open_thread_mock, _ = self._run_inchannel_delivery(
            {"cron_continuable_surface": "in_channel"}, adapter,
        )
        open_thread_mock.assert_not_called()


    # --- _seed_cron_channel_session: the create-then-mirror unit + the
    #     KEY-MATCH invariant (seed key must equal the inbound reply's key) ---

    def test_seed_channel_session_key_matches_inbound_channel_reply(self):
        """The whole point: the flat session the seed CREATES must be keyed
        identically to what a plain inbound channel reply resolves to. Assert
        the invariant directly via build_session_key, not just call args."""
        from cron.scheduler_delivery import _seed_cron_channel_session
        from gateway.session import build_session_key, SessionSource
        from gateway.config import Platform

        store = MagicMock()
        adapter = MagicMock()
        adapter._session_store = store

        with patch("gateway.mirror.mirror_to_session", return_value=True) as mirror_mock:
            ok = _seed_cron_channel_session(
                {"id": "j1", "name": "Brief"}, adapter, "slack", "C123",
                "Daily brief", is_dm=False, user_id="U_HUMAN", chat_name="ops",
            )
        assert ok is True
        seeded_source = store.get_or_create_session.call_args[0][0]
        seed_key = build_session_key(seeded_source)

        # What a plain top-level channel reply (reply_in_thread:false → thread
        # None) from the same user resolves to:
        inbound = SessionSource(
            platform=Platform.SLACK, chat_id="C123", chat_type="group",
            user_id="U_HUMAN", thread_id=None,
        )
        assert seed_key == build_session_key(inbound), (
            f"seed key {seed_key} != inbound reply key {build_session_key(inbound)} "
            "— the reply would NOT continue the seeded session"
        )
        mirror_mock.assert_called_once()
        assert mirror_mock.call_args.kwargs.get("thread_id") is None
        assert mirror_mock.call_args.kwargs.get("user_id") == "U_HUMAN"

    def test_in_channel_seed_fires_without_attach_to_session(self):
        """REGRESSION (live, Alice 2026-08-19): the in_channel seed was gated on
        mirror_this_target (mirror_enabled AND origin match), so a continuable
        in_channel cron created WITHOUT attach_to_session (and with the
        cron.mirror_delivery global at its default False) delivered the brief
        flat but never seeded the flat session — the next plain reply hit a
        blank session and the agent had no idea about its own delivery message.

        in_channel IS the continuation surface: the seed must fire on origin
        match alone. attach_to_session stays the opt-in for the SEPARATE
        default-surface mirror behavior; it must not be required here."""
        from cron.scheduler import _deliver_result  # noqa: F401 (driven via helper)

        adapter = self._slack_adapter(supports_inchannel=True)
        with patch("cron.scheduler_delivery._seed_cron_channel_session", return_value=True) as seed_mock:
            self._run_inchannel_delivery(
                {"slack": {"cron_continuable_surface": "in_channel"}}, adapter,
                attach_to_session=False,
            )
        seed_mock.assert_called_once()
        # user_id must ride along even without the mirror opt-in — the flat
        # session key includes it on per-user-isolated chats.
        assert seed_mock.call_args.kwargs.get("user_id") == "U_HUMAN"

    def test_in_channel_flattens_thread_without_attach_to_session(self):
        """REGRESSION: the thread-id-clearing gate was `mirror_this_target`
        while the seed below had been decoupled to origin-match alone. With
        the default knobs off (attach_to_session=False, cron.mirror_delivery
        unset) and an origin carrying a REAL thread_id, the brief still
        delivered INTO the origin thread while the flat (thread_id=None)
        session got seeded — brief and continuation surface in different
        places. The flatten must use the same gate as the seed: origin_target.
        Asserts on the routed DeliveryTarget, not just that the seed ran."""
        captured = {}

        class _SpyRouter:
            def __init__(self, *a, **k):
                pass

            async def _deliver_to_platform(self, target, text, metadata):
                captured["target"] = target
                return {"success": True, "message_id": "msg_1"}

        adapter = self._slack_adapter(supports_inchannel=True)
        origin_with_thread = {
            "platform": "slack", "chat_id": "C123", "user_id": "U_HUMAN",
            # Genuine origin thread (job created from inside a thread).
            "thread_id": "1787188000.000100",
        }
        with patch("gateway.delivery.DeliveryRouter", _SpyRouter), \
             patch("cron.scheduler_delivery._seed_cron_channel_session", return_value=True) as seed_mock:
            self._run_inchannel_delivery(
                {"slack": {"cron_continuable_surface": "in_channel"}}, adapter,
                attach_to_session=False, origin=origin_with_thread,
            )
        seed_mock.assert_called_once()
        assert captured["target"].thread_id is None, (
            "in_channel delivery routed into the origin thread "
            f"({captured['target'].thread_id}) — the flat seeded session "
            "does not match where the brief actually landed"
        )

    def test_origin_scope_id_rides_delivery_metadata(self):
        """REGRESSION (restart-shaped): the connector's fail-closed tenant
        guard resolves the workspace from metadata.scope_id. After a gateway
        restart the RelayAdapter's per-chat scope cache is cold, and
        DeliveryRouter stamps scope only for the configured HOME channel —
        so a scoped Slack origin that is NOT the home chat egressed with no
        scope_id and could be rejected before delivery. The scheduler must
        stamp the persisted origin scope onto origin-matching routing
        metadata (and never onto fan-out targets, which the origin-match
        gate already excludes)."""
        captured = {}

        class _SpyRouter:
            def __init__(self, *a, **k):
                pass

            async def _deliver_to_platform(self, target, text, metadata):
                captured["metadata"] = metadata
                return {"success": True, "message_id": "msg_1"}

        adapter = self._slack_adapter(supports_inchannel=True)
        scoped_origin = {
            "platform": "slack", "chat_id": "C123", "user_id": "U_HUMAN",
            # Persisted workspace scope (captured at job creation). C123 is
            # not any configured home channel in this harness.
            "scope_id": "T0AAAA111",
        }
        with patch("gateway.delivery.DeliveryRouter", _SpyRouter), \
             patch("cron.scheduler_delivery._seed_cron_channel_session", return_value=True):
            self._run_inchannel_delivery(
                {"slack": {"cron_continuable_surface": "in_channel"}}, adapter,
                attach_to_session=False, origin=scoped_origin,
            )
        assert captured["metadata"].get("scope_id") == "T0AAAA111", (
            "persisted origin scope_id did not reach the delivery metadata — "
            "a cold-cache relay egress has no tenant discriminator"
        )

    def test_legacy_origin_without_scope_stamps_nothing(self):
        """Legacy jobs (origin persisted before scope capture) must not gain
        a scope_id key — the relay's per-chat cache / home-channel stamping
        remain the only sources, exactly today's behavior."""
        captured = {}

        class _SpyRouter:
            def __init__(self, *a, **k):
                pass

            async def _deliver_to_platform(self, target, text, metadata):
                captured["metadata"] = metadata
                return {"success": True, "message_id": "msg_1"}

        adapter = self._slack_adapter(supports_inchannel=True)
        with patch("gateway.delivery.DeliveryRouter", _SpyRouter), \
             patch("cron.scheduler_delivery._seed_cron_channel_session", return_value=True):
            self._run_inchannel_delivery(
                {"slack": {"cron_continuable_surface": "in_channel"}}, adapter,
                attach_to_session=False,
            )
        assert "scope_id" not in captured["metadata"]

    def test_native_adapter_scalar_false_fails_safe_to_thread(self):
        """D6 fallback boundary with a REAL (non-mock) adapter shape: a native
        adapter defines only the scalar supports_inchannel_continuable and no
        per-platform accessor — MagicMock-based fixtures can't prove this
        branch because they fabricate a truthy accessor. Scalar False must
        fail safe to thread mode: the in_channel seed never fires."""

        class _NativeShapedAdapter:
            supports_inchannel_continuable = False
            _session_store = None

            def __init__(self):
                self.sent = []

            async def send(self, chat_id, content, metadata=None, **kwargs):
                self.sent.append((chat_id, content))
                return MagicMock(success=True, message_id="msg_1",
                                 raw_response=None)

        adapter = _NativeShapedAdapter()
        assert not callable(
            getattr(adapter, "supports_inchannel_continuable_for_platform", None)
        )
        with patch("cron.scheduler_delivery._seed_cron_channel_session") as seed_mock:
            self._run_inchannel_delivery(
                {"slack": {"cron_continuable_surface": "in_channel"}}, adapter,
                attach_to_session=False,
            )
        # Delivery must have gone through the LIVE adapter — otherwise a
        # broken harness that never delivers would also leave the seed
        # uncalled and this test would pass for the wrong reason.
        assert len(adapter.sent) == 1
        assert adapter.sent[0][0] == "C123"
        # Capability absent -> surface fails safe to thread -> flat seed
        # must NOT run (D6).
        seed_mock.assert_not_called()

    def test_seed_mirrors_into_exact_created_session_on_populated_chat(self):
        """REGRESSION (live, Alice 2026-08-19 19:17): 'in_channel seed did NOT
        land'. The seed created the flat session row, then mirror_to_session
        re-discovered the target via origin heuristics — and on a populated
        chat (flat session + N per-message thread sessions sharing chat_id,
        mixed user_ids) find_session_by_origin's multi-candidate bail-out
        returned None, silently dropping the brief. The seed must mirror into
        the EXACT session row it just created, no rediscovery."""
        from cron.scheduler_delivery import _seed_cron_channel_session

        store = MagicMock()
        created = MagicMock()
        created.session_id = "sess-flat-exact"
        store.get_or_create_session.return_value = created
        adapter = MagicMock()
        adapter._session_store = store

        with patch("gateway.mirror.mirror_to_session", return_value=True) as mirror_mock:
            ok = _seed_cron_channel_session(
                {"id": "j1", "name": "Brief"}, adapter, "slack", "D0BJTDCSR7C",
                "Daily brief", is_dm=True, user_id="U_HUMAN", chat_name=None,
            )
        assert ok is True
        # The mirror received the exact created session id — origin-scan
        # heuristics (and their populated-chat bail-out) are out of the path.
        assert mirror_mock.call_args.kwargs.get("session_id") == "sess-flat-exact"

    def test_in_channel_also_seeds_thread_surface_of_delivered_brief(self):
        """REGRESSION (live, Alice 2026-08-19 19:19): the user replied IN THE
        BRIEF'S THREAD (Slack's natural affordance on a flat message). That
        reply keys to (chat, thread=<brief ts>) — a session in_channel mode
        never seeded, so the agent had no idea about its own brief. The flat
        delivery's message_id must anchor a companion thread-surface seed."""
        adapter = self._slack_adapter(supports_inchannel=True)
        with patch("cron.scheduler_delivery._seed_cron_channel_session", return_value=True), \
             patch("cron.scheduler_delivery._seed_cron_thread_session") as thread_seed_mock:
            self._run_inchannel_delivery(
                {"slack": {"cron_continuable_surface": "in_channel"}}, adapter,
                attach_to_session=False,
            )
        thread_seed_mock.assert_called_once()
        # Anchored on the delivered message id (the router's SendResult).
        assert thread_seed_mock.call_args.args[4] == "msg_1"


class TestMultiTargetDeliveryContinuesOnFailure:
    """When delivery to one target fails inside the standalone thread-pool
    fallback, the loop must continue to the remaining targets (#47163).

    The fallback runs inside the `except RuntimeError` block of
    `_deliver_result`. Before the fix, an exception raised there (SMTP
    ConnectionError, future.result timeout) escaped the function entirely —
    it is NOT caught by the sibling `except Exception` — crashing the loop
    and silently dropping every subsequent target.
    """

    def _email_cfg(self):
        from gateway.config import Platform

        pconfig = MagicMock()
        pconfig.enabled = True
        mock_cfg = MagicMock()
        mock_cfg.platforms = {Platform.EMAIL: pconfig}
        return mock_cfg

    def test_first_target_failure_does_not_crash_loop(self):
        """First email target fails in the fallback; the second is still attempted."""
        job = {
            "id": "multi-email-job",
            "deliver": "email:a@example.com,email:b@example.com",
        }

        with patch("gateway.config.load_gateway_config", return_value=self._email_cfg()), \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}), \
             patch("asyncio.run", side_effect=RuntimeError("no running loop")), \
             patch("concurrent.futures.ThreadPoolExecutor") as mock_pool_cls:
            mock_pool = MagicMock()
            mock_pool_cls.return_value = mock_pool

            fail_future = MagicMock()
            fail_future.result.side_effect = ConnectionError("SMTP connection refused")
            ok_future = MagicMock()
            ok_future.result.return_value = {"success": True}
            mock_pool.submit.side_effect = [fail_future, ok_future]

            result = _deliver_result(job, "Report content")

        # Both targets attempted — the loop did not crash after the first failure.
        assert mock_pool.submit.call_count == 2, (
            f"expected 2 delivery attempts, got {mock_pool.submit.call_count}"
        )
        # First target's failure is surfaced in the returned error string.
        assert result is not None
        assert "a@example.com" in result
        assert "SMTP connection refused" in result

    def test_all_targets_fail_returns_combined_errors(self):
        """When every target fails, the result reports all of them."""
        job = {
            "id": "all-fail-job",
            "deliver": "email:a@example.com,email:b@example.com",
        }

        with patch("gateway.config.load_gateway_config", return_value=self._email_cfg()), \
             patch("cron.scheduler.load_config", return_value={"cron": {"wrap_response": False}}), \
             patch("asyncio.run", side_effect=RuntimeError("no running loop")), \
             patch("concurrent.futures.ThreadPoolExecutor") as mock_pool_cls:
            mock_pool = MagicMock()
            mock_pool_cls.return_value = mock_pool

            fail_future = MagicMock()
            fail_future.result.side_effect = ConnectionError("connection refused")
            mock_pool.submit.return_value = fail_future

            result = _deliver_result(job, "Report content")

        assert result is not None
        assert "a@example.com" in result
        assert "b@example.com" in result
        assert mock_pool.submit.call_count == 2

class TestBuildJobPromptExtraPrompt:
    """Regression: _build_job_prompt merges extra_prompt into the assembled prompt."""

    def test_extra_prompt_appended_with_header(self):
        """extra_prompt appears under a '## Run Context' header."""
        job = {"prompt": "stored prompt"}
        result = _build_job_prompt(job, extra_prompt="CONTEXT: client=Foo")
        assert "stored prompt" in result
        assert "## Run Context" in result
        assert "CONTEXT: client=Foo" in result

    def test_extra_prompt_does_not_mutate_job(self):
        """The job dict's 'prompt' field must remain unchanged."""
        job = {"prompt": "original"}
        _build_job_prompt(job, extra_prompt="transient context")
        assert job["prompt"] == "original"

    def test_no_extra_prompt_omits_header(self):
        """Without extra_prompt, no '## Run Context' header is injected."""
        job = {"prompt": "just the stored prompt"}
        result = _build_job_prompt(job)
        assert "## Run Context" not in result
        assert "just the stored prompt" in result


class TestSetCronSessionTitle:
    """Robust cron session titling: #50535/#50536/#50537."""


    def test_dedupes_on_duplicate_title(self):
        # First write collides (ValueError); helper falls back to lineage #N.
        from cron.scheduler import _set_cron_session_title
        db = MagicMock()
        db.set_session_title.side_effect = [ValueError("in use"), True]
        db.get_next_title_in_lineage.return_value = "Nightly Synthesis #2"
        out = _set_cron_session_title(db, "sess-1", "Nightly Synthesis")
        assert out == "Nightly Synthesis #2"
        db.get_next_title_in_lineage.assert_called_once_with("Nightly Synthesis")



    def test_returns_none_without_db_or_session(self):
        from cron.scheduler import _set_cron_session_title
        assert _set_cron_session_title(None, "sess-1", "X") is None
        assert _set_cron_session_title(MagicMock(), "", "X") is None


class TestSuspendAwareTimeouts:
    """A host suspend must not be billed to the running cron job.

    Regression for 2026-08-25: jobflow-ats-url-resolve was killed with
    "exceeded wall-clock limit 3600s (elapsed 24269.4s) -- last activity:
    waiting for non-streaming API response", which reads like a hung API call.
    It was not: telemetry showed a 6.67h gap across the ENTIRE cron fleet
    (11:20:06Z -> 18:00:01Z), so every job froze. The watchdog resumed and
    applied a limit to time the job never had.
    """

    POLL = 5.0

    # --- suspended_seconds -------------------------------------------------

    def test_normal_poll_is_not_suspend(self):
        from cron.scheduler import suspended_seconds
        assert suspended_seconds(5.2, self.POLL) == 0.0

    def test_loaded_host_jitter_is_still_charged_to_the_job(self):
        """A slow host is the job's problem; only a stopped loop is not."""
        from cron.scheduler import suspended_seconds
        assert suspended_seconds(45.0, self.POLL) == 0.0

    def test_threshold_boundary_is_not_suspend(self):
        from cron.scheduler import suspended_seconds, _CRON_SUSPEND_GAP_SECS
        assert suspended_seconds(_CRON_SUSPEND_GAP_SECS, self.POLL) == 0.0

    def test_real_suspend_discounts_all_but_one_poll(self):
        from cron.scheduler import suspended_seconds
        gap = 6.67 * 3600
        assert suspended_seconds(gap, self.POLL) == pytest.approx(gap - self.POLL)

    def test_gap_below_poll_interval_never_goes_negative(self):
        from cron.scheduler import suspended_seconds
        assert suspended_seconds(1.0, self.POLL) == 0.0

    # --- wallclock_exceeded ------------------------------------------------

    def test_the_2026_08_25_incident_no_longer_kills_the_job(self):
        """The exact numbers from the incident must NOT trip the limit."""
        from cron.scheduler import wallclock_exceeded, suspended_seconds
        suspended = suspended_seconds(6.67 * 3600, self.POLL)
        assert wallclock_exceeded(24269.4, suspended, 3600.0) is False

    def test_a_genuine_overrun_still_kills(self):
        """No suspend: the limit must behave exactly as before."""
        from cron.scheduler import wallclock_exceeded
        assert wallclock_exceeded(24269.4, 0.0, 3600.0) is True
        assert wallclock_exceeded(3600.0, 0.0, 3600.0) is True
        assert wallclock_exceeded(3599.0, 0.0, 3600.0) is False

    def test_active_time_past_the_limit_after_a_suspend_still_kills(self):
        """A suspend buys time back, it does not grant immunity."""
        from cron.scheduler import wallclock_exceeded
        # 10h elapsed, 6h of it suspended -> 4h active against a 1h limit.
        assert wallclock_exceeded(36000.0, 21600.0, 3600.0) is True

    def test_unlimited_is_preserved(self):
        from cron.scheduler import wallclock_exceeded
        assert wallclock_exceeded(1e9, 0.0, None) is False

    # --- inactivity_exceeded -----------------------------------------------

    def test_idle_inflated_purely_by_suspend_does_not_kill(self):
        from cron.scheduler import inactivity_exceeded
        assert inactivity_exceeded(24000.0, 24000.0, 600.0) is False

    def test_genuine_idleness_still_kills(self):
        from cron.scheduler import inactivity_exceeded
        assert inactivity_exceeded(700.0, 0.0, 600.0) is True

    def test_idle_beyond_the_suspend_still_kills(self):
        from cron.scheduler import inactivity_exceeded
        # idle 24000s of which 23000s was suspend -> 1000s real idle > 600s
        assert inactivity_exceeded(24000.0, 23000.0, 600.0) is True

    def test_inactivity_never_goes_negative(self):
        from cron.scheduler import inactivity_exceeded
        assert inactivity_exceeded(10.0, 24000.0, 600.0) is False

    def test_inactivity_unlimited_is_preserved(self):
        from cron.scheduler import inactivity_exceeded
        assert inactivity_exceeded(1e9, 0.0, None) is False



# Every test here drives the REAL run_job, which lazily imports the agent and
# MCP machinery (`from tools.mcp_tool import discover_mcp_tools`) and walks the
# plugin manifests. The first test in the process to do that pays the whole
# cold-import tax, and on a loaded host it exceeds the 30s addopts cap — which
# --timeout-method=thread reports as a bare `Timeout (>30.0s)`, easily misread
# as a hang in the poll loop these tests fake. In a full-file run
# TestRunJobSessionPersistence pays it first; under `-k SuspendAware` this class
# does. Same honest-budget mark, and same reason, as TestResolveDeliveryTarget
# above: it hides no failure — every assertion below is unchanged and still
# fails if the wiring breaks.
@pytest.mark.timeout(180)
@pytest.mark.usefixtures("_tick_lock_isolated")
class TestSuspendAwareTimeoutWiring:
    """Covers the poll-loop WIRING, which the pure-helper tests above cannot.

    ``TestSuspendAwareTimeouts`` proves ``suspended_seconds`` /
    ``wallclock_exceeded`` / ``inactivity_exceeded`` behave correctly in
    isolation. It says nothing about whether ``run_job``'s poll loop actually
    FEEDS them the accumulated suspend — reverting either call site to a
    literal ``0.0`` (i.e. restoring the pre-fix "bill raw elapsed" behaviour)
    fails none of those tests.

    The seam is ``concurrent.futures.wait``: the loop's only blocking call, so
    it is where a host suspend surfaces as an oversized poll gap. Faking it
    lets a test jump a fake ``time.monotonic`` across one poll exactly as a
    suspend does, with no real waiting and nothing left running afterwards.

    A previous attempt at this test drove the loop with a patched clock ALONE
    and passed with the fix reverted: the mock agent's future was already done,
    so the loop broke at ``if done:`` on its first poll and never reached
    either watchdog check. Every test here therefore asserts the "poll loop
    stalled" warning (or its absence) as a positive control that the loop
    really ran and really classified the gap.
    """

    SUSPEND = 6.67 * 3600  # the 2026-08-25 fleet-wide gap
    HARD_LIMIT = 3600.0
    IDLE_LIMIT = 600.0

    def _run(self, tmp_path, monkeypatch, caplog, *, gaps,
             hard_timeout, inactivity_timeout, idle_tracks_clock=False,
             activity_resumes_after_poll=None):
        """Drive ``run_job``'s poll loop over a scripted sequence of poll gaps.

        ``gaps`` is one float per poll iteration: the seconds the fake clock
        jumps while that poll is blocked in ``concurrent.futures.wait``. Once
        the script is exhausted the real ``wait`` runs and the (already
        finished) agent future completes the loop normally.

        ``idle_tracks_clock`` makes the agent report idle time measured against
        the same fake clock, which is what a real agent does: its last-activity
        stamp predates a suspend, so raw idle is inflated by the full suspend.
        ``activity_resumes_after_poll`` restamps that last-activity marker to
        NOW once, after the given poll — the agent waking up and doing work.
        """
        monkeypatch.setenv("HERMES_CRON_HARD_TIMEOUT", str(hard_timeout))
        monkeypatch.setenv("HERMES_CRON_TIMEOUT", str(inactivity_timeout))

        # BOTH fakes below are scoped to THIS thread. The agent runs in a
        # worker thread and other subsystems keep background threads alive
        # across tests; an unscoped fake would let one of them consume a
        # scripted gap (silently disarming the test) or read a clock jumped
        # 6.67h forward (expiring deadlines it holds).
        this_thread = threading.current_thread()
        real_monotonic = time.monotonic
        real_wait = concurrent.futures.wait

        # Seeded from the real clock so a value that does escape to another
        # thread is still in the real monotonic domain — and only ever AHEAD
        # of it, which makes a foreign deadline look pending, never expired.
        clock = {"t": real_monotonic()}
        started = clock["t"]
        polls = {"n": 0}
        scripted = list(gaps)

        def fake_monotonic():
            if threading.current_thread() is this_thread:
                return clock["t"]
            return real_monotonic()

        def fake_wait(fs, timeout=None, **kwargs):
            if threading.current_thread() is not this_thread:
                return real_wait(fs, timeout=timeout, **kwargs)
            if polls["n"] < len(scripted):
                clock["t"] += scripted[polls["n"]]
                polls["n"] += 1
                # Report NOT done so the loop reaches the watchdog checks.
                return set(), set(fs)
            polls["n"] += 1
            return real_wait(fs, timeout=timeout, **kwargs)

        monkeypatch.setattr(time, "monotonic", fake_monotonic)
        monkeypatch.setattr(concurrent.futures, "wait", fake_wait)

        job = {"id": "suspend-wiring", "name": "suspend-wiring", "prompt": "hello"}
        agent = MagicMock()
        agent.run_conversation.return_value = {"final_response": "ok"}

        resumed = {"at": None}

        def _activity():
            if (
                activity_resumes_after_poll is not None
                and resumed["at"] is None
                and polls["n"] > activity_resumes_after_poll
            ):
                resumed["at"] = clock["t"]
            since = started if resumed["at"] is None else resumed["at"]
            return {
                "seconds_since_activity": (
                    clock["t"] - since if idle_tracks_clock else 0.0
                ),
                "last_activity_desc": "waiting for non-streaming API response",
                "current_tool": None,
                "api_call_count": 1,
                "max_iterations": 10,
            }

        agent.get_activity_summary.side_effect = _activity

        with patch("cron.scheduler._hermes_home", tmp_path), \
             patch("cron.scheduler._resolve_origin", return_value=None), \
             patch("hermes_cli.env_loader.load_hermes_dotenv"), \
             patch("hermes_cli.env_loader.reset_secret_source_cache"), \
             patch("hermes_state.SessionDB", return_value=MagicMock()), \
             patch(
                 "hermes_cli.runtime_provider.resolve_runtime_provider",
                 return_value={
                     "api_key": "test-key",
                     "base_url": "https://example.invalid/v1",
                     "provider": "openrouter",
                     "api_mode": "chat_completions",
                 },
             ), \
             patch("run_agent.AIAgent") as mock_agent_cls:
            mock_agent_cls.return_value = agent
            with caplog.at_level(logging.WARNING, logger="cron.scheduler"):
                success, output, final_response, error = run_job(job)

        # The loop is the only consumer of the script; if it broke out early
        # (or something else ate a gap) the rest of this test is vacuous.
        assert polls["n"] >= 1, "the poll loop never ran"
        return {
            "success": success,
            "error": error,
            "polls": polls["n"],
            "logs": [r.getMessage() for r in caplog.records],
            "agent": agent,
        }

    @staticmethod
    def _stalled(run):
        return [m for m in run["logs"] if "poll loop stalled" in m]

    # --- wall-clock wiring -------------------------------------------------

    def test_suspend_is_discounted_from_the_wallclock_check(
        self, tmp_path, monkeypatch, caplog,
    ):
        """The loop must charge ACTIVE elapsed, not raw, against the hard limit.

        MUTATION GUARD: replacing ``_suspended_total`` with ``0.0`` in the
        ``wallclock_exceeded(...)`` call fails this test.
        """
        run = self._run(
            tmp_path, monkeypatch, caplog,
            gaps=[self.SUSPEND],
            hard_timeout=self.HARD_LIMIT,
            inactivity_timeout=self.IDLE_LIMIT,
        )
        # Positive control: the loop ran and saw the stall. Without it a green
        # result proves nothing (see the class docstring).
        assert self._stalled(run), run["logs"]
        assert run["success"] is True, run["error"]
        assert run["error"] is None
        run["agent"].interrupt.assert_not_called()

    def test_a_genuine_overrun_still_kills_through_the_loop(
        self, tmp_path, monkeypatch, caplog,
    ):
        """Control for the test above: the harness CAN produce a kill.

        Many sub-threshold gaps are ordinary jitter on a loaded host, are
        charged to the job in full, and must still trip the limit — otherwise
        the previous test's green would only prove the watchdog is inert.
        """
        run = self._run(
            tmp_path, monkeypatch, caplog,
            gaps=[50.0] * 80,  # 4000s of charged time vs a 3600s limit
            hard_timeout=self.HARD_LIMIT,
            inactivity_timeout=self.IDLE_LIMIT,
        )
        assert not self._stalled(run), "sub-threshold gaps are not a suspend"
        assert run["success"] is False
        assert "exceeded wall-clock limit" in (run["error"] or "")
        run["agent"].interrupt.assert_called_once()

    def test_active_time_past_the_limit_still_kills_after_a_suspend(
        self, tmp_path, monkeypatch, caplog,
    ):
        """A suspend buys time back; it does not grant immunity."""
        run = self._run(
            tmp_path, monkeypatch, caplog,
            gaps=[self.SUSPEND] + [50.0] * 80,
            hard_timeout=self.HARD_LIMIT,
            inactivity_timeout=self.IDLE_LIMIT,
        )
        assert self._stalled(run), run["logs"]
        assert run["success"] is False
        assert "exceeded wall-clock limit" in (run["error"] or "")

    def test_timeout_log_reports_active_raw_and_discounted(
        self, tmp_path, monkeypatch, caplog,
    ):
        """The kill line must be self-explaining about a suspend.

        MUTATION GUARD for the SECOND wiring site: the diagnostic
        ``_wc_elapsed = _wc_raw - _suspended_total`` in the timeout branch,
        which is what made the 2026-08-25 kill read as a hung API call.
        """
        with caplog.at_level(logging.ERROR, logger="cron.scheduler"):
            run = self._run(
                tmp_path, monkeypatch, caplog,
                gaps=[self.SUSPEND] + [50.0] * 80,
                hard_timeout=self.HARD_LIMIT,
                inactivity_timeout=self.IDLE_LIMIT,
            )
        kill = [m for m in run["logs"] if "exceeded wall-clock limit" in m]
        assert kill, run["logs"]
        # Three distinct numbers — active, raw, discounted — so a suspend can
        # never again be read off this line as an overrun. Parsed rather than
        # string-matched so the assertion is on the ARITHMETIC: billing raw
        # here would make active == raw while discounted stayed non-zero.
        m = re.search(
            r"active (\S+?)s of (\S+?)s raw; (\S+?)s discounted", kill[0]
        )
        assert m, kill[0]
        active, raw, discounted = (float(x) for x in m.groups())
        assert discounted == pytest.approx(self.SUSPEND - 5.0)
        assert raw - active == pytest.approx(discounted)
        # The kill lands on the first poll past the limit: 5s of active time
        # survived the suspend, then 72 charged 50s gaps.
        assert active == pytest.approx(3605.0)
        assert active < self.SUSPEND < raw

    # --- inactivity wiring -------------------------------------------------

    def test_suspend_is_discounted_from_the_inactivity_check(
        self, tmp_path, monkeypatch, caplog,
    ):
        """The idle watchdog fires FIRST in the loop and inflates the same way.

        MUTATION GUARD: replacing ``_suspend_since_activity`` with ``0.0`` in
        the ``inactivity_exceeded(...)`` call fails this test.
        """
        run = self._run(
            tmp_path, monkeypatch, caplog,
            gaps=[self.SUSPEND],
            hard_timeout=0,  # unlimited: isolate the inactivity path
            inactivity_timeout=self.IDLE_LIMIT,
            idle_tracks_clock=True,
        )
        assert self._stalled(run), run["logs"]
        assert run["success"] is True, run["error"]
        run["agent"].interrupt.assert_not_called()

    def test_a_genuine_stall_still_kills_through_the_loop(
        self, tmp_path, monkeypatch, caplog,
    ):
        """Control: real idleness with no suspend must still trip the limit."""
        run = self._run(
            tmp_path, monkeypatch, caplog,
            gaps=[50.0] * 20,  # 1000s idle vs a 600s limit
            hard_timeout=0,
            inactivity_timeout=self.IDLE_LIMIT,
            idle_tracks_clock=True,
        )
        assert not self._stalled(run), "sub-threshold gaps are not a suspend"
        assert run["success"] is False
        assert "idle for" in (run["error"] or ""), run["error"]

    def test_fresh_activity_retires_the_suspend_credit(
        self, tmp_path, monkeypatch, caplog,
    ):
        """A suspend must not immunise the job against LATER idleness.

        The credit is only valid while the idle reading it inflated is still
        the one being measured. Once the agent does something, the stamp moves
        past the suspend and the credit has to be dropped, or a job that wakes
        up and then genuinely wedges is never killed again for the rest of its
        run.

        MUTATION GUARD: turning ``_suspend_since_activity = 0.0`` into a no-op
        (``+= 0.0``) fails this test and nothing else in the suite.
        """
        run = self._run(
            tmp_path, monkeypatch, caplog,
            gaps=[self.SUSPEND] + [50.0] * 20,
            hard_timeout=0,  # unlimited: isolate the inactivity path
            inactivity_timeout=self.IDLE_LIMIT,
            idle_tracks_clock=True,
            activity_resumes_after_poll=1,  # the agent wakes after the suspend
        )
        assert self._stalled(run), run["logs"]
        assert run["success"] is False, "post-suspend stall must still be killed"
        assert "idle for" in (run["error"] or ""), run["error"]



class TestFailureStreakNudge:
    """Poke-inspired repeated-failure review nudge (_failure_streak_nudge)."""

    def _job(self, streak, kind="cron", name="scout"):
        return {
            "id": "j1",
            "name": name,
            "failure_streak": streak,
            "schedule": {"kind": kind},
        }

    def test_nudges_at_threshold(self):
        from cron.scheduler import _failure_streak_nudge
        # stored streak 2 + this run = 3 >= default threshold 3
        with patch("cron.scheduler.load_config", return_value={}):
            out = _failure_streak_nudge(self._job(2))
        assert "failed 3 runs in a row" in out
        assert "hermes cron pause scout" in out

    def test_silent_below_threshold(self):
        from cron.scheduler import _failure_streak_nudge
        with patch("cron.scheduler.load_config", return_value={}):
            assert _failure_streak_nudge(self._job(0)) == ""
            assert _failure_streak_nudge(self._job(1)) == ""

    def test_oneshot_never_nudges(self):
        from cron.scheduler import _failure_streak_nudge
        with patch("cron.scheduler.load_config", return_value={}):
            assert _failure_streak_nudge(self._job(10, kind="once")) == ""

    def test_config_threshold_and_disable(self):
        from cron.scheduler import _failure_streak_nudge
        cfg5 = {"cron": {"failure_nudge_threshold": 5}}
        with patch("cron.scheduler.load_config", return_value=cfg5):
            assert _failure_streak_nudge(self._job(3)) == ""
            assert "failed 5 runs" in _failure_streak_nudge(self._job(4))
        with patch("cron.scheduler.load_config", return_value={"cron": {"failure_nudge_threshold": 0}}):
            assert _failure_streak_nudge(self._job(50)) == ""

    def test_missing_streak_field_backcompat(self):
        from cron.scheduler import _failure_streak_nudge
        job = {"id": "old", "schedule": {"kind": "interval"}}  # pre-field job
        with patch("cron.scheduler.load_config", return_value={}):
            assert _failure_streak_nudge(job) == ""

    def test_config_load_failure_falls_back(self):
        from cron.scheduler import _failure_streak_nudge
        with patch("cron.scheduler.load_config", side_effect=RuntimeError("boom")):
            assert "failed 3 runs" in _failure_streak_nudge(self._job(2))
