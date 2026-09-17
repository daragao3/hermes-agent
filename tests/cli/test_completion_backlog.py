"""Completion backlogs preserve results without multiplying autonomous turns."""
import pytest

from evals.completion_backlog_probe import probe
from tests.timeout_budget import scaled

# Backstop only: each test drives the probe across 3 surfaces x several scenarios, spawning
# ~100 real interpreter children in total (24 s alone here; well past the suite-wide 30 s
# cap under the parallel runner's load). Same shape as the other real-process tests.
pytestmark = pytest.mark.timeout(scaled(300))


def test_ready_completions_share_one_turn_across_interactive_routes(tmp_path):
    for surface in ("cli", "poller", "post-turn"):
        for scenario in ("backlog", "single", "mixed"):
            result = probe(surface, scenario, tmp_path / surface / scenario)
            assert result["wire_turns"] == (5 if scenario == "mixed" else 1), result
            assert result["payload_order"] == sorted(result["payload_order"]), result
            if scenario == "mixed":
                assert result["delegation_delivered_once"], result
            assert result["all_payloads_preserved"], result
            if scenario == "single":
                assert result["single_exact"], result


def test_consumed_or_foreign_completions_never_start_a_turn(tmp_path):
    for surface in ("cli", "poller", "post-turn"):
        for scenario in ("consumed", "foreign"):
            result = probe(surface, scenario, tmp_path / surface / scenario)
            assert result["wire_turns"] == 0, result
            if scenario == "foreign":
                assert result["queue_remaining"] == result["children"], result
