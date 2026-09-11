"""Safe Hermes Console command engine."""

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import contextvars
import logging
import threading
from urllib.parse import urlparse
import contextlib
import difflib
import functools
import importlib
import io
import json
import sys
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable, Literal, NoReturn, Sequence

from tools.ansi_strip import strip_ansi as _strip_ansi


ConsoleStatus = Literal["ok", "error", "confirm_required", "exit", "clear"]


logger = logging.getLogger(__name__)

ConsoleContext = Literal["local", "hosted"]

ALL_CONTEXTS: frozenset[ConsoleContext] = frozenset({"local", "hosted"})

LOCAL_CONTEXTS: frozenset[ConsoleContext] = frozenset({"local"})

EXPECTED_HOSTED_PATHS: tuple[tuple[str, ...], ...] = (
    ("status",),
    ("doctor",),
    ("logs",),
    ("version",),
    ("prompt-size",),
    ("insights",),
    ("security", "audit"),
    ("portal", "info"),
    ("portal", "tools"),
    ("send",),
    ("config", "show"),
    ("config", "path"),
    ("config", "env-path"),
    ("config", "check"),
    ("config", "migrate"),
    ("config", "set"),
    ("sessions", "list"),
    ("sessions", "stats"),
    ("sessions", "export"),
    ("sessions", "rename"),
    ("sessions", "optimize"),
    ("sessions", "repair"),
    ("cron", "list"),
    ("cron", "status"),
    ("cron", "create"),
    ("cron", "edit"),
    ("cron", "pause"),
    ("cron", "resume"),
    ("cron", "run"),
    ("cron", "remove"),
    ("cron", "tick"),
    ("profile",),
    ("profile", "list"),
    ("profile", "show"),
    ("profile", "info"),
    ("tools", "list"),
    ("tools", "enable"),
    ("tools", "disable"),
    ("tools", "post-setup"),
    ("skills", "browse"),
    ("skills", "search"),
    ("skills", "inspect"),
    ("skills", "list"),
    ("skills", "check"),
    ("skills", "list-modified"),
    ("skills", "diff"),
    ("skills", "install"),
    ("skills", "update"),
    ("skills", "audit"),
    ("skills", "uninstall"),
    ("skills", "reset"),
    ("skills", "opt-in"),
    ("skills", "opt-out"),
    ("skills", "repair-official"),
    ("skills", "snapshot", "export"),
    ("skills", "tap", "list"),
    ("mcp", "list"),
    ("mcp", "catalog"),
    ("mcp", "test"),
    ("mcp", "add"),
    ("mcp", "remove"),
    ("mcp", "install"),
    ("mcp", "login"),
    ("mcp", "reauth"),
    ("mcp", "configure"),
    ("mcp", "picker"),
    ("memory", "status"),
    ("auth", "list"),
    ("auth", "status"),
    ("auth", "reset"),
    ("auth", "spotify", "status"),
    ("pairing", "list"),
    ("pairing", "approve"),
    ("pairing", "revoke"),
    ("pairing", "clear-pending"),
    ("webhook", "list"),
    ("webhook", "subscribe"),
    ("webhook", "remove"),
    ("webhook", "test"),
)

HOSTED_CONFIG_ALLOWED_PREFIXES = (
    "display.",
    "ui.",
    "tts.",
    "voice.",
    "speech.",
    "sessions.",
    "cron.",
)

HOSTED_CONFIG_ALLOWED_KEYS = {
    "display.interface",
}

HOSTED_CONFIG_BLOCKED_PREFIXES = (
    "auth.",
    "dashboard.",
    "gateway.",
    "managed.",
    "model.",
    "portal.",
    "provider.",
    "providers.",
    "tool_gateway.",
    "custom_providers.",
    "mcp_servers.",
)

HOSTED_CONFIG_BLOCKED_NAMES = {
    "portal_url",
    "portal.url",
    "portal.base_url",
    "inference_url",
    "inference.url",
    "inference.base_url",
    "nous.portal_url",
    "nous.inference_url",
    "openrouter_api_key",
    "openai_api_key",
    "anthropic_api_key",
}

_CONSOLE_RUN_EXECUTOR_MAX_WORKERS = 2
_console_run_executor: concurrent.futures.ThreadPoolExecutor | None = None

_console_run_executor_lock = threading.Lock()



class ConsoleCommandError(RuntimeError):
    """User-facing console command failure."""


class _ConsoleParserExit(ConsoleCommandError):
    """Raised when an argparse parser would have called ``sys.exit()``.

    argparse terminates the process (via ``parser.exit()`` -> ``sys.exit()``)
    for ``--help``/``--version`` and a few internal paths. In the dashboard the
    console runs inside a worker thread whose ``SystemExit`` escapes the asyncio
    Task and tears down the whole uvicorn process. ``_ArgumentParser.exit()``
    raises this instead so the line can be surfaced at the prompt.

    Subclasses :class:`ConsoleCommandError` so any code path that already only
    catches ``ConsoleCommandError`` still contains it (never reaching
    ``sys.exit``); ``execute()`` special-cases it to render ``--help`` output as
    a normal result rather than an error.
    """

    def __init__(self, message: str, *, code: int = 0):
        super().__init__(message)
        self.code = code



@dataclass(frozen=True)
class ConsoleResult:
    status: ConsoleStatus
    output: str = ""
    command: str = ""
    confirmation_message: str = ""


@dataclass(frozen=True)
class ConsoleCommand:
    path: tuple[str, ...]
    usage: str
    summary: str
    handler: Callable[["HermesConsoleEngine", list[str]], str]
    mutating: bool = False
    confirmation: str = ""
    contexts: frozenset[ConsoleContext] = LOCAL_CONTEXTS



class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:  # pragma: no cover - argparse hook
        raise ConsoleCommandError(f"{self.prog}: {message}")

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        # argparse calls exit() for --help/--version and some terminal paths.
        # The default implementation calls sys.exit(), which would raise
        # SystemExit out of the console worker thread and — because SystemExit
        # is a BaseException, not an Exception — sail past the dashboard's
        # `except Exception` guard, escape the asyncio Task, and tear down the
        # uvicorn event loop (killing the whole dashboard). Convert it to a
        # catchable console error carrying whatever help/usage/version text
        # argparse buffered via _print_message below. Mirrors error(), which
        # already keeps parse failures from reaching sys.exit().
        buffered = getattr(self, "_console_output_buffer", "")
        text = (buffered + (message or "")).strip()
        raise _ConsoleParserExit(text, code=int(status or 0))

    def _print_message(self, message: str, file: object | None = None) -> None:
        # argparse routes help/usage/version text through _print_message on its
        # way to stdout/stderr. The web console never surfaces the process's own
        # stdout, so capture the text onto the parser instead; exit() (above)
        # then returns it to the prompt.
        if message:
            self._console_output_buffer = (
                getattr(self, "_console_output_buffer", "") + message
            )



