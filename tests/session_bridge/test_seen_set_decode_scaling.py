from __future__ import annotations

import time

import pytest

from session_bridge.coordinator import _decode_native_id_set_state


def _state(native_ids: list[str]) -> dict[str, object]:
    return {"version": 1, "native_ids": native_ids}


def _ids(count: int, *, prefix: str = "id") -> list[str]:
    return [f"{prefix}-{index:08d}" for index in range(count)]


# --- semantics: these pass before AND after the fix, and exist to prove the
# --- optimisation did not change behaviour. They are not the regression guard.


def test_order_is_preserved_exactly() -> None:
    ids = ["zeta", "alpha", "middle", "beta"]
    assert _decode_native_id_set_state(_state(ids), label="t") == ids


def test_duplicate_still_raises() -> None:
    with pytest.raises(RuntimeError, match="invalid t state"):
        _decode_native_id_set_state(_state(["a", "b", "a"]), label="t")


def test_duplicate_raises_even_when_far_apart() -> None:
    """The duplicate check must still see the whole prefix, not a window."""
    ids = _ids(500) + ["id-00000000"]
    with pytest.raises(RuntimeError, match="invalid t state"):
        _decode_native_id_set_state(_state(ids), label="t")


@pytest.mark.parametrize(
    "bad",
    [
        [" leading"],
        ["trailing "],
        [""],
        [1234],
    ],
)
def test_per_element_validation_unchanged(bad: list[object]) -> None:
    with pytest.raises(RuntimeError, match="invalid t state"):
        _decode_native_id_set_state(_state(bad), label="t")  # type: ignore[arg-type]


def test_empty_and_absent_states() -> None:
    assert _decode_native_id_set_state(None, label="t") == []
    assert _decode_native_id_set_state(_state([]), label="t") == []


# --- the actual regression guard ---


def _best_of_three(count: int) -> float:
    """Fastest of three runs. `min` is deliberate: a load spike can only ever
    make a sample slower, so the minimum is the sample least contaminated by
    whatever else this box is doing."""
    ids = _ids(count)
    state = _state(ids)
    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        _decode_native_id_set_state(state, label="t")
        best = min(best, time.perf_counter() - started)
    return best


def test_decode_is_not_quadratic_in_the_seen_set_size() -> None:
    """Quadrupling the input must not ~16x the cost.

    WHY THIS IS A SCALING TEST AND NOT AN ASSERTION ABOUT BEHAVIOUR: the fix
    this guards is a pure performance change -- the decode returns the same
    list, in the same order, and raises on exactly the same inputs as before.
    No correctness assertion can fail without it, so the only property that
    distinguishes fixed from broken is algorithmic complexity.

    WHY A RATIO AND NOT A WALL-CLOCK CEILING: this suite has a documented
    history of load-dependent wall-clock flakes, and an absolute threshold
    encodes this machine's speed. A ratio cancels both -- uniform load and
    slower hardware scale the two measurements together. Combined with
    best-of-three it takes a spike landing on exactly one arm to fool it.

    THE NUMBERS: measured 2026-09-03 against the live codex seen-set shape,
    the pre-fix list-membership decode ran 220.8 ms at n=4352, 1312.7 ms at
    n=10000 and 4717.5 ms at n=20000 -- ~4x per doubling, i.e. ~16x per
    quadrupling. The set-membership decode ran 2.0-19 ms across the same
    range. So a 4x input increase costs ~4x linear versus ~16x quadratic, and
    the bound below sits between them with room on both sides.
    """

    small = _best_of_three(3_000)
    large = _best_of_three(12_000)

    # Guard against a divide-by-zero on an implausibly fast clock, and against
    # asserting on timings too small to be meaningful.
    if small < 1e-4:
        pytest.skip("decode too fast to time reliably on this machine")

    ratio = large / small
    assert ratio < 8.0, (
        f"decode scaling looks quadratic: 4x the input cost {ratio:.1f}x the "
        f"time ({small * 1000:.1f} ms at n=3000 -> {large * 1000:.1f} ms at "
        f"n=12000). Linear is ~4x; the pre-2026-09-03 list-membership "
        f"duplicate check was ~16x. This decode runs on the asyncio event "
        f"loop, so a regression here starves the static /health route."
    )
