"""Local console policy survives upstream declarative command registration."""
import pytest
from hermes_cli.console_engine import HermesConsoleEngine, _ArgumentParser


def test_hosted_policy_blocks_local_commands_and_unsafe_arguments():
    engine = HermesConsoleEngine(context="hosted")
    assert engine.execute("config set model.default secret", confirmed=True).status == "error"
    assert engine.execute("mcp add local --command python", confirmed=True).status == "error"
    assert engine.execute("plugins install arbitrary", confirmed=True).status == "error"
    assert engine.execute("cron pause example").status == "confirm_required"
    assert "plugins install" not in engine.help_text()


@pytest.mark.parametrize("code,expected", [(0, "ok"), (7, "error")])
def test_handler_exit_is_contained(code, expected):
    engine = HermesConsoleEngine()

    def handler(engine, args):
        raise SystemExit(code)

    engine.register(("probe",), "probe", "probe", handler)
    assert engine.execute("probe").status == expected


def test_parser_help_returns_text_without_exiting():
    engine = HermesConsoleEngine()

    def handler(engine, args):
        parser = _ArgumentParser(prog="probe")
        parser.parse_args(args)
        return ""

    engine.register(("probe",), "probe", "probe", handler)
    result = engine.execute("probe --help")
    assert result.status == "ok"
    assert "usage: probe" in result.output


def test_bare_hermes_uses_upstream_help_result():
    result = HermesConsoleEngine().execute("hermes")
    assert result.status == "ok"
    assert "Supported commands:" in result.output
