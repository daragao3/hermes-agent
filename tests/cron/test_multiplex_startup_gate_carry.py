"""A desktop scheduler must not recover or heartbeat a gateway-owned store."""
from unittest.mock import patch


def test_deferred_profile_is_untouched_until_admitted(tmp_path):
    from cron.scheduler_provider import InProcessCronScheduler

    home = tmp_path / "profile"
    home.mkdir()
    events = []

    class Stop:
        cycles = 0

        def is_set(self):
            return self.cycles == 3

        def wait(self, seconds):
            self.cycles += 1

    stop = Stop()

    def gate(name, path):
        events.append(("gate", stop.cycles))
        if stop.cycles == 0:
            assert list(home.iterdir()) == []
            assert recover.call_count == 0
            return False
        return True

    def tick(**kwargs):
        events.append(("tick", stop.cycles))
        assert recover.call_count == 1

    provider = InProcessCronScheduler()
    with patch.object(provider, "recover_interrupted", return_value=0) as recover:
        with patch("cron.scheduler.tick", side_effect=tick):
            provider.start(stop, interval=0, profile_homes=[("profile", home)], profile_gate=gate)

    assert recover.call_count == 1
    assert events == [("gate", 0), ("gate", 1), ("tick", 1), ("gate", 2), ("tick", 2)]
    assert (home / "cron" / "ticker_last_success").exists()