def _capture_output(fn: Callable[[], object]) -> str:
    stdout, stderr = io.StringIO(), io.StringIO()
    code, message = 0, ""
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = fn()
            if isinstance(result, int) and result:
                raise SystemExit(result)
        except SystemExit as exc:
            # sys.exit("msg") carries the message as exc.code (not an int); int() on it would
            # raise ValueError past execute()'s handler and crash the REPL.
            if isinstance(exc.code, str):
                message, code = exc.code, 1
            else:
                code = int(exc.code or 0)
        except ConsoleCommandError:
            raise
        except RuntimeError as exc:
            # Fail-closed config write guards raise RuntimeError; surface it as a console error
            # instead of killing the REPL / websocket session.
            message, code = str(exc), 1
    text = stdout.getvalue() + stderr.getvalue()
    if code:
        raise ConsoleCommandError(
            message.strip() or text.strip() or f"Command exited with status {code}")
    return text.rstrip()


def _is_status_footer_rule(line: str) -> bool:
    stripped = _strip_ansi(line).strip()
    return len(stripped) >= 8 and set(stripped.replace("\u2500", "-")) <= {"-"}


def _drop_trailing_blank(lines: list[str]) -> None:
    while lines and not _strip_ansi(lines[-1]).strip():
        lines.pop()


def _strip_console_status_footer(text: str) -> str:
    lines = text.splitlines()
    _drop_trailing_blank(lines)
    if len(lines) < 2:
        return text.rstrip()
    last, prev = (_strip_ansi(lines[i]).strip() for i in (-1, -2))
    if not (prev.startswith("Run 'hermes doctor'") and last.startswith("Run 'hermes setup'")):
        return text.rstrip()
    lines = lines[:-2]
    _drop_trailing_blank(lines)
    if lines and _is_status_footer_rule(lines[-1]):
        lines.pop()
    return "\n".join(lines).rstrip()


def _table_summary(summary: str, *, limit: int = 76) -> str:
    summary = " ".join(summary.split())
    return summary if len(summary) <= limit else f"{summary[: limit - 3].rstrip()}..."


def _split_line(line: str) -> list[str]:
    # Windows-safe splitter: plain shlex posix=True eats backslashes in paths.
    # See #78293.
    # See #83934.
    from hermes_cli._subprocess_compat import split_command_line
    try:
        return split_command_line(line)
    except ValueError as exc:
        raise ConsoleCommandError(f"Could not parse command: {exc}") from exc


_SHELL_TOKENS = {"|", "||", "&", "&&", ";", ">", ">>", "<", "<<", "2>", "2>>"}


def _contains_shell_syntax(line: str, tokens: Sequence[str]) -> bool:
    return (
        "$(" in line or "`" in line
        or any(token in _SHELL_TOKENS for token in tokens)
        or any(ch in line for ch in "|<>;"))


def _format_sessions(sessions: Sequence[dict]) -> str:
    if not sessions:
        return "No sessions found."
    lines = [f"{'ID':<32} {'Source':<12} {'Msgs':>5}  Title / Preview", "-" * 82]
    for session in sessions:
        sid = str(session.get("id") or "")[:32]
        source = str(session.get("source") or "-")[:12]
        messages = session.get("message_count") or 0
        title = str(session.get("title") or session.get("preview") or "").replace("\n", " ")[:60]
        lines.append(f"{sid:<32} {source:<12} {messages:>5}  {title}")
    return "\n".join(lines)


def _format_job(job: dict, action: str) -> str:
    from cron.jobs import effective_job_state
    job_id = job.get("id") or job.get("job_id") or "?"
    return f"{action} job: {job.get('name') or '(unnamed)'} ({job_id}) [{effective_job_state(job)}]"


def _clean_summary(text: str | None) -> str:
    if not text or text is argparse.SUPPRESS:
        return ""
    summary = " ".join(str(text).split())
    return "" if summary.startswith("Run `hermes ") else summary


def _choice_help(action: argparse._SubParsersAction, name: str) -> str:
    for choice in action._choices_actions:
        help_text = choice.help if name in (choice.dest, choice.metavar) else None
        if help_text and help_text is not argparse.SUPPRESS:
            return str(help_text)
    return ""


def _summaries_from_parser(parser: argparse.ArgumentParser) -> dict[tuple[str, ...], str]:
    """``{subcommand path: help}`` over the whole tree; choice help beats child description."""
    summaries: dict[tuple[str, ...], str] = {}

    def walk(current: argparse.ArgumentParser, path: tuple[str, ...]) -> None:
        for action in current._actions:
            if not isinstance(action, argparse._SubParsersAction):
                continue
            for name, child in action.choices.items():
                child_path = (*path, name)
                summary = _clean_summary(_choice_help(action, name)) or _clean_summary(
                    child.description)
                if summary:
                    summaries.setdefault(child_path, summary)
                walk(child, child_path)

    walk(parser, ())
    return summaries


def _noop_console_command(_args: argparse.Namespace) -> None:
    return None


@dataclass(frozen=True)
class _CliSurface:
    """How a CLI subcommand module hangs its argparse tree off a root subparsers action.
    ``extracted``: ``builder(subparsers, <handler>=fn)``, fn from hermes_cli.main.
    ``registered``: ``register(subparsers.add_parser(root))``, optional module ``handler``.
    ``builder``: ``top = builder(subparsers)``, func from hermes_cli.main.
    ``adder``: self-wiring."""
    kind: Literal["extracted", "registered", "builder", "adder"]
    module: str
    builder: str
    handler: str | None = None

    def build(self, root: str, *, live: bool) -> _ArgumentParser:
        """Build a throwaway parser; ``live=False`` wires no-op handlers (summary extraction)."""
        parser = _ArgumentParser(prog="hermes", add_help=False)
        subparsers = parser.add_subparsers(dest="_console_command")
        module = importlib.import_module(self.module)
        entry = getattr(module, self.builder)
        main_handler = (
            (lambda: getattr(importlib.import_module("hermes_cli.main"), self.handler))
            if live else (lambda: _noop_console_command))
        if self.kind == "extracted":
            entry(subparsers, **{self.handler: main_handler()})
        elif self.kind == "registered":
            top_parser = subparsers.add_parser(root)
            entry(top_parser)
            if live and self.handler:
                top_parser.set_defaults(func=getattr(module, self.handler))
        elif self.kind == "builder":
            top_parser = entry(subparsers)
            if live:
                top_parser.set_defaults(func=main_handler())
        else:
            entry(subparsers)
        return parser


# Memoized: the surface is process-static, but the dashboard opens a fresh engine per
# /api/console connection and would otherwise re-import + re-parse it on every reconnect.
@functools.lru_cache(maxsize=None)
def _surface_summaries(surface: _CliSurface, root: str) -> dict[tuple[str, ...], str]:
    try:
        return _summaries_from_parser(surface.build(root, live=False))
    except Exception:
        return {}


