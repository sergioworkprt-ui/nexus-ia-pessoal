"""
NEXUS Core — Command Interpreter
Parses raw text commands and dispatches them to registered handlers.
"""

import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParsedCommand:
    raw: str
    namespace: str          # e.g. "nexus", "web", "profit"
    action: str             # e.g. "search", "start", "report"
    subaction: Optional[str] = None   # e.g. "deep" in "web search --deep"
    args: List[str] = field(default_factory=list)
    flags: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [self.namespace, self.action]
        if self.subaction:
            parts.append(self.subaction)
        return " ".join(parts)


@dataclass
class CommandResult:
    success: bool
    command: str
    output: Any = None
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success


HandlerFn = Callable[[ParsedCommand], Any]


# ---------------------------------------------------------------------------
# Command Interpreter
# ---------------------------------------------------------------------------

class CommandInterpreter:
    """
    Parses NEXUS command strings and dispatches to registered handlers.

    Command syntax:
        <namespace> <action> [subaction] [args...] [--flag [value]]

    Example:
        nexus web search --deep "machine learning trends"
        nexus profit report --period week
        nexus ia ask claude "What is the market outlook?"
    """

    def __init__(self) -> None:
        # Registry: key = "namespace.action", value = handler
        self._handlers: Dict[str, HandlerFn] = {}
        self._middleware: List[Callable[[ParsedCommand], Optional[ParsedCommand]]] = []
        self._default_namespace = "nexus"

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, namespace: str, action: str, handler: HandlerFn) -> None:
        """Register a handler for a specific namespace + action pair."""
        key = self._make_key(namespace, action)
        self._handlers[key] = handler

    def register_middleware(self, fn: Callable[[ParsedCommand], Optional[ParsedCommand]]) -> None:
        """
        Register a middleware that runs before dispatch.
        Return None from the middleware to abort execution.
        """
        self._middleware.append(fn)

    def unregister(self, namespace: str, action: str) -> bool:
        key = self._make_key(namespace, action)
        return self._handlers.pop(key, None) is not None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, raw: str) -> CommandResult:
        """Parse and execute a raw command string."""
        try:
            parsed = self.parse(raw)
        except ValueError as exc:
            return CommandResult(success=False, command=raw, error=str(exc))

        for mw in self._middleware:
            result = mw(parsed)
            if result is None:
                return CommandResult(
                    success=False,
                    command=str(parsed),
                    error="Command blocked by middleware.",
                )
            parsed = result

        key = self._make_key(parsed.namespace, parsed.action)
        handler = self._handlers.get(key)

        if handler is None:
            return CommandResult(
                success=False,
                command=str(parsed),
                error=f"Unknown command: '{parsed.namespace} {parsed.action}'. Use 'nexus help' for a list of commands.",
            )

        try:
            output = handler(parsed)
            return CommandResult(success=True, command=str(parsed), output=output)
        except Exception as exc:
            return CommandResult(success=False, command=str(parsed), error=str(exc))

    # ------------------------------------------------------------------
    # Parser
    # ------------------------------------------------------------------

    def parse(self, raw: str) -> ParsedCommand:
        """
        Tokenise the raw string and populate a ParsedCommand.
        Raises ValueError on malformed input.
        """
        raw = raw.strip()
        if not raw:
            raise ValueError("Empty command.")

        try:
            tokens = shlex.split(raw)
        except ValueError as exc:
            raise ValueError(f"Malformed command (unmatched quotes?): {exc}") from exc

        if len(tokens) < 2:
            # Single token treated as "<namespace> help"
            tokens.append("help")

        namespace = tokens[0].lower()
        action = tokens[1].lower()
        rest = tokens[2:]

        subaction: Optional[str] = None
        args: List[str] = []
        flags: Dict[str, Any] = {}

        # Check if the next token is a subaction (no leading --)
        if rest and not rest[0].startswith("-"):
            subaction = rest[0].lower()
            rest = rest[1:]

        # Parse remaining as flags and positional args
        i = 0
        while i < len(rest):
            token = rest[i]
            if token.startswith("--"):
                flag_name = token[2:]
                if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
                    flags[flag_name] = self._coerce(rest[i + 1])
                    i += 2
                else:
                    flags[flag_name] = True
                    i += 1
            elif token.startswith("-") and len(token) == 2:
                flags[token[1:]] = True
                i += 1
            else:
                args.append(token)
                i += 1

        return ParsedCommand(
            raw=raw,
            namespace=namespace,
            action=action,
            subaction=subaction,
            args=args,
            flags=flags,
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_commands(self) -> List[str]:
        return sorted(self._handlers.keys())

    def has_command(self, namespace: str, action: str) -> bool:
        return self._make_key(namespace, action) in self._handlers

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(namespace: str, action: str) -> str:
        return f"{namespace.lower()}.{action.lower()}"

    @staticmethod
    def _coerce(value: str) -> Any:
        """Try to convert a string token to int or float; fall back to str."""
        for cast in (int, float):
            try:
                return cast(value)
            except (ValueError, TypeError):
                pass
        if value.lower() in ("true", "yes"):
            return True
        if value.lower() in ("false", "no"):
            return False
        return value
