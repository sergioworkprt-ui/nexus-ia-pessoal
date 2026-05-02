"""
NEXUS Core — Initialisation
Wires all core modules together and exposes a single NexusCore entry point.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .cognitive_engine import CognitiveEngine, CognitiveInput, ReasoningStrategy
from .command_interpreter import CommandInterpreter, ParsedCommand, CommandResult
from .heartbeat import Heartbeat
from .logger import NexusLogger, LogLevel, get_logger
from .memory_manager import MemoryManager
from .security_manager import SecurityManager, SecurityPolicy
from .task_manager import TaskManager, Priority


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class NexusCoreConfig:
    log_dir: str = "logs"
    log_level: LogLevel = LogLevel.INFO
    data_dir: str = "data"
    stm_capacity: int = 512
    task_workers: int = 4
    heartbeat_interval: float = 30.0
    security_policy: SecurityPolicy = field(default_factory=SecurityPolicy)
    secret_key: str = ""
    enable_console_log: bool = True


# ---------------------------------------------------------------------------
# NexusCore
# ---------------------------------------------------------------------------

class NexusCore:
    """
    Top-level facade that initialises and wires all NEXUS core subsystems.

    Usage:
        core = NexusCore()
        core.start()
        result = core.execute("nexus status")
        core.stop()

    All modules are accessible as attributes after start():
        core.memory, core.tasks, core.security,
        core.cognitive, core.interpreter, core.heartbeat, core.logger
    """

    _instance: Optional[NexusCore] = None
    _init_lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "NexusCore":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[NexusCoreConfig] = None) -> None:
        if getattr(self, "_ready", False):
            return

        self._config = config or NexusCoreConfig()
        self._ready = False

        # Initialise subsystems
        self.logger: NexusLogger = NexusLogger(
            log_dir=self._config.log_dir,
            level=self._config.log_level,
            enable_console=self._config.enable_console_log,
        )
        self.memory: MemoryManager = MemoryManager(
            stm_capacity=self._config.stm_capacity,
            ltm_path=f"{self._config.data_dir}/long_term_memory.json",
        )
        self.security: SecurityManager = SecurityManager(
            policy=self._config.security_policy,
            secret_key=self._config.secret_key,
        )
        self.tasks: TaskManager = TaskManager(max_workers=self._config.task_workers)
        self.cognitive: CognitiveEngine = CognitiveEngine()
        self.interpreter: CommandInterpreter = CommandInterpreter()
        self.heartbeat: Heartbeat = Heartbeat(interval_seconds=self._config.heartbeat_interval)

        self._register_builtin_commands()
        self._register_builtin_health_checks()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background services (heartbeat monitor)."""
        self.heartbeat.start()
        self._ready = True
        self.logger.info("core", "NEXUS Core started.", config=self._config.__class__.__name__)

    def stop(self) -> None:
        """Gracefully stop all background services."""
        self.heartbeat.stop()
        self.tasks.shutdown(wait=True)
        self._ready = False
        self.logger.info("core", "NEXUS Core stopped.")

    # ------------------------------------------------------------------
    # Primary interfaces
    # ------------------------------------------------------------------

    def execute(self, raw_command: str, actor: str = "system") -> CommandResult:
        """Validate and execute a raw NEXUS command string."""
        try:
            validated = self.security.validate_input(raw_command, actor=actor)
        except Exception as exc:
            self.logger.warning("core", f"Security rejection: {exc}", actor=actor)
            return CommandResult(success=False, command=raw_command, error=str(exc))

        result = self.interpreter.execute(validated)
        self.logger.audit(
            actor=actor,
            action="execute_command",
            target=result.command,
            outcome="ok" if result.success else "fail",
        )
        return result

    def think(
        self,
        content: str,
        strategy: ReasoningStrategy = ReasoningStrategy.DIRECT,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the cognitive engine on a piece of content."""
        output = self.cognitive.think_raw(content, strategy=strategy, context=context or {})
        self.logger.debug("cognitive", f"Thought completed in {output.elapsed_ms:.1f}ms")
        return output.to_dict()

    def status(self) -> Dict[str, Any]:
        """Return a full system status snapshot."""
        snapshot = self.heartbeat.beat()
        return {
            "ready": self._ready,
            "health": snapshot.status,
            "uptime_seconds": snapshot.uptime_seconds,
            "memory": self.memory.stats(),
            "tasks": self.tasks.stats(),
            "cognitive": self.cognitive.stats(),
            "system": snapshot.system_info,
            "checks": snapshot.checks,
        }

    # ------------------------------------------------------------------
    # Built-in command handlers
    # ------------------------------------------------------------------

    def _register_builtin_commands(self) -> None:
        ci = self.interpreter

        def _handle_status(cmd: ParsedCommand) -> Dict[str, Any]:
            return self.status()

        def _handle_help(cmd: ParsedCommand) -> str:
            commands = self.interpreter.list_commands()
            return "Available commands:\n" + "\n".join(f"  {c}" for c in commands)

        def _handle_memory_stats(cmd: ParsedCommand) -> Dict[str, Any]:
            return self.memory.stats()

        def _handle_memory_recall(cmd: ParsedCommand) -> Any:
            key = cmd.args[0] if cmd.args else cmd.flags.get("key")
            if not key:
                return {"error": "Usage: nexus memory recall <key>"}
            return {"key": key, "value": self.memory.recall(str(key))}

        def _handle_task_stats(cmd: ParsedCommand) -> Dict[str, Any]:
            return self.tasks.stats()

        def _handle_diagnostics(cmd: ParsedCommand) -> Dict[str, Any]:
            return self.heartbeat.diagnostics()

        ci.register("nexus", "status", _handle_status)
        ci.register("nexus", "help", _handle_help)
        ci.register("nexus", "diagnostics", _handle_diagnostics)
        ci.register("nexus", "memory", _handle_memory_stats)
        ci.register("memory", "recall", _handle_memory_recall)
        ci.register("task", "stats", _handle_task_stats)

    # ------------------------------------------------------------------
    # Built-in health checks
    # ------------------------------------------------------------------

    def _register_builtin_health_checks(self) -> None:
        self.heartbeat.register_check(
            "memory_manager",
            fn=lambda: self.memory is not None,
            critical=True,
        )
        self.heartbeat.register_check(
            "task_manager",
            fn=lambda: self.tasks is not None,
            critical=True,
        )
        self.heartbeat.register_check(
            "cognitive_engine",
            fn=lambda: self.cognitive is not None,
            critical=False,
        )
        self.heartbeat.register_check(
            "security_manager",
            fn=lambda: self.security is not None,
            critical=True,
        )


# ---------------------------------------------------------------------------
# Module-level convenience accessor
# ---------------------------------------------------------------------------

def get_core(config: Optional[NexusCoreConfig] = None) -> NexusCore:
    """Return (or create) the singleton NexusCore instance."""
    return NexusCore(config=config)
