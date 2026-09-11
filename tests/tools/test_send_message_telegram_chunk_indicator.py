"""Chunk indicators must be MarkdownV2-escaped on the standalone send path.

``tools.send_message_tool._send_telegram`` formats a message to MarkdownV2 and
then chunks it with ``BasePlatformAdapter.truncate_message``, which appends a
raw ``" (1/2)"`` suffix *after* escaping has run.  Telegram then rejects the
chunk with::

    Can't parse entities: character '(' is reserved and must be escaped
    with the preceding '\\'

and the send falls back to plain text, losing all formatting and burning a
retry against Telegram's flood limit.

The in-gateway adapter (``plugins.platforms.telegram.adapter``) already escapes
the indicator after chunking; this standalone path is a second copy that did
not.  Measured 2026-09-02: a 4,221-char TelegramNotifier batch produced exactly
two chunks and exactly two parse failures one second apart.

The send is intercepted at ``_send_telegram_message_with_retry`` -- the seam
where a chunk's final text reaches the Bot API.  Patching ``telegram.Bot``
itself is not viable: replacing the class with a ``MagicMock`` raises
"metaclass conflict" because it gets subclassed downstream.
"""

import re

import pytest

BS = chr(92)

# " (1/2)" with both parens backslash-escaped, anchored at end of chunk.
ESCAPED_INDICATOR_RE = re.compile(r" \\\(\d+/\d+\\\)$")
# A trailing "(1/2)" whose opening paren is NOT preceded by a backslash.
BARE_INDICATOR_RE = re.compile(r"(?<!\\)\(\d+/\d+\)$")

# Shape-valid token so telegram.Bot() constructs without network access.
FAKE_TOKEN = "123456:AAHfake-token-for-tests-only-0123456789"


def _long_markdown_message(n_lines: int = 200) -> str:
    """A message that exceeds Telegram's 4096-unit cap once formatted."""
    body = chr(10).join("Event %d: job finished ok" % i for i in range(n_lines))
    return "Batched (7 events):" + chr(10) + body


@pytest.fixture
def captured_sends(monkeypatch):
    """Intercept every chunk at the Bot API seam and record its text."""
    from tools import send_message_senders as send_message_tool

    sent_texts = []

    async def _fake_retry(bot, *, attempts=3, **kwargs):
        sent_texts.append(kwargs["text"])

        class _Msg:
            message_id = len(sent_texts)

        return _Msg()

    monkeypatch.setattr(
        send_message_tool, "_send_telegram_message_with_retry", _fake_retry
    )
    return sent_texts


@pytest.mark.asyncio
async def test_standalone_send_escapes_chunk_indicator(captured_sends):
    """Every chunk's (N/M) suffix must be escaped before it reaches Telegram."""
    from tools import send_message_senders as send_message_tool

    await send_message_tool._send_telegram(
        token=FAKE_TOKEN, chat_id="123", message=_long_markdown_message()
    )

    assert len(captured_sends) > 1, "message should have been split into chunks"

    for idx, text in enumerate(captured_sends):
        assert not BARE_INDICATOR_RE.search(text), (
            "chunk %d ends with an UNESCAPED (N/M) indicator, which Telegram "
            "rejects: %r" % (idx + 1, text[-40:])
        )
        assert ESCAPED_INDICATOR_RE.search(text), (
            "chunk %d is missing an escaped (N/M) indicator: %r"
            % (idx + 1, text[-40:])
        )


@pytest.mark.asyncio
async def test_html_mode_indicator_is_not_backslash_escaped(captured_sends):
    """HTML parse mode must NOT get MarkdownV2 backslashes in its indicator.

    Guards the fix from over-reaching: a backslash is a literal character in
    HTML mode, so escaping there would corrupt the visible text.
    """
    from tools import send_message_senders as send_message_tool

    # A recognized Telegram HTML tag forces the HTML branch.
    body = chr(10).join("<b>Event %d</b> finished ok" % i for i in range(300))

    await send_message_tool._send_telegram(
        token=FAKE_TOKEN, chat_id="123", message=body
    )

    assert len(captured_sends) > 1
    for text in captured_sends:
        assert BS + "(" not in text, (
            "HTML-mode chunk must not contain MarkdownV2 backslash escapes: %r"
            % (text[-40:],)
        )


@pytest.mark.asyncio
async def test_single_chunk_message_gets_no_indicator(captured_sends):
    """A message that fits in one chunk must be sent unchanged (no suffix)."""
    from tools import send_message_senders as send_message_tool

    await send_message_tool._send_telegram(
        token=FAKE_TOKEN, chat_id="123", message="Short message (with parens)"
    )

    assert len(captured_sends) == 1
    assert not BARE_INDICATOR_RE.search(captured_sends[0])
    assert not ESCAPED_INDICATOR_RE.search(captured_sends[0])
    # The body's own parens are still escaped by format_message.
    assert BS + "(with parens" + BS + ")" in captured_sends[0]