def _dispatch(
    surface: _CliSurface,
    root: str,
    fixed: Sequence[str],
    args: Sequence[str],
    namespace_update: Callable[[argparse.Namespace], None] | None = None) -> str:
    namespace = surface.build(root, live=True).parse_args([root, *fixed, *args])
    if namespace_update:
        namespace_update(namespace)
    func = getattr(namespace, "func", None)
    if not callable(func):
        raise ConsoleCommandError("No handler is available for that console command.")
    return _capture_output(lambda: func(namespace))


def _paths(spec: str) -> list[tuple[tuple[str, ...], bool]]:
    """``"list, *snapshot export"`` -> ``[(("list",), False), (("snapshot", "export"), True)]``;
    ``*`` marks a mutating path, ``.`` is the bare root."""
    items = [item.strip() for item in spec.split(",") if item.strip()]
    return [
        (() if item.lstrip("*") == "." else tuple(item.lstrip("*").split()), item.startswith("*"))
        for item in items]


def _sub(module: str, builder: str, handler: str) -> _CliSurface:
    return _CliSurface("extracted", f"hermes_cli.subcommands.{module}", builder, handler)


def _reg(module: str, handler: str | None = None) -> _CliSurface:
    return _CliSurface("registered", f"hermes_cli.{module}", "register_cli", handler)


# root -> (surface, subcommand paths as a ``_paths`` spec). Registered in this order.
_CLI_FAMILIES: dict[str, tuple[_CliSurface, str]] = {
    "dump": (_sub("dump", "build_dump_parser", "cmd_dump"), "."),
    "debug": (_sub("debug", "build_debug_parser", "cmd_debug"), "*share, *delete"),
    "prompt-size": (_sub("prompt_size", "build_prompt_size_parser", "cmd_prompt_size"), "."),
    "insights": (_sub("insights", "build_insights_parser", "cmd_insights"), "."),
    "security": (_sub("security", "build_security_parser", "cmd_security"), "audit"),
    "backup": (_sub("backup", "build_backup_parser", "cmd_backup"), "*."),
    "import": (_sub("import_cmd", "build_import_cmd_parser", "cmd_import"), "*."),
    "config": (_sub("config", "build_config_parser", "cmd_config"), "env-path, check"),
    "tools": (
        _sub("tools", "build_tools_parser", "cmd_tools"),
        "list, *enable, *disable, *post-setup"),
    "plugins": (
        _sub("plugins", "build_plugins_parser", "cmd_plugins"),
        "list, *enable, *disable, *install, *update, *remove"),
    "skills": (
        _sub("skills", "build_skills_parser", "cmd_skills"),
        "browse, search, inspect, list, check, list-modified, diff, *install, *update, *audit, "
        "*uninstall, *reset, *opt-in, *opt-out, *repair-official, *snapshot export, "
        "*snapshot import, tap list, *tap add, *tap remove"),
    "mcp": (
        _sub("mcp", "build_mcp_parser", "cmd_mcp"),
        "list, catalog, test, *add, *remove, *install, *login, *reauth, *configure, *picker"),
    "memory": (_sub("memory", "build_memory_parser", "cmd_memory"), "status, *off, *reset"),
    "auth": (
        _sub("auth", "build_auth_parser", "cmd_auth"),
        "list, status, *reset, *priority, *refresh, *add, *remove, *logout, spotify status, *spotify login, "
        "*spotify logout"),
    "pairing": (
        _sub("pairing", "build_pairing_parser", "cmd_pairing"),
        "list, *approve, *revoke, *clear-pending"),
    "webhook": (
        _sub("webhook", "build_webhook_parser", "cmd_webhook"),
        "list, *subscribe, *remove, test"),
    "hooks": (_sub("hooks", "build_hooks_parser", "cmd_hooks"), "list, *test, *doctor, *revoke"),
    "slack": (_sub("slack", "build_slack_parser", "cmd_slack"), "manifest"),
    "profile": (
        _sub("profile", "build_profile_parser", "cmd_profile"),
        "list, show, info, *create, *use, *describe, *rename, *delete, *export, *import, "
        "*install, *update"),
    "cron": (_sub("cron", "build_cron_parser", "cmd_cron"), "*create, *edit, *remove, *tick"),
    "portal": (_CliSurface("adder", "hermes_cli.portal_cli", "add_parser"), "info, tools"),
    "project": (
        _CliSurface("builder", "hermes_cli.projects_cmd", "build_parser", "cmd_project"),
        "list, show, *create, *add-folder, *remove-folder, *rename, *set-primary, *use, "
        "*archive, *restore, *bind-board"),
    "kanban": (
        _CliSurface("builder", "hermes_cli.kanban", "build_parser", "cmd_kanban"),
        "*init, boards list, *boards create, *boards rm, *boards switch, boards current, "
        "*boards rename, *boards set-workdir, *create, list, show, *assign, *reclaim, *reassign, "
        "diagnose, *link, *unlink, *claim, *comment, *complete, *edit, *block, *schedule, "
        "*unblock, *promote, *archive, stats, runs, heartbeat, assignments, context"),
    "bundles": (_reg("bundles", "bundles_command"), "list, show, *create, *delete, *reload"),
    "checkpoints": (_reg("checkpoints"), "status, list, *prune, *clear, *clear-legacy"),
    "curator": (
        _reg("curator"),
        "status, *run, *pause, *resume, *pin, *unpin, *restore, list-archived, *archive, *prune, "
        "*backup, *rollback"),
    "pets": (_reg("pets"), "list, *install, *select, show, *off, *scale, *remove, doctor"),
}

# Only extracted/registered families skip nested prompts after console confirmation
# (builder/adder families never did).
_CONFIRMED_KINDS = {"extracted", "registered"}

_SEND_SURFACE = _CliSurface("adder", "hermes_cli.send_cmd", "register_send_subparser")


def _register_command_family(
    engine: "HermesConsoleEngine", root: str, surface: _CliSurface, paths: str) -> None:
    summaries = _surface_summaries(surface, root)
    namespace_update = _apply_confirmed_defaults if surface.kind in _CONFIRMED_KINDS else None
    for child_path, mutating in _paths(paths):
        full_path = (root, *child_path)
        usage = " ".join(full_path)

        def handler(_engine: HermesConsoleEngine, args: list[str], fixed=child_path) -> str:
            return _dispatch(surface, root, fixed, args, namespace_update)

        engine.register(
            full_path, usage, summaries.get(full_path) or f"Run `hermes {usage}`.", handler,
            mutating=mutating, confirmation=f"Run `hermes {usage}`?")


