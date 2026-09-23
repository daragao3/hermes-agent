"""A notifier batch is sent as single-message pages; a failed page requeues only what was not sent.

2026-09-22 22:18-22:50: a 20-event ~10.7 KB batch went out as ONE message that the sender split into
three 4096-char chunks; each "Timed out" requeued the whole batch, so chunk 1 was re-posted to the
topic on every 3-minute retry.
"""

from events.batch_observations import render_batch
from events.subscribers import telegram_notifier as tn


def _items(n, size=400):
    return [f"event {i} " + "x" * size for i in range(n)]


def test_pages_cover_everything_in_order_within_budget():
    items = _items(20)
    pages = tn._batch_pages(items, {}, None)
    assert pages[0][0] == 0 and pages[-1][1] == 20
    assert all(a[1] == b[0] for a, b in zip(pages, pages[1:]))
    assert len(pages) > 1
    for start, end in pages:
        assert len(render_batch(items[start:end], {}, None)[0]) <= tn.BATCH_PAGE_CHAR_BUDGET


def test_an_oversized_single_item_is_its_own_page():
    items = ["small", "y" * 9000, "small2"]
    assert tn._batch_pages(items, {}, None) == [(0, 1), (1, 2), (2, 3)] or \
        tn._batch_pages(items, {}, None)[1] == (1, 2)


def _notifier(monkeypatch, outcomes):
    n = tn.TelegramNotifier.__new__(tn.TelegramNotifier)
    n._batch_buffer, n._batch_metadata = {}, {}
    n._batch_timestamps, n._batch_started_at, n._batch_retry_at = {}, {}, {}
    n._latest_observations = {}
    sent = []

    def deliver(chat_id, thread_id, text, **kw):
        ok = outcomes.pop(0) if outcomes else True
        if ok:
            sent.append(kw["batch_count"])
        return ok

    monkeypatch.setattr(n, "_deliver", deliver, raising=False)
    monkeypatch.setattr(n, "_thread_id_to_key", lambda t: t, raising=False)
    monkeypatch.setattr(n, "_persist_batch_buffer", lambda: None, raising=False)
    return n, sent


def test_failure_requeues_only_unsent_pages(monkeypatch):
    items = _items(20)
    n, sent = _notifier(monkeypatch, [True, False])
    n._batch_buffer["-100:9631"] = list(items)
    n._batch_metadata["-100:9631"] = list(items)
    n._flush_batch_key("-100:9631")
    first_page = sent[0]
    assert len(sent) == 1
    assert n._batch_buffer["-100:9631"] == items[first_page:]
    assert n._batch_metadata["-100:9631"] == items[first_page:]


def test_full_success_clears_the_key(monkeypatch):
    n, sent = _notifier(monkeypatch, [])
    n._batch_buffer["k:1"] = _items(20)
    n._batch_metadata["k:1"] = _items(20)
    n._batch_retry_at["k:1"] = 1.0
    n._flush_batch_key("k:1")
    assert sum(sent) == 20 and "k:1" not in n._batch_buffer and "k:1" not in n._batch_retry_at
