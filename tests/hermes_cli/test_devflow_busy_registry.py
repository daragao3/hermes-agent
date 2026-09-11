"""DevFlow control commands must remain reachable during an active turn."""
from hermes_cli.commands import is_interrupt_then_dispatch, resolve_command, should_bypass_active_session


def test_devflow_lifecycle_commands_dispatch_without_interrupting_active_turn():
    for name in ("ddp-approve", "ddp-decline", "ddp-approve-confirm", "ddp-decline-confirm", "devflow-login"):
        command = resolve_command(name)
        assert command is not None and command.busy_policy == "dispatch"
        for spelling in (name, *command.aliases):
            assert should_bypass_active_session(spelling)
            assert not is_interrupt_then_dispatch(spelling)