_BLOCKED_TOP = frozenset(
    "acp chat claw completion dashboard desktop fallback gateway gui login logout model moa "
    "oneshot proxy serve setup uninstall update whatsapp whatsapp-cloud".split())

_BLOCKED_PAIRS = {
    ("config", "edit"): "`config edit` opens an editor and is not available in Hermes Console.",
    ("mcp", "serve"): "`mcp serve` starts a server and is not available in Hermes Console.",
    ("profile", "alias"): "`profile alias` creates shell wrappers and is not available in Hermes Console.",
    ("skills", "config"): "`skills config` is interactive and is not available in Hermes Console.",
    ("skills", "publish"): "`skills publish` is not available in Hermes Console.",
    ("portal", "login"): "`portal login` is interactive and is not available in Hermes Console.",
    ("portal", "open"): "`portal open` opens a browser and is not available in Hermes Console.",
    ("kanban", "tail"): "`kanban tail` streams output and is not available in Hermes Console.",
    ("kanban", "watch"): "`kanban watch` streams output and is not available in Hermes Console.",
    ("kanban", "daemon"): "`kanban daemon` starts a service and is not available in Hermes Console.",
    ("kanban", "dispatcher"): "`kanban dispatcher` starts a worker and is not available in Hermes Console.",
    ("kanban", "swarm"): "`kanban swarm` starts agent work and is not available in Hermes Console.",
    ("kanban", "decompose"): "`kanban decompose` starts agent work and is not available in Hermes Console.",
    ("kanban", "specify"): "`kanban specify` starts agent work and is not available in Hermes Console.",
    ("kanban", "gc"): "`kanban gc` is not available in Hermes Console.",
    ("sessions", "delete"): "`sessions delete` and `sessions prune` are not available in Hermes Console.",
    ("sessions", "prune"): "`sessions delete` and `sessions prune` are not available in Hermes Console.",
}


class HermesConsoleEngine:
    """Curated line-command executor for Hermes Console."""

    def __init__(self, *, output_limit: int = 20000, context: ConsoleContext = "local"):
        if context not in ALL_CONTEXTS:
            raise ValueError(f"Unknown console context: {context}")
        self.context = context
        self.output_limit = output_limit
        self.history: list[str] = []
        self.commands: dict[tuple[str, ...], ConsoleCommand] = {}
        self._register_defaults()


    def execute(self, line: str, *, confirmed: bool = False) -> ConsoleResult:
        raw_line = line.strip()
        if not raw_line:
            return ConsoleResult("ok")

        try:
            tokens = _split_line(raw_line)
            if tokens and tokens[0] == "hermes":
                tokens = tokens[1:]
            if not tokens:
                return ConsoleResult("ok", output=self.help_text())

            if _contains_shell_syntax(raw_line, tokens):
                raise ConsoleCommandError(
                    "Hermes Console does not run shell syntax. Use one supported "
                    "Hermes command at a time."
                )

            builtin = self._execute_builtin(tokens)
            if builtin is not None:
                if raw_line not in {"history", "clear"}:
                    self.history.append(raw_line)
                return builtin

            command, args = self._resolve_command(tokens)
            if command.mutating and not confirmed:
                return ConsoleResult(
                    "confirm_required",
                    command=raw_line,
                    confirmation_message=command.confirmation
                    or f"Run `{command.usage}`?",
                )

            output = command.handler(self, args).rstrip()
            output = self._cap_output(output)
            self.history.append(raw_line)
            return ConsoleResult("ok", output=output, command=raw_line)
        except _ConsoleParserExit as exc:
            # argparse --help/--version (exit code 0) is a successful, informational
            # result — show it as normal output; a non-zero code is a failure.
            status: ConsoleStatus = "ok" if exc.code == 0 else "error"
            return ConsoleResult(
                status, output=self._cap_output(str(exc).strip()), command=raw_line
            )
        except ConsoleCommandError as exc:
            return ConsoleResult("error", output=str(exc).strip(), command=raw_line)
        except SystemExit as exc:
            # Defense-in-depth: a handler called sys.exit() directly, or built a
            # parser that is not our _ArgumentParser. SystemExit is a
            # BaseException, so without this it would escape execute(), slip past
            # the dashboard worker's `except Exception`, and crash the uvicorn
            # loop. Contain it here so execute() ALWAYS returns a ConsoleResult.
            code = exc.code
            if code in (0, None):
                return ConsoleResult("ok", command=raw_line)
            message = code if isinstance(code, str) else f"Command exited with status {code}."
            return ConsoleResult("error", output=str(message).strip(), command=raw_line)


    def help_text(self, subject: str | None = None) -> str:
        if subject:
            tokens = subject.split()
            command, _args = self._resolve_command(tokens)
            return f"{command.usage}\n{command.summary}"

        lines = [
            "Hermes Console",
            "",
            "Supported commands:",
        ]
        for command in sorted(self.commands.values(), key=lambda c: c.usage):
            if self.context not in command.contexts:
                continue
            marker = " *" if command.mutating else "  "
            lines.append(f"{marker} {command.usage:<32} {_table_summary(command.summary)}")
        lines.extend(
            [
                "",
                "* requires confirmation",
                "Built-ins: help, help <command>, history, clear, exit, quit",
            ]
        )
        return "\n".join(lines)


    def _register_defaults(self) -> None:
        for path, usage, summary, handler, confirmation in _BUILTIN_COMMANDS:
            self.register(
                path, usage, summary, handler,
                mutating=bool(confirmation), confirmation=confirmation)
        for root, (surface, paths) in _CLI_FAMILIES.items():
            _register_command_family(self, root, surface, paths)
        self.register(
            ("send",), "send --to <target> <message>", "Send a message to a configured platform.",
            lambda _engine, args: _dispatch(_SEND_SURFACE, "send", (), args),
            mutating=True, confirmation="Send this message?")
        self._mark_hosted(EXPECTED_HOSTED_PATHS)

    def register(
        self,
        path: Iterable[str],
        usage: str,
        summary: str,
        handler: Callable[["HermesConsoleEngine", list[str]], str],
        *,
        mutating: bool = False,
        confirmation: str = "",
        contexts: Iterable[ConsoleContext] = LOCAL_CONTEXTS,
    ) -> None:
        key = tuple(path)
        self.commands[key] = ConsoleCommand(
            path=key,
            usage=usage,
            summary=summary,
            handler=handler,
            mutating=mutating,
            confirmation=confirmation,
            contexts=frozenset(contexts),
        )


    def _execute_builtin(self, tokens: list[str]) -> ConsoleResult | None:
        head = tokens[0]
        if head == "help":
            subject = " ".join(tokens[1:]).strip() or None
            try:
                return ConsoleResult("ok", output=self.help_text(subject))
            except ConsoleCommandError as exc:
                return ConsoleResult("error", output=str(exc))
        if head == "history":
            output = "\n".join(f"{idx + 1}: {cmd}" for idx, cmd in enumerate(self.history))
            return ConsoleResult("ok", output=output or "No history yet.")
        if head == "clear":
            return ConsoleResult("clear", output="\033[2J\033[H")
        return ConsoleResult("exit") if head in {"exit", "quit"} else None

    def _resolve_command(self, tokens: Sequence[str]) -> tuple[ConsoleCommand, list[str]]:
        rejected = self._rejection_for(tokens)
        if rejected:
            raise ConsoleCommandError(rejected)

        for size in range(min(len(tokens), 3), 0, -1):
            key = tuple(tokens[:size])
            command = self.commands.get(key)
            if command:
                if self.context not in command.contexts:
                    raise ConsoleCommandError(
                        f"`hermes {command.usage}` is not available in "
                        f"{self.context} Hermes Console."
                    )
                self._enforce_context_policy(command, list(tokens[size:]))
                return command, list(tokens[size:])

        available = [
            " ".join(path)
            for path, command in self.commands.items()
            if self.context in command.contexts
        ]
        probe = " ".join(tokens[:2]) if len(tokens) > 1 else tokens[0]
        suggestions = difflib.get_close_matches(probe, available, n=3, cutoff=0.45)
        suffix = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise ConsoleCommandError(f"Unsupported Hermes Console command: {probe}.{suffix}")


    def _rejection_for(self, tokens: Sequence[str]) -> str:
        first = tokens[0]
        if first.startswith("-"):
            return f"{first} is not available in Hermes Console."
        if first in _BLOCKED_TOP:
            return f"`hermes {first}` is not available in Hermes Console."
        return _BLOCKED_PAIRS.get(tuple(tokens[:2]), "")

    def _cap_output(self, output: str) -> str:
        if len(output) <= self.output_limit:
            return output
        omitted = len(output) - self.output_limit
        return f"{output[:self.output_limit]}\n... output truncated ({omitted} bytes omitted)"

    def _mark_hosted(self, paths: Iterable[Sequence[str]]) -> None:
        for path in paths:
            key = tuple(path)
            command = self.commands.get(key)
            if command is None:
                raise RuntimeError(f"Hosted console policy references unknown command: {' '.join(key)}")
            self.commands[key] = replace(
                command,
                contexts=command.contexts | frozenset({"hosted"}),
            )

    def _enforce_context_policy(self, command: ConsoleCommand, args: list[str]) -> None:
        if self.context != "hosted":
            return
        _enforce_hosted_line_policy(command.path, args)




