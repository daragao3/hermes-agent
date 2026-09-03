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
    """Decoding 20,000 ids must not take anywhere near a second.

    WHY A TIMING TEST AT ALL: the fix this guards is a pure performance change
    -- the decode returns the same list, in the same order, and raises on
    exactly the same inputs as before. No correctness assertion can fail
    without it, so complexity is the only property that separates fixed from
    broken. The eight semantics tests above deliberately pass either way.

    WHY AN ABSOLUTE CEILING AND NOT A SCALING RATIO -- learned the hard way on
    2026-09-03. The first version of this test asserted that quadrupling the
    input must not more than 8x the cost, reasoning that a ratio cancels
    machine speed and background load. That reasoning was sound and beside the
    point: at n=3000 the fixed decode runs in about 1 ms, where constant
    overhead and allocator noise dominate, so the FIXED implementation's own
    ratio was measured at 4.0, 4.0, 4.3, 5.2, 5.7 and 5.9 across six trials --
    and 8.4 on the run that failed CI. The bound had no margin. The dominant
    noise was small-n timing variance, not machine speed, so the ratio
    cancelled the wrong variable.

    An absolute ceiling at a LARGER n has the margin the ratio never did.
    Measured on this box: fixed 8.8-11.4 ms at n=20000 (best of three);
    the pre-fix list-membership decode 4535 ms. A 1.5 s ceiling therefore sits
    132x above the fixed implementation and 3x below the broken one. It takes a
    132x slowdown of a pure-CPU loop to produce a false positive, which is a
    different universe from the ~2x headroom the ratio had.
    """

    elapsed = _best_of_three(20_000)

    assert elapsed < 1.5, (
        f"decoding 20,000 ids took {elapsed * 1000:.0f} ms; the set-membership "
        f"implementation does this in ~10 ms and the pre-2026-09-03 "
        f"list-membership duplicate check took ~4535 ms. This decode runs on "
        f"the asyncio event loop, so a regression here starves the static "
        f"/health route and the launcher tears the service down on a single "
        f"over-budget probe."
    )
