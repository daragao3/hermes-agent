"""Platform adapters for messaging integrations (receive, send, auth, media)."""

from .base import BasePlatformAdapter, SendResult
from .event import MessageEvent

__all__ = ["BasePlatformAdapter", "MessageEvent", "SendResult"]


def __getattr__(name):
    if name == "QQAdapter":
        from .qqbot import QQAdapter  # noqa: F401
        return QQAdapter
    if name == "YuanbaoAdapter":
        from .yuanbao import YuanbaoAdapter  # noqa: F401
        return YuanbaoAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ += ["QQAdapter", "YuanbaoAdapter"]  # noqa: F822 - lazy compatibility exports