def _expect_no_args(args: Sequence[str], usage: str) -> None:
    if args:
        raise ConsoleCommandError(f"Usage: {usage}")


def _parse(prog: str, args: Sequence[str], *specs) -> argparse.Namespace:
    """Parse ``args`` with a help-less parser; each spec is ``(flags, kwargs)`` or a bare flag."""
    parser = _ArgumentParser(prog=prog, add_help=False)
    for spec in specs:
        flags, kwargs = spec if isinstance(spec, tuple) else ((spec,), {})
        parser.add_argument(*flags, **kwargs)
    return parser.parse_args(args)


def _captured(fn):
    """Handler decorator: run ``fn(engine, args)`` under ``_capture_output`` and return its text."""
    @functools.wraps(fn)
    def wrapper(engine: HermesConsoleEngine, args: list[str]) -> str:
        return _capture_output(lambda: fn(engine, args))
    return wrapper


def _simple_command(usage: str, module: str, name: str, make_args=lambda: (), **kwargs):
    """Handler for no-arg commands that capture ``module.name(*make_args(), **kwargs)``."""
    def handler(_engine: HermesConsoleEngine, args: list[str]) -> str:
        _expect_no_args(args, usage)
        fn = getattr(importlib.import_module(module), name)
        return _capture_output(lambda: fn(*make_args(), **kwargs))
    return handler


def _apply_confirmed_defaults(args: argparse.Namespace) -> None:
    """Skip nested prompts after the console-level confirmation has happened."""
    if hasattr(args, "yes"):
        args.yes = True
    if getattr(args, "_console_command", None) == "import":
        args.force = True
    # Every mutating checkpoints subcommand gates its own confirmation on --force; `prune`
    # reaches _confirm() for its orphan preview, and the console never redirects stdin.
    if getattr(args, "checkpoints_command", None) in {"prune", "clear", "clear-legacy"}:
        args.force = True
    if (
        getattr(args, "plugins_action", None) == "install"
        and not getattr(args, "enable", False)
        and not getattr(args, "no_enable", False)):
        args.no_enable = True
    if getattr(args, "auth_action", None) == "add":
        auth_type = getattr(args, "auth_type", None)
        if auth_type in {"api-key", "api_key"} and not getattr(args, "api_key", None):
            raise ConsoleCommandError(
                "auth add --type api-key requires --api-key in Hermes Console.")
    if getattr(args, "import_name", None) is not None:
        return  # profile import has no prompt flag; leave it alone.
    if getattr(args, "skills_action", None) in {"install", "reset", "opt-out", "repair-official"}:
        args.yes = True
    if getattr(args, "memory_command", None) == "reset":
        args.yes = True


_version_info = _simple_command(
    "version", "hermes_cli._startup_fast", "print_fast_version_info", check_updates=True)


def _version(engine: HermesConsoleEngine, args: list[str]) -> str:
    _ArgumentParser(prog="version", description="Show Hermes version information.").parse_args(args)
    return _version_info(engine, [])


def _status(_engine: HermesConsoleEngine, args: list[str]) -> str:
    _expect_no_args(args, "status")
    from hermes_cli.status import show_status
    output = _capture_output(lambda: show_status(SimpleNamespace(all=False, deep=False)))
    return _strip_console_status_footer(output)


_doctor = _simple_command(
    "doctor", "hermes_cli.doctor", "run_doctor", lambda: (SimpleNamespace(fix=False, ack=None),))
_config_show = _simple_command("config show", "hermes_cli.config", "show_config")
_cron_status = _simple_command("cron status", "hermes_cli.cron", "cron_status")


def _logs(_engine: HermesConsoleEngine, args: list[str]) -> str:
    if "-f" in args or "--follow" in args:
        raise ConsoleCommandError("`logs -f` is not available in Hermes Console.")
    ns = _parse(
        "logs", args, (("log_name",), dict(nargs="?", default="agent")),
        (("-n", "--lines"), dict(type=int, default=50)),
        "--level", "--session", "--since", "--component")
    if ns.lines < 1 or ns.lines > 500:
        raise ConsoleCommandError("logs --lines must be between 1 and 500")
    from hermes_cli.logs import list_logs, tail_log
    if ns.log_name == "list":
        return _capture_output(list_logs)
    return _capture_output(
        lambda: tail_log(
            ns.log_name, num_lines=ns.lines, follow=False, level=ns.level,
            session=ns.session, since=ns.since, component=ns.component))


def _session_db():
    """``with _session_db() as db:`` — SessionDB closed on exit."""
    from hermes_state import SessionDB
    return closing(SessionDB())


def _sessions_list(_engine: HermesConsoleEngine, args: list[str]) -> str:
    ns = _parse("sessions list", args, (("--limit",), dict(type=int, default=20)))
    if ns.limit < 1 or ns.limit > 200:
        raise ConsoleCommandError("sessions list --limit must be between 1 and 200")
    with _session_db() as db:
        sessions = db.list_sessions_rich(
            exclude_sources=["kanban", "tool"], limit=ns.limit, order_by_last_active=True)
    return _format_sessions(sessions)


def _sessions_stats(_engine: HermesConsoleEngine, args: list[str]) -> str:
    _expect_no_args(args, "sessions stats")
    with _session_db() as db:
        total = db.session_count()
        listable = db.session_count(exclude_children=True, exclude_sources=["kanban", "tool"])
        lines = [
            f"Total sessions: {total}",
            f"Listable sessions: {listable}",
            f"Total messages: {db.message_count()}"]
        for source in ["cli", "tui", "telegram", "discord", "slack", "cron"]:
            count = db.session_count(source=source)
            if count:
                lines.append(f"  {source}: {count}")
        return "\n".join(lines)


def _config_path(_engine: HermesConsoleEngine, args: list[str]) -> str:
    _expect_no_args(args, "config path")
    from hermes_cli.config import get_config_path
    return str(get_config_path())


def _config_set(_engine: HermesConsoleEngine, args: list[str]) -> str:
    if len(args) < 2:
        raise ConsoleCommandError("Usage: config set <key> <value>")
    from hermes_cli.config import set_config_value
    return _capture_output(lambda: set_config_value(args[0], " ".join(args[1:])))


@_captured
def _config_migrate(_engine: HermesConsoleEngine, args: list[str]) -> None:
    _expect_no_args(args, "config migrate")
    from hermes_cli.config import migrate_config
    results = migrate_config(interactive=False, quiet=False)
    if results.get("env_added") or results.get("config_added"):
        print("Configuration updated.")
    else:
        print("Configuration is up to date.")
    for warning in results.get("warnings") or []:
        print(f"Warning: {warning}")


def _guard_exports(db, session_ids: list[str]) -> None:
    """Per-session export budget: only an individual runaway transcript trips it; 0 disables."""
    from hermes_state import SessionExportTooLargeError, resolved_max_export_messages
    limit = resolved_max_export_messages()
    if limit <= 0:
        return
    try:
        for session_id in session_ids:
            db.assert_export_safe(session_id, max_messages=limit)
    except SessionExportTooLargeError as exc:
        raise ConsoleCommandError(
            f"Session '{exc.session_id}' has more than {limit:,} active "
            "messages; in-memory export is capped per session. "
            "Use the Sessions page's streaming Export action, or set "
            "sessions.max_export_messages: 0 in config.yaml to disable "
            "the guard.") from exc


@_captured
def _sessions_export(_engine: HermesConsoleEngine, args: list[str]) -> None:
    ns = _parse("sessions export", args, "output", "--source", "--session-id")
    with _session_db() as db:
        if ns.session_id:
            resolved_session_id = db.resolve_session_id(ns.session_id)
            if not resolved_session_id:
                raise ConsoleCommandError(f"Session '{ns.session_id}' not found.")
            _guard_exports(db, [resolved_session_id])
            rows = [db.export_session(resolved_session_id)]
            if not rows[0]:
                raise ConsoleCommandError(f"Session '{ns.session_id}' not found.")
        else:
            found = db.search_sessions(source=ns.source, limit=100000)
            _guard_exports(db, [session["id"] for session in found])
            rows = db.export_all(source=ns.source)
        text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
        if text:
            text += "\n"
        if ns.output == "-":
            sys.stdout.write(text)
        else:
            Path(ns.output).expanduser().write_text(text, encoding="utf-8")
            print(f"Exported {len(rows)} session(s) to {ns.output}")


@_captured
def _sessions_rename(_engine: HermesConsoleEngine, args: list[str]) -> None:
    ns = _parse("sessions rename", args, "session_id", (("title",), dict(nargs="+")))
    with _session_db() as db:
        resolved_session_id = db.resolve_session_id(ns.session_id)
        title = " ".join(ns.title)
        if not resolved_session_id or not db.set_session_title(resolved_session_id, title):
            raise ConsoleCommandError(f"Session '{ns.session_id}' not found.")
        print(f"Session '{resolved_session_id}' renamed to: {title}")


@_captured
def _sessions_optimize(_engine: HermesConsoleEngine, args: list[str]) -> None:
    _expect_no_args(args, "sessions optimize")
    with _session_db() as db:
        print(f"Optimized {db.vacuum()} FTS index(es).")


@_captured
def _sessions_repair(_engine: HermesConsoleEngine, args: list[str]) -> None:
    ns = _parse(
        "sessions repair", args, (("--check-only",), dict(action="store_true")),
        (("--no-backup",), dict(action="store_true")))
    from hermes_state import DEFAULT_DB_PATH
    from hermes_state_repair import _db_opens_cleanly, repair_state_db_schema
    db_path = DEFAULT_DB_PATH
    if not db_path.exists():
        print(f"No session database at {db_path} (nothing to repair).")
        return
    reason = _db_opens_cleanly(db_path)
    if reason is None:
        print(f"{db_path} opens cleanly; no repair needed.")
        return
    print(f"{db_path} does not open cleanly: {reason}")
    if ns.check_only:
        return
    report = repair_state_db_schema(db_path, backup=not ns.no_backup)
    if not report.get("repaired"):
        raise ConsoleCommandError(f"Repair failed: {report.get('error')}")
    if report.get("backup_path"):
        print(f"backup: {report['backup_path']}")
    print(f"strategy: {report.get('strategy')}")
    print("Repaired session database.")


def _profile_status(_engine: HermesConsoleEngine, args: list[str]) -> str:
    _expect_no_args(args, "profile")
    return _dispatch(_CLI_FAMILIES["profile"][0], "profile", (), ())


def _cron_list(_engine: HermesConsoleEngine, args: list[str]) -> str:
    ns = _parse("cron list", args, (("--all",), dict(action="store_true")))
    from hermes_cli.cron import cron_list
    return _capture_output(lambda: cron_list(show_all=ns.all))


def _cron_job_action(args: list[str], usage: str, action: str, run) -> str:
    """Shared body for single-job cron commands: ``run(job_ref) -> job | None``."""
    if len(args) != 1:
        raise ConsoleCommandError(f"Usage: {usage}")
    from cron.jobs import AmbiguousJobReference
    try:
        job = run(args[0])
    except AmbiguousJobReference as exc:
        raise ConsoleCommandError(str(exc)) from exc
    if not job:
        raise ConsoleCommandError(f"Job not found: {args[0]}")
    return _format_job(job, action)


def _cron_pause(_engine: HermesConsoleEngine, args: list[str]) -> str:
    from cron.jobs import pause_job
    return _cron_job_action(
        args, "cron pause <job>", "Paused",
        lambda ref: pause_job(ref, reason="paused from hermes console", caller="hermes_console:cron_pause"))


def _cron_resume(_engine: HermesConsoleEngine, args: list[str]) -> str:
    ns = _parse("cron resume", args, "job", "--at", (("--run-now",), dict(action="store_true")))
    if ns.at and ns.run_now:
        raise ConsoleCommandError("Use exactly one of --at or --run-now.")
    from cron.jobs import AmbiguousJobReference, _hermes_now, rearm_oneshot, resume_job
    try:
        job = (
            rearm_oneshot(ns.job, _hermes_now().isoformat() if ns.run_now else ns.at)
            if ns.at or ns.run_now else resume_job(ns.job, caller="hermes_console:cron_resume"))
    except (AmbiguousJobReference, ValueError) as exc:
        raise ConsoleCommandError(str(exc)) from exc
    if not job:
        raise ConsoleCommandError(f"Job not found: {ns.job}")
    return _format_job(job, "Resumed")


def _cron_run(_engine: HermesConsoleEngine, args: list[str]) -> str:
    if len(args) != 1:
        raise ConsoleCommandError("Usage: cron run <job>")
    from cron.jobs import AmbiguousJobReference

    # Context-aware execution semantics (see spec 2026-07-14-hosted-console-
    # cron-run-background-design.md; supersedes the earlier 2026-07-14 defer
    # decision). "run" now means run-NOW on every surface:
    #
    #   local (standalone REPL)  → execute NOW, blocking, matching `hermes cron
    #                              run` (CLI) and the cronjob(action='run') tool,
    #                              both of which route through _execute_job_now.
    #                              A manual run then actually fires even when no
    #                              gateway ticker is active (the #41037 case).
    #
    #   hosted (dashboard web-console) → also fire NOW, but on a dedicated
    #                              BACKGROUND pool. That surface runs each command
    #                              in a bounded 4-worker pool under a 60s asyncio
    #                              timeout (web_server.py), so a synchronous agent
    #                              run would be mis-reported as timed-out and could
    #                              starve the shared pool. Dispatching
    #                              _execute_job_now off-thread returns an immediate
    #                              "started" ack and surfaces the result via the
    #                              CRON_TRIGGERED + completion events the dashboard
    #                              already consumes.
    #
    # Both paths keep caller="tui:console_engine" attribution and emit exactly one
    # CRON_TRIGGERED (via emit_cron_triggered_safe) so the audit contract holds.
    if _engine.context != "local":
        from cron.jobs import resolve_job_ref

        # Resolve on the console thread so `not found`/ambiguous come back
        # immediately; only the actual fire goes to the background pool.
        try:
            job = resolve_job_ref(args[0])
        except AmbiguousJobReference as exc:
            raise ConsoleCommandError(str(exc)) from exc
        if not job:
            raise ConsoleCommandError(f"Job not found: {args[0]}")

        _dispatch_console_background_run(job, caller="tui:console_engine")
        name = job.get("name") or job["id"]
        return (
            f"Started job: {name} ({job['id']}) - running now in the "
            "background; watch the activity feed for the result."
        )

    from cron.jobs import get_job, resolve_job_ref
    from tools.cronjob_tools import _execute_job_now

    try:
        job = resolve_job_ref(args[0])
    except AmbiguousJobReference as exc:
        raise ConsoleCommandError(str(exc)) from exc
    if not job:
        raise ConsoleCommandError(f"Job not found: {args[0]}")

    # Execute now: _execute_job_now claims at-most-once (blocking a concurrent
    # tick), emits CRON_TRIGGERED with the console caller, then fires via the
    # shared run_one_job body. A lost claim means the scheduler already owns this
    # fire — report it rather than double-running.
    exec_result = _execute_job_now(job, caller="tui:console_engine")

    refreshed = get_job(job["id"]) or job
    name = refreshed.get("name") or job.get("name") or job["id"]
    job_id = job["id"]

    if not exec_result.get("claimed", False):
        return (
            f"Run skipped: {name} ({job_id}) is already being fired "
            "by the scheduler."
        )
    if exec_result.get("success"):
        return f"Ran job: {name} ({job_id}) - succeeded."
    error = exec_result.get("error")
    if error:
        return f"Ran job: {name} ({job_id}) - failed: {error}"
    return f"Ran job: {name} ({job_id}) - failed."



# (path, usage, summary, handler, confirmation prompt) — a non-empty prompt marks it mutating.
_BUILTIN_COMMANDS = (
    (("status",), "status", "Show Hermes component status.", _status, ""),
    (("version",), "version", "Show Hermes version information.", _version, ""),
    (("doctor",), "doctor", "Run diagnostics without auto-fix.", _doctor, ""),
    (("logs",), "logs [name] [-n N]", "Show recent Hermes logs.", _logs, ""),
    (("sessions", "list"), "sessions list [--limit N]", "List recent sessions.", _sessions_list,
     ""),
    (("sessions", "stats"), "sessions stats", "Show session store statistics.", _sessions_stats,
     ""),
    (("config", "show"), "config show", "Show current configuration.", _config_show, ""),
    (("config", "path"), "config path", "Print config.yaml path.", _config_path, ""),
    (("cron", "list"), "cron list [--all]", "List scheduled jobs.", _cron_list, ""),
    (("cron", "status"), "cron status", "Show cron scheduler status.", _cron_status, ""),
    (("profile",), "profile", "Show active profile status.", _profile_status, ""),
    (("config", "set"), "config set <key> <value>", "Set a configuration value.", _config_set,
     "Update Hermes configuration?"),
    (("cron", "pause"), "cron pause <job>", "Pause a scheduled job.", _cron_pause,
     "Pause this cron job?"),
    (("cron", "resume"), "cron resume <job>", "Resume a paused cron job.", _cron_resume,
     "Resume this cron job?"),
    (("cron", "run"), "cron run <job>", "Run a job on the next scheduler tick.", _cron_run,
     "Trigger this cron job?"),
    (("config", "migrate"), "config migrate", "Update config with new options.", _config_migrate,
     "Update Hermes configuration with missing defaults?"),
    (("sessions", "export"), "sessions export <output> [--source SOURCE] [--session-id ID]",
     "Export sessions to JSONL.", _sessions_export, "Export session data?"),
    (("sessions", "rename"), "sessions rename <session> <title>", "Rename a session.",
     _sessions_rename, "Rename this session?"),
    (("sessions", "optimize"), "sessions optimize", "Optimize the session store.",
     _sessions_optimize, "Optimize the session database?"),
    (("sessions", "repair"), "sessions repair [--check-only] [--no-backup]",
     "Repair a malformed session database schema.", _sessions_repair,
     "Repair the session database?"))


def run_console_repl(
    *, stdin=None, stdout=None, stderr=None, interactive: bool | None = None) -> int:
    """Run the local ``hermes console`` REPL."""
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    if interactive is None:
        interactive = bool(getattr(stdin, "isatty", lambda: False)())
    engine = HermesConsoleEngine()

    def say(text: str, **kw) -> None:
        if interactive:
            print(text, file=stdout, **kw)

    say("Hermes Console. Type `help` for commands, `exit` to quit.")
    while True:
        say("hermes> ", end="", flush=True)
        line = stdin.readline()
        if line == "":
            say("")
            return 0
        result = engine.execute(line)
        if result.status == "confirm_required":
            if not interactive:
                print(f"Confirmation required: {result.confirmation_message}", file=stderr)
                return 1
            print(f"{result.confirmation_message} [y/N] ", end="", file=stdout, flush=True)
            if stdin.readline().strip().lower() not in {"y", "yes"}:
                print("Cancelled.", file=stdout)
                continue
            result = engine.execute(result.command, confirmed=True)
        if result.output:
            print(result.output, file=stderr if result.status == "error" else stdout)
        if result.status == "exit":
            return 0


# ---- BEGIN PLUGIN-COMPAT (revert-scheduled; see COMPAT_MANIFEST.md) ----
# Names external plugins imported from this module before the Sep 2026 decomposition.
# Internal code MUST NOT use these (scripts/check_compat_pointers.py fails CI if it does).
# The whole block is removed by reverting the commit that added it.
import shlex  # noqa: F401,E402
# ---- END PLUGIN-COMPAT ----


def _flag_present(args: Sequence[str], flag: str) -> bool:
    return any(arg == flag or arg.startswith(f"{flag}=") for arg in args)



def _flag_value(args: Sequence[str], flag: str) -> str | None:
    for index, arg in enumerate(args):
        if arg == flag:
            if index + 1 < len(args):
                return args[index + 1]
            return ""
        prefix = f"{flag}="
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None



def _hosted_config_key_allowed(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in HOSTED_CONFIG_BLOCKED_NAMES:
        return False
    if normalized.startswith(HOSTED_CONFIG_BLOCKED_PREFIXES):
        return False
    return normalized in HOSTED_CONFIG_ALLOWED_KEYS or normalized.startswith(
        HOSTED_CONFIG_ALLOWED_PREFIXES
    )



def _enforce_hosted_line_policy(path: tuple[str, ...], args: Sequence[str]) -> None:
    if path == ("config", "set"):
        key = args[0] if args else ""
        if key and not _hosted_config_key_allowed(key):
            raise ConsoleCommandError(
                f"`config set {key}` is not available in hosted Hermes Console. "
                "Use the dashboard setting for hosted account/provider changes."
            )
        return

    if path == ("mcp", "add"):
        if _flag_present(args, "--command") or _flag_present(args, "--args"):
            raise ConsoleCommandError(
                "Hosted Hermes Console does not add stdio MCP servers. "
                "Use catalog install or an HTTP/SSE URL."
            )
        if _flag_present(args, "--preset"):
            raise ConsoleCommandError(
                "Hosted Hermes Console does not add MCP presets directly. "
                "Use `mcp install <catalog-name>`."
            )
        url = _flag_value(args, "--url")
        if not url:
            raise ConsoleCommandError(
                "Hosted Hermes Console requires `mcp add` to use --url with "
                "an HTTP/SSE endpoint."
            )
        scheme = urlparse(url).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ConsoleCommandError(
                "Hosted Hermes Console only accepts http:// or https:// MCP URLs."
            )
        return

    if path in {("cron", "create"), ("cron", "edit")}:
        for flag in ("--script", "--no-agent", "--workdir"):
            if _flag_present(args, flag):
                raise ConsoleCommandError(
                    f"`cron {' '.join(path[1:])} {flag}` is not available in "
                    "hosted Hermes Console."
                )



def _get_console_run_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Lazily create the bounded background pool for hosted `cron run` (once)."""
    global _console_run_executor
    if _console_run_executor is None:
        with _console_run_executor_lock:
            if _console_run_executor is None:
                _console_run_executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=_CONSOLE_RUN_EXECUTOR_MAX_WORKERS,
                    thread_name_prefix="hermes-console-cronrun",
                )
                # Tear down at interpreter exit without waiting on an in-flight
                # agent run (mirrors web_server's console pool).
                atexit.register(
                    lambda: _console_run_executor
                    and _console_run_executor.shutdown(
                        wait=False, cancel_futures=True
                    )
                )
    return _console_run_executor



def _log_console_background_run_result(
    job: dict, future: concurrent.futures.Future
) -> None:
    """Log the outcome of a background hosted `cron run`.

    The dashboard activity feed already surfaces the real trigger/completion via
    the event stream; this makes the outcome visible in the gateway logs and
    ensures a crash in the background fire is never silently swallowed.
    """
    job_id = job.get("id", "?")
    name = job.get("name") or job_id
    try:
        result = future.result()
    except Exception:  # pragma: no cover - _execute_job_now catches its own
        logger.exception(
            "console background cron run crashed: %s (%s)", name, job_id
        )
        return
    if not result.get("claimed", False):
        logger.info(
            "console background cron run skipped: %s (%s) — already being "
            "fired by the scheduler",
            name,
            job_id,
        )
    elif result.get("success"):
        logger.info(
            "console background cron run succeeded: %s (%s)", name, job_id
        )
    else:
        logger.warning(
            "console background cron run failed: %s (%s) — %s",
            name,
            job_id,
            result.get("error"),
        )



def _dispatch_console_background_run(job: dict, *, caller: str) -> None:
    """Fire `_execute_job_now` on the background pool, off the console thread.

    Reuses the same at-most-once claim + single-CRON_TRIGGERED emit + shared
    `run_one_job` body the local path uses, so attribution and the audit
    contract are identical; only the executing thread differs.

    The fire runs inside a COPY of the caller's context so it inherits the
    hosted request's context-local HERMES_HOME override (set by web_server's
    `_profile_scope` for a non-default profile). A ThreadPoolExecutor worker
    otherwise starts with an empty context and would resolve the WRONG profile's
    cron store / secret scope — the same per-profile fire correctness cron.jobs'
    dynamic path resolution exists to preserve.
    """
    from tools.cronjob_tools import _execute_job_now

    ctx = contextvars.copy_context()
    future = _get_console_run_executor().submit(
        ctx.run, functools.partial(_execute_job_now, job, caller=caller)
    )
    future.add_done_callback(
        functools.partial(_log_console_background_run_result, job)
    )
